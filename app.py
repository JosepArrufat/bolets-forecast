#!/usr/bin/env python3
"""
Bolets Forecast — single-file Python web app.
Run: python3 app.py
Then open: http://localhost:8765
"""

import json
import math
import os
import re
import urllib.request
import urllib.parse
from datetime import date, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ── Paths ─────────────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
MUSHROOMS  = os.path.join(BASE_DIR, "mushrooms.json")
_data_dir  = os.environ.get("DATA_DIR", BASE_DIR)
CACHE_FILE = os.path.join(_data_dir, "geo_cache.json")
PARKING_CACHE_FILE = os.path.join(_data_dir, "parking_cache.json")
PARKING_SEED_FILE = os.path.join(BASE_DIR, "parking_cache.json")

# ── Load species data ─────────────────────────────────────────────────────────

with open(MUSHROOMS) as f:
    SPECIES_DATA = json.load(f)

SPECIES_LIST = SPECIES_DATA["species"]
STATIONS     = SPECIES_DATA["target_stations"]

# ── Re-read stations on each forecast call so edits to mushrooms.json take effect ──

def get_stations():
    with open(MUSHROOMS) as f:
        return json.load(f)["target_stations"]

# ── Geo cache (IGME + CORINE, persistent) ────────────────────────────────────

_cache_lock = threading.Lock()

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

GEO_CACHE = load_cache()

# Parking is precomputed for the known stations because public Overpass can take
# tens of seconds. `warm_parking.py` fills this file; unknown points fall back
# to a live query with a short timeout.
def load_parking_cache():
    # Prefer the writable data dir; fall back to the seed shipped in the image.
    for path in (PARKING_CACHE_FILE, PARKING_SEED_FILE):
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (ValueError, OSError):
                continue
    return {}

