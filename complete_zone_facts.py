#!/usr/bin/env python3
"""Phase 7.2 — complete the curated zone facts (access, water, canopy consistency).

Fills the fields that the curated `zones.json` leaves null even though real,
citable data exists, so the curated layer stops being thinner than the enriched
layer:

- `water_m`            — distance to the nearest OSM waterway/waterbody (Overpass).
                         A missing feature reads "unknown" (water_m stays null;
                         when Overpass answered, `water_source` says no feature was
                         mapped within the radius), never "no water".
- `access.parking_*`   — for the 69 zones added in Phase 6.2 whose parking is null,
                         the nearest OSM `amenity=parking` (same Overpass query as
                         water). Existing curated Phase-2 parking points are kept.
- `access.drive_min`   — OSRM driving time (minutes) from the comarca capital (a
                         documented reference point) to the zone's parking point,
                         or to the zone centroid when no parking is mapped.
- `access.difficulty`  — a written rule from slope + walk distance (straight-line
                         parking → centroid, or station forest point → centroid
                         when no parking is mapped).
- removes `forest.canopy_pct` / `forest.undergrowth` from `zones.json`: these are
  duplicated null placeholders — the real LiDAR canopy lives in
  `zones_enriched.json` under `enrichment.canopy` (Phase 3.3).

Nothing here invents a distance, coordinate or difficulty: every value is either
computed (OSRM route, Overpass geometry, slope/walk rule) or explicitly "unknown"
with a source label. External results are cached in `water_cache.json` and
`route_cache.json` (both gitignored), so a re-run never re-queries a point it has
already answered.

The water/parking derivation degrades gracefully: when Overpass is unreachable,
water_m/parking stay null (unknown) and nothing is written that implies "no
water" or "no parking"; the OSRM/slope/rule derivations still run, so a partial
run never fabricates.

Usage:
    python3 complete_zone_facts.py              # derive + write zones.json
    python3 complete_zone_facts.py --skip-overpass  # no Overpass (OSRM + rules only)
    python3 complete_zone_facts.py --dry-run    # derive, print summary, do not write
    python3 complete_zone_facts.py --self-test  # offline unit checks (no network)
    python3 complete_zone_facts.py --check-schema  # zones.json ↔ zones_enriched.json agree
"""

import argparse
import json
import math
import os
import sys
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZONES_FILE = os.environ.get("ZONES_FILE") or os.path.join(BASE_DIR, "zones.json")
ENRICHED_FILE = os.environ.get("ZONES_ENRICHED_FILE") or os.path.join(BASE_DIR, "zones_enriched.json")
MUSHROOMS = os.path.join(BASE_DIR, "mushrooms.json")
WATER_CACHE = os.path.join(BASE_DIR, "water_cache.json")
ROUTE_CACHE = os.path.join(BASE_DIR, "route_cache.json")

UA = "BoletsForecast/1.0 (zone facts; water/parking + drive time)"

# Radii (metres). Water uses a tighter radius than parking (a stand's drainage
# is a local feature; parking is a road feature reached by car).
WATER_RADIUS_M = 2000.0
PARKING_RADIUS_M = 2500.0

# World mirrors, tried in order. The French mirror is first because the main
# instance has been flapping between 502 "at capacity" and multi-second queues
# (2026-11-16 retry) while overpass.openstreetmap.fr answered a Catalan
# station bbox in ~2 s with full water/parking coverage. The primary and the
# kumi mirror stay as fallbacks.
OVERPASS_ENDPOINTS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_TIMEOUT = 60  # seconds; fail fast when the instance is degraded

OSRM_ENDPOINT = "https://router.project-osrm.org/route/v1/driving"

