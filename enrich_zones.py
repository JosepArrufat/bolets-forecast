#!/usr/bin/env python3
"""Phase 3.1 — terrain/canopy enrichment skeleton and cache.

Reads the curated micro-zones from `zones.json`, runs each zone through the
enrichment providers, and writes `zones_enriched.json`. External samples (DEM,
LiDAR, soil, habitat) are cached by rounded lat/lon — with their source and a
timestamp — so a later run, or a later phase step, reuses them instead of
re-querying.

This is the enrichment pipeline. The DEM provider (step 3.2) and the LiDAR
canopy provider (step 3.3) are implemented; the soil and habitat providers
(step 3.4) are still stubs that return `None` ("not implemented"). Nothing here
invents a value: the output carries every curated field from `zones.json`
unchanged, plus an `enrichment` block whose un-computed factors are `null` /
`"pending"` with a note pointing at the step that will fill them.

Usage:
    python3 enrich_zones.py             # enrich all zones → zones_enriched.json
    python3 enrich_zones.py --self-test # offline round-trip of cache + enrich

Environment:
    ZONES_FILE            — path to the curated zones file (default: zones.json)
    ZONES_ENRICHED_FILE   — output path (default: zones_enriched.json)
    ENRICH_CACHE_FILE     — cache path (default: terrain_cache.json)
"""

import json
import math
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZONES_FILE = os.environ.get("ZONES_FILE") or os.path.join(BASE_DIR, "zones.json")
OUT_FILE = os.environ.get("ZONES_ENRICHED_FILE") or os.path.join(BASE_DIR, "zones_enriched.json")
CACHE_FILE = os.environ.get("ENRICH_CACHE_FILE") or os.path.join(BASE_DIR, "terrain_cache.json")

# Rounding precision for the cache key. 4 decimal places ≈ 11 m, matching the
# `cache_key` used by app.py for IGME/CORINE geo caching.
CACHE_PRECISION = 4

# ── Step 3.2: ICGC 5 m LiDAR DEM sampling ─────────────────────────────────────
#
# The DEM (Digital Elevation Model) is queried through the ICGC "elevacions-
# territorial" WMS GetFeatureInfo, which returns the ground elevation at a pixel.
# We sample a small neighbourhood around each zone centroid (cardinal points at
# ~50 m for fine slope/aspect/curvature, diagonals at ~150 m for a broader
# topographic context) and derive the terrain metrics below from that grid.
#
#     DEM_LAYER — "model-elevacions-terreny-catalunya-lidar-5m-2021-2023"
#
# Nothing here invents a value: every metric is a deterministic function of the
# sampled elevations (or of latitude + slope + aspect for solar radiation), and
# the raw samples are cached with their source and timestamp.

DEM_WMS = "https://geoserveis.icgc.cat/servei/catalunya/elevacions-territorial/wms"
DEM_LAYER = "model-elevacions-terreny-catalunya-lidar-5m-2021-2023"
DEM_SOURCE = "ICGC 5m LiDAR DEM (2021-2023)"
DEM_UA = "BoletsForecast/1.0 (terrain enrichment; step 3.2)"

# Neighbourhood radii for the derived metrics (metres). The fine cross drives
# slope/aspect/curvature at the stand scale; the coarse diagonals drive TPI and
# cold-air pooling against the surrounding terrain context.
DEM_FINE_M = 100.0
DEM_COARSE_M = 250.0


# ── Cache by rounded lat/lon, with source + timestamp per sample ───────────────

def cache_key(lat, lon, precision=CACHE_PRECISION):
    """Canonical key for a coordinate: rounded to `precision` decimal places."""
    return f"{lat:.{precision}f},{lon:.{precision}f}"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_cache_write_lock = threading.Lock()


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            pass
    return {}


def save_cache(cache):
    with _cache_write_lock:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)


def get_sample(cache, lat, lon, provider_key):
    """Return a previously cached sample for (lat, lon, provider), or None."""
    entry = cache.get(cache_key(lat, lon)) or {}
    return entry.get(provider_key)


def put_sample(cache, lat, lon, provider_key, source, values):
    """Record a sample with its source and timestamp. Returns the stored record."""
    entry = cache.setdefault(cache_key(lat, lon), {})
    record = {"source": source, "timestamp": _now(), "values": values}
    entry[provider_key] = record
    return record


# ── DEM sampling and derived metrics (step 3.2) ────────────────────────────────

def _metres_per_deg_lat():
    # 1 degree of latitude ≈ 111,320 m (WGS84 mean). Good to <0.5% over Catalonia.
    return 111320.0


def _offset(lat, lon, dn_m, de_m):
    """Return (lat, lon) offset by dn_m north and de_m east."""
    m = _metres_per_deg_lat()
    return lat + dn_m / m, lon + de_m / (m * math.cos(math.radians(lat)))