def save_parking_cache(cache):
    with open(PARKING_CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

_parking_lock = threading.Lock()
PARKING_CACHE = load_parking_cache()

def cache_key(lat, lon):
    return f"{lat:.4f},{lon:.4f}"

def get_cached_geo(lat, lon):
    with _cache_lock:
        return GEO_CACHE.get(cache_key(lat, lon))

def set_cached_geo(lat, lon, data):
    with _cache_lock:
        GEO_CACHE[cache_key(lat, lon)] = data
        save_cache(GEO_CACHE)

# ── Coordinate helpers ────────────────────────────────────────────────────────

def to_mercator(lat, lon):
    x = lon * 20037508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
    y = y * 20037508.34 / 180
    return x, y

# ── IGME lithology (soil type) ────────────────────────────────────────────────

CALCAREOUS_KW = [
    "caliza", "calizas", "dolomia", "dolomías", "dolomia", "marga", "margas",
    "calcárea", "calcáreo", "calcarenita", "cretácic", "jurásic",
    "travertino", "carbonato", "calcisiltita", "nodulosa", "calco",
    "evaporita", "evaporitas",
]
SILICEOUS_KW = [
    "granito", "granitos", "esquisto", "esquistos", "pizarra", "pizarras",
    "gneis", "cuarcita", "cuarcitas", "silíceo", "micaesquisto", "ortogneis",
    "paragneiss", "filita", "granodiorita", "tonalita", "migmatita",
    "riolita", "pórfido",
]

def classify_lithology(text):
    """Return 'calcareous', 'siliceous', or 'mixed' from IGME text."""
    if not text or text in ("?", "NO DATA"):
        return "unknown"
    t = text.lower()
    has_cal = any(k in t for k in CALCAREOUS_KW)
    has_sil = any(k in t for k in SILICEOUS_KW)
    if has_sil and not has_cal:
        return "siliceous"
    if has_cal and not has_sil:
        return "calcareous"
    if has_cal and has_sil:
        return "mixed"
    # arenisca/conglomerado without clear signal → mixed
    return "mixed"

def fetch_igme_litho(lat, lon):
    """Query IGME Litologias 1M REST API. Returns (litho_text, soil_type)."""
    x, y = to_mercator(lat, lon)
    url = (
        "https://mapas.igme.es/gis/rest/services/Cartografia_Geologica/"
        "IGME_Litologias_1M/MapServer/identify"
        f"?geometry={x:.2f},{y:.2f}"
        "&geometryType=esriGeometryPoint"
        "&layers=0"
        "&tolerance=5"
        f"&mapExtent={x-5000:.2f},{y-5000:.2f},{x+5000:.2f},{y+5000:.2f}"
        "&imageDisplay=500,500,96"
        "&returnGeometry=false"
        "&f=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read())
        for res in d.get("results", []):
            text = res["attributes"].get("Litologia", "")
            return text, classify_lithology(text)
    except Exception:
        pass
    return "unknown", "unknown"

# ── CORINE land cover (forest type) ──────────────────────────────────────────

CORINE_CODES = {
    "111": "Urban (continuous)",
    "112": "Urban (discontinuous)",
    "121": "Urban (industrial)",
    "211": "Arable land",
    "221": "Vineyards",
    "231": "Pastures",
    "311": "Broadleaf forest",
    "312": "Coniferous forest",
    "313": "Mixed forest",
    "321": "Natural grasslands",
    "322": "Moors/heathland",
    "323": "Sclerophyllous vegetation",
    "324": "Transitional woodland/shrub",
    "331": "Beaches/dunes",
    "332": "Bare rock",
    "333": "Sparsely vegetated",
    "334": "Burnt areas",
    "411": "Inland marshes",
    "512": "Water bodies",
}

FOREST_CODES = {"311", "312", "313", "324"}

def fetch_corine(lat, lon):
    """Query CORINE CLC 2018 WMS GetFeatureInfo. Returns (code, label)."""
    delta = 0.03
    bbox = f"{lat-delta},{lon-delta},{lat+delta},{lon+delta}"
    url = (
        "https://image.discomap.eea.europa.eu/arcgis/services/Corine/"
        "CLC2018_WM/MapServer/WMSServer"
        "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo"
        "&LAYERS=13&QUERY_LAYERS=13"
        f"&CRS=EPSG:4326&BBOX={bbox}"
        "&WIDTH=100&HEIGHT=100&I=50&J=50"
        "&INFO_FORMAT=text/html"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="replace")
        # Parse table: FID, Shape, Code_18, ...
        rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
        for row in rows[1:]:  # skip header
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)
            cells = [c.strip() for c in cells]
            if len(cells) >= 3:
                code = cells[2]
                label = CORINE_CODES.get(code, f"Code {code}")
                return code, label
    except Exception:
        pass
    return "unknown", "Unknown"

# ── SoilGrids pH (fallback for mixed/unknown lithology) ──────────────────────

def fetch_soilgrids_ph(lat, lon):
    """Query SoilGrids v2 for pH at 0-5cm. Returns float or None."""
    url = (
        "https://rest.isric.org/soilgrids/v2.0/properties/query"
        f"?lon={lon}&lat={lat}&property=phh2o&depth=0-5cm&value=mean"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        layer = d["properties"]["layers"][0]
        val   = layer["depths"][0]["values"]["mean"]
        factor = layer["unit_measure"]["d_factor"]
        return val / factor
    except Exception:
        return None

# ── Fetch all geo data for a station (cached) ────────────────────────────────

def fetch_geo(lat, lon):
    """Returns dict with soil_type, litho_text, forest_code, forest_label, ph."""
    cached = get_cached_geo(lat, lon)
    if cached:
        return cached

    # Run IGME + CORINE in parallel
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_igme   = ex.submit(fetch_igme_litho, lat, lon)
        fut_corine = ex.submit(fetch_corine, lat, lon)
        litho_text, soil_type  = fut_igme.result()
        forest_code, forest_label = fut_corine.result()

    # SoilGrids fallback only when soil type is ambiguous
    ph = None
    if soil_type in ("mixed", "unknown"):
        ph = fetch_soilgrids_ph(lat, lon)
        if ph is not None:
            if ph < 6.3:
                soil_type = "siliceous"
            elif ph > 7.0:
                soil_type = "calcareous"
            # else keep "mixed"

    result = {
        "soil_type":    soil_type,
        "litho_text":   litho_text,
        "forest_code":  forest_code,
        "forest_label": forest_label,
        "ph":           ph,
    }
    set_cached_geo(lat, lon, result)
    return result

# ── Open-Meteo weather ────────────────────────────────────────────────────────

def fetch_weather(lat, lon):
    params = {
        "latitude":  lat,
        "longitude": lon,
        "daily": ",".join([
            "precipitation_sum",
            "temperature_2m_max",
            "temperature_2m_min",
            "windspeed_10m_max",
            "relative_humidity_2m_max",
        ]),
        "past_days":     14,
        "forecast_days": 7,
        "timezone":      "Europe/Madrid",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["daily"]

# ── Place search (geocoding proxy) ────────────────────────────────────────────

def geocode_place(query):
    """Forward a place search to Nominatim with a proper User-Agent.

    Kept server-side so the browser never has to deal with CORS or rate-limit
    headers, and so we can restrict results to the Pyrenees / Catalonia box.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 6,
        "accept-language": "ca,es,en",
        "countrycodes": "es,ad,fr",
        # Soft bias to Catalonia; viewbox is left,top,right,bottom
        "viewbox": "-0.5,43.2,3.5,40.4",
        "bounded": 0,
    }
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BoletsForecast/1.0 (mushroom forecast; contact: local)",
            "Accept-Language": "ca,es,en",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as r:
        rows = json.loads(r.read())
    out = []
    for row in rows:
        try:
            out.append({
                "name": row.get("display_name", "").split(",")[0],
                "display": row.get("display_name", ""),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "type": row.get("type", ""),
                "category": row.get("category", ""),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out

# ── Nearby parking (OpenStreetMap / Overpass, proxied server-side) ────────────

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))

def find_parking(lat, lon, radius_m=2500):
    """Return the nearest mapped parking places around a zone.

    Results are precomputed in `parking_cache.json` for the known stations.
    Unknown points fall back to a live Overpass query. Overpass rejects requests
    without a descriptive User-Agent (HTTP 406), so this stays server-side.
    """
    key = f"{lat:.4f},{lon:.4f}"
    with _parking_lock:
        cached = PARKING_CACHE.get(key)
    if cached is not None:
        return cached

    query = (
        f'[out:json][timeout:20];'
        f'(node["amenity"="parking"](around:{int(radius_m)},{lat},{lon});'
        f'way["amenity"="parking"](around:{int(radius_m)},{lat},{lon}););'
        f'out center 12;'
    )
    body = urllib.parse.urlencode({"data": query}).encode()

    data = None
    last_err = None
    for endpoint in ("https://overpass-api.de/api/interpreter",):
        try:
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={
                    "User-Agent": "BoletsForecast/1.0 (mushroom forecast; local app)",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read())
            break
        except Exception as e:
            last_err = e
    if data is None:
        raise last_err or RuntimeError("Overpass unavailable")

    rows = []
    for el in data.get("elements", []):
        center = el.get("center") or {}
        plat = el.get("lat", center.get("lat"))
        plon = el.get("lon", center.get("lon"))
        if plat is None or plon is None:
            continue
        tags = el.get("tags") or {}
        rows.append({
            "name": tags.get("name") or "Aparcament",
            "lat": plat,
            "lon": plon,
            "distance_m": round(haversine_m(lat, lon, plat, plon)),
            "capacity": tags.get("capacity"),
        })
    rows.sort(key=lambda x: x["distance_m"])
    rows = rows[:5]

    with _parking_lock:
        PARKING_CACHE[key] = rows
        try:
            save_parking_cache(PARKING_CACHE)
        except OSError:
            pass
    return rows

# ── Data quality (not prediction confidence) ───────────────────────────────────

def data_quality(weather, geo):
    """How complete are the inputs behind a station's score?

    This is deliberately *data completeness*, not a probability. It tells the
    user whether the score rests on full weather + soil + forest data or on
    fallbacks. Naming it "qualitat de dades" avoids pretending it is a
    calibrated confidence interval.
    """
    pct = 0
    reasons = []

    precip = [p for p in (weather or {}).get("precipitation_sum", []) if p is not None]
    temps  = [t for t in (weather or {}).get("temperature_2m_max", []) if t is not None]
    if len(precip) >= 7 and len(temps) >= 5:
        pct += 40
    else:
        reasons.append("meteo incompleta")

    soil = (geo or {}).get("soil_type")
    if soil in ("calcareous", "siliceous", "mixed"):
        pct += 30
    else:
        reasons.append("sòl desconegut")

    forest = (geo or {}).get("forest_code")
    if forest and forest != "unknown":
        pct += 30
    else:
        reasons.append("bosc desconegut")

    if pct >= 90:
        label = "alta"
    elif pct >= 60:
        label = "mitjana"
    else:
        label = "baixa"

    return {"pct": pct, "label": label, "reasons": reasons}

# ── Scoring helpers ───────────────────────────────────────────────────────────

def gaussian_score(value, ideal_min, ideal_max, hard_min=None, hard_max=None):
    if hard_min is not None and value < hard_min: return 0.0
    if hard_max is not None and value > hard_max: return 0.0
    if ideal_min <= value <= ideal_max: return 1.0
    center = (ideal_min + ideal_max) / 2
    sigma  = (ideal_max - ideal_min) / 2
    return math.exp(-0.5 * ((value - center) / (sigma + 1e-9)) ** 2)

def rain_score(precip, trigger_mm, window_days, dry_spell_before):
    if len(precip) < window_days:
        window_days = len(precip)
    recent = precip[-window_days:]
    total  = sum(p for p in recent if p is not None)
    base   = min(total / max(trigger_mm, 1), 1.5)
    # Dry spell bonus
    if dry_spell_before > 0 and len(precip) >= window_days + dry_spell_before:
        pre = precip[-(window_days + dry_spell_before):-window_days]
        pre_total = sum(p for p in pre if p is not None)
        if pre_total < 5:
            base = min(base * 1.2, 1.5)
    return min(base, 1.0)

def wind_score(gusts, sensitivity):
    recent = [g for g in gusts[-3:] if g is not None]
    if not recent: return 0.5
    avg = sum(recent) / len(recent)
    threshold = {"high": 25, "medium": 35, "low": 50}.get(sensitivity, 35)
    return max(0.0, 1.0 - avg / threshold)

def temp_score(t_max, t_min, sp):
    recent_max = [t for t in t_max[-5:] if t is not None]
    recent_min = [t for t in t_min[-5:] if t is not None]
    if not recent_max or not recent_min: return 0.5
    avg = (sum(recent_max)/len(recent_max) + sum(recent_min)/len(recent_min)) / 2
    t = sp["temperature_c"]
    return gaussian_score(avg, t["ideal_min"], t["ideal_max"],
                          hard_min=t["min"], hard_max=t["max"])

def humidity_score(humidity):
    recent = [h for h in humidity[-5:] if h is not None]
    if not recent: return 0.5
    return min(sum(recent) / len(recent) / 70.0, 1.0)

# ── Soil & forest multipliers ─────────────────────────────────────────────────

def soil_multiplier(sp, soil_type):
    """How well does this soil type match the species preference?"""
    pref = sp["soil"]["ph"]  # "basic", "acid", "neutral_to_acid", etc.
    if soil_type == "unknown":
        return 0.9  # slight penalty for missing data
    if soil_type == "mixed":
        return 0.85
    is_acid = "acid" in pref
    is_basic = "basic" in pref and "acid" not in pref
    is_neutral = "neutral" in pref and "acid" not in pref and "basic" not in pref
    if soil_type == "calcareous":
        if is_acid:   return 0.15  # strong mismatch
        if is_basic:  return 1.0
        return 0.75  # neutral tolerance
    if soil_type == "siliceous":
        if is_acid:   return 1.0
        if is_basic:  return 0.15  # strong mismatch
        return 0.75
    return 1.0

def forest_multiplier(sp, forest_code):
    """How well does the detected forest type match the species' trees?"""
    if forest_code == "unknown":
        return 0.9
    if forest_code not in FOREST_CODES:
        # Not a forest at all (urban, pasture, etc.)
        pref_trees = sp.get("tree_keywords", [])
        if any(k in ["grassland", "meadow", "prat", "herba", "forest edge"]
               for k in pref_trees):
            return 1.0  # species likes open/meadow habitat
        return 0.3
    # 311=broadleaf, 312=conifer, 313=mixed, 324=transitional
    pref_trees = sp.get("tree_keywords", [])
    needs_pine = sp.get("prefers_scots_pine", False)
    needs_broadleaf = any(k in ["faig", "roure", "castanyer", "beech", "oak", "chestnut"]
                          for k in pref_trees)
    if forest_code == "312":  # conifer
        if needs_pine: return 1.0
        if needs_broadleaf: return 0.3
        return 0.8
    if forest_code == "311":  # broadleaf
        if needs_broadleaf: return 1.0
        if needs_pine: return 0.2
        return 0.7
    if forest_code == "313":  # mixed
        return 0.85
    if forest_code == "324":  # transitional
        return 0.6
    return 0.8

# ── Main scoring function ─────────────────────────────────────────────────────

def score_station(station, weather, geo, day_offset=0):
    """Score all species for a station.
    day_offset=0 → today, 1 → tomorrow, … 6 → 6 days from now.
    The weather arrays have past_days=14 + forecast_days=7, total ~21 entries.
    day_offset shifts which 'current' day we treat as 'now'.
    """
    # Total array length: past(14) + today(1) + future(6) = 21
    # Index of 'today' in the array = len - 7 (last 7 are forecast)
    total_len = len(weather["precipitation_sum"])
    # today_idx is the index after which data is forecast
    today_idx = total_len - 7  # e.g. 14

    # Shift: for day_offset=N we pretend we're N days in the future
    # so the 'past' window ends at today_idx + day_offset
    end = today_idx + day_offset  # exclusive end of 'past' data

    precip   = weather["precipitation_sum"][:end + 1]
    t_max    = weather["temperature_2m_max"][:end + 1]
    t_min    = weather["temperature_2m_min"][:end + 1]
    wind     = weather["windspeed_10m_max"][:end + 1]
    humidity = weather["relative_humidity_2m_max"][:end + 1]

    results = []
    current_month = date.today().month

    for sp in SPECIES_LIST:
        if sp.get("season") == "spring" and current_month not in (3, 4, 5):
            continue

        r_sc = rain_score(precip, sp["rain_trigger_mm"],
                          sp["rain_window_days"], sp["dry_spell_before_days"])
        t_sc = temp_score(t_max, t_min, sp)
        w_sc = wind_score(wind, sp["wind_sensitivity"])
        h_sc = humidity_score(humidity)
        alt  = station.get("alt_m", 900)
        a    = sp["altitude_m"]
        a_sc = gaussian_score(alt, a["ideal_min"], a["ideal_max"],
                              hard_min=a["min"], hard_max=a["max"])

        base   = (r_sc * 0.35 + t_sc * 0.25 + w_sc * 0.20 +
                  a_sc * 0.10 + h_sc * 0.10)
        s_mult = soil_multiplier(sp, geo["soil_type"])
        f_mult = forest_multiplier(sp, geo["forest_code"])
        total  = base * s_mult * f_mult

        pct = round(min(total * 100, 99))
        if pct >= 75:   label = "Molt bona"
        elif pct >= 55: label = "Bona"
        elif pct >= 35: label = "Possible"
        else:           label = "Baixa"

        # Raw numbers for educational explanation
        p7  = round(sum(p for p in precip[-7:] if p is not None), 1)
        p14 = round(sum(p for p in precip[-14:] if p is not None), 1)
        pre_window = precip[-(sp["rain_window_days"]+sp["dry_spell_before_days"]):-sp["rain_window_days"]] \
            if len(precip) >= sp["rain_window_days"]+sp["dry_spell_before_days"] else []
        pre_dry = sum(1 for p in pre_window if p is not None and p < 1)

        recent_max_vals = [t for t in t_max[-5:] if t is not None]
        recent_min_vals = [t for t in t_min[-5:] if t is not None]
        avg_max = round(sum(recent_max_vals)/len(recent_max_vals), 1) if recent_max_vals else None
        avg_min = round(sum(recent_min_vals)/len(recent_min_vals), 1) if recent_min_vals else None
        t_avg   = round((avg_max + avg_min)/2, 1) if avg_max and avg_min else None

        recent_gusts = [g for g in wind[-3:] if g is not None]
        w3     = round(max(recent_gusts, default=0))
        w3_avg = round(sum(recent_gusts)/len(recent_gusts), 1) if recent_gusts else 0

        recent_hum = [h for h in humidity[-5:] if h is not None]
        avg_hum = round(sum(recent_hum)/len(recent_hum), 1) if recent_hum else None

        wind_thresh = {"high": 25, "medium": 35, "low": 50}.get(sp["wind_sensitivity"], 35)

        results.append({
            "id":         sp["id"],
            "name":       sp["common_name"],
            "scientific": sp["scientific_name"],
            "score":      pct,
            "label":      label,
            "soil_match":   round(s_mult * 100),
            "forest_match": round(f_mult * 100),
            "breakdown": {
                "pluja":       round(r_sc * 100),
                "temperatura": round(t_sc * 100),
                "vent":        round(w_sc * 100),
                "altitud":     round(a_sc * 100),
                "humitat":     round(h_sc * 100),
            },
            "weather": {
                "rain_7d":  p7,
                "rain_14d": p14,
                "temp_avg": t_avg,
                "avg_max":  avg_max,
                "avg_min":  avg_min,
                "wind_max": w3,
                "wind_avg": w3_avg,
                "humidity": avg_hum,
                "pre_dry_days": pre_dry,
            },
            # species thresholds — sent to frontend for explanation
            "thresholds": {
                "rain_trigger_mm":      sp["rain_trigger_mm"],
                "rain_window_days":     sp["rain_window_days"],
                "dry_spell_before_days":sp["dry_spell_before_days"],
                "temp_ideal_min":       sp["temperature_c"]["ideal_min"],
                "temp_ideal_max":       sp["temperature_c"]["ideal_max"],
                "temp_min":             sp["temperature_c"]["min"],
                "temp_max":             sp["temperature_c"]["max"],
                "wind_sensitivity":     sp["wind_sensitivity"],
                "wind_threshold_kmh":   wind_thresh,
                "alt_ideal_min":        sp["altitude_m"]["ideal_min"],
                "alt_ideal_max":        sp["altitude_m"]["ideal_max"],
                "soil_ph":              sp["soil"]["ph"],
                "tree_keywords":        sp["tree_keywords"][:4],
                "prefers_scots_pine":   sp.get("prefers_scots_pine", False),
            },
            "soil_type":    geo["soil_type"],
            "litho_text":   geo["litho_text"],
            "forest_code":  geo["forest_code"],
            "forest_label": geo["forest_label"],
            "ph":           geo.get("ph"),
            "notes":        sp["notes"],
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ── API handler ───────────────────────────────────────────────────────────────

def build_forecast():
    """Run full forecast for all stations. Returns structured dict."""
    output = {
        "date":    date.today().isoformat(),
        "comarques": {}
    }

    stations = get_stations()

    def process_station(comarca, station):
        try:
            weather = fetch_weather(station["lat"], station["lon"])
            geo     = fetch_geo(station["lat"], station["lon"])
            # Score all 7 forecast days (0=today … 6=day+6)
            days = []
            for offset in range(7):
                species = score_station(station, weather, geo, day_offset=offset)
                days.append(species)
            # Derive forecast dates from weather time array
            dates = weather.get("time", [])[-7:]
            return comarca, {
                "name":    station["name"],
                "lat":     station["lat"],
                "lon":     station["lon"],
                "alt_m":   station["alt_m"],
                "radius_m": station.get("radius_m", 2000),
                "notes":   station.get("notes", ""),
                "geo":     geo,
                "quality": data_quality(weather, geo),
                "days":    days,    # list[7] of species lists
                "dates":   dates,   # list[7] of ISO date strings
                "species": days[0], # today — kept for backward compat
            }
        except Exception as e:
            return comarca, {
                "name":    station["name"],
                "lat":     station["lat"],
                "lon":     station["lon"],
                "alt_m":   station["alt_m"],
                "radius_m": station.get("radius_m", 2000),
                "notes":   station.get("notes", ""),
                "error":   str(e),
                "geo":     {},
                "quality": {"pct": 0, "label": "baixa", "reasons": ["error de dades"]},
                "days":    [[] for _ in range(7)],
                "dates":   [],
                "species": [],
            }

    all_tasks = []
    for comarca, stns in stations.items():
        output["comarques"][comarca] = []
        for stn in stns:
            all_tasks.append((comarca, stn))

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(process_station, c, s): (c, s)
                   for c, s in all_tasks}
        results_map = {c: [] for c in stations}
        for fut in as_completed(futures):
            comarca, data = fut.result()
            results_map[comarca].append(data)

    # Preserve station order
    for comarca, stns in stations.items():
        station_names = [s["name"] for s in stns]
        ordered = sorted(results_map[comarca],
                         key=lambda x: station_names.index(x["name"])
                         if x["name"] in station_names else 99)
        output["comarques"][comarca] = ordered

    return output

# ── HTML page (embedded) ──────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="ca">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bolets Forecast — Catalunya</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f5f0eb;
    color: #2a2015;
    height: 100dvh;
    display: flex;
    flex-direction: column;
  }

  header {
    background: #2a2015;
    color: #f5f0eb;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    gap: 16px;
    flex-shrink: 0;
  }
  header h1 { font-size: 1.1rem; font-weight: 600; letter-spacing: 0.01em; }
  header .date { font-size: 0.8rem; opacity: 0.6; margin-left: auto; }
  .status-bar {
    font-size: 0.75rem;
    padding: 6px 20px;
    background: #e8e0d5;
    border-bottom: 1px solid #cdc4b8;
    flex-shrink: 0;
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .status-bar .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #bbb; display: inline-block;
  }
  .status-bar .dot.loading { background: #f0a500; animation: pulse 1s infinite; }
  .status-bar .dot.ok { background: #4a8c3f; }
  .status-bar .dot.err { background: #c0392b; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }

  .main {
    display: flex;
    flex: 1;
    overflow: hidden;
  }

  /* ── Sidebar ── */
  .sidebar {
    width: 380px;
    flex-shrink: 0;
    overflow-y: auto;
    background: #faf7f3;
    border-right: 1px solid #ddd6cc;
    display: flex;
    flex-direction: column;
  }
  #station-list { flex: 1; overflow-y: auto; }

  /* ── Toolbar: search + filters ── */
  .toolbar {
    position: sticky;
    top: 0;
    z-index: 8;
    background: #faf7f3;
    border-bottom: 1px solid #ddd6cc;
    padding: 10px 12px 8px;
    flex-shrink: 0;
  }
  .search-wrap { position: relative; }
  .search-icon {
    position: absolute;
    left: 9px; top: 50%;
    transform: translateY(-50%);
    font-size: 0.8rem;
    opacity: 0.5;
    pointer-events: none;
  }
  #search-input {
    width: 100%;
    padding: 9px 30px 9px 30px;
    border: 1px solid #cdc4b8;
    border-radius: 8px;
    background: #fff;
    font-size: 0.82rem;
    color: #2a2015;
  }
  #search-input:focus {
    outline: 2px solid #7a4c2a;
    outline-offset: 1px;
  }
  #search-clear {
    position: absolute;
    right: 5px; top: 50%;
    transform: translateY(-50%);
    display: none;
    width: 22px; height: 22px;
    border: none; border-radius: 50%;
    background: #e8e2d8;
    color: #5a4a38;
    font-size: 0.7rem;
    cursor: pointer;
  }
  #search-clear.visible { display: block; }
  .filter-row {
    display: flex;
    gap: 6px;
    margin-top: 7px;
  }
  .filter-row select {
    flex: 1;
    min-width: 0;
    padding: 6px 6px;
    border: 1px solid #cdc4b8;
    border-radius: 6px;
    background: #fff;
    font-size: 0.7rem;
    color: #5a4a38;
  }
  .filter-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-top: 6px;
    font-size: 0.68rem;
    color: #7a6e62;
  }
  .filter-check {
    display: flex;
    align-items: center;
    gap: 5px;
    cursor: pointer;
  }
  .filter-check input { accent-color: #7a4c2a; }
  #result-count { white-space: nowrap; font-variant-numeric: tabular-nums; }

  /* ── Free best zones leaderboard ── */
  .best-zones {
    padding: 8px 12px 6px;
    border-bottom: 1px solid #ddd6cc;
    background: #f0ebe4;
    flex-shrink: 0;
  }
  .best-zones-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 4px;
  }
  .best-zones-title {
    font-size: 0.62rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7a4c2a;
  }
  .best-zones-sub { font-size: 0.6rem; color: #7a6e62; }
  .best-zone {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 4px 4px;
    cursor: pointer;
    border-radius: 6px;
  }
  .best-zone:hover { background: #e8e2d8; }
  .best-zone-rank {
    width: 16px;
    font-size: 0.65rem;
    color: #9a8870;
    font-weight: 700;
    text-align: right;
    flex-shrink: 0;
  }
  .best-zone-name {
    flex: 1;
    min-width: 0;
    font-size: 0.72rem;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .best-zone-meta {
    font-size: 0.6rem;
    color: #7a6e62;
    white-space: nowrap;
  }
  .best-zone-route {
    border: none;
    background: none;
    cursor: pointer;
    font-size: 0.8rem;
    padding: 2px 3px;
    color: #7a4c2a;
    flex-shrink: 0;
  }
  .best-zone-route:hover { color: #2a2015; }
  .best-empty { font-size: 0.68rem; color: #7a6e62; padding: 2px 0 4px; }

  /* ── Station card extras ── */
  .card-top {
    display: flex;
    align-items: baseline;
    gap: 6px;
    margin-bottom: 5px;
  }
  .card-top .station-name { flex: 1; margin-bottom: 0; }
  .route-mini {
    border: 1px solid #cdc4b8;
    background: #fff;
    border-radius: 5px;
    font-size: 0.66rem;
    padding: 2px 5px;
    cursor: pointer;
    color: #7a4c2a;
    flex-shrink: 0;
  }
  .route-mini:hover { background: #e8e2d8; }
  .best-day-tag {
    font-size: 0.6rem;
    color: #7a4c2a;
    background: #f7efe6;
    border: 1px solid #e0d2c2;
    border-radius: 8px;
    padding: 1px 5px;
    white-space: nowrap;
  }
  .sp-selected { background: #f7efe6; border-radius: 4px; padding: 1px 3px; }
  .filter-empty {
    padding: 26px 16px;
    text-align: center;
    font-size: 0.8rem;
    color: #7a6e62;
    line-height: 1.6;
  }

  /* ── Detail trip actions ── */
  .trip-actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    padding: 10px 16px;
    border-bottom: 1px solid #e8e2d8;
  }
  .trip-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 6px 9px;
    font-size: 0.7rem;
    font-weight: 600;
    background: #f0ebe4;
    border: 1px solid #cdc4b8;
    border-radius: 6px;
    color: #5a4a38;
    cursor: pointer;
    text-decoration: none;
  }
  .trip-btn:hover { background: #e4ddd4; }
  .trip-btn.primary {
    background: #7a4c2a;
    border-color: #7a4c2a;
    color: #fff;
  }
  .trip-btn.primary:hover { background: #5f3a20; }
  .parking-list {
    padding: 0 16px 10px;
    font-size: 0.7rem;
    color: #5a4a38;
    line-height: 1.6;
  }
  .parking-list a { color: #7a4c2a; }
  .parking-list .muted { color: #7a6e62; }

  /* ── Data quality ── */
  .quality-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-bottom: 1px solid #e8e2d8;
    font-size: 0.68rem;
    color: #7a6e62;
  }
  .quality-bar {
    flex: 1;
    height: 5px;
    border-radius: 3px;
    background: #e0d8ce;
    overflow: hidden;
  }
  .quality-bar-fill { height: 100%; border-radius: 3px; }
  .quality-label { font-weight: 700; color: #5a4a38; white-space: nowrap; }

  /* ── 7-day strip in detail ── */
  .day-strip {
    display: flex;
    gap: 3px;
    padding: 9px 16px;
    border-bottom: 1px solid #e8e2d8;
  }
  .day-cell {
    flex: 1;
    text-align: center;
    border-radius: 5px;
    padding: 4px 2px;
    background: #f0ebe4;
    border: 1px solid transparent;
    cursor: pointer;
  }
  .day-cell:hover { border-color: #cdc4b8; }
  .day-cell.active { border-color: #7a4c2a; background: #f7efe6; }
  .day-cell .dc-day { font-size: 0.58rem; color: #7a6e62; text-transform: uppercase; }
  .day-cell .dc-score { font-size: 0.78rem; font-weight: 800; margin-top: 1px; }
  .day-cell .dc-bar { height: 3px; border-radius: 2px; background: #e0d8ce; margin-top: 3px; overflow: hidden; }
  .day-cell .dc-bar-fill { height: 100%; }

  /* ── Marker clusters in the app's palette ── */
  .marker-cluster-small,
  .marker-cluster-medium,
  .marker-cluster-large { background: rgba(122, 76, 42, 0.22); }
  .marker-cluster-small div,
  .marker-cluster-medium div,
  .marker-cluster-large div {
    background: #7a4c2a;
    color: #fff;
    font-weight: 700;
    font-family: inherit;
  }

  /* ── Map legend ── */
  .map-legend {
    background: rgba(250,247,243,0.94);
    border: 1px solid #cdc4b8;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 0.68rem;
    color: #5a4a38;
    line-height: 1.6;
    box-shadow: 0 1px 6px rgba(0,0,0,0.12);
    max-width: 180px;
  }
  .legend-title {
    font-size: 0.6rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7a4c2a;
    margin-bottom: 3px;
  }
  .legend-dot {
    display: inline-block;
    width: 9px; height: 9px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }
  .legend-note {
    margin-top: 4px;
    padding-top: 4px;
    border-top: 1px solid #e0d8ce;
    font-size: 0.6rem;
    color: #7a6e62;
    line-height: 1.4;
  }
  @media (max-width: 700px) {
    .map-legend { display: none; }
  }

  .comarca-section { border-bottom: 1px solid #ddd6cc; }
  .comarca-header {
    padding: 10px 16px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7a6e62;
    background: #f0ebe4;
    cursor: pointer;
    user-select: none;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .comarca-header:hover { background: #e8e2d8; }
  .comarca-header .chevron { transition: transform 0.2s; }
  .comarca-header.collapsed .chevron { transform: rotate(-90deg); }
  .comarca-body.collapsed { display: none; }

  .station-card {
    padding: 10px 16px 12px;
    border-bottom: 1px solid #e8e2d8;
    cursor: pointer;
    transition: background 0.15s;
  }
  .station-card:hover { background: #f0ebe4; }
  .station-card.active { background: #e8e2d8; border-left: 3px solid #7a4c2a; }
  .station-name {
    font-size: 0.85rem;
    font-weight: 600;
    margin-bottom: 6px;
  }
  .station-meta {
    font-size: 0.72rem;
    color: #7a6e62;
    margin-bottom: 8px;
    display: flex;
    gap: 10px;
  }
  .top-species {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .species-row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.75rem;
  }
  .score-pill {
    width: 36px;
    height: 18px;
    border-radius: 9px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.68rem;
    font-weight: 700;
    flex-shrink: 0;
    color: white;
  }
  .score-bar {
    height: 4px;
    border-radius: 2px;
    flex: 1;
    max-width: 80px;
    background: #e0d8ce;
    overflow: hidden;
  }
  .score-bar-fill { height: 100%; border-radius: 2px; }
  .score-high   { background: #4a8c3f; }
  .score-mid    { background: #c08b00; }
  .score-low    { background: #a0573a; }
  .score-none   { background: #b0a090; }

  /* ── Map ── */
  #map {
    flex: 1;
  }

  /* ── Detail panel ── */
  .detail-panel {
    width: 320px;
    flex-shrink: 0;
    overflow-y: auto;
    background: #faf7f3;
    border-left: 1px solid #ddd6cc;
    display: none;
  }
  .detail-panel.visible { display: block; }
  .detail-header {
    padding: 14px 16px 10px;
    border-bottom: 1px solid #e8e2d8;
    position: sticky;
    top: 0;
    background: #faf7f3;
    z-index: 1;
  }
  .detail-header h2 { font-size: 0.95rem; font-weight: 700; }
  .detail-header .alt { font-size: 0.75rem; color: #7a6e62; margin-top: 2px; }
  .detail-close {
    position: absolute;
    top: 12px; right: 14px;
    background: none; border: none;
    font-size: 1.1rem; cursor: pointer; color: #7a6e62;
    line-height: 1;
  }
  .detail-close:hover { color: #2a2015; }

  .geo-badges {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    padding: 10px 16px;
    border-bottom: 1px solid #e8e2d8;
  }
  .badge {
    font-size: 0.68rem;
    padding: 3px 8px;
    border-radius: 10px;
    font-weight: 600;
    border: 1px solid;
  }
  .badge-cal  { background: #fff3e0; border-color: #f0a500; color: #7a5500; }
  .badge-sil  { background: #e8f5e9; border-color: #4a8c3f; color: #2a5a20; }
  .badge-mix  { background: #fce4ec; border-color: #c07080; color: #7a2040; }
  .badge-unk  { background: #f5f5f5; border-color: #bbb; color: #666; }
  .badge-for  { background: #e3f2fd; border-color: #5b9bd5; color: #2a5080; }
  .badge-ph   { background: #f3e5f5; border-color: #9c6bb5; color: #5a3070; }

  .litho-text {
    padding: 6px 16px 10px;
    font-size: 0.7rem;
    color: #7a6e62;
    font-style: italic;
    border-bottom: 1px solid #e8e2d8;
  }

  .weather-summary {
    display: flex;
    gap: 0;
    border-bottom: 1px solid #e8e2d8;
  }
  .weather-stat {
    flex: 1;
    text-align: center;
    padding: 10px 4px;
    border-right: 1px solid #e8e2d8;
  }
  .weather-stat:last-child { border-right: none; }
  .weather-val { font-size: 1.0rem; font-weight: 700; }
  .weather-lbl { font-size: 0.62rem; color: #7a6e62; margin-top: 2px; text-transform: uppercase; }

  .species-list { padding: 8px 0; }
  .sp-item {
    padding: 8px 16px;
    border-bottom: 1px solid #f0ebe4;
    cursor: pointer;
    transition: background 0.1s;
  }
  .sp-item:hover { background: #f0ebe4; }
  .sp-item.expanded { background: #f0ebe4; }
  .sp-top {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sp-name { font-size: 0.82rem; font-weight: 600; flex: 1; }
  .sp-sci  { font-size: 0.68rem; color: #7a6e62; margin-top: 1px; }
  .sp-label { font-size: 0.68rem; color: #7a6e62; }
  .sp-detail {
    display: none;
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #e8e2d8;
  }
  .sp-detail.visible { display: block; }
  .breakdown-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px 12px;
    margin-bottom: 8px;
  }
  .bd-item {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 0.7rem;
    color: #5a5048;
  }
  .bd-bar {
    flex: 1;
    height: 3px;
    background: #e0d8ce;
    border-radius: 2px;
    overflow: hidden;
  }
  .bd-bar-fill { height: 100%; border-radius: 2px; background: #7a4c2a; }
  .sp-notes {
    font-size: 0.68rem;
    color: #7a6e62;
    font-style: italic;
    line-height: 1.4;
  }
  .geo-mult {
    font-size: 0.68rem;
    color: #7a6e62;
    margin-bottom: 6px;
  }

  .loading-overlay {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    font-size: 0.85rem;
    color: #7a6e62;
  }

  /* Leaflet marker colors */
  .marker-high  { background: #4a8c3f; }
  .marker-mid   { background: #c08b00; }
  .marker-low   { background: #a0573a; }
  .marker-none  { background: #b0a090; }
  .custom-marker {
    border-radius: 50%;
    border: 2px solid white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.35);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 700;
    color: white;
    cursor: pointer;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
  }
  .custom-marker.marker-hl {
    transform: scale(1.2);
    box-shadow: 0 0 0 3px rgba(122,76,42,0.55), 0 2px 8px rgba(0,0,0,0.35);
    z-index: 1000;
  }
  .station-card.hovered { background: #f0ebe4; }

  /* ── Explain overlay ── */
  .explain-overlay {
    display: none;
    position: fixed;
    inset: 0;
    z-index: 9000;
    background: rgba(30,20,10,0.55);
    backdrop-filter: blur(2px);
    align-items: center;
    justify-content: center;
  }
  .explain-overlay.visible { display: flex; }
  .explain-box {
    background: #faf7f3;
    border-radius: 12px;
    width: min(680px, 96vw);
    max-height: 88vh;
    overflow-y: auto;
    box-shadow: 0 8px 40px rgba(0,0,0,0.3);
    display: flex;
    flex-direction: column;
  }
  .explain-header {
    position: sticky;
    top: 0;
    background: #2a2015;
    color: #f5f0eb;
    padding: 16px 20px 14px;
    border-radius: 12px 12px 0 0;
    display: flex;
    align-items: flex-start;
    gap: 12px;
    z-index: 1;
  }
  .explain-header h2 { font-size: 1rem; font-weight: 700; flex: 1; }
  .explain-header .sci { font-size: 0.72rem; opacity: 0.6; margin-top: 3px; }
  .explain-close {
    background: none; border: none; color: #f5f0eb;
    font-size: 1.2rem; cursor: pointer; line-height: 1;
    padding: 0; opacity: 0.7; flex-shrink: 0;
  }
  .explain-close:hover { opacity: 1; }
  .explain-score-hero {
    text-align: center;
    padding: 20px 20px 10px;
    border-bottom: 1px solid #e8e2d8;
  }
  .explain-score-big {
    font-size: 3.5rem;
    font-weight: 800;
    line-height: 1;
  }
  .explain-score-label {
    font-size: 0.8rem;
    color: #7a6e62;
    margin-top: 4px;
  }
  .explain-body { padding: 0 20px 24px; }
  .explain-section {
    margin-top: 20px;
  }
  .explain-section-title {
    font-size: 0.65rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #7a4c2a;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 2px solid #e8e2d8;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .explain-card {
    background: white;
    border: 1px solid #e8e2d8;
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 8px;
  }
  .explain-card-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 6px;
  }
  .explain-label {
    font-size: 0.7rem;
    font-weight: 700;
    color: #5a5048;
    flex-shrink: 0;
    width: 90px;
  }
  .explain-value {
    font-size: 0.9rem;
    font-weight: 700;
    color: #2a2015;
  }
  .explain-need {
    font-size: 0.72rem;
    color: #7a6e62;
    margin-left: auto;
    text-align: right;
  }
  .explain-verdict {
    font-size: 0.75rem;
    line-height: 1.5;
    color: #3a3028;
    margin-top: 4px;
  }
  .explain-verdict b { color: #2a2015; }
  .verdict-good  { color: #2a6020; }
  .verdict-ok    { color: #7a5500; }
  .verdict-bad   { color: #8a2000; }
  .explain-meter {
    height: 6px;
    background: #e8e2d8;
    border-radius: 3px;
    margin: 6px 0 8px;
    overflow: hidden;
  }
  .explain-meter-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.4s ease;
  }
  .learn-more-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 8px;
    padding: 4px 10px;
    font-size: 0.7rem;
    font-weight: 600;
    background: #f0ebe4;
    border: 1px solid #cdc4b8;
    border-radius: 6px;
    cursor: pointer;
    color: #5a4a38;
    transition: background 0.15s;
  }
  .learn-more-btn:hover { background: #e4ddd4; }

  /* ── Day selector ── */
  .day-selector {
    background: #2a2015;
    padding: 6px 16px;
    display: flex;
    gap: 4px;
    align-items: center;
    flex-shrink: 0;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }
  .day-selector-label {
    font-size: 0.65rem;
    color: #9a8870;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-right: 6px;
    white-space: nowrap;
  }
  .day-btn {
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid #4a3a28;
    background: #3d3020;
    color: #c8b898;
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;
    white-space: nowrap;
    transition: background 0.15s, color 0.15s;
    -webkit-tap-highlight-color: transparent;
  }
  .day-btn:hover { background: #5a4530; color: #f5f0eb; }
  .day-btn.active { background: #7a4c2a; border-color: #9a6a40; color: white; }

  /* ── Mobile tab bar ── */
  .tab-bar {
    display: none;
  }

  /* ══════════════════════════════════════════════
     MOBILE  ≤ 700px
  ══════════════════════════════════════════════ */
  @media (max-width: 700px) {

    body { font-size: 15px; }

    header { padding: 10px 14px; }
    header h1 { font-size: 1rem; }
    header .date { display: none; }

    .status-bar { padding: 5px 14px; font-size: 0.7rem; }

    .day-selector { padding: 5px 10px; gap: 5px; }
    .day-btn { padding: 5px 10px; font-size: 0.7rem; line-height: 1.3; }

    /* Stack: map fills the screen, sidebar hidden behind tab */
    .main {
      position: relative;
      flex-direction: column;
    }

    .sidebar {
      display: none;
      width: 100%;
      height: 100%;
      position: absolute;
      top: 0; left: 0;
      z-index: 1100;
      overflow-y: auto;
      border-right: none;
      padding-bottom: 60px; /* room for tab bar */
    }
    .sidebar.mob-visible { display: block; }
    #station-list { overflow: visible; }
    .toolbar { padding: 8px 10px 6px; }
    #search-input { font-size: 0.85rem; padding: 10px 32px 10px 32px; }
    .filter-row select { font-size: 0.68rem; padding: 7px 5px; }
    .best-zones { padding: 7px 10px 5px; }
    .best-zone { padding: 5px 4px; }

    #map {
      width: 100%;
      height: 100%;
    }

    /* Detail panel: full-screen slide up from bottom */
    .detail-panel {
      display: none;
      width: 100%;
      position: fixed;
      bottom: 0; left: 0; right: 0;
      top: auto;
      height: 75vh;
      z-index: 1200;
      border-left: none;
      border-top: 2px solid #cdc4b8;
      border-radius: 14px 14px 0 0;
      box-shadow: 0 -4px 24px rgba(0,0,0,0.18);
      padding-bottom: 58px; /* keep the last row above the tab bar */
    }
    .detail-panel.visible {
      display: block;
    }
    /* drag handle visual */
    .detail-panel::before {
      content: '';
      display: block;
      width: 36px; height: 4px;
      background: #cdc4b8;
      border-radius: 2px;
      margin: 8px auto 0;
    }

    /* Tab bar at bottom */
    .tab-bar {
      display: flex;
      position: fixed;
      bottom: 0; left: 0; right: 0;
      height: 52px;
      background: #2a2015;
      border-top: 1px solid #4a3a28;
      z-index: 1300;
    }
    .tab-btn {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 3px;
      background: none;
      border: none;
      color: #9a8870;
      font-size: 0.6rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      cursor: pointer;
      -webkit-tap-highlight-color: transparent;
      transition: color 0.15s;
    }
    .tab-btn .tab-icon { font-size: 1.2rem; line-height: 1; }
    .tab-btn.active { color: #f5f0eb; }
    .tab-btn.active .tab-icon { filter: drop-shadow(0 0 4px rgba(255,220,150,0.6)); }

    /* Push map content above tab bar */
    .main { padding-bottom: 52px; }

    /* Comarca headers bigger tap target */
    .comarca-header { padding: 14px 16px; font-size: 0.72rem; }

    /* Station cards: bigger, more spacing */
    .station-card { padding: 12px 16px 14px; }
    .station-name { font-size: 0.9rem; }
    .station-meta { font-size: 0.74rem; gap: 8px; flex-wrap: wrap; }
    .species-row { gap: 8px; }
    .score-pill { width: 40px; height: 22px; font-size: 0.72rem; }

    /* Explain overlay already uses min(680px,96vw) - fine on mobile */
    .explain-body { padding: 0 14px 80px; }
  }
</style>
</head>
<body>

<header>
  <span style="font-size:1.5rem">🍄</span>
  <h1 id="app-title">Bolets Forecast · Catalunya</h1>
  <span class="date" id="hdr-date"></span>
  <button id="lang-btn" onclick="setLang(lang==='ca'?'en':'ca')"
    style="margin-left:12px;padding:4px 12px;font-size:0.75rem;font-weight:700;
           background:#3d3020;border:1px solid #6a5a40;border-radius:6px;
           color:#f5f0eb;cursor:pointer;letter-spacing:0.05em">EN</button>
</header>

<!-- Day selector -->
<div class="day-selector" id="day-selector" style="display:none">
  <!-- filled by JS -->
</div>

<div class="status-bar">
  <span class="dot loading" id="status-dot"></span>
  <span id="status-text">Carregant dades...</span>
</div>

<div class="main">
  <div class="sidebar" id="sidebar">
    <div class="toolbar">
      <div class="search-wrap">
        <span class="search-icon">🔍</span>
        <input id="search-input" type="search" autocomplete="off"
               placeholder="Cerca lloc, bosc, municipi o espècie…"
               aria-label="Cerca lloc, bosc, municipi o espècie">
        <button id="search-clear" aria-label="Neteja la cerca">✕</button>
      </div>
      <div class="filter-row">
        <select id="filter-species" aria-label="Filtra per espècie">
          <option value="">Totes les espècies</option>
        </select>
        <select id="filter-comarca" aria-label="Filtra per comarca">
          <option value="">Totes les comarques</option>
        </select>
      </div>
      <div class="filter-row">
        <select id="filter-sort" aria-label="Ordena les zones">
          <option value="score">Millor puntuació</option>
          <option value="distance">Més a prop</option>
          <option value="altitude">Altitud</option>
          <option value="name">Nom</option>
          <option value="comarca">Comarca</option>
        </select>
      </div>
      <div class="filter-meta">
        <label class="filter-check">
          <input type="checkbox" id="filter-min"> <span id="filter-min-label">Només ≥ 55</span>
        </label>
        <span id="result-count"></span>
      </div>
    </div>
    <div class="best-zones" id="best-zones"></div>
    <div id="station-list">
      <div class="loading-overlay">Carregant...</div>
    </div>
  </div>
  <div id="map"></div>
  <div class="detail-panel" id="detail-panel">
    <div class="loading-overlay">Selecciona una estació</div>
  </div>
</div>

<!-- Mobile tab bar -->
<nav class="tab-bar" id="tab-bar">
  <button class="tab-btn active" id="tab-map" onclick="switchTab('map')">
    <span class="tab-icon">🗺️</span>
    <span id="tab-map-lbl">Mapa</span>
  </button>
  <button class="tab-btn" id="tab-list" onclick="switchTab('list')">
    <span class="tab-icon">🍄</span>
    <span id="tab-list-lbl">Zones</span>
  </button>
</nav>

<!-- Explain overlay -->
<div class="explain-overlay" id="explain-overlay" onclick="closeExplain(event)">
  <div class="explain-box" id="explain-box"></div>
</div>

<script>
// ── Map init ──────────────────────────────────────────────────────────────────
const map = L.map('map', {
  center: [42.24, 2.05],
  zoom: 11,
  zoomControl: true,
});

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 18,
}).addTo(map);

L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

// Marker clustering keeps the map readable as the station list grows.
const markerCluster = (typeof L.markerClusterGroup === 'function')
  ? L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 48,
      disableClusteringAtZoom: 14,
      spiderfyOnMaxZoom: true,
    })
  : L.layerGroup();
map.addLayer(markerCluster);

let searchMarker = null;

// Optional: ICGC topo overlay
const icgcTopo = L.tileLayer(
  'https://geoserveis.icgc.cat/servei/catalunya/mapa-base/wmts/topografic/MON3857NW/{z}/{x}/{y}.png',
  { attribution: '© ICGC', opacity: 0.5, maxZoom: 18 }
);

let icgcOn = false;
const topoBtn = L.control({ position: 'topright' });
topoBtn.onAdd = () => {
  const btn = L.DomUtil.create('button');
  btn.textContent = 'Topo ICGC';
  btn.style.cssText = 'padding:4px 10px;font-size:11px;cursor:pointer;background:white;border:1px solid #ccc;border-radius:4px;';
  L.DomEvent.on(btn, 'click', () => {
    icgcOn = !icgcOn;
    icgcOn ? icgcTopo.addTo(map) : map.removeLayer(icgcTopo);
    btn.style.background = icgcOn ? '#e8e2d8' : 'white';
  });
  return btn;
};
topoBtn.addTo(map);

// "Where am I" control, free and always visible.
const locateBtn = L.control({ position: 'topright' });
locateBtn.onAdd = () => {
  const btn = L.DomUtil.create('button');
  btn.id = 'locate-btn';
  btn.textContent = '◎ Situa\'m';
  btn.title = 'Centra el mapa i ordena les zones per distància';
  btn.style.cssText = 'padding:4px 10px;font-size:11px;cursor:pointer;background:white;border:1px solid #ccc;border-radius:4px;margin-top:6px;';
  L.DomEvent.on(btn, 'click', () => requestUserPos(true));
  return btn;
};
locateBtn.addTo(map);

// Always-visible score legend. "Not evaluated" is deliberately separate from 0.
function legendHtml() {
  return `
    <div class="legend-title">${U('legendTitle')}</div>
    <div><span class="legend-dot" style="background:#4a8c3f"></span>${U('legendVeryGood')}</div>
    <div><span class="legend-dot" style="background:#c08b00"></span>${U('legendGood')}</div>
    <div><span class="legend-dot" style="background:#a0573a"></span>${U('legendPossible')}</div>
    <div><span class="legend-dot" style="background:#b0a090"></span>${U('legendLow')}</div>
    <div class="legend-note">${U('legendNote')}</div>`;
}

const legend = L.control({ position: 'bottomright' });
legend.onAdd = () => {
  const div = L.DomUtil.create('div', 'map-legend');
  // Static fallback; applyStaticText() localises it once the app boots.
  div.innerHTML = `
    <div class="legend-title">Puntuació</div>
    <div><span class="legend-dot" style="background:#4a8c3f"></span>Molt bona · 75+</div>
    <div><span class="legend-dot" style="background:#c08b00"></span>Bona · 55–74</div>
    <div><span class="legend-dot" style="background:#a0573a"></span>Possible · 35–54</div>
    <div><span class="legend-dot" style="background:#b0a090"></span>Baixa · &lt;35</div>
    <div class="legend-note">Color = condicions estimades, no observacions.</div>`;
  L.DomEvent.disableClickPropagation(div);
  return div;
};
legend.addTo(map);

// ── i18n ─────────────────────────────────────────────────────────────────────
const TRANSLATIONS = {
  ca: {
    appTitle: 'Bolets Forecast · Catalunya',
    loading: 'Carregant dades...', loadingGeo: 'Carregant dades meteorològiques i geogràfiques...',
    statusOk: (d) => `Dades de ${d} · Open-Meteo + IGME + CORINE`,
    selectStation: 'Selecciona una estació',
    today: 'Avui', tomorrow: 'Demà',
    dayNames: ['Dg','Dl','Dt','Dc','Dj','Dv','Ds'],
    monthNames: ['gen','feb','mar','abr','mai','jun','jul','ago','set','oct','nov','des'],
    scoreLabels: { 'Molt bona':'Molt bona','Bona':'Bona','Possible':'Possible','Baixa':'Baixa' },
    rain7d: 'Pluja 7d', tempAvg: 'Temp mitjana', windMax: 'Vent màx km/h',
    altLabel: '⬆', topoBtn: 'Topo ICGC',
    learnMore: '✦ Aprèn més — per què aquesta puntuació?',
    soilLbl: 'Sòl detectat', forestLbl: 'Bosc (CORINE)',
    needsLbl: 'Necessita', rain7dLbl: 'Caiguts (7d)', minLbl: 'Mínim',
    tempLbl: 'Mitjana 5d', idealLbl: 'Ideal', windLbl: 'Ratxa màx 3d', threshLbl: 'Llindar',
    altLbl: 'Elevació', humLbl: 'HR màx 5d', goodLbl: 'Bo',
    secSoil: '🪨 Sòl i vegetació', secRain: '🌧 Pluja', secTemp: '🌡 Temperatura',
    secWind: '💨 Vent', secAlt: '⛰ Altitud', secHum: '💧 Humitat',
    overallScore: 'puntuació global',
    overallExplain: 'El càlcul combina condicions meteorològiques (pluja, temperatura, vent, altitud, humitat) multiplicades per la idoneïtat del sòl i el tipus de bosc detectats per satèl·lit.',
    soilTypes: { calcareous:'calcari (bàsic)', siliceous:'silícic (àcid)', mixed:'mixt', unknown:'desconegut' },
    phPrefs: {
      acid:'àcid (pH < 6.5)', basic:'bàsic (pH > 7)',
      neutral_to_acid:'neutre a lleugerament àcid', neutral_to_slightly_acid:'neutre a lleugerament àcid',
      neutral:'neutre', basic_to_neutral:'bàsic a neutre',
    },
    forestDescs: {
      '311':'bosc de fulla caduca (roure, faig, castanyer)', '312':'bosc de coníferes (pi, avet)',
      '313':'bosc mixt (coníferes i fulla caduca)', '324':'matollar de transició cap a bosc',
    },
    windSens: { high:'alta', medium:'mitjana', low:'baixa' },
    soilVerdicts: {
      great: (n,sp,ph) => `<b class="verdict-good">Excel·lent concordança.</b> El sòl ${n} s'ajusta perfectament al que necessita el ${sp}. Prefereix sòls ${ph}.`,
      ok: (n,sp,ph) => `<b class="verdict-ok">Concordança parcial.</b> El sòl ${n} no és ideal però tampoc descarta el ${sp}. Prefereix ${ph}.`,
      bad: (n,sp,ph) => `<b class="verdict-bad">Sòl inadequat.</b> El sòl ${n} és el contrari del que prefereix el ${sp} (${ph}).`,
      igme: (txt) => ` L'IGME descriu la roca mare com: <em>"${txt}"</em>.`,
      ph: (ph) => ` pH mesurat (SoilGrids): <b>${ph}</b>.`,
    },
    forestVerdicts: {
      great: (fd,sp,tr) => `<b class="verdict-good">Bosc ideal.</b> CORINE detecta ${fd}, exactament el que necessita el ${sp} (associat a: ${tr}).`,
      ok: (fd,sp,tr) => `<b class="verdict-ok">Bosc acceptable.</b> CORINE detecta ${fd}. El ${sp} pot aparèixer però no és el seu hàbitat preferit (vol: ${tr}).`,
      bad: (fd,sp,tr) => `<b class="verdict-bad">Bosc poc adequat.</b> CORINE detecta ${fd}, però el ${sp} prefereix ${tr}.`,
      pine: () => ' Especialment abundant en pinedes de pi roig (<em>Pinus sylvestris</em>) obertes.',
    },
    rainVerdicts: {
      great:(mm,need,days) => `<b class="verdict-good">Pluja excel·lent.</b> Han caigut <b>${mm}mm</b> els darrers 7 dies. Mínim necessari: <b>${need}mm</b> en ${days} dies. `,
      ok:(mm,need,days) => `<b class="verdict-ok">Pluja suficient.</b> Han caigut <b>${mm}mm</b> els darrers 7 dies (mínim: ${need}mm/${days}d). `,
      bad:(mm,need,days) => `<b class="verdict-bad">Pluja insuficient.</b> Només <b>${mm}mm</b> els darrers 7 dies, quan calen almenys <b>${need}mm</b> en ${days} dies. `,
      dryBonus:(n) => `A més, hi havia una <b>sequera prèvia d'almenys ${n} dies secs</b> — el miceli sec s'activa millor amb una pluja forta i sobtada.`,
      noDry:(n) => `No s'ha detectat una sequera prèvia clara (calen ~${n} dies secs), cosa que redueix el potencial d'activació.`,
    },
    tempVerdicts: {
      great:(avg,mx,mn,imin,imax) => `<b class="verdict-good">Temperatura ideal.</b> Màxima ${mx}°C, mínima ${mn}°C (promig ~${avg}°C). Rang ideal: <b>${imin}–${imax}°C</b>. `,
      ok:(avg,imin,imax) => `<b class="verdict-ok">Temperatura acceptable.</b> ~${avg}°C (ideal: ${imin}–${imax}°C). `,
      cold:(avg,tmin) => `<b class="verdict-bad">Massa fred.</b> ${avg}°C és per sota del mínim de <b>${tmin}°C</b>. `,
      hot:(avg,tmax) => `<b class="verdict-bad">Massa calor.</b> ${avg}°C supera el màxim de <b>${tmax}°C</b>. `,
      explain:(tmin,tmax) => `Per sota de ${tmin}°C durant dies seguits el bolet es congela; per sobre de ${tmax}°C no fructifica.`,
    },
    windVerdicts: {
      great:(avg,w) => `<b class="verdict-good">Vent favorable.</b> Ratxa màxima de <b>${avg}km/h</b> els darrers 3 dies. `,
      ok:(avg) => `<b class="verdict-ok">Vent moderat.</b> Ratxa de <b>${avg}km/h</b>. `,
      bad:(avg,mx) => `<b class="verdict-bad">Vent excessiu.</b> Ratxa de <b>${avg}km/h</b> (màx ${mx}km/h). `,
      explain:(sp,sens,thr) => `El ${sp} té sensibilitat <b>${sens}</b> al vent. Per sobre de <b>${thr}km/h</b> el sòl s'asseca ràpidament. El vent de nord (Tramuntana) és especialment perjudicial.`,
    },
    altVerdicts: {
      great:(alt,imin,imax) => `<b class="verdict-good">Altitud perfecta.</b> <b>${alt}m</b>, dins la franja ideal de <b>${imin}–${imax}m</b>. `,
      ok:(alt,imin,imax) => `<b class="verdict-ok">Altitud acceptable.</b> ${alt}m (ideal: ${imin}–${imax}m). `,
      low:(alt,imin) => `<b class="verdict-bad">Massa baix.</b> ${alt}m és per sota de l'altitud ideal (>${imin}m). `,
      high:(alt,imax) => `<b class="verdict-bad">Massa alt.</b> ${alt}m supera el màxim de ${imax}m. `,
      explain: () => `Regla pràctica: cada 150m de guany perdem ~1°C. Els rovellons surten primer als 800m i pugen als 1.400m a mesura que avança la tardor.`,
    },
    humVerdicts: {
      great:(h) => `<b class="verdict-good">Humitat alta.</b> HR màxima de <b>${h}%</b>. `,
      ok:(h) => `<b class="verdict-ok">Humitat acceptable.</b> ${h}%. `,
      bad:(h) => `<b class="verdict-bad">Ambient sec.</b> Només ${h}% d'humitat. `,
      explain: () => `Per sota del 60–65% l'evaporació del sòl és ràpida, especialment en dies de vent. Una HR alta (>80%) dóna temps al miceli per fructificar.`,
    },
    stnNotes: 'Notes del bosc',
    ui: {
      searchPlaceholder: 'Cerca lloc, bosc, municipi o espècie…',
      allSpecies: 'Totes les espècies',
      allComarques: 'Totes les comarques',
      sortScore: 'Millor puntuació',
      sortDistance: 'Més a prop',
      sortAltitude: 'Altitud',
      sortName: 'Nom',
      sortComarca: 'Comarca',
      only55: 'Només ≥ 55',
      bestZones: 'Millors zones',
      freeNoSignup: 'gratuït · sense registre',
      noZones: 'Cap zona amb aquests filtres.',
      noZonesHint: 'Cap zona coincideix amb aquests filtres.',
      clearFilters: 'Neteja els filtres',
      best: 'millor',
      route: 'ruta',
      routeLong: 'Com arribar-hi',
      osm: 'OSM',
      parkingNear: 'Parking a prop',
      share: 'Comparteix',
      quality: 'Qualitat de dades',
      qualityHigh: 'alta',
      qualityMedium: 'mitjana',
      qualityLow: 'baixa',
      searchingParking: 'Buscant aparcaments a prop…',
      noParking: 'No hi ha aparcaments mapejats a 2,5 km. Fes servir la pista forestal i no bloquegis el pas.',
      parkingError: "No s'ha pogut consultar Overpass. Obre OSM per veure la zona.",
      linkCopied: 'Enllaç copiat:',
      searchingPlace: 'Cercant',
      noPlace: 'Cap lloc trobat',
      goingTo: 'Anant a',
      geolocating: 'Obtenint la teva posició…',
      sortedByDistance: 'Ordenat per distància des de la teva posició.',
      geoDenied: "No s'ha pogut obtenir la posició. Revisa els permisos.",
      geoUnsupported: 'Aquest navegador no permet geolocalització.',
      filteringBy: 'Filtrant per',
      legendTitle: 'Puntuació',
      legendVeryGood: 'Molt bona · 75+',
      legendGood: 'Bona · 55–74',
      legendPossible: 'Possible · 35–54',
      legendLow: 'Baixa · <35',
      legendNote: 'Color = condicions estimades, no observacions.',
      zones: 'zona',
      zonesPlural: 'zones',
      locateMe: "Situa'm",
      dataQuality: 'Qualitat de dades',
    },
    langBtn: 'EN',
    tabMap: 'Mapa',
    tabList: 'Zones',
  },
  en: {
    appTitle: 'Mushroom Forecast · Catalonia',
    loading: 'Loading data...', loadingGeo: 'Loading weather and geographic data...',
    statusOk: (d) => `Data for ${d} · Open-Meteo + IGME + CORINE`,
    selectStation: 'Select a station',
    today: 'Today', tomorrow: 'Tomorrow',
    dayNames: ['Su','Mo','Tu','We','Th','Fr','Sa'],
    monthNames: ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],
    scoreLabels: { 'Molt bona':'Excellent','Bona':'Good','Possible':'Possible','Baixa':'Low' },
    rain7d: 'Rain 7d', tempAvg: 'Avg temp', windMax: 'Max wind km/h',
    altLabel: '⬆', topoBtn: 'ICGC Topo',
    learnMore: '✦ Learn more — why this score?',
    soilLbl: 'Detected soil', forestLbl: 'Forest (CORINE)',
    needsLbl: 'Needs', rain7dLbl: 'Fallen (7d)', minLbl: 'Min required',
    tempLbl: 'Avg 5d', idealLbl: 'Ideal', windLbl: 'Max gust 3d', threshLbl: 'Threshold',
    altLbl: 'Elevation', humLbl: 'Max RH 5d', goodLbl: 'Good',
    secSoil: '🪨 Soil & vegetation', secRain: '🌧 Rain', secTemp: '🌡 Temperature',
    secWind: '💨 Wind', secAlt: '⛰ Altitude', secHum: '💧 Humidity',
    overallScore: 'overall score',
    overallExplain: 'Score combines weather (rain, temperature, wind, altitude, humidity) multiplied by soil suitability and forest type detected by satellite.',
    soilTypes: { calcareous:'calcareous (basic)', siliceous:'siliceous (acid)', mixed:'mixed', unknown:'unknown' },
    phPrefs: {
      acid:'acid (pH < 6.5)', basic:'basic (pH > 7)',
      neutral_to_acid:'neutral to slightly acid', neutral_to_slightly_acid:'neutral to slightly acid',
      neutral:'neutral', basic_to_neutral:'basic to neutral',
    },
    forestDescs: {
      '311':'broadleaf forest (oak, beech, chestnut)', '312':'coniferous forest (pine, fir)',
      '313':'mixed forest (conifers and broadleaf)', '324':'transitional woodland/shrub',
    },
    windSens: { high:'high', medium:'medium', low:'low' },
    soilVerdicts: {
      great: (n,sp,ph) => `<b class="verdict-good">Excellent match.</b> The ${n} soil is perfect for ${sp}, which prefers ${ph} soils.`,
      ok: (n,sp,ph) => `<b class="verdict-ok">Partial match.</b> ${n} soil is not ideal but doesn't rule out ${sp} (prefers ${ph}).`,
      bad: (n,sp,ph) => `<b class="verdict-bad">Wrong soil.</b> ${n} soil is the opposite of what ${sp} needs (needs ${ph}).`,
      igme: (txt) => ` IGME describes the bedrock as: <em>"${txt}"</em>.`,
      ph: (ph) => ` Measured pH (SoilGrids): <b>${ph}</b>.`,
    },
    forestVerdicts: {
      great: (fd,sp,tr) => `<b class="verdict-good">Ideal forest.</b> CORINE detects ${fd}, exactly what ${sp} needs (associated with: ${tr}).`,
      ok: (fd,sp,tr) => `<b class="verdict-ok">Acceptable forest.</b> CORINE detects ${fd}. ${sp} may appear but this isn't its preferred habitat (prefers: ${tr}).`,
      bad: (fd,sp,tr) => `<b class="verdict-bad">Poor forest match.</b> CORINE detects ${fd}, but ${sp} prefers ${tr}.`,
      pine: () => ' Especially abundant in open Scots pine (<em>Pinus sylvestris</em>) reforestation without undergrowth.',
    },
    rainVerdicts: {
      great:(mm,need,days) => `<b class="verdict-good">Excellent rainfall.</b> <b>${mm}mm</b> fallen in the last 7 days. Minimum needed: <b>${need}mm</b> over ${days} days. `,
      ok:(mm,need,days) => `<b class="verdict-ok">Sufficient rain.</b> <b>${mm}mm</b> in the last 7 days (minimum: ${need}mm/${days}d). `,
      bad:(mm,need,days) => `<b class="verdict-bad">Insufficient rain.</b> Only <b>${mm}mm</b> in the last 7 days; need at least <b>${need}mm</b> over ${days} days. `,
      dryBonus:(n) => `There was also a <b>prior dry spell of at least ${n} dry days</b> — dry mycelium activates better after a strong sudden rain.`,
      noDry:(n) => `No clear prior dry spell detected (need ~${n} dry days), which slightly reduces activation potential.`,
    },
    tempVerdicts: {
      great:(avg,mx,mn,imin,imax) => `<b class="verdict-good">Ideal temperature.</b> Max ${mx}°C, min ${mn}°C (avg ~${avg}°C). Ideal range: <b>${imin}–${imax}°C</b>. `,
      ok:(avg,imin,imax) => `<b class="verdict-ok">Acceptable temperature.</b> ~${avg}°C (ideal: ${imin}–${imax}°C). `,
      cold:(avg,tmin) => `<b class="verdict-bad">Too cold.</b> ${avg}°C is below the minimum of <b>${tmin}°C</b>. `,
      hot:(avg,tmax) => `<b class="verdict-bad">Too hot.</b> ${avg}°C exceeds the maximum of <b>${tmax}°C</b>. `,
      explain:(tmin,tmax) => `Below ${tmin}°C for several consecutive days the mushroom freezes; above ${tmax}°C it won't fruit.`,
    },
    windVerdicts: {
      great:(avg,w) => `<b class="verdict-good">Favourable wind.</b> Max gust <b>${avg}km/h</b> over last 3 days. `,
      ok:(avg) => `<b class="verdict-ok">Moderate wind.</b> Gust <b>${avg}km/h</b>. `,
      bad:(avg,mx) => `<b class="verdict-bad">Excessive wind.</b> Gust <b>${avg}km/h</b> (max ${mx}km/h). `,
      explain:(sp,sens,thr) => `${sp} has <b>${sens}</b> wind sensitivity. Above <b>${thr}km/h</b> the soil dries quickly. Cold northerly winds (Tramuntana) are especially damaging.`,
    },
    altVerdicts: {
      great:(alt,imin,imax) => `<b class="verdict-good">Perfect altitude.</b> <b>${alt}m</b>, within the ideal range of <b>${imin}–${imax}m</b>. `,
      ok:(alt,imin,imax) => `<b class="verdict-ok">Acceptable altitude.</b> ${alt}m (ideal: ${imin}–${imax}m). `,
      low:(alt,imin) => `<b class="verdict-bad">Too low.</b> ${alt}m is below the ideal altitude (>${imin}m). `,
      high:(alt,imax) => `<b class="verdict-bad">Too high.</b> ${alt}m exceeds the maximum of ${imax}m. `,
      explain: () => `Rule of thumb: every 150m gained loses ~1°C. Rovellons appear first at 800m and move up to 1,400m as autumn deepens.`,
    },
    humVerdicts: {
      great:(h) => `<b class="verdict-good">High humidity.</b> Max RH <b>${h}%</b>. `,
      ok:(h) => `<b class="verdict-ok">Acceptable humidity.</b> ${h}%. `,
      bad:(h) => `<b class="verdict-bad">Dry air.</b> Only ${h}% humidity. `,
      explain: () => `Below 60–65% the soil evaporates quickly, especially on windy days. High RH (>80%) gives the mycelium time to fruit.`,
    },
    stnNotes: 'Forest notes',
    ui: {
      searchPlaceholder: 'Search a place, forest, town or species…',
      allSpecies: 'All species',
      allComarques: 'All comarques',
      sortScore: 'Best score',
      sortDistance: 'Nearest',
      sortAltitude: 'Altitude',
      sortName: 'Name',
      sortComarca: 'Comarca',
      only55: 'Only ≥ 55',
      bestZones: 'Best zones',
      freeNoSignup: 'free · no sign-up',
      noZones: 'No zones match these filters.',
      noZonesHint: 'No zone matches these filters.',
      clearFilters: 'Clear filters',
      best: 'best',
      route: 'route',
      routeLong: 'Get directions',
      osm: 'OSM',
      parkingNear: 'Nearby parking',
      share: 'Share',
      quality: 'Data quality',
      qualityHigh: 'high',
      qualityMedium: 'medium',
      qualityLow: 'low',
      searchingParking: 'Looking for nearby parking…',
      noParking: 'No mapped parking within 2.5 km. Use the forest track and do not block it.',
      parkingError: 'Could not reach Overpass. Open OSM to inspect the area.',
      linkCopied: 'Link copied:',
      searchingPlace: 'Searching',
      noPlace: 'No place found',
      goingTo: 'Going to',
      geolocating: 'Getting your position…',
      sortedByDistance: 'Sorted by distance from your position.',
      geoDenied: 'Could not get your position. Check permissions.',
      geoUnsupported: 'This browser does not allow geolocation.',
      filteringBy: 'Filtering by',
      legendTitle: 'Score',
      legendVeryGood: 'Very good · 75+',
      legendGood: 'Good · 55–74',
      legendPossible: 'Possible · 35–54',
      legendLow: 'Low · <35',
      legendNote: 'Colour = estimated conditions, not observations.',
      zones: 'zone',
      zonesPlural: 'zones',
      locateMe: 'Locate me',
      dataQuality: 'Data quality',
    },
    langBtn: 'CA',
    tabMap: 'Map',
    tabList: 'Zones',
  },
};

let lang = (() => {
  try {
    const q = new URLSearchParams(location.search).get('lang');
    if (q === 'ca' || q === 'en') return q;
    const saved = localStorage.getItem('bolets-lang');
    if (saved === 'ca' || saved === 'en') return saved;
  } catch (e) {}
  return 'ca';
})();
function T(key, ...args) {
  const v = TRANSLATIONS[lang][key];
  return typeof v === 'function' ? v(...args) : (v ?? key);
}
function U(key, ...args) {
  const v = TRANSLATIONS[lang].ui[key];
  return typeof v === 'function' ? v(...args) : (v ?? key);
}
function setLang(l) {
  lang = l;
  try { localStorage.setItem('bolets-lang', l); } catch (e) {}
  document.getElementById('lang-btn').textContent = T('langBtn');
  document.getElementById('app-title').textContent = T('appTitle');
  const ml = document.getElementById('tab-map-lbl');
  const ll = document.getElementById('tab-list-lbl');
  if (ml) ml.textContent = T('tabMap');
  if (ll) ll.textContent = T('tabList');
  applyStaticText();
  // Re-render everything with new language
  if (forecastData) {
    renderDaySelector(forecastData);
    renderSidebar(forecastData);
    renderMarkers(forecastData);
    if (activeStation) {
      const stn = findStation(activeStation);
      if (stn) renderDetail(stn);
    }
  }
}

// ── State ─────────────────────────────────────────────────────────────────────
let forecastData = null;
let activeStation = null;
let markers = [];
let markerByName = {};
let selectedDay = 0;
let activeCircle = null;   // the currently shown forest zone circle
let activeTab = (new URLSearchParams(location.search).get('tab') === 'list') ? 'list' : 'map';  // mobile only

// Phase 1 navigation state
let filterSpecies = '';    // species id
let filterComarca = '';    // comarca name
let filterSort = 'score';  // score | distance | altitude | name | comarca
let filterMin = false;     // only >= 55
let searchQuery = '';      // free text
let userPos = null;        // {lat, lon} once geolocation is granted
let parkingCache = {};     // station name -> parking rows
let restoredFromUrl = false;

const isMobile = () => window.innerWidth <= 700;

// ── Station helpers ───────────────────────────────────────────────────────────
function allStationEntries() {
  const out = [];
  if (!forecastData) return out;
  for (const [comarca, stations] of Object.entries(forecastData.comarques)) {
    for (const stn of stations) out.push({ comarca, stn });
  }
  return out;
}

function findStation(name) {
  for (const { stn } of allStationEntries()) {
    if (stn.name === name) return stn;
  }
  return null;
}

function speciesFor(stn) {
  // The 7-day arrays are keyed by selectedDay; keep the old fallback.
  if (!stn.days || !stn.days[selectedDay]) return stn.species || [];
  return stn.days[selectedDay];
}

function activeSpeciesFor(stn) {
  const list = speciesFor(stn);
  if (!filterSpecies) return list[0] || null;
  return list.find(s => s.id === filterSpecies) || null;
}

function stationScore(stn) {
  const sp = activeSpeciesFor(stn);
  return sp ? sp.score : -1;
}

function bestDayFor(stn) {
  // Best score across the 7-day window for the current species filter.
  let best = null;
  const days = stn.days || [];
  for (let i = 0; i < days.length; i++) {
    const list = filterSpecies
      ? days[i].filter(s => s.id === filterSpecies)
      : days[i];
    const top = list[0];
    if (top && (!best || top.score > best.score)) {
      best = { score: top.score, day: i, name: top.name };
    }
  }
  return best;
}

function distanceKm(a, b) {
  if (!a || !b) return Infinity;
  const R = 6371;
  const dLat = (b.lat - a.lat) * Math.PI / 180;
  const dLon = (b.lon - a.lon) * Math.PI / 180;
  const la1 = a.lat * Math.PI / 180;
  const la2 = b.lat * Math.PI / 180;
  const h = Math.sin(dLat/2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon/2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function matchesSearch(stn, comarca, q) {
  if (!q) return true;
  const hay = [
    stn.name, comarca, stn.notes || '',
    ...(stn.species || []).map(s => `${s.name} ${s.scientific}`),
    ...(speciesFor(stn) || []).map(s => `${s.name} ${s.scientific}`),
  ].join(' ').toLowerCase();
  return q.toLowerCase().split(/\s+/).filter(Boolean).every(term => hay.includes(term));
}

function findSpeciesByName(q) {
  const ql = q.trim().toLowerCase();
  if (!ql) return null;
  const seen = new Map();
  for (const { stn } of allStationEntries()) {
    for (const list of (stn.days || [stn.species || []])) {
      for (const sp of list) seen.set(sp.id, sp.name);
    }
  }
  for (const [id, name] of seen.entries()) {
    const nl = name.toLowerCase();
    if (nl === ql || id.toLowerCase() === ql || nl.includes(ql) || ql.includes(nl)) {
      return { id, name };
    }
  }
  return null;
}

function visibleEntries() {
  let rows = allStationEntries().filter(({ comarca, stn }) => {
    if (stn.error) return false;
    if (filterComarca && comarca !== filterComarca) return false;
    if (!matchesSearch(stn, comarca, searchQuery)) return false;
    if (filterSpecies && !activeSpeciesFor(stn)) return false;
    if (filterMin && stationScore(stn) < 55) return false;
    return true;
  });

  rows.sort((a, b) => {
    if (filterSort === 'name') return a.stn.name.localeCompare(b.stn.name, 'ca');
    if (filterSort === 'comarca') return a.comarca.localeCompare(b.comarca, 'ca') || a.stn.name.localeCompare(b.stn.name, 'ca');
    if (filterSort === 'altitude') return (b.stn.alt_m || 0) - (a.stn.alt_m || 0);
    if (filterSort === 'distance') {
      if (!userPos) return stationScore(b.stn) - stationScore(a.stn);
      return distanceKm(userPos, a.stn) - distanceKm(userPos, b.stn);
    }
    return stationScore(b.stn) - stationScore(a.stn);
  });
  return rows;
}

// ── Tab switching (mobile) ────────────────────────────────────────────────────
function switchTab(tab) {
  activeTab = tab;
  const sidebar = document.getElementById('sidebar');
  document.getElementById('tab-map').classList.toggle('active', tab === 'map');
  document.getElementById('tab-list').classList.toggle('active', tab === 'list');
  if (tab === 'list') {
    sidebar.classList.add('mob-visible');
    // Close detail panel when switching to list
    document.getElementById('detail-panel').classList.remove('visible');
  } else {
    sidebar.classList.remove('mob-visible');
  }
  // Invalidate map size after sidebar hides/shows
  if (tab === 'map') setTimeout(() => map.invalidateSize(), 50);
  if (forecastData) updateUrl();
}

// ── Score → style ─────────────────────────────────────────────────────────────
function scoreClass(s) {
  if (s >= 75) return 'high';
  if (s >= 55) return 'mid';
  if (s >= 35) return 'low';
  return 'none';
}
function scoreColor(s) {
  if (s >= 75) return '#4a8c3f';
  if (s >= 55) return '#c08b00';
  if (s >= 35) return '#a0573a';
  return '#b0a090';
}

// ── Soil badge ────────────────────────────────────────────────────────────────
function soilBadge(type) {
  const map = {
    calcareous: ['badge-cal', 'Calcàri (bàsic)'],
    siliceous:  ['badge-sil', 'Silícic (àcid)'],
    mixed:      ['badge-mix', 'Mixt'],
    unknown:    ['badge-unk', 'Desconegut'],
  };
  const [cls, label] = map[type] || ['badge-unk', type];
  return `<span class="badge ${cls}">${label}</span>`;
}

function forestBadge(code, label) {
  if (!code || code === 'unknown') return '';
  return `<span class="badge badge-for">${label}</span>`;
}

function phBadge(ph) {
  if (ph == null) return '';
  return `<span class="badge badge-ph">pH ${ph.toFixed(1)}</span>`;
}

// ── Render sidebar ────────────────────────────────────────────────────────────
// ── Day selector ─────────────────────────────────────────────────────────────
function setDay(i) {
  selectedDay = i;
  document.querySelectorAll('.day-btn').forEach((b,j) =>
    b.classList.toggle('active', j === i));
  if (forecastData) {
    renderSidebar(forecastData);
    renderMarkers(forecastData);
  }
  if (activeStation) {
    const stn = findStation(activeStation);
    if (stn) {
      if (activeCircle) {
        const sp = activeSpeciesFor(stn);
        const color = scoreColor(sp?.score ?? 0);
        activeCircle.setStyle({ color, fillColor: color });
      }
      renderDetail(stn);
    }
  }
  updateUrl();
}

function renderDaySelector(data) {
  const bar = document.getElementById('day-selector');
  bar.style.display = 'flex';
  // Get dates from first station that has them
  let dates = [];
  for (const stns of Object.values(data.comarques)) {
    if (stns[0]?.dates?.length) { dates = stns[0].dates; break; }
  }
  const today = new Date();
  bar.innerHTML = `<span class="day-selector-label">📅</span>`;
  for (let i = 0; i < 7; i++) {
    const d = dates[i] ? new Date(dates[i] + 'T12:00:00') : new Date(today.getTime() + i*86400000);
    const dayName = i === 0 ? T('today') : i === 1 ? T('tomorrow')
      : T('dayNames')[d.getDay()];
    const mon = T('monthNames')[d.getMonth()];
    const btn = document.createElement('button');
    btn.className = 'day-btn' + (i === selectedDay ? ' active' : '');
    btn.innerHTML = `${dayName}<br><span style="font-size:0.62rem;opacity:0.8">${d.getDate()} ${mon}</span>`;
    btn.setAttribute('aria-label', `${dayName} ${d.getDate()} ${mon}`);
    btn.onclick = () => setDay(i);
    bar.appendChild(btn);
  }
}

function getSpecies(stn) {
  return speciesFor(stn);
}

function populateFilters(data) {
  const spSel = document.getElementById('filter-species');
  const coSel = document.getElementById('filter-comarca');

  // Species: union across all stations and all seven days so seasonal species
  // still appear in the filter.
  const seen = new Map();
  for (const { stn } of allStationEntries()) {
    for (const list of (stn.days || [stn.species || []])) {
      for (const sp of list) seen.set(sp.id, sp.name);
    }
  }
  spSel.innerHTML = `<option value="">${U('allSpecies')}</option>` +
    [...seen.entries()].sort((a,b) => a[1].localeCompare(b[1], 'ca'))
      .map(([id, name]) => `<option value="${id}">${name}</option>`).join('');
  spSel.value = filterSpecies;

  const comarques = Object.keys(data.comarques);
  coSel.innerHTML = `<option value="">${U('allComarques')}</option>` +
    comarques.map(c => `<option value="${c}">${c}</option>`).join('');
  coSel.value = filterComarca;
}

function stationMetaLine(stn) {
  const sp = speciesFor(stn)[0];
  const w = sp?.weather || {};
  return `<span>⬆ ${stn.alt_m}m</span>
          <span>🌧 ${w.rain_7d ?? '—'}mm/7d</span>
          <span>🌡 ${w.temp_avg ?? '—'}°C</span>
          <span>💨 ${w.wind_max ?? '—'}km/h</span>`;
}

function routeUrl(stn) {
  return `https://www.google.com/maps/dir/?api=1&destination=${stn.lat},${stn.lon}&travelmode=driving`;
}
function osmUrl(stn) {
  return `https://www.openstreetmap.org/?mlat=${stn.lat}&mlon=${stn.lon}#map=15/${stn.lat}/${stn.lon}`;
}
function openRoute(stn, ev) {
  if (ev) ev.stopPropagation();
  window.open(routeUrl(stn), '_blank', 'noopener');
}

function selectedDayLabel() {
  if (selectedDay === 0) return T('today');
  const first = allStationEntries()[0]?.stn;
  const iso = first?.dates?.[selectedDay];
  if (iso) {
    const d = new Date(iso + 'T12:00:00');
    return `${T('dayNames')[d.getDay()]} ${d.getDate()} ${T('monthNames')[d.getMonth()]}`;
  }
  return `+${selectedDay}d`;
}

function renderBestZones(rows) {
  const box = document.getElementById('best-zones');
  const ranked = rows.slice()
    .sort((a,b) => stationScore(b.stn) - stationScore(a.stn))
    .slice(0, 6);

  if (!ranked.length) {
    box.innerHTML = `<div class="best-zones-head">
      <span class="best-zones-title">${U('bestZones')} · ${selectedDayLabel()}</span>
    </div><div class="best-empty">${U('noZones')}</div>`;
    return;
  }

  box.innerHTML = `
    <div class="best-zones-head">
      <span class="best-zones-title">${U('bestZones')} · ${selectedDayLabel()}</span>
      <span class="best-zones-sub">${U('freeNoSignup')}</span>
    </div>
    ${ranked.map((row, i) => {
      const sp = activeSpeciesFor(row.stn);
      const score = sp ? sp.score : 0;
      const bd = bestDayFor(row.stn);
      const dayTxt = bd ? (bd.day === selectedDay ? T('today') : T('dayNames')[new Date(row.stn.dates?.[bd.day] || Date.now()).getDay()]) : '';
      return `<div class="best-zone" onclick="selectStation('${row.stn.name.replace(/'/g, "\\'")}', '${row.comarca.replace(/'/g, "\\'")}')"
                   role="button" tabindex="0"
                   title="${escHtml(row.stn.name)} · ${escHtml(row.comarca)}"
                   onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();selectStation('${row.stn.name.replace(/'/g, "\\'")}', '${row.comarca.replace(/'/g, "\\'")}')}">
        <span class="best-zone-rank">${i + 1}</span>
        <span class="score-pill" style="background:${scoreColor(score)}">${score}</span>
        <span class="best-zone-name" title="${row.stn.name}">${row.stn.name}</span>
        <span class="best-zone-meta">${sp ? sp.name : ''}${bd ? ' · ' + dayTxt : ''}</span>
        <button class="best-zone-route" title="${U('routeLong')}" aria-label="${U('routeLong')} · ${row.stn.name}"
                onclick="openRoute(findStation('${row.stn.name.replace(/'/g, "\\'")}'), event)">↗</button>
      </div>`;
    }).join('')}`;
}

function renderSidebar(data) {
  populateFilters(data);
  const rows = visibleEntries();
  renderBestZones(rows);

  const list = document.getElementById('station-list');
  list.innerHTML = '';

  const count = document.getElementById('result-count');
  if (count) count.textContent = `${rows.length} ${U(rows.length === 1 ? 'zones' : 'zonesPlural')}`;

  if (!rows.length) {
    list.innerHTML = `<div class="filter-empty">
      ${U('noZonesHint')}<br>
      <button class="learn-more-btn" onclick="clearFilters()">${U('clearFilters')}</button>
    </div>`;
    return;
  }

  // Preserve the comarca order from the API.
  for (const comarca of Object.keys(data.comarques)) {
    const group = rows.filter(r => r.comarca === comarca);
    if (!group.length) continue;

    const section = document.createElement('div');
    section.className = 'comarca-section';

    const hdr = document.createElement('div');
    hdr.className = 'comarca-header';
    hdr.innerHTML = `<span>${comarca} <span style="opacity:.55;font-weight:600">${group.length}</span></span><span class="chevron">▾</span>`;
    section.appendChild(hdr);

    const body = document.createElement('div');
    body.className = 'comarca-body';
    hdr.onclick = () => {
      hdr.classList.toggle('collapsed');
      body.classList.toggle('collapsed');
    };

    for (const { stn } of group) {
      const card = document.createElement('div');
      card.className = 'station-card';
      card.dataset.id = stn.name;
      card.dataset.comarca = comarca;
      card.tabIndex = 0;
      card.setAttribute('role', 'button');
      card.setAttribute('aria-label', `Zona ${stn.name}, ${comarca}`);

      const all = speciesFor(stn);
      let top = all.slice(0, 4);
      if (filterSpecies) {
        const chosen = all.find(s => s.id === filterSpecies);
        top = chosen ? [chosen, ...all.filter(s => s.id !== filterSpecies).slice(0, 3)] : all.slice(0, 4);
      }
      const bd = bestDayFor(stn);

      card.innerHTML = `
        <div class="card-top">
          <div class="station-name">${stn.name}</div>
          ${bd && bd.day !== selectedDay ? `<span class="best-day-tag">${U('best')} ${T('dayNames')[new Date(stn.dates?.[bd.day] || Date.now()).getDay()]} · ${bd.score}</span>` : ''}
          <button class="route-mini" title="${U('routeLong')}" aria-label="${U('routeLong')} · ${stn.name}"
                  onclick="openRoute(findStation('${stn.name.replace(/'/g, "\\'")}'), event)">↗ ${U('route')}</button>
        </div>
        <div class="station-meta">${stationMetaLine(stn)}</div>
        <div class="top-species">
          ${top.map(sp => `
            <div class="species-row ${filterSpecies && sp.id === filterSpecies ? 'sp-selected' : ''}">
              <span class="score-pill" style="background:${scoreColor(sp.score)}">${sp.score}</span>
              <span style="flex:1;font-size:0.75rem">${sp.name}</span>
              <div class="score-bar">
                <div class="score-bar-fill score-${scoreClass(sp.score)}"
                     style="width:${sp.score}%"></div>
              </div>
            </div>`).join('')}
        </div>`;

      card.onclick = () => selectStation(stn.name, comarca);
      card.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectStation(stn.name, comarca); }
      };
      card.onmouseenter = () => highlightMarker(stn.name, true);
      card.onmouseleave = () => highlightMarker(stn.name, false);

      body.appendChild(card);
    }

    section.appendChild(body);
    list.appendChild(section);
  }
}

function clearFilters() {
  filterSpecies = '';
  filterComarca = '';
  filterSort = 'score';
  filterMin = false;
  searchQuery = '';
  document.getElementById('search-input').value = '';
  document.getElementById('search-clear').classList.remove('visible');
  document.getElementById('filter-species').value = '';
  document.getElementById('filter-comarca').value = '';
  document.getElementById('filter-sort').value = 'score';
  document.getElementById('filter-min').checked = false;
  renderSidebar(forecastData);
  renderMarkers(forecastData);
  updateUrl();
}

// ── Render markers ────────────────────────────────────────────────────────────
function renderMarkers(data) {
  markerCluster.clearLayers();
  markers = [];
  markerByName = {};

  for (const { comarca, stn } of visibleEntries()) {
    const sp = activeSpeciesFor(stn);
    if (!sp) continue;
    const best  = sp.score;
    const color = scoreColor(best);

    const icon = L.divIcon({
      className: '',
      html: `<div class="custom-marker" style="width:32px;height:32px;background:${color}">${best}</div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });

    const m = L.marker([stn.lat, stn.lon], { icon, title: stn.name })
      .on('click', () => selectStation(stn.name, comarca))
      .on('mouseover', () => highlightCard(stn.name, true))
      .on('mouseout', () => highlightCard(stn.name, false));

    const topNames = speciesFor(stn).slice(0,2).map(s=>s.name).join(', ');
    const routeBtn = `<a href="${routeUrl(stn)}" target="_blank" rel="noopener"
        style="display:inline-block;margin-top:4px;font-weight:600;color:#7a4c2a">↗ Com arribar-hi</a>`;
    m.bindTooltip(`<b>${stn.name}</b><br>${stn.alt_m}m · ${sp.name} ${best}<br>${topNames}<br>${routeBtn}`,
      { permanent: false, direction: 'top', className: 'leaflet-tooltip', opacity: 1 });

    markers.push(m);
    markerByName[stn.name] = m;
    markerCluster.addLayer(m);
  }
}

function highlightMarker(name, on) {
  const m = markerByName[name];
  if (!m) return;
  const el = m.getElement()?.querySelector('.custom-marker');
  if (el) el.classList.toggle('marker-hl', on);
  if (on) m.openTooltip(); else m.closeTooltip();
}

function highlightCard(name, on) {
  const card = document.querySelector(`.station-card[data-id="${CSS.escape(name)}"]`);
  if (card) card.classList.toggle('hovered', on);
  highlightMarker(name, on);
}

// ── Forest zone circle ────────────────────────────────────────────────────────
function showForestCircle(stn) {
  // Remove any existing circle
  if (activeCircle) {
    map.removeLayer(activeCircle);
    activeCircle = null;
  }

  const sp = activeSpeciesFor(stn);
  const best    = sp?.score ?? 0;
  const color   = scoreColor(best);
  const radius  = stn.radius_m || 2000;

  activeCircle = L.circle([stn.lat, stn.lon], {
    radius,
    color,
    fillColor: color,
    fillOpacity: 0.10,
    weight: 2,
    opacity: 0.55,
    dashArray: '6 5',
  }).addTo(map);

  // Fit map to circle without zooming in too far
  const circleBounds = activeCircle.getBounds().pad(0.15);
  const currentZoom  = map.getZoom();
  const boundsZoom   = map.getBoundsZoom(circleBounds);
  // Only zoom in if it helps see the circle, don't zoom past 14
  map.fitBounds(circleBounds, { maxZoom: Math.min(14, Math.max(currentZoom, boundsZoom)) });
}

// ── Select station ────────────────────────────────────────────────────────────
function selectStation(name, comarca) {
  activeStation = name;

  document.querySelectorAll('.station-card').forEach(c => {
    const on = c.dataset.id === name;
    c.classList.toggle('active', on);
    if (on) c.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  });

  const stn = findStation(name);
  if (!stn) return;

  highlightMarker(name, true);
  setTimeout(() => highlightMarker(name, false), 1800);

  // On mobile: switch to map tab so the circle is visible
  if (isMobile() && activeTab === 'list') {
    switchTab('map');
    // Slight delay so map is visible before we pan+zoom
    setTimeout(() => { showForestCircle(stn); renderDetail(stn); }, 80);
  } else {
    showForestCircle(stn);
    renderDetail(stn);
  }

  updateUrl();
}

// ── Render detail panel ───────────────────────────────────────────────────────
function jsq(s) {
  return String(s).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}
function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));
}

function qualityBadge(q) {
  const pct = q?.pct ?? 0;
  const color = pct >= 90 ? '#4a8c3f' : pct >= 60 ? '#c08b00' : '#a0573a';
  const qKey = pct >= 90 ? 'qualityHigh' : pct >= 60 ? 'qualityMedium' : 'qualityLow';
  const reasons = (q?.reasons || []).join(' · ');
  return `<div class="quality-row" title="${escHtml(reasons || 'Meteo, sòl i bosc detectats')}">
    <span class="quality-label">${U('quality')}: ${U(qKey)}</span>
    <div class="quality-bar"><div class="quality-bar-fill" style="width:${pct}%;background:${color}"></div></div>
    <span>${pct}%</span>
  </div>${reasons ? `<div class="quality-row" style="padding-top:0;border-bottom:1px solid #e8e2d8;display:block">${escHtml(reasons)}</div>` : ''}`;
}

function dayStrip(stn) {
  const dates = stn.dates || [];
  return `<div class="day-strip">${Array.from({length: 7}, (_, i) => {
    const list = stn.days?.[i] || [];
    const sp = filterSpecies ? list.find(s => s.id === filterSpecies) : list[0];
    if (!sp) {
      return `<div class="day-cell ${i === selectedDay ? 'active' : ''}" onclick="setDay(${i})">
        <div class="dc-day">${dates[i] ? T('dayNames')[new Date(dates[i]+'T12:00:00').getDay()] : '—'}</div>
        <div class="dc-score" style="color:#b0a090">—</div>
        <div class="dc-bar"></div>
      </div>`;
    }
    const col = scoreColor(sp.score);
    return `<div class="day-cell ${i === selectedDay ? 'active' : ''}" onclick="setDay(${i})"
                 title="${escHtml(sp.name)} · ${sp.label}">
      <div class="dc-day">${dates[i] ? T('dayNames')[new Date(dates[i]+'T12:00:00').getDay()] : '—'}</div>
      <div class="dc-score" style="color:${col}">${sp.score}</div>
      <div class="dc-bar"><div class="dc-bar-fill" style="width:${sp.score}%;background:${col}"></div></div>
    </div>`;
  }).join('')}</div>`;
}

function renderDetail(stn) {
  const panel = document.getElementById('detail-panel');
  panel.classList.add('visible');
  const species = speciesFor(stn);

  if (stn.error) {
    panel.innerHTML = `<div class="detail-header">
      <h2>${stn.name}</h2>
      <button class="detail-close" onclick="closeDetail()">✕</button>
      <div class="alt" style="color:#c0392b">Error: ${stn.error}</div>
    </div>`;
    return;
  }

  const geo = stn.geo || {};
  const w   = species[0]?.weather ?? {};
  const ordered = filterSpecies
    ? [...species].sort((a,b) => (b.id === filterSpecies) - (a.id === filterSpecies))
    : species;
  _currentSpeciesList = ordered;

  panel.innerHTML = `
    <div class="detail-header">
      <h2>${escHtml(stn.name)}</h2>
      <button class="detail-close" onclick="closeDetail()" aria-label="Tanca">✕</button>
      <div class="alt">⬆ ${stn.alt_m}m · ${stn.lat.toFixed(3)}°N ${stn.lon.toFixed(3)}°E</div>
      ${stn.notes ? `<div style="font-size:0.7rem;color:#7a6e62;margin-top:4px;font-style:italic">${escHtml(stn.notes)}</div>` : ''}
    </div>

    ${qualityBadge(stn.quality)}

    <div class="trip-actions">
      <a class="trip-btn primary" href="${routeUrl(stn)}" target="_blank" rel="noopener">↗ ${U('routeLong')}</a>
      <a class="trip-btn" href="${osmUrl(stn)}" target="_blank" rel="noopener">🗺 ${U('osm')}</a>
      <button class="trip-btn" onclick="loadParking('${jsq(stn.name)}')">🅿️ ${U('parkingNear')}</button>
      <button class="trip-btn" onclick="copyZoneLink('${jsq(stn.name)}')">🔗 ${U('share')}</button>
    </div>
    <div class="parking-list" id="parking-box" style="display:none"></div>

    <div class="day-strip-wrap">${dayStrip(stn)}</div>

    <div class="geo-badges">
      ${soilBadge(geo.soil_type)}
      ${forestBadge(geo.forest_code, geo.forest_label)}
      ${phBadge(geo.ph)}
    </div>
    ${geo.litho_text && geo.litho_text !== 'unknown'
      ? `<div class="litho-text">${escHtml(geo.litho_text)}</div>` : ''}

    <div class="weather-summary">
      <div class="weather-stat">
        <div class="weather-val">${w.rain_7d ?? '—'}mm</div>
        <div class="weather-lbl">${T('rain7d')}</div>
      </div>
      <div class="weather-stat">
        <div class="weather-val">${w.temp_avg ?? '—'}°C</div>
        <div class="weather-lbl">${T('tempAvg')}</div>
      </div>
      <div class="weather-stat">
        <div class="weather-val">${w.wind_max ?? '—'}</div>
        <div class="weather-lbl">${T('windMax')}</div>
      </div>
    </div>

    <div class="species-list">
      ${ordered.map((sp, i) => `
        <div class="sp-item ${filterSpecies && sp.id === filterSpecies ? 'sp-selected' : ''}" onclick="toggleSp(this, ${i})">
          <div class="sp-top">
            <span class="score-pill" style="background:${scoreColor(sp.score)};width:36px;height:20px;border-radius:10px;display:inline-flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;color:white;flex-shrink:0">${sp.score}</span>
            <span>
              <div class="sp-name">${escHtml(sp.name)}</div>
              <div class="sp-sci">${escHtml(sp.scientific)}</div>
            </span>
            <span class="sp-label">${T('scoreLabels')[sp.label] ?? sp.label}</span>
          </div>
          <div class="sp-detail" id="sp-${i}">
            <div class="geo-mult">
              ${T('soilLbl')}: ${sp.soil_match}% · ${T('forestLbl')}: ${sp.forest_match}%
            </div>
            <div class="breakdown-grid">
              ${Object.entries(sp.breakdown).map(([k, v]) => `
                <div class="bd-item">
                  <span style="width:60px;text-transform:capitalize">${k}</span>
                  <div class="bd-bar"><div class="bd-bar-fill" style="width:${v}%"></div></div>
                  <span>${v}%</span>
                </div>`).join('')}
            </div>
            <div class="sp-notes">${escHtml(sp.notes)}</div>
            <button class="learn-more-btn" onclick="event.stopPropagation();openExplain(${i})">
              ${T('learnMore')}
            </button>
          </div>
        </div>`).join('')}
    </div>`;
}

// ── Parking near a zone (Overpass, free, cached per session) ──────────────────
async function loadParking(name) {
  const stn = findStation(name);
  const box = document.getElementById('parking-box');
  if (!stn || !box) return;
  box.style.display = 'block';

  if (parkingCache[name]) {
    box.innerHTML = parkingCache[name];
    return;
  }

  box.innerHTML = `<span class="muted">${U('searchingParking')}</span>`;
  try {
    const res = await fetch(`/api/parking?lat=${stn.lat}&lon=${stn.lon}`);
    if (!res.ok) throw new Error('Parking ' + res.status);
    const data = await res.json();
    const rows = (data.results || []).map(p => ({
      lat: p.lat,
      lon: p.lon,
      name: p.name || 'Aparcament',
      km: Math.max(0, p.distance_m / 1000),
    })).slice(0, 3);

    if (!rows.length) {
      box.innerHTML = `<span class="muted">${U('noParking')}</span>`;
    } else {
      box.innerHTML = rows.map(p =>
        `🅿️ <a href="https://www.openstreetmap.org/?mlat=${p.lat}&mlon=${p.lon}#map=17/${p.lat}/${p.lon}"
             target="_blank" rel="noopener">${escHtml(p.name)}</a>
         <span class="muted">· ${p.km.toFixed(1)} km</span>`
      ).join('<br>');
    }
  } catch (e) {
    box.innerHTML = `<span class="muted">${U('parkingError')}</span>`;
  }
  parkingCache[name] = box.innerHTML;
}

function copyZoneLink(name) {
  const stn = findStation(name);
  if (!stn) return;
  const url = new URL(window.location.href);
  url.searchParams.set('est', name);
  const text = url.toString();
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
  }
  const box = document.getElementById('parking-box');
  if (box) {
    box.style.display = 'block';
    box.innerHTML = `<span class="muted">${U('linkCopied')} ${escHtml(text)}</span>`;
  }
}

function toggleSp(el, i) {
  const detail = document.getElementById(`sp-${i}`);
  if (!detail) return;
  detail.classList.toggle('visible');
  el.classList.toggle('expanded');
}

function closeDetail() {
  document.getElementById('detail-panel').classList.remove('visible');
  document.querySelectorAll('.station-card').forEach(c => c.classList.remove('active'));
  if (activeCircle) { map.removeLayer(activeCircle); activeCircle = null; }
  activeStation = null;
  updateUrl();
  // On mobile stay on map tab
  if (isMobile()) switchTab('map');
}

// ── Explain overlay ───────────────────────────────────────────────────────────

let _currentSpeciesList = [];

function openExplain(i) {
  const sp  = _currentSpeciesList[i];
  const stn = (() => {
    for (const stns of Object.values(forecastData.comarques)) {
      const found = stns.find(s => s.name === activeStation);
      if (found) return found;
    }
  })();
  if (!sp || !stn) return;

  document.getElementById('explain-box').innerHTML = buildExplain(sp, stn);
  document.getElementById('explain-overlay').classList.add('visible');
  document.body.style.overflow = 'hidden';
}

function closeExplain(e) {
  if (e && e.target !== document.getElementById('explain-overlay')) return;
  document.getElementById('explain-overlay').classList.remove('visible');
  document.body.style.overflow = '';
}

function closeExplainBtn() {
  document.getElementById('explain-overlay').classList.remove('visible');
  document.body.style.overflow = '';
}

function meterHtml(pct, color) {
  return `<div class="explain-meter">
    <div class="explain-meter-fill" style="width:${pct}%;background:${color}"></div>
  </div>`;
}

function verdictClass(pct) {
  if (pct >= 75) return 'verdict-good';
  if (pct >= 45) return 'verdict-ok';
  return 'verdict-bad';
}
function verdictColor(pct) {
  if (pct >= 75) return '#4a8c3f';
  if (pct >= 45) return '#c08b00';
  return '#c0392b';
}

function buildExplain(sp, stn) {
  const th = sp.thresholds;
  const w  = sp.weather;
  const bd = sp.breakdown;
  const color = scoreColor(sp.score);

  const soilName  = T('soilTypes')[sp.soil_type] || sp.soil_type;
  const phPref    = T('phPrefs')[th.soil_ph] || th.soil_ph;
  const forestDesc = T('forestDescs')[sp.forest_code] || sp.forest_label;
  const treeList   = th.tree_keywords.slice(0,3).join(', ');

  // Soil verdict
  let soilVerdict;
  if (sp.soil_match >= 90)     soilVerdict = T('soilVerdicts').great(soilName, sp.name, phPref);
  else if (sp.soil_match >= 60) soilVerdict = T('soilVerdicts').ok(soilName, sp.name, phPref);
  else                          soilVerdict = T('soilVerdicts').bad(soilName, sp.name, phPref);
  if (sp.litho_text && sp.litho_text !== 'unknown')
    soilVerdict += T('soilVerdicts').igme(sp.litho_text);
  if (sp.ph != null)
    soilVerdict += T('soilVerdicts').ph(sp.ph.toFixed(1));

  // Forest verdict
  let forestVerdict;
  if (sp.forest_match >= 90)     forestVerdict = T('forestVerdicts').great(forestDesc, sp.name, treeList);
  else if (sp.forest_match >= 60) forestVerdict = T('forestVerdicts').ok(forestDesc, sp.name, treeList);
  else                            forestVerdict = T('forestVerdicts').bad(forestDesc, sp.name, treeList);
  if (th.prefers_scots_pine)      forestVerdict += T('forestVerdicts').pine();

  // Rain verdict
  const rainPct = bd.pluja, rainMm = w.rain_7d, needMm = th.rain_trigger_mm, winDays = th.rain_window_days, dryDays = th.dry_spell_before_days;
  let rainVerdict;
  if (rainPct >= 80)     rainVerdict = T('rainVerdicts').great(rainMm, needMm, winDays);
  else if (rainPct >= 50) rainVerdict = T('rainVerdicts').ok(rainMm, needMm, winDays);
  else                    rainVerdict = T('rainVerdicts').bad(rainMm, needMm, winDays);
  rainVerdict += (w.pre_dry_days >= dryDays)
    ? T('rainVerdicts').dryBonus(w.pre_dry_days)
    : T('rainVerdicts').noDry(dryDays);

  // Temperature verdict
  const tempPct = bd.temperatura, tAvg = w.temp_avg, tMax5 = w.avg_max, tMin5 = w.avg_min;
  let tempVerdict;
  if (tempPct >= 80)              tempVerdict = T('tempVerdicts').great(tAvg, tMax5, tMin5, th.temp_ideal_min, th.temp_ideal_max);
  else if (tempPct >= 45)         tempVerdict = T('tempVerdicts').ok(tAvg, th.temp_ideal_min, th.temp_ideal_max);
  else if (tAvg !== null && tAvg < th.temp_min) tempVerdict = T('tempVerdicts').cold(tAvg, th.temp_min);
  else                            tempVerdict = T('tempVerdicts').hot(tAvg, th.temp_max);
  tempVerdict += T('tempVerdicts').explain(th.temp_min, th.temp_max);

  // Wind verdict
  const windPct = bd.vent, wAvg = w.wind_avg, wMax = w.wind_max, wThresh = th.wind_threshold_kmh;
  const windSens = T('windSens')[th.wind_sensitivity] || th.wind_sensitivity;
  let windVerdict;
  if (windPct >= 80)      windVerdict = T('windVerdicts').great(wAvg, wThresh);
  else if (windPct >= 45)  windVerdict = T('windVerdicts').ok(wAvg);
  else                     windVerdict = T('windVerdicts').bad(wAvg, wMax);
  windVerdict += T('windVerdicts').explain(sp.name, windSens, wThresh);

  // Altitude verdict
  const altPct = bd.altitud, altM = stn.alt_m;
  let altVerdict;
  if (altPct >= 80)            altVerdict = T('altVerdicts').great(altM, th.alt_ideal_min, th.alt_ideal_max);
  else if (altPct >= 45)        altVerdict = T('altVerdicts').ok(altM, th.alt_ideal_min, th.alt_ideal_max);
  else if (altM < th.alt_ideal_min) altVerdict = T('altVerdicts').low(altM, th.alt_ideal_min);
  else                          altVerdict = T('altVerdicts').high(altM, th.alt_ideal_max);
  altVerdict += T('altVerdicts').explain();

  // Humidity verdict
  const humPct = bd.humitat, humVal = w.humidity;
  let humVerdict;
  if (humPct >= 80)      humVerdict = T('humVerdicts').great(humVal);
  else if (humPct >= 50)  humVerdict = T('humVerdicts').ok(humVal);
  else                    humVerdict = T('humVerdicts').bad(humVal);
  humVerdict += T('humVerdicts').explain();

  const scoreLabel = T('scoreLabels')[sp.label] ?? sp.label;

  return `
  <div class="explain-header">
    <div style="flex:1">
      <h2>${sp.name}</h2>
      <div class="sci">${sp.scientific} · ${stn.name} (${stn.alt_m}m)</div>
    </div>
    <button class="explain-close" onclick="closeExplainBtn()">✕</button>
  </div>

  <div class="explain-score-hero">
    <div class="explain-score-big" style="color:${color}">${sp.score}%</div>
    <div class="explain-score-label">${scoreLabel} — ${T('overallScore')}</div>
    <div style="font-size:0.7rem;color:#7a6e62;margin-top:6px;max-width:440px;margin-inline:auto">
      ${T('overallExplain')}
    </div>
  </div>

  <div class="explain-body">

    <div class="explain-section">
      <div class="explain-section-title">${T('secSoil')}</div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('soilLbl')}</span>
          <span class="explain-value">${soilName}</span>
          <span class="explain-need">${T('needsLbl')}: ${phPref}</span>
        </div>
        ${meterHtml(sp.soil_match, verdictColor(sp.soil_match))}
        <div class="explain-verdict">${soilVerdict}</div>
      </div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('forestLbl')}</span>
          <span class="explain-value">${sp.forest_label}</span>
          <span class="explain-need">${T('needsLbl')}: ${treeList}</span>
        </div>
        ${meterHtml(sp.forest_match, verdictColor(sp.forest_match))}
        <div class="explain-verdict">${forestVerdict}</div>
      </div>
    </div>

    <div class="explain-section">
      <div class="explain-section-title">${T('secRain')}</div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('rain7dLbl')}</span>
          <span class="explain-value">${rainMm}mm</span>
          <span class="explain-need">${T('minLbl')}: ${needMm}mm / ${winDays}d</span>
        </div>
        ${meterHtml(rainPct, verdictColor(rainPct))}
        <div class="explain-verdict">${rainVerdict}</div>
      </div>
    </div>

    <div class="explain-section">
      <div class="explain-section-title">${T('secTemp')}</div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('tempLbl')}</span>
          <span class="explain-value">${tAvg !== null ? tAvg+'°C' : '—'}</span>
          <span class="explain-need">${T('idealLbl')}: ${th.temp_ideal_min}–${th.temp_ideal_max}°C</span>
        </div>
        ${meterHtml(tempPct, verdictColor(tempPct))}
        <div class="explain-verdict">${tempVerdict}</div>
      </div>
    </div>

    <div class="explain-section">
      <div class="explain-section-title">${T('secWind')}</div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('windLbl')}</span>
          <span class="explain-value">${wMax}km/h</span>
          <span class="explain-need">${T('threshLbl')}: ${wThresh}km/h</span>
        </div>
        ${meterHtml(windPct, verdictColor(windPct))}
        <div class="explain-verdict">${windVerdict}</div>
      </div>
    </div>

    <div class="explain-section">
      <div class="explain-section-title">${T('secAlt')}</div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('altLbl')}</span>
          <span class="explain-value">${altM}m</span>
          <span class="explain-need">${T('idealLbl')}: ${th.alt_ideal_min}–${th.alt_ideal_max}m</span>
        </div>
        ${meterHtml(altPct, verdictColor(altPct))}
        <div class="explain-verdict">${altVerdict}</div>
      </div>
    </div>

    <div class="explain-section">
      <div class="explain-section-title">${T('secHum')}</div>
      <div class="explain-card">
        <div class="explain-card-row">
          <span class="explain-label">${T('humLbl')}</span>
          <span class="explain-value">${humVal !== null ? humVal+'%' : '—'}</span>
          <span class="explain-need">${T('goodLbl')}: ≥ 70%</span>
        </div>
        ${meterHtml(humPct, verdictColor(humPct))}
        <div class="explain-verdict">${humVerdict}</div>
      </div>
    </div>

  </div>`;
}

// ── URL state ────────────────────────────────────────────────────────────────
let urlTimer = null;
function updateUrl() {
  if (urlTimer) clearTimeout(urlTimer);
  urlTimer = setTimeout(() => {
    const p = new URLSearchParams();
    if (filterSpecies) p.set('esp', filterSpecies);
    if (filterComarca) p.set('com', filterComarca);
    if (selectedDay) p.set('dia', selectedDay);
    if (filterSort !== 'score') p.set('ord', filterSort);
    if (filterMin) p.set('min', '1');
    if (searchQuery) p.set('q', searchQuery);
    if (activeStation) p.set('est', activeStation);
    if (lang !== 'ca') p.set('lang', lang);
    if (isMobile() && activeTab === 'list') p.set('tab', 'list');
    const c = map.getCenter();
    p.set('lat', c.lat.toFixed(4));
    p.set('lon', c.lng.toFixed(4));
    p.set('z', map.getZoom());
    history.replaceState(null, '', '?' + p.toString());
  }, 120);
}

function applyUrlState() {
  const p = new URLSearchParams(location.search);
  filterSpecies = p.get('esp') || '';
  filterComarca = p.get('com') || '';
  filterSort = p.get('ord') || 'score';
  filterMin = p.get('min') === '1';
  searchQuery = p.get('q') || '';
  selectedDay = Math.min(6, Math.max(0, parseInt(p.get('dia') || '0', 10) || 0));

  const si = document.getElementById('search-input');
  si.value = searchQuery;
  document.getElementById('search-clear').classList.toggle('visible', !!searchQuery);
  document.getElementById('filter-min').checked = filterMin;
  const spSel = document.getElementById('filter-species');
  const coSel = document.getElementById('filter-comarca');
  const soSel = document.getElementById('filter-sort');
  if (spSel) spSel.value = filterSpecies;
  if (coSel) coSel.value = filterComarca;
  if (soSel) soSel.value = filterSort;

  return {
    est: p.get('est') || '',
    lat: parseFloat(p.get('lat')),
    lon: parseFloat(p.get('lon')),
    z: Number.isFinite(parseInt(p.get('z') || '11', 10)) ? parseInt(p.get('z') || '11', 10) : 11,
  };
}

// ── Search ────────────────────────────────────────────────────────────────────
function setStatus(msg, kind) {
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');
  if (dot && kind) dot.className = 'dot ' + kind;
  if (txt && msg) txt.textContent = msg;
}

function onSearchInput() {
  searchQuery = document.getElementById('search-input').value.trim();
  document.getElementById('search-clear').classList.toggle('visible', !!searchQuery);
  if (forecastData) {
    renderSidebar(forecastData);
    renderMarkers(forecastData);
  }
  updateUrl();
}

async function geocodeSearch() {
  const q = searchQuery.trim();
  if (q.length < 2) return;

  // Species name? Turn it into a filter instead of a geocode request.
  const spHit = findSpeciesByName(q);
  if (spHit) {
    filterSpecies = spHit.id;
    document.getElementById('filter-species').value = spHit.id;
    if (forecastData) { renderSidebar(forecastData); renderMarkers(forecastData); }
    if (activeStation) { const stn = findStation(activeStation); if (stn) renderDetail(stn); }
    setStatus(`${U('filteringBy')} ${spHit.name}.`, 'ok');
    updateUrl();
    return;
  }

  // Exact station match first — no network round trip.
  const exact = allStationEntries().find(({ stn }) =>
    stn.name.toLowerCase() === q.toLowerCase());
  if (exact) { selectStation(exact.stn.name, exact.comarca); return; }

  setStatus(`${U('searchingPlace')} “${q}”…`, 'loading');
  try {
    const res = await fetch('/api/geocode?q=' + encodeURIComponent(q));
    const data = await res.json();
    const hit = (data.results || [])[0];
    if (!hit) {
      setStatus(`${U('noPlace')} “${q}”.`, 'err');
      return;
    }
    if (searchMarker) map.removeLayer(searchMarker);
    searchMarker = L.marker([hit.lat, hit.lon], { title: hit.name }).addTo(map);
    searchMarker.bindPopup(
      `<b>${escHtml(hit.name)}</b><br>${escHtml(hit.display)}<br>` +
      `<a href="https://www.google.com/maps/dir/?api=1&destination=${hit.lat},${hit.lon}" ` +
      `target="_blank" rel="noopener" style="color:#7a4c2a;font-weight:600">↗ ${U('routeLong')}</a>`
    ).openPopup();
    map.setView([hit.lat, hit.lon], 13);
    setStatus(`${U('goingTo')} ${hit.name} · ${T('statusOk')(forecastData?.date || '')}`, 'ok');
  } catch (e) {
    setStatus(U('noPlace'), 'err');
  }
}

function clearSearch() {
  searchQuery = '';
  document.getElementById('search-input').value = '';
  document.getElementById('search-clear').classList.remove('visible');
  if (searchMarker) { map.removeLayer(searchMarker); searchMarker = null; }
  if (forecastData) {
    renderSidebar(forecastData);
    renderMarkers(forecastData);
  }
  updateUrl();
}

// ── Geolocation ───────────────────────────────────────────────────────────────
function requestUserPos(centerMap) {
  if (!navigator.geolocation) {
    setStatus(U('geoUnsupported'), 'err');
    return;
  }
  setStatus(U('geolocating'), 'loading');
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      userPos = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      filterSort = 'distance';
      const soSel = document.getElementById('filter-sort');
      if (soSel) soSel.value = 'distance';
      if (centerMap) map.setView([userPos.lat, userPos.lon], 12);
      if (searchMarker) { map.removeLayer(searchMarker); }
      searchMarker = L.circleMarker([userPos.lat, userPos.lon], {
        radius: 7, color: '#fff', weight: 2, fillColor: '#2a6fdb', fillOpacity: 1,
      }).addTo(map).bindPopup(U('locateMe'));
      if (forecastData) {
        renderSidebar(forecastData);
        renderMarkers(forecastData);
      }
      setStatus(U('sortedByDistance'), 'ok');
      updateUrl();
    },
    () => setStatus(U('geoDenied'), 'err'),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
  );
}

// ── UI event wiring ───────────────────────────────────────────────────────────
function applyStaticText() {
  const si = document.getElementById('search-input');
  if (si) si.placeholder = U('searchPlaceholder');
  const ml = document.getElementById('filter-min-label');
  if (ml) ml.textContent = U('only55');
  const so = document.getElementById('filter-sort');
  if (so) {
    ['sortScore','sortDistance','sortAltitude','sortName','sortComarca']
      .forEach((k, i) => { if (so.options[i]) so.options[i].textContent = U(k); });
  }
  const lb = document.getElementById('locate-btn');
  if (lb) lb.textContent = '◎ ' + U('locateMe');
  const lc = legend.getContainer?.();
  if (lc) lc.innerHTML = legendHtml();
}

function wireUi() {
  setLang(lang);
  const si = document.getElementById('search-input');
  si.addEventListener('input', onSearchInput);
  si.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); geocodeSearch(); }
    if (e.key === 'Escape') clearSearch();
  });
  document.getElementById('search-clear').addEventListener('click', clearSearch);

  document.getElementById('filter-species').addEventListener('change', (e) => {
    filterSpecies = e.target.value;
    if (forecastData) { renderSidebar(forecastData); renderMarkers(forecastData); }
    if (activeStation) { const stn = findStation(activeStation); if (stn) renderDetail(stn); }
    updateUrl();
  });
  document.getElementById('filter-comarca').addEventListener('change', (e) => {
    filterComarca = e.target.value;
    if (forecastData) { renderSidebar(forecastData); renderMarkers(forecastData); }
    updateUrl();
  });
  document.getElementById('filter-sort').addEventListener('change', (e) => {
    filterSort = e.target.value;
    if (filterSort === 'distance' && !userPos) requestUserPos(false);
    else if (forecastData) { renderSidebar(forecastData); renderMarkers(forecastData); }
    updateUrl();
  });
  document.getElementById('filter-min').addEventListener('change', (e) => {
    filterMin = e.target.checked;
    if (forecastData) { renderSidebar(forecastData); renderMarkers(forecastData); }
    updateUrl();
  });

  map.on('moveend', updateUrl);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const overlay = document.getElementById('explain-overlay');
      if (overlay?.classList.contains('visible')) closeExplainBtn();
      else if (activeStation) closeDetail();
    }
  });
}


document.getElementById('hdr-date').textContent =
  new Date().toLocaleDateString('ca-ES', { weekday:'long', day:'numeric', month:'long', year:'numeric' });

async function loadForecast() {
  const dot  = document.getElementById('status-dot');
  const txt  = document.getElementById('status-text');
  dot.className = 'dot loading';
  txt.textContent = T('loadingGeo');

  try {
    const res  = await fetch('/api/forecast');
    const data = await res.json();
    forecastData = data;
    const urlState = applyUrlState();

    renderDaySelector(data);
    renderSidebar(data);
    renderMarkers(data);

    if (urlState.est) {
      selectStation(urlState.est);
    } else if (Number.isFinite(urlState.lat) && Number.isFinite(urlState.lon)) {
      map.setView([urlState.lat, urlState.lon], Math.max(6, Math.min(18, urlState.z || 11)));
    } else {
      const allCoords = [];
      for (const stns of Object.values(data.comarques))
        for (const stn of stns) allCoords.push([stn.lat, stn.lon]);
      if (allCoords.length) map.fitBounds(allCoords, { padding: [40, 40] });
    }

    if (isMobile() && activeTab === 'list' && !urlState.est) switchTab('list');

    dot.className = 'dot ok';
    txt.textContent = T('statusOk', data.date);
    updateUrl();
  } catch (e) {
    dot.className = 'dot err';
    txt.textContent = (lang === 'ca' ? 'Error carregant dades: ' : 'Error loading data: ') + e.message;
  }
}

wireUi();
loadForecast();

// Invalidate map on resize/orientation change
window.addEventListener('resize', () => {
  map.invalidateSize();
  // If detail panel is open on mobile, keep it open
});
window.addEventListener('orientationchange', () => {
  setTimeout(() => map.invalidateSize(), 200);
});
</script>
</body>
</html>"""

# ── HTTP server ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html_str):
        body = html_str.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            self.send_html(HTML)

        elif path == "/api/forecast":
            try:
                data = build_forecast()
                self.send_json(data)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/api/stations":
            self.send_json(STATIONS)

        elif path == "/api/geocode":
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                results = geocode_place(qs.get("q", [""])[0])
                self.send_json({"query": qs.get("q", [""])[0], "results": results})
            except Exception as e:
                self.send_json({"results": [], "error": str(e)}, 502)

        elif path == "/api/parking":
            try:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                lat = float(qs.get("lat", [""])[0])
                lon = float(qs.get("lon", [""])[0])
                self.send_json({"results": find_parking(lat, lon)})
            except Exception as e:
                self.send_json({"results": [], "error": str(e)}, 502)

        else:
            self.send_response(404)
            self.end_headers()

# ── Entry point ───────────────────────────────────────────────────────────────

PORT = int(os.environ.get("PORT", 8765))

if __name__ == "__main__":
    server = HTTPServer(("", PORT), Handler)
    print(f"\n  🍄  Bolets Forecast")
    print(f"  ➜  http://localhost:{PORT}")
    print(f"  ➜  API: http://localhost:{PORT}/api/forecast")
    print(f"\n  Ctrl+C to stop\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