# ── Comarca capitals (documented reference points for drive_min) ──────────────
#
# One official capital per comarca (Viquipèdia / OSM Nominatim place records).
# The mushrooms.json "Montseny" key is a massís, not a comarca, so its three
# stations are overridden to their real comarca capital below. "La Canya –
# Ripollès/Cerdanya" is keyed under Cerdanya but sits in Ripollès (flagged in
# step 2.4), so it is overridden to Ripoll too.
CAPITALS = {
    "Alt Penedès":      ("Vilafranca del Penedès", 41.3462, 1.6994),
    "Alt Urgell":       ("la Seu d'Urgell", 42.3576, 1.4560),
    "Alta Ribagorça":   ("el Pont de Suert", 42.4082, 0.7411),
    "Baix Empordà":     ("la Bisbal d'Empordà", 41.9592, 3.0398),
    "Berguedà":         ("Berga", 42.1011, 1.8455),
    "Cerdanya":         ("Puigcerdà", 42.4318, 1.9279),
    "Garraf":           ("Vilanova i la Geltrú", 41.2240, 1.7250),
    "Garrotxa":         ("Olot", 42.1820, 2.4890),
    "Gironès":          ("Girona", 41.9794, 2.8214),
    "La Selva":         ("Santa Coloma de Farners", 41.8600, 2.6620),
    "Maresme":          ("Mataró", 41.5381, 2.4457),
    "Montseny":         None,  # massís — see STATION_CAPITAL below
    "Montsià":          ("Amposta", 40.7100, 0.5800),
    "Noguera":          ("Balaguer", 41.7890, 0.8050),
    "Osona":            ("Vic", 41.9301, 2.2540),
    "Pallars Sobirà":   ("Sort", 42.4115, 1.1298),
    "Priorat":          ("Falset", 41.1450, 0.8210),
    "Ripollès":         ("Ripoll", 42.2000, 2.1900),
    "Solsonès":         ("Solsona", 41.9940, 1.5170),
    "Terra Alta":       ("Gandesa", 41.0530, 0.4380),
    "Val d'Aran":       ("Vielha", 42.7010, 0.7950),
    "Vallès Oriental":  ("Granollers", 41.6080, 2.2876),
}

STATION_CAPITAL = {
    "Montseny – Arbúcies":        ("Santa Coloma de Farners (La Selva)", 41.8600, 2.6620),
    "Montseny – Santa Fe":        ("Granollers (Vallès Oriental)", 41.6080, 2.2876),
    "Montseny – El Brull":        ("Vic (Osona)", 41.9301, 2.2540),
    "La Canya – Ripollès/Cerdanya": ("Ripoll (Ripollès)", 42.2000, 2.1900),
}

CAPITAL_SOURCE = "Viquipèdia / OSM Nominatim — capital de comarca"


# ── Small geometry helpers ────────────────────────────────────────────────────

def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _metres_per_deg(lat):
    """Approximate metres per degree at `lat` (equirectangular, fine for <3 km)."""
    mlat = 111132.92
    mlon = 111412.84 * math.cos(math.radians(lat)) \
        - 93.5 * math.cos(3 * math.radians(lat))
    return mlat, mlon


def _p2seg_m(ax, ay, bx, by):
    """Distance from the origin (0,0) to the segment (ax,ay)-(bx,by), metres."""
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(ax + t * dx, ay + t * dy)


def nearest_water_m(zone_lat, zone_lon, ways):
    """Minimum straight-line distance (m) from a point to any water polyline."""
    mlat, mlon = _metres_per_deg(zone_lat)
    best = None
    for way in ways:
        if not way:
            continue
        prev = way[0]
        px = (prev[1] - zone_lon) * mlon
        py = (prev[0] - zone_lat) * mlat
        if len(way) == 1:
            d = math.hypot(px, py)
            if best is None or d < best:
                best = d
            continue
        for nxt in way[1:]:
            qx = (nxt[1] - zone_lon) * mlon
            qy = (nxt[0] - zone_lat) * mlat
            d = _p2seg_m(px, py, qx, qy)
            if best is None or d < best:
                best = d
            px, py = qx, qy
    return best


def nearest_parking_m(zone_lat, zone_lon, parking):
    """Nearest parking point (node, or way centroid) within `PARKING_RADIUS_M`."""
    best = None
    best_row = None
    for row in parking:
        d = haversine_m(zone_lat, zone_lon, row["lat"], row["lon"])
        if d <= PARKING_RADIUS_M and (best is None or d < best):
            best = d
            best_row = row
    return best, best_row


# ── Difficulty rule (written, documented) ─────────────────────────────────────