def _dem_elevation(lat, lon):
    """Ground elevation (m) at a point from the ICGC 5m LiDAR DEM, or None."""
    d = 0.0005  # ~55 m box centred on the point
    url = (
        f"{DEM_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo"
        f"&LAYERS={DEM_LAYER}&QUERY_LAYERS={DEM_LAYER}&STYLES="
        f"&CRS=EPSG:4326&BBOX={lat-d},{lon-d},{lat+d},{lon+d}"
        "&WIDTH=101&HEIGHT=101&I=50&J=50&INFO_FORMAT=text/plain"
    )
    time.sleep(0.1)  # be polite: one elevation probe at a time
    try:
        req = urllib.request.Request(url, headers={"User-Agent": DEM_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8", "replace")
        for line in txt.splitlines():
            if "value_0" in line:
                return float(line.split("=", 1)[1].strip().strip("'"))
    except Exception:
        pass
    return None


def _sample_dem_neighborhood(cache, lat, lon):
    """Sample the 9-point DEM neighbourhood (cached per coordinate).

    Returns a dict:
        center          — (lat, lon, z) of the zone centroid
        cardinal        — [(lat, lon, z) x4] N/S/E/W at DEM_FINE_M
        diagonals       — [(lat, lon, z) x4] NE/NW/SE/SW at DEM_COARSE_M
    or None when the centre elevation cannot be sampled.
    """
    def elev(la, lo):
        key = cache_key(la, lo)
        entry = cache.setdefault(key, {})
        rec = entry.get("dem_elev")
        if rec and rec.get("source") == DEM_SOURCE and isinstance(rec.get("values", {}).get("z"), float):
            return rec["values"]["z"]
        z = _dem_elevation(la, lo)
        if z is None:
            return None
        entry["dem_elev"] = {"source": DEM_SOURCE, "timestamp": _now(),
                             "values": {"z": z, "unit": "m"}}
        return z

    zc = elev(lat, lon)
    if zc is None:
        return None
    center = (lat, lon, zc)
    cardinal = []
    for dn, de in ((DEM_FINE_M, 0), (-DEM_FINE_M, 0), (0, DEM_FINE_M), (0, -DEM_FINE_M)):
        la, lo = _offset(lat, lon, dn, de)
        z = elev(la, lo)
        if z is None:
            return None
        cardinal.append((la, lo, z))
    diagonals = []
    for dn, de in ((DEM_COARSE_M, DEM_COARSE_M), (DEM_COARSE_M, -DEM_COARSE_M),
                   (-DEM_COARSE_M, DEM_COARSE_M), (-DEM_COARSE_M, -DEM_COARSE_M)):
        la, lo = _offset(lat, lon, dn, de)
        z = elev(la, lo)
        if z is None:
            return None
        diagonals.append((la, lo, z))
    return {"center": center, "cardinal": cardinal, "diagonals": diagonals}


def _slope_aspect(zc, z_n, z_s, z_e, z_w, step_m):
    """Slope (deg) and aspect (deg from north) from a cross of elevations."""
    dzdx = (z_e - z_w) / (2 * step_m)
    dzdy = (z_n - z_s) / (2 * step_m)
    slope = math.degrees(math.atan(math.hypot(dzdx, dzdy)))
    # Aspect = the direction the slope faces (downslope = -gradient), clockwise
    # from north. A north-facing slope (zN > zS) → aspect ~0°.
    aspect = (math.degrees(math.atan2(-dzdx, -dzdy)) + 360.0) % 360.0
    return slope, aspect


def _solar_radiation(lat, slope_deg, aspect_deg):
    """Relative potential clear-sky solar radiation.

    Annual index = mean over 12 months of the daily clear-sky insolation on a
    tilted surface, expressed as a ratio to a horizontal surface at the same
    latitude. `seasonal` holds the same ratio for the peak six months
    (Mar–Aug, the growing season). This is a dimensionless potential-irradiation
    ratio derived only from latitude, slope and aspect — not a cloud-corrected
    absolute insolation.

    Computed by numerically integrating cos(incidence angle) for every 12-minute
    step of the sunlit day (Gates, 1980), then dividing tilted by horizontal.
    """
    latr = math.radians(lat)
    slope = math.radians(slope_deg)
    # Surface azimuth measured from SOUTH (south = 0, east positive), per the
    # standard incidence-angle formula; `aspect_deg` is clockwise from NORTH.
    gamma = math.radians(aspect_deg - 180.0)

    decl_by_month = [-20.9, -12.9, -1.8, 9.9, 18.9, 23.3,
                     21.0, 13.3, 2.2, -9.6, -18.9, -23.1]

    def day_energy(decl_deg):
        decl = math.radians(decl_deg)
        # Hour angle at sunset (cos h0 = -tan(phi)·tan(δ)).
        cos_h0 = -math.tan(latr) * math.tan(decl)
        cos_h0 = max(-1.0, min(1.0, cos_h0))
        h0 = math.acos(cos_h0)
        if h0 <= 0:
            return 0.0, 0.0  # polar night: no sun on either surface
        n = 24  # 12-minute steps over a symmetric -h0..+h0 day
        tilted = horizontal = 0.0
        for k in range(1, n + 1):
            h = -h0 + (2 * h0) * k / n
            sin_h = math.sin(h)
            cos_h = math.cos(h)
            # cos(zenith) on a horizontal surface
            cos_zen_h = math.sin(latr) * math.sin(decl) + math.cos(latr) * math.cos(decl) * cos_h
            # cos(incidence) on the tilted surface (surface azimuth from south)
            cos_inc = (
                math.sin(decl) * math.sin(latr) * math.cos(slope)
                - math.sin(decl) * math.cos(latr) * math.sin(slope) * math.cos(gamma)
                + math.cos(decl) * math.cos(latr) * math.cos(slope) * cos_h
                + math.cos(decl) * math.sin(latr) * math.sin(slope) * math.cos(gamma) * cos_h
                + math.cos(decl) * math.sin(slope) * math.sin(gamma) * sin_h
            )
            if cos_inc > 0:
                tilted += cos_inc
            if cos_zen_h > 0:
                horizontal += cos_zen_h
        if horizontal <= 0:
            return 0.0, 0.0
        return tilted / horizontal, 1.0

    ratios = []
    for decl in decl_by_month:
        r, _ = day_energy(decl)
        ratios.append(r)
    annual = sum(ratios) / 12.0
    seasonal = sum(ratios[2:8]) / 6.0  # March–August
    return {"annual": round(annual, 3), "seasonal": round(seasonal, 3)}


def _dem_metrics(neighborhood, lat):
    """Derive curvature, TPI and cold-air pooling from a sampled neighbourhood.

    `neighborhood` is the dict from `_sample_dem_neighborhood`. Curvature is the
    Laplacian of elevation over the fine 100 m cross (m⁻¹); negative is convex
    (ridge/crest), positive is concave (hollow/gully). TPI is the centre minus
    the mean of the coarse 250 m ring (m): negative = valley bottom, positive =
    ridge top. Cold-air pooling is the centre minus the minimum of the coarse
    ring (m): ~0 means the point sits in the local depression where cold air
    settles, a large positive value means it drains.
    """
    _, _, zc = neighborhood["center"]
    (_, _, zn), (_, _, zs), (_, _, ze), (_, _, zw) = neighborhood["cardinal"]
    (_, _, zne), (_, _, znw), (_, _, zse), (_, _, zsw) = neighborhood["diagonals"]

    slope, aspect = _slope_aspect(zc, zn, zs, ze, zw, DEM_FINE_M)
    # Laplacian over a cross of spacing h: (zN + zS + zE + zW - 4·zc) / h².
    curvature = (zn + zs + ze + zw - 4 * zc) / (DEM_FINE_M ** 2)

    ring = [zne, znw, zse, zsw]
    tpi = zc - sum(ring) / len(ring)
    pooling = zc - min(ring)

    solar = _solar_radiation(lat, slope, aspect)

    return {
        "dem_alt_m": round(zc, 1),
        "slope_deg": round(slope, 1),
        "aspect_deg": round(aspect, 0),
        "curvature": round(curvature, 6),      # m⁻¹ (second derivative of z)
        "tpi": round(tpi, 1),                  # m (centre vs 150 m ring mean)
        "cold_air_pooling": round(pooling, 1),  # m (centre vs 150 m ring min)
        "solar_radiation": solar,              # dimensionless ratio (annual/seasonal)
    }


# ── Step 3.3: ICGC LiDAR vegetation height (canopy) sampling ──────────────────
#
# The canopy metrics come from the ICGC LiDAR *vegetation height* raster (the
# "alcàries de vegetació" model — the canopy height model CHM = surface − ground,
# already computed by ICGC at 1 m). We sample a 5×5 grid around each zone
# centroid and derive four stand-level descriptors:
#
#     canopy_pct      — fraction of sampled cells with vegetation ≥ 5 m (tree
#                       cover), i.e. how closed the canopy is.
#     canopy_height_m — 90th percentile of sampled vegetation heights (the
#                       dominant canopy top).
#     undergrowth     — fraction of sampled cells with 0.5–5 m vegetation
#                       (shrub/understory/regeneration). This is a *proxy*:
#                       top-down LiDAR cannot see sub-canopy vegetation under a
#                       closed canopy, so it only registers low vegetation where
#                       the canopy is open (gaps, edges, clearings).
#     edge_density    — fraction of adjacent sampled cells with a ≥ 3 m height
#                       jump (canopy edges / gaps), a fragmentation proxy.
#
# Every value is a deterministic function of the sampled heights. Cells that
# return no data are excluded from the metrics and reported via `sample_coverage`
# (never fabricated as "zero").
#
#     CANOPY_LAYER — "model-alcaries-vegetacio-catalunya-lidar-1m-2021-2023"

CANOPY_LAYER = "model-alcaries-vegetacio-catalunya-lidar-1m-2021-2023"
CANOPY_SOURCE = "ICGC LiDAR vegetation height 1m (2021-2023)"
CANOPY_UA = "BoletsForecast/1.0 (canopy enrichment; step 3.3)"
CANOPY_GRID_N = 5        # 5×5 grid = 25 cells
CANOPY_GRID_M = 25.0     # grid spacing (metres) → ~100 m stand box
CANOPY_TREE_MIN_M = 5.0  # ≥ this counts as tree canopy (drives canopy_pct)
CANOPY_SHRUB_MIN_M = 0.5  # ≥ this counts as vegetated (undergrowth band)
CANOPY_EDGE_M = 3.0      # height jump that counts as a canopy edge
CANOPY_CACHE_KEY = "lidar_veg_h"


def _canopy_height(lat, lon):
    """Vegetation height (m) at a point from the ICGC 1m CHM, or None."""
    d = 0.0005  # ~55 m box centred on the point
    url = (
        f"{DEM_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo"
        f"&LAYERS={CANOPY_LAYER}&QUERY_LAYERS={CANOPY_LAYER}&STYLES="
        f"&CRS=EPSG:4326&BBOX={lat-d},{lon-d},{lat+d},{lon+d}"
        "&WIDTH=101&HEIGHT=101&I=50&J=50&INFO_FORMAT=text/plain"
    )
    time.sleep(0.1)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": CANOPY_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8", "replace")
    except Exception:
        return None  # network / server error → genuine coverage gap

    for line in txt.splitlines():
        if "value_0" in line:
            try:
                v = float(line.split("=", 1)[1].strip().strip("'"))
            except ValueError:
                return None
            if not math.isfinite(v) or v > 100.0:
                return None  # non-physical height → genuine gap
            if v < 0.0:
                # -9999 is ICGC's nodata sentinel: in the vegetation-height
                # raster it means "no vegetation" (bare ground/rock/water), i.e.
                # height 0 — not a coverage gap. Small negatives (surface-below-
                # ground noise) clamp to 0 too.
                return 0.0
            return v

    # A valid response with no `value_0` line at all also means no vegetation was
    # recorded at this cell (bare); a malformed/empty response is a genuine gap.
    if "GetFeatureInfo results" in txt or "Feature 0" in txt:
        return 0.0
    return None


def _sample_canopy_grid(cache, lat, lon):
    """Sample the 5×5 vegetation-height grid (cached per cell).

    Returns a flat list of 25 heights (row-major, north→south), with `None`
    for cells that returned no data; the list is `None` when the centre cell
    cannot be sampled (the stand anchor is missing).
    """
    n = CANOPY_GRID_N
    half = (n - 1) / 2.0
    heights = []
    for i in range(n):
        for j in range(n):
            dn_m = (half - i) * CANOPY_GRID_M   # + = north
            de_m = (j - half) * CANOPY_GRID_M   # + = east
            la, lo = _offset(lat, lon, dn_m, de_m)
            entry = cache.setdefault(cache_key(la, lo), {})
            rec = entry.get(CANOPY_CACHE_KEY)
            if rec and rec.get("source") == CANOPY_SOURCE and isinstance(rec.get("values", {}).get("h"), float):
                heights.append(rec["values"]["h"])
                continue
            h = _canopy_height(la, lo)
            if h is None:
                heights.append(None)
                continue
            entry[CANOPY_CACHE_KEY] = {"source": CANOPY_SOURCE, "timestamp": _now(),
                                       "values": {"h": h, "unit": "m"}}
            heights.append(h)
    centre = heights[len(heights) // 2]
    if centre is None:
        return None
    return heights


def _percentile(sorted_vals, p):
    """p-th percentile (0–100) of an already-sorted list."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _canopy_metrics(heights):
    """Derive canopy cover, height, undergrowth and edge density from a grid.

    `heights` is the flat 5×5 list from `_sample_canopy_grid` (row-major,
    north→south), possibly containing `None` for no-data cells.
    """
    n = CANOPY_GRID_N
    grid = []
    for i in range(n):
        grid.append([max(0.0, h) if h is not None else None
                     for h in heights[i * n:(i + 1) * n]])

    vals = [v for row in grid for v in row if v is not None]
    n_total = n * n
    n_sampled = len(vals)
    if n_sampled == 0:
        return None

    tree = sum(1 for v in vals if v >= CANOPY_TREE_MIN_M)
    shrub = sum(1 for v in vals if CANOPY_SHRUB_MIN_M <= v < CANOPY_TREE_MIN_M)
    canopy_pct = tree / n_sampled
    undergrowth = shrub / n_sampled
    canopy_height = _percentile(sorted(vals), 90.0)

    pairs = 0
    edges = 0
    for i in range(n):
        for j in range(n):
            v = grid[i][j]
            if v is None:
                continue
            if j + 1 < n and grid[i][j + 1] is not None:
                pairs += 1
                if abs(v - grid[i][j + 1]) >= CANOPY_EDGE_M:
                    edges += 1
            if i + 1 < n and grid[i + 1][j] is not None:
                pairs += 1
                if abs(v - grid[i + 1][j]) >= CANOPY_EDGE_M:
                    edges += 1
    edge_density = edges / pairs if pairs else 0.0

    return {
        "canopy_pct": round(canopy_pct, 3),
        "canopy_height_m": round(canopy_height, 1),
        "undergrowth": round(undergrowth, 3),
        "edge_density": round(edge_density, 3),
        "sample_coverage": round(n_sampled / n_total, 3),
    }


# ── Step 3.4: soil and habitat (fallback sources) ─────────────────────────────
#
# The intended sources are the ICGC 1:25k soil map and the ICGC/CREAF habitat map
# (CHC50 v3, 1:25k). Both are currently unavailable: the habitat cartography is
# served by the UB "geoveg" host that has been down (documented in README), and
# the ICGC "sols"/"geologia" WMS endpoints returned empty/error responses in
# testing. Rather than invent a higher-resolution value, step 3.4 falls back to
# the three sources the app already uses for the same signals:
#
#     soil.type   — IGME 1:1M lithology → calcareous / siliceous / mixed
#     soil.ph     — SoilGrids v2 (0–5 cm) mean pH
#     habitat     — CORINE CLC 2018 forest class → dominant tree group
#
# These are the same values the curated zones already carry (Phase 2 populated
# `soil.type` / `soil.ph_approx` / `forest.type` from them); step 3.4 records
# them in the enrichment blocks with explicit provenance and marks the 1:25k
# upgrade as pending.

_IGME_CALC_KW = [
    "caliza", "calizas", "dolomia", "dolomías", "marga", "margas",
    "calcárea", "calcáreo", "calcarenita", "cretácic", "jurásic",
    "travertino", "carbonato", "calcisiltita", "nodulosa", "calco",
    "evaporita", "evaporitas",
]
_IGME_SIL_KW = [
    "granito", "granitos", "esquisto", "esquistos", "pizarra", "pizarras",
    "gneis", "cuarcita", "cuarcitas", "silíceo", "micaesquisto", "ortogneis",
    "paragneiss", "filita", "granodiorita", "tonalita", "migmatita",
    "riolita", "pórfido",
]

_CORINE_TREE_GROUP = {
    "311": "broadleaf (faig/roure/alzina)",
    "312": "conifer (pi/avet)",
    "313": "mixed conifer-broadleaf",
    "324": "transitional woodland/shrub",
}


def _to_mercator(lat, lon):
    x = lon * 20037508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180)
    return x, y * 20037508.34 / 180


def _classify_lithology(text):
    if not text or text in ("?", "NO DATA"):
        return "unknown"
    t = text.lower()
    has_cal = any(k in t for k in _IGME_CALC_KW)
    has_sil = any(k in t for k in _IGME_SIL_KW)
    if has_sil and not has_cal:
        return "siliceous"
    if has_cal and not has_sil:
        return "calcareous"
    if has_cal and has_sil:
        return "mixed"
    return "mixed"


def _igme_litho(lat, lon):
    """IGME 1:1M lithology → (litho_text, soil_type)."""
    x, y = _to_mercator(lat, lon)
    url = (
        "https://mapas.igme.es/gis/rest/services/Cartografia_Geologica/"
        "IGME_Litologias_1M/MapServer/identify"
        f"?geometry={x:.2f},{y:.2f}&geometryType=esriGeometryPoint&layers=0"
        f"&tolerance=5&mapExtent={x-5000:.2f},{y-5000:.2f},{x+5000:.2f},{y+5000:.2f}"
        "&imageDisplay=500,500,96&returnGeometry=false&f=json"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read())
        for res in d.get("results", []):
            text = res["attributes"].get("Litologia", "")
            return text, _classify_lithology(text)
    except Exception:
        pass
    return "unknown", "unknown"


def _soilgrids_ph(lat, lon):
    """SoilGrids v2 pH (0–5 cm) mean, or None."""
    url = (
        "https://rest.isric.org/soilgrids/v2.0/properties/query"
        f"?lon={lon}&lat={lat}&property=phh2o&depth=0-5cm&value=mean"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        layer = d["properties"]["layers"][0]
        val = layer["depths"][0]["values"]["mean"]
        factor = layer["unit_measure"]["d_factor"]
        return val / factor
    except Exception:
        return None


def _corine(lat, lon):
    """CORINE CLC 2018 forest class code, or 'unknown'."""
    delta = 0.03
    bbox = f"{lat-delta},{lon-delta},{lat+delta},{lon+delta}"
    url = (
        "https://image.discomap.eea.europa.eu/arcgis/services/Corine/"
        "CLC2018_WM/MapServer/WMSServer"
        "?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo"
        "&LAYERS=13&QUERY_LAYERS=13"
        f"&CRS=EPSG:4326&BBOX={bbox}&WIDTH=100&HEIGHT=100&I=50&J=50"
        "&INFO_FORMAT=text/html"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="replace")
        rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
        for row in rows[1:]:
            cells = [c.strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)]
            if len(cells) >= 3:
                return cells[2]
    except Exception:
        pass
    return "unknown"


# ── Enrichment providers ───────────────────────────────────────────────────────
#
# Each provider is a `compute(lat, lon, zone)` function that returns a dict of
# sampled values, or `None` when it has nothing to add yet. `source` is the
# human-readable provenance recorded against every cached sample.

def _dem_compute(lat, lon, zone, cache):
    """Step 3.2: ICGC 5m DEM → curvature, TPI, cold-air pooling, solar radiation."""
    neighborhood = _sample_dem_neighborhood(cache, lat, lon)
    if neighborhood is None:
        return None
    return _dem_metrics(neighborhood, lat)


def _lidar_compute(lat, lon, zone, cache):
    """Step 3.3: ICGC LiDAR vegetation height → cover, height, undergrowth, edge."""
    heights = _sample_canopy_grid(cache, lat, lon)
    if heights is None:
        return None
    return _canopy_metrics(heights)


def _soil_compute(lat, lon, zone, cache):
    """Step 3.4: soil type (IGME lithology) + pH (SoilGrids). Texture pending."""
    litho, soil_type = _igme_litho(lat, lon)
    if soil_type == "unknown":
        return None
    ph = _soilgrids_ph(lat, lon)
    return {
        "type": soil_type,
        "texture": None,  # 1:25k soil-texture map unavailable (see note)
        "ph": round(ph, 1) if ph is not None else None,
        "litho_text": litho,
    }


def _habitat_compute(lat, lon, zone, cache):
    """Step 3.4: dominant tree group from CORINE CLC 2018 (fallback for CHC50)."""
    code = _corine(lat, lon)
    if code == "unknown":
        return None
    return {
        "dominant": _CORINE_TREE_GROUP.get(code, "non-forest"),
        "corine_code": code,
    }


PROVIDERS = {
    "dem":      {"step": "3.2", "source": DEM_SOURCE, "compute": _dem_compute},
    "lidar":    {"step": "3.3", "source": CANOPY_SOURCE,      "compute": _lidar_compute},
    "soil_1_25k": {"step": "3.4", "source": "IGME 1:1M (litho) + SoilGrids v2 (pH)", "compute": _soil_compute},
    "habitat":  {"step": "3.4", "source": "CORINE CLC 2018 (fallback for CHC50)", "compute": _habitat_compute},
}


def _terrain_source(zone):
    """Pick the DEM/LiDAR source already recorded on the curated zone (Phase 2)."""
    for s in zone.get("sources", []):
        if "LiDAR" in s or "DEM" in s or "elevation" in s.lower():
            return s
    return None


def _sample(cache, lat, lon, provider_key):
    """Sample one provider, caching real values by rounded lat/lon.

    Returns (values, source, timestamp). When the provider has not been
    implemented yet (compute → None), returns (None, None, None); a missing
    value is never fabricated and never written to the cache.
    """
    hit = get_sample(cache, lat, lon, provider_key)
    if hit:
        return hit["values"], hit["source"], hit["timestamp"]

    values = PROVIDERS[provider_key]["compute"](lat, lon, None, cache)
    if values is None:
        return None, None, None

    source = PROVIDERS[provider_key]["source"]
    record = put_sample(cache, lat, lon, provider_key, source, values)
    return values, record["source"], record["timestamp"]


def enrich_zone(zone, cache):
    """Return a copy of `zone` with an `enrichment` block attached.

    Curated (Phase 2) altitude/slope/aspect are carried through unchanged. The
    DEM provider (step 3.2) adds curvature, TPI, cold-air pooling and solar
    radiation computed from a 9-point ICGC 5m LiDAR sample; the remaining
    factors (LiDAR canopy, 1:25k soil/habitat) stay `null` / "pending" until
    steps 3.3–3.4.
    """
    lat, lon = float(zone["lat"]), float(zone["lon"])

    dem_vals, dem_src, dem_at = _sample(cache, lat, lon, "dem")
    lidar_vals, lidar_src, lidar_at = _sample(cache, lat, lon, "lidar")
    soil_vals, soil_src, soil_at = _sample(cache, lat, lon, "soil_1_25k")
    hab_vals, hab_src, hab_at = _sample(cache, lat, lon, "habitat")

    # Curated (Phase 2) terrain factors — real values, real source, no sampling.
    terrain_source = _terrain_source(zone)
    # A full 3.2 sample carries every derived metric; a partial/legacy cache
    # entry does not, and is left as-is rather than half-populated.
    dem_done = isinstance(dem_vals, dict) and all(
        k in dem_vals for k in ("dem_alt_m", "curvature", "tpi",
                                "cold_air_pooling", "solar_radiation",
                                "slope_deg", "aspect_deg")
    )
    lidar_done = isinstance(lidar_vals, dict) and all(
        k in lidar_vals for k in ("canopy_pct", "canopy_height_m",
                                  "undergrowth", "edge_density")
    )
    soil_done = isinstance(soil_vals, dict) and soil_vals.get("type")
    hab_done = isinstance(hab_vals, dict) and hab_vals.get("dominant")

    terrain = {
        "status": "partial" if dem_done else "partial",
        "source": terrain_source,
        "alt_m": zone.get("alt_m"),
        "slope_deg": zone.get("slope_deg"),
        "aspect_deg": zone.get("aspect_deg"),
        "aspect": zone.get("aspect"),
        "curvature": None,
        "tpi": None,
        "cold_air_pooling": None,
        "solar_radiation": {"annual": None, "seasonal": None},
        "dem_source": dem_src,
        "dem_sampled_at": dem_at,
    }
    if dem_done:
        # DEM-derived metrics (step 3.2). `dem_alt_m`/`slope_deg`/`aspect_deg`
        # are the DEM's own reading at the centroid (kept separate from the
        # curated Phase 2 values so both are preserved and comparable).
        terrain.update({
            "status": "complete",
            "dem_alt_m": dem_vals["dem_alt_m"],
            "dem_slope_deg": dem_vals["slope_deg"],
            "dem_aspect_deg": dem_vals["aspect_deg"],
            "curvature": dem_vals["curvature"],
            "tpi": dem_vals["tpi"],
            "cold_air_pooling": dem_vals["cold_air_pooling"],
            "solar_radiation": dem_vals["solar_radiation"],
            "curvature_unit": "1/m",
            "tpi_unit": "m",
            "cold_air_pooling_unit": "m",
            "solar_radiation_unit": "ratio (tilted / horizontal)",
        })

    pending = []
    if not dem_done:
        pending.append("3.2 — DEM: curvature, TPI, cold-air pooling, solar radiation")
    if not lidar_done:
        pending.append("3.3 — LiDAR: canopy cover %, height, undergrowth, edge density")
    if not (soil_done and hab_done):
        pending.append("3.4 — soil (type/texture/pH) and habitat (dominant tree)")

    canopy = {
        "status": "complete" if lidar_done else "pending",  # step 3.3 (LiDAR)
        "source": lidar_src,
        "sampled_at": lidar_at,
        "canopy_pct": None,
        "canopy_height_m": None,
        "undergrowth": None,
        "edge_density": None,
    }
    if lidar_done:
        canopy.update({
            "canopy_pct":      lidar_vals["canopy_pct"],
            "canopy_height_m": lidar_vals["canopy_height_m"],
            "undergrowth":     lidar_vals["undergrowth"],
            "edge_density":    lidar_vals["edge_density"],
            "sample_coverage": lidar_vals.get("sample_coverage"),
            "canopy_pct_unit":      "fraction of sampled cells ≥ 5 m vegetation",
            "canopy_height_m_unit": "m (90th percentile of sampled heights)",
            "undergrowth_unit":     "fraction of sampled cells 0.5–5 m (shrub, visible where canopy is open)",
            "edge_density_unit":    "fraction of adjacent cells with ≥ 3 m height jump",
        })

    soil = {
        "status": "complete" if soil_done else "pending",  # step 3.4 (soil)
        "source": soil_src,
        "sampled_at": soil_at,
        "type": None,
        "texture": None,
        "ph": None,
    }
    if soil_done:
        soil.update({
            "type": soil_vals["type"],
            "texture": soil_vals.get("texture"),
            "ph": soil_vals.get("ph"),
            "litho_text": soil_vals.get("litho_text"),
            "note": "type from IGME 1:1M lithology, pH from SoilGrids v2; "
                    "1:25k soil-texture upgrade pending (source unavailable)",
        })

    habitat = {
        "status": "complete" if hab_done else "pending",  # step 3.4 (habitat)
        "source": hab_src,
        "sampled_at": hab_at,
        "dominant": None,
    }
    if hab_done:
        habitat.update({
            "dominant": hab_vals["dominant"],
            "corine_code": hab_vals.get("corine_code"),
            "note": "dominant tree group from CORINE CLC 2018 (fallback for "
                    "the ICGC/CREAF CHC50 habitat map, source unavailable)",
        })

    enrichment = {
        "terrain": terrain,
        "canopy": canopy,
        "soil": soil,
        "habitat": habitat,
        "pending_steps": pending,
    }

    enriched = dict(zone)
    enriched["enrichment"] = enrichment
    return enriched


# ── Main ───────────────────────────────────────────────────────────────────────

def enrich_all():
    """Enrich every curated zone and write zones_enriched.json. Returns counts."""
    with open(ZONES_FILE) as f:
        source = json.load(f)
    zones_by_station = source.get("zones", {})

    cache = load_cache()
    out_zones = {}
    n_stations = 0
    n_zones = 0
    n_dem = 0
    n_lidar = 0
    n_soil = 0
    n_habitat = 0

    for station, zones in zones_by_station.items():
        enriched = []
        for zone in zones:
            e = enrich_zone(zone, cache)
            enriched.append(e)
            n_zones += 1
            if e["enrichment"]["terrain"].get("dem_source"):
                n_dem += 1
            if e["enrichment"]["canopy"].get("source"):
                n_lidar += 1
            if e["enrichment"]["soil"].get("source"):
                n_soil += 1
            if e["enrichment"]["habitat"].get("source"):
                n_habitat += 1
        out_zones[station] = enriched
        n_stations += 1
        save_cache(cache)  # persist samples incrementally (resumable on interruption)
        print(f"  {station}: {len(zones)} zones ({n_zones} total, {n_dem} DEM, {n_lidar} canopy, {n_soil} soil, {n_habitat} habitat)", flush=True)

    save_cache(cache)

    output = {
        "version": source.get("version", 1),
        "zones": out_zones,
        "_meta": {
            "generator": "enrich_zones.py (Phase 3.4)",
            "generated_at": _now(),
            "source_zones": os.path.basename(ZONES_FILE),
            "stations": n_stations,
            "zones": n_zones,
            "providers": {
                "dem":       {"step": "3.2", "status": "done" if n_dem else "pending"},
                "lidar":     {"step": "3.3", "status": "done" if n_lidar else "pending"},
                "soil_1_25k": {"step": "3.4", "status": "done" if n_soil else "pending",
                               "note": "fallback IGME 1:1M + SoilGrids; 1:25k upgrade pending"},
                "habitat":   {"step": "3.4", "status": "done" if n_habitat else "pending",
                              "note": "fallback CORINE CLC 2018; CHC50 1:25k upgrade pending"},
            },
        },
    }
    with open(OUT_FILE, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUT_FILE} ({n_stations} stations, {n_zones} zones, {n_dem} DEM, {n_soil} soil, {n_habitat} habitat)")
    return n_stations, n_zones


def self_test():
    """Offline round-trip of the cache and enrichment shape (no network)."""
    cache = {}

    # cache_key rounding
    assert cache_key(42.1546, 1.9025) == "42.1546,1.9025", cache_key(42.1546, 1.9025)
    assert cache_key(42.15464, 1.90254) == "42.1546,1.9025", cache_key(42.15464, 1.90254)

    # put → get round-trip records source + timestamp
    put_sample(cache, 42.1546, 1.9025, "dem", "self-test", {"tpi": -1.0})
    hit = get_sample(cache, 42.1546, 1.9025, "dem")
    assert hit["source"] == "self-test"
    assert hit["values"] == {"tpi": -1.0}
    assert hit["timestamp"]  # non-empty ISO timestamp
    put_sample(cache, 42.1546, 1.9025, "lidar", "self-test", {"canopy_pct": 0.5})
    put_sample(cache, 42.1546, 1.9025, "soil_1_25k", "self-test", {"type": "calcareous"})
    put_sample(cache, 42.1546, 1.9025, "habitat", "self-test", {"dominant": "conifer"})

    # a different rounded cell does not collide
    assert get_sample(cache, 42.9999, 1.9999, "dem") is None

    # ── DEM metric derivation (offline, synthetic neighbourhood) ──────────────
    lat = 42.1546
    cos = math.cos(math.radians(lat))
    fine = DEM_FINE_M
    coarse = DEM_COARSE_M
    # (a) slope/aspect on a north-facing plane descending 10 m over `fine` m
    #     → slope ≈ atan(10/fine), aspect ~0°.
    zc, zn, zs, ze, zw = 1100.0, 1090.0, 1110.0, 1100.0, 1100.0
    slope, aspect = _slope_aspect(zc, zn, zs, ze, zw, fine)
    assert abs(slope - math.degrees(math.atan(10 / fine))) < 0.15, slope
    assert aspect < 1.0 or aspect > 359.0, aspect  # north

    # (b) curvature/TPI/pooling on a convex dome (centre 5 m above a flat ring).
    neighborhood = {
        "center":    (lat, 1.9025, 1100.0),
        "cardinal":  [(lat + fine / 111320.0, 1.9025, 1095.0),
                      (lat - fine / 111320.0, 1.9025, 1095.0),
                      (lat, 1.9025 + fine / (111320.0 * cos), 1095.0),
                      (lat, 1.9025 - fine / (111320.0 * cos), 1095.0)],
        "diagonals": [(lat + coarse / 111320.0, 1.9, 1095.0),
                      (lat + coarse / 111320.0, 1.91, 1095.0),
                      (lat - coarse / 111320.0, 1.9, 1095.0),
                      (lat - coarse / 111320.0, 1.91, 1095.0)],
    }
    m = _dem_metrics(neighborhood, lat)
    assert m["curvature"] < 0, m["curvature"]  # convex dome
    assert abs(m["tpi"] - 5.0) < 0.1, m["tpi"]
    assert abs(m["cold_air_pooling"] - 5.0) < 0.1, m["cold_air_pooling"]
    # Solar radiation: at this latitude a south aspect captures more than north.
    sr_n = _solar_radiation(lat, slope, 0.0)["annual"]
    sr_s = _solar_radiation(lat, slope, 180.0)["annual"]
    assert sr_n < sr_s, (sr_n, sr_s)
    assert 0.0 <= sr_n and sr_s <= 3.0, (sr_n, sr_s)

    # ── Canopy metric derivation (offline, synthetic 5×5 grid) ────────────────
    # Dense uniform canopy (all 12 m) → full cover, no shrub/edge.
    dense = [12.0] * 25
    cm = _canopy_metrics(dense)
    assert cm["canopy_pct"] == 1.0, cm
    assert cm["canopy_height_m"] == 12.0, cm
    assert cm["undergrowth"] == 0.0, cm
    assert cm["edge_density"] == 0.0, cm

    # Top 3 rows tall (12 m), bottom 2 rows shrub (2 m) → 15/25 tree, 10/25 shrub.
    mixed = [12.0] * 15 + [2.0] * 10
    cm2 = _canopy_metrics(mixed)
    assert abs(cm2["canopy_pct"] - 15 / 25) < 1e-6, cm2
    assert abs(cm2["undergrowth"] - 10 / 25) < 1e-6, cm2
    assert cm2["edge_density"] > 0.0, cm2  # tall↔shrub boundary has a ≥3 m jump

    # No-data cells are excluded (sample_coverage < 1), never counted as zero.
    gaps = [12.0] * 10 + [None] * 15
    cm3 = _canopy_metrics(gaps)
    assert abs(cm3["sample_coverage"] - 10 / 25) < 1e-6, cm3
    assert cm3["canopy_pct"] == 1.0, cm3  # every *sampled* cell is tree

    # ── Lithology classification (offline) ─────────────────────────────────────
    assert _classify_lithology("Calizas y margas") == "calcareous"
    assert _classify_lithology("Granitos y esquistos") == "siliceous"
    assert _classify_lithology("Calizas y esquistos") == "mixed"
    assert _classify_lithology("NO DATA") == "unknown"
    assert _CORINE_TREE_GROUP["312"] == "conifer (pi/avet)"
    assert _CORINE_TREE_GROUP["311"] == "broadleaf (faig/roure/alzina)"

    # ── enrich_zone shape (offline, cached dem sample) ────────────────────────
    zone = {
        "id": "test", "name": "Test", "lat": 42.1546, "lon": 1.9025,
        "alt_m": 1202, "slope_deg": 24.6, "aspect_deg": 352, "aspect": "north",
        "forest": {"type": "conifer", "dominant": "Pinus sylvestris"},
        "sources": ["ICGC 5m LiDAR DEM (2021-2023)"],
    }
    out = enrich_zone(zone, cache)
    assert out["alt_m"] == 1202 and out["id"] == "test"
    e = out["enrichment"]
    t = e["terrain"]
    assert t["alt_m"] == 1202
    assert t["slope_deg"] == 24.6 and t["aspect_deg"] == 352  # curated preserved
    assert t["tpi"] is None  # partial synthetic sample is not a full 3.2 result
    assert "dem_alt_m" not in t  # no dem-derived fields for a partial sample
    assert t["curvature"] is None and t["solar_radiation"]["annual"] is None
    assert e["canopy"]["canopy_pct"] is None
    assert e["canopy"]["status"] == "pending"
    assert e["soil"]["type"] == "calcareous"       # partial cached sample
    assert e["soil"]["ph"] is None                 # pH not in the partial sample
    assert e["habitat"]["dominant"] == "conifer"   # partial cached sample
    assert t["source"] == "ICGC 5m LiDAR DEM (2021-2023)"
    assert len(e["pending_steps"]) == 2  # only 3.2 + 3.3 remain for this partial sample

    print("self-test OK: cache round-trip + DEM + canopy + soil/habitat + enrichment shape")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return
    enrich_all()


if __name__ == "__main__":
    main()