def difficulty(walk_m, slope_deg):
    """Derive a difficulty label from slope + walk distance.

    Written rule (documented in README):
      with a walk origin (parking, else the station forest point):
        fàcil    walk ≤ 1500 m and slope < 20°
        moderada walk ≤ 4000 m and slope < 30°
        exigent  otherwise
      when no walk origin is available (slope only):
        fàcil    slope < 15°
        moderada slope < 25°
        exigent  otherwise
    """
    if walk_m is not None:
        if walk_m <= 1500 and slope_deg < 20:
            return "fàcil"
        if walk_m <= 4000 and slope_deg < 30:
            return "moderada"
        return "exigent"
    if slope_deg is None:
        return None
    if slope_deg < 15:
        return "fàcil"
    if slope_deg < 25:
        return "moderada"
    return "exigent"


# ── Overpass (water + parking, one bbox query per station) ────────────────────

def _bbox_pad(lat):
    mlat, mlon = _metres_per_deg(lat)
    radius = max(WATER_RADIUS_M, PARKING_RADIUS_M)
    return radius / mlat, radius / mlon


def station_bbox(zones):
    """Bounding box of a station's zones, padded by the query radius."""
    lats = [z["lat"] for z in zones]
    lons = [z["lon"] for z in zones]
    clat = sum(lats) / len(lats)
    plat, plon = _bbox_pad(clat)
    return (min(lats) - plat, min(lons) - plon,
            max(lats) + plat, max(lons) + plon)


def overpass_query(south, west, north, east):
    """Fetch water ways + parking nodes/ways in a bbox. Returns raw elements."""
    query = (
        "[out:json][timeout:60];"
        "("
        f'way["waterway"]({south},{west},{north},{east});'
        f'way["natural"="water"]({south},{west},{north},{east});'
        f'way["water"]({south},{west},{north},{east});'
        f'node["amenity"="parking"]({south},{west},{north},{east});'
        f'way["amenity"="parking"]({south},{west},{north},{east});'
        ");"
        "out geom;"
    )
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint, data=body,
                headers={"User-Agent": UA,
                         "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=OVERPASS_TIMEOUT) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
    raise last


def parse_overpass(data):
    """Return (water_ways, parking) from an Overpass `out geom` response."""
    water_ways = []
    parking = []
    for el in data.get("elements", []):
        eltype = el.get("type")
        tags = el.get("tags") or {}
        if eltype == "way":
            geom = el.get("geometry") or []
            pts = [[g["lat"], g["lon"]] for g in geom if "lat" in g and "lon" in g]
            if not pts:
                continue
            is_water = "waterway" in tags or (tags.get("natural") == "water") \
                or "water" in tags
            if is_water:
                water_ways.append(pts)
            if tags.get("amenity") == "parking":
                lat = sum(p[0] for p in pts) / len(pts)
                lon = sum(p[1] for p in pts) / len(pts)
                parking.append({"lat": lat, "lon": lon,
                                "name": tags.get("name") or "Aparcament"})
        elif eltype == "node" and tags.get("amenity") == "parking":
            parking.append({"lat": el.get("lat"), "lon": el.get("lon"),
                            "name": tags.get("name") or "Aparcament"})
    return water_ways, parking


# ── OSRM drive time ───────────────────────────────────────────────────────────

_route_lock = threading.Lock()


def load_route_cache():
    try:
        with open(ROUTE_CACHE) as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def save_route_cache(cache):
    with _route_lock:
        with open(ROUTE_CACHE, "w") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)


def osrm_drive_min(route_cache, olat, olon, dlat, dlon):
    """OSRM driving time in whole minutes (cached). Returns None on failure."""
    key = f"{olat:.5f},{olon:.5f}|{dlat:.5f},{dlon:.5f}"
    with _route_lock:
        if key in route_cache:
            return route_cache[key]
    url = (f"{OSRM_ENDPOINT}/{olon},{olat};{dlon},{dlat}"
           "?overview=false&steps=false")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        mins = int(round(data["routes"][0]["duration"] / 60.0))
    except Exception:
        return None
    with _route_lock:
        route_cache[key] = mins
    return mins


# ── Schema agreement check ────────────────────────────────────────────────────

def check_schema(zones, enriched):
    """Verify zones.json and zones_enriched.json agree. Returns list of errors."""
    errs = []
    z_stations = zones.get("zones", {})
    e_stations = enriched.get("zones", {})
    if set(z_stations.keys()) != set(e_stations.keys()):
        errs.append("station keys differ between zones.json and zones_enriched.json")
    e_by_id = {}
    for stn, zs in e_stations.items():
        for z in zs:
            e_by_id.setdefault(z.get("id"), []).append(z)
    for stn, zs in z_stations.items():
        for z in zs:
            zid = z.get("id")
            if zid not in e_by_id:
                errs.append(f"zone {zid!r} missing from zones_enriched.json")
                continue
            e = next(zz for zz in e_by_id[zid] if zz.get("id") == zid)
            for k, v in z.items():
                if k == "enrichment":
                    continue
                if k not in e or e[k] != v:
                    errs.append(f"zone {zid}: curated field {k!r} differs")
            if "canopy_pct" in z.get("forest", {}) or "undergrowth" in z.get("forest", {}):
                errs.append(f"zone {zid}: forest.canopy_pct/undergrowth still present")
            canopy = (e.get("enrichment") or {}).get("canopy") or {}
            if canopy.get("canopy_pct") is None:
                errs.append(f"zone {zid}: enrichment.canopy.canopy_pct missing")
    return errs


# ── Derivation ────────────────────────────────────────────────────────────────

def _capital_for(comarca, station_name):
    override = STATION_CAPITAL.get(station_name)
    if override:
        return override
    return CAPITALS.get(comarca)


def _derive_zone(zone, water_ways, parking, ref, route_cache, overpass_ok,
                 station_lat, station_lon):
    """Fill one zone's water/access facts and remove canopy placeholders."""
    lat, lon = zone["lat"], zone["lon"]

    # water_m (only touched when Overpass actually answered — otherwise the
    # field is left null with no source, i.e. "not yet derived", never faked)
    if overpass_ok:
        d = nearest_water_m(lat, lon, water_ways) if water_ways else None
        if d is not None and d <= WATER_RADIUS_M:
            zone["water_m"] = int(round(d))
            zone["water_source"] = ("OSM waterway/waterbody via Overpass "
                                    "(distància al segment més proper)")
        else:
            zone["water_m"] = None
            zone["water_source"] = ("OSM: cap element d'aigua cartografiat en "
                                    f"{int(WATER_RADIUS_M)} m (desconegut, no 'sense aigua')")

    # parking — only fill when null (keep curated Phase-2 points)
    acc = zone.setdefault("access", {})
    if acc.get("parking_lat") is None or acc.get("parking_lon") is None:
        if overpass_ok:
            _dist, row = nearest_parking_m(lat, lon, parking)
            if row is not None:
                acc["parking_lat"] = round(row["lat"], 6)
                acc["parking_lon"] = round(row["lon"], 6)
                acc["parking_source"] = "OSM (Overpass, aparcament més proper)"

    # drive_min (OSRM, documented reference → parking, else centroid)
    plat = acc.get("parking_lat")
    plon = acc.get("parking_lon")
    if plat is None or plon is None:
        plat, plon = lat, lon
        dest_note = "la zona (sense aparcament cartografiat)"
    else:
        dest_note = "l'aparcament"
    if ref is not None:
        mins = osrm_drive_min(route_cache, ref[1], ref[2], plat, plon)
        if mins is not None:
            acc["drive_min"] = mins
            acc["drive_min_source"] = (
                f"OSRM driving · {ref[0]} → {dest_note}; "
                f"origen: {CAPITAL_SOURCE}")
        elif acc.get("drive_min") is not None:
            # OSRM failed: keep the previous sourced value instead of nulling a
            # fact that was already derived from a real route (a retry must not
            # destroy data).
            pass
        else:
            acc["drive_min"] = None
            acc["drive_min_source"] = "OSRM no disponible (sense valor)"
    else:
        acc["drive_min"] = None
        acc["drive_min_source"] = "cap capital de comarca documentat"

    # difficulty (slope + walk distance rule). Walk origin is the mapped parking
    # when present, otherwise the station's documented forest/access point.
    walk_lat = acc.get("parking_lat") if acc.get("parking_lat") is not None else station_lat
    walk_lon = acc.get("parking_lon") if acc.get("parking_lon") is not None else station_lon
    walk = haversine_m(lat, lon, walk_lat, walk_lon) \
        if walk_lat is not None and walk_lon is not None else None
    acc["difficulty"] = difficulty(walk, zone.get("slope_deg"))
    acc["difficulty_source"] = (
        "regla escrita: pendent + distància a peu en línia recta des de "
        "l'aparcament (o el punt d'estació si no hi ha aparcament)" if walk is not None else
        "regla escrita: pendent (sense punt de partida)")

    # remove duplicated null canopy placeholders (real values in enrichment)
    forest = zone.get("forest")
    if isinstance(forest, dict):
        forest.pop("canopy_pct", None)
        forest.pop("undergrowth", None)


def derive_station(zones, comarca, station_name, station_lat, station_lon,
                   water_cache, route_cache, skip_overpass):
    """Derive facts for one station's zones. Mutates the zone dicts in place."""
    ref = _capital_for(comarca, station_name)
    overpass_ok = False
    water_ways = []
    parking = []

    if not skip_overpass:
        cached = water_cache.get(station_name)
        if isinstance(cached, dict) and cached.get("water_ways") is not None:
            water_ways = cached["water_ways"]
            parking = cached["parking"]
            overpass_ok = True
        else:
            south, west, north, east = station_bbox(zones)
            try:
                data = overpass_query(south, west, north, east)
                water_ways, parking = parse_overpass(data)
                water_cache[station_name] = {
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source": "Overpass (waterway/natural=water/water + amenity=parking)",
                    "water_ways": water_ways,
                    "parking": parking,
                }
                overpass_ok = True
            except Exception:
                overpass_ok = False

    for z in zones:
        _derive_zone(z, water_ways, parking, ref, route_cache, overpass_ok,
                     station_lat, station_lon)
    return station_name, overpass_ok


# ── Main ──────────────────────────────────────────────────────────────────────

def _counts(zones_doc):
    c = {"water": 0, "water_unknown": 0, "parking": 0, "drive": 0,
         "difficulty": 0, "difficulty_null": 0}
    for stn, zs in zones_doc["zones"].items():
        for z in zs:
            if z.get("water_m") is not None:
                c["water"] += 1
            else:
                c["water_unknown"] += 1
            acc = z.get("access", {})
            if acc.get("parking_lat") is not None:
                c["parking"] += 1
            if acc.get("drive_min") is not None:
                c["drive"] += 1
            if acc.get("difficulty") is not None:
                c["difficulty"] += 1
            else:
                c["difficulty_null"] += 1
    return c


def run(dry_run=False, skip_overpass=False):
    with open(ZONES_FILE) as f:
        zones_doc = json.load(f)
    with open(MUSHROOMS) as f:
        stations_doc = json.load(f)
    target = stations_doc["target_stations"]
    zones_by_station = zones_doc.get("zones", {})

    water_cache = {}
    if os.path.exists(WATER_CACHE):
        try:
            with open(WATER_CACHE) as f:
                water_cache = json.load(f)
        except (ValueError, OSError):
            water_cache = {}
    route_cache = load_route_cache()

    jobs = []
    for comarca, stns in target.items():
        for stn in stns:
            zs = zones_by_station.get(stn["name"], [])
            if zs:
                jobs.append((comarca, stn["name"], stn.get("lat"),
                             stn.get("lon"), zs))

    n_overpass_ok = 0
    n_overpass_fail = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(derive_station, zs, comarca, name, slat, slon,
                          water_cache, route_cache, skip_overpass): name
                for (comarca, name, slat, slon, zs) in jobs}
        for fut in as_completed(futs):
            name, overpass_ok = fut.result()
            if overpass_ok:
                n_overpass_ok += 1
            else:
                n_overpass_fail += 1
            print(f"  {name}: {'overpass OK' if overpass_ok else 'overpass unavailable'}",
                  flush=True)

    try:
        with open(WATER_CACHE, "w") as f:
            json.dump(water_cache, f, ensure_ascii=False)
    except OSError:
        pass
    save_route_cache(route_cache)

    if not dry_run:
        with open(ZONES_FILE, "w") as f:
            json.dump(zones_doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

    counts = _counts(zones_doc)
    counts["overpass_ok"] = n_overpass_ok
    counts["overpass_fail"] = n_overpass_fail
    return zones_doc, counts


def _self_test():
    """Offline unit checks: geometry, difficulty rule, canopy removal, schema."""
    import copy
    d = _p2seg_m(0.0, 3.0, 10.0, 3.0)
    assert abs(d - 3.0) < 1e-6, d
    way = [[42.0009, 1.0], [42.0009, 1.0009]]  # ~100 m north of the origin
    d = nearest_water_m(42.0, 1.0, [way])
    assert 90 < d < 110, d
    assert difficulty(1500, 19) == "fàcil"
    assert difficulty(1501, 19) == "moderada"
    assert difficulty(1000, 20) == "moderada"
    assert difficulty(4001, 10) == "exigent"
    assert difficulty(1000, 30) == "exigent"
    assert difficulty(None, 14) == "fàcil"
    assert difficulty(None, 15) == "moderada"
    assert difficulty(None, 25) == "exigent"
    assert difficulty(None, None) is None

    z = {
        "id": "t", "lat": 42.0, "lon": 1.0, "alt_m": 1000, "slope_deg": 18.0,
        "forest": {"type": "conifer", "canopy_pct": None, "undergrowth": None},
        "access": {"parking_lat": None, "parking_lon": None},
    }
    _derive_zone(z, [], [], None, {}, overpass_ok=False,
                 station_lat=42.0, station_lon=1.0)
    assert "canopy_pct" not in z["forest"] and "undergrowth" not in z["forest"]
    assert "water_m" not in z  # overpass down → left untouched, never faked
    assert z["access"]["difficulty"] == "fàcil"  # walk 0 + slope 18 → fàcil
    assert z["access"]["drive_min"] is None  # no capital

    # A retry must not wipe a drive_min that was already derived from a route
    # just because OSRM is momentarily unavailable.
    z2 = {"id": "t2", "lat": 42.0, "lon": 1.0, "slope_deg": 10.0,
          "access": {"parking_lat": 42.01, "parking_lon": 1.01,
                     "drive_min": 33, "drive_min_source": "prev"}}
    _orig_osrm = globals()["osrm_drive_min"]
    globals()["osrm_drive_min"] = lambda *a: None
    try:
        _derive_zone(z2, [], [], ("Ref", 42.0, 1.0), {}, overpass_ok=False,
                     station_lat=42.0, station_lon=1.0)
    finally:
        globals()["osrm_drive_min"] = _orig_osrm
    assert z2["access"]["drive_min"] == 33, z2["access"]
    assert z2["access"]["drive_min_source"] == "prev", z2["access"]

    zz = {"version": 1, "zones": {"S": [z]}}
    ee = {"version": 1, "zones": {"S": [{
        **copy.deepcopy(z),
        "enrichment": {"canopy": {"canopy_pct": 0.7}},
    }]}}
    errs = check_schema(zz, ee)
    assert errs == [], errs
    print("self-test OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-overpass", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check-schema", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        _self_test()
        return

    if args.check_schema:
        with open(ZONES_FILE) as f:
            zones = json.load(f)
        with open(ENRICHED_FILE) as f:
            enriched = json.load(f)
        errs = check_schema(zones, enriched)
        if errs:
            for e in errs:
                print("MISMATCH:", e)
            sys.exit(1)
        print(f"schema OK: {len(zones['zones'])} stations / "
              f"{sum(len(v) for v in zones['zones'].values())} zones agree")
        return

    zones_doc, counts = run(dry_run=args.dry_run, skip_overpass=args.skip_overpass)
    n_zones = sum(len(v) for v in zones_doc["zones"].values())
    verb = "DRY RUN" if args.dry_run else "WROTE"
    print(f"\n{verb} {ZONES_FILE}: {len(zones_doc['zones'])} stations / "
          f"{n_zones} zones")
    print(f"  overpass: {counts['overpass_ok']} stations OK / "
          f"{counts['overpass_fail']} unavailable")
    print(f"  water_m: {counts['water']} filled / {counts['water_unknown']} unknown")
    print(f"  parking: {counts['parking']} zones")
    print(f"  drive_min: {counts['drive']} filled")
    print(f"  difficulty: {counts['difficulty']} filled / "
          f"{counts['difficulty_null']} null")


if __name__ == "__main__":
    main()
