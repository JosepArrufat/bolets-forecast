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


# A transient provider error is retried after this window; a genuine
# "no coverage" answer is permanent. See `_negative_cache_usable`.
CACHE_ERROR_RETRY_S = 24 * 3600


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


# ── Step 7.4: IGME MAGNA 50 (1:50,000) lithology ─────────────────────────────
#
# The 1:1M lithology cannot resolve a few-hundred-metre siliceous pocket inside a
# calcareous hillside, so `mixed` (the model's "I don't know") caps the strongest
# habitat discriminator. The MAGNA 50 series ("Mapa Geológico de España 1:50.000")
# maps the same signal at 1:50k. We query the "Litologías color" polygon layer and
# normalise its verbose legend into calcareous / siliceous / mixed with a
# *conservative* reviewed rule below: a class is promoted only when the MAGNA text
# is unambiguous (pure carbonate/evaporite → calcareous; igneous/metamorphic →
# siliceous). Detrital terms (sandstone, conglomerate, lutite, silt, clay, …) are
# neutral on their own — a carbonate-cemented conglomerate is calcareous — so they
# force "mixed" (fall back to 1:1M) rather than guessing. Unconsolidated / surficial
# deposits (glacial, colluvium, dunes, landslides, piedmont) are also "mixed".

MAGNA_URL = ("https://mapas.igme.es/gis/rest/services/Cartografia_Geologica/"
             "IGME_MAGNA_50/MapServer/identify")
MAGNA_LAYER = "visible:11"   # "Litologías color MAGNA 50" (polygon, field DLO)
MAGNA_SOURCE = "IGME MAGNA 50 (1:50k) lithology"
MAGNA_UA = "BoletsForecast/1.0 (soil enrichment; step 7.4)"

# Two promotions are held at 1:1M until a field check. Both flip a 1:1M
# calcareous unit to siliceous on the same "Liditas y alternancia de areniscas y
# lutitas" member (sheet 255, Coll de Pal / Bagà). The MAGNA polygon and the
# classification are reproducible at ±300 m, but the class change inverts the
# soil multiplier (×6.67 for acid-loving species, ×0.15 for basic-loving ones),
# so the evidence is recorded for review and the value is not promoted yet.
MAGNA_REVIEW_HOLDS = {
    "colldepal-cresta-alta": "calcareous→siliceous flip on the Liditas unit; field review pending",
    "baga-obaga-pi": "calcareous→siliceous flip on the Liditas unit; field review pending",
}

_MAGNA_CALC_KW = [
    "caliza", "calizas", "dolomía", "dolomías", "dolomíti", "marga", "margas",
    "calcárea", "calcáreo", "calcarenita", "cretácic", "jurásic", "travertino",
    "carbonato", "calcisiltita", "nodulosa", "calco", "evaporita", "evaporitas",
    "yeso", "yesos", "margocalc", "calcirrudita",
]
_MAGNA_SIL_KW = [
    "granito", "granitos", "granodiorita", "granodioritas", "leucogranito",
    "monzogran", "esquisto", "esquistos", "pizarra", "pizarras", "gneis",
    "cuarcita", "cuarcitas", "silíceo", "micaesquisto", "ortogneis", "paragneiss",
    "filita", "tonalita", "migmatita", "riolita", "pórfido", "lidita", "liditas",
    "porfiroide", "porfiroides", "ignimbrita", "piroclas", "gabro", "basalto",
    "andesita", "toba", "cuarzo",
]
_MAGNA_DETRITAL_KW = [
    "arenisca", "areniscas", "conglomerado", "conglomerados", "lutita", "lutitas",
    "limolita", "limolitas", "limo", "limos", "arena", "arenas", "grava", "gravas",
    "arcilla", "arcillas", "arcillosa", "arcillosas", "pelita", "pelitas",
    "microconglomerado", "ritmita", "ritmitas",
]
_MAGNA_SURFICIAL_KW = [
    "glaciar", "till", "morrena", "morrenas", "coluvión", "coluvion", "coluviones",
    "canchal", "canchales", "deslizamiento", "duna", "dunas", "eólico", "eolico",
    "avalancha", "aluvial", "pie de monte", "bloques", "vertiente", "conos de",
    "alud", "desmantelamiento", "depósito", "deposito", "cantos", "clastos",
]


def _classify_magna(text):
    """Normalise a MAGNA 50 lithology description to calcareous/siliceous/mixed.

    Conservative: only unambiguous rock types promote. A detrital-only description
    (sandstone/conglomerate/shale) is "mixed" because it does not say whether the
    cement is carbonate or siliceous; a carbonate keyword alongside a detrital one
    is also "mixed" (transitional facies). Surficial/transported deposits are
    "mixed" (not bedrock). Returns "unknown" only for empty/NO DATA text.
    """
    if not text or text in ("?", "NO DATA"):
        return "unknown"
    t = text.lower()
    if any(k in t for k in _MAGNA_SURFICIAL_KW):
        return "mixed"
    has_cal = any(k in t for k in _MAGNA_CALC_KW)
    has_sil = any(k in t for k in _MAGNA_SIL_KW)
    has_det = any(k in t for k in _MAGNA_DETRITAL_KW)
    if has_sil and not has_cal:
        return "siliceous"
    if has_cal and not has_sil and not has_det:
        return "calcareous"
    return "mixed"


def _igme_magna50(lat, lon):
    """IGME MAGNA 50 lithology → (litho_text, hoja, classification).

    Returns (None, None, "no coverage") when no sheet polygon answers at the point,
    and (None, None, "error") when the request fails — so the caller can fall back
    to 1:1M and record why.
    """
    x, y = _to_mercator(lat, lon)
    url = (
        f"{MAGNA_URL}?geometry={x:.2f},{y:.2f}&geometryType=esriGeometryPoint"
        f"&layers={MAGNA_LAYER}&tolerance=5"
        f"&mapExtent={x-3000:.2f},{y-3000:.2f},{x+3000:.2f},{y+3000:.2f}"
        "&imageDisplay=500,500,96&returnGeometry=false&f=json"
    )
    time.sleep(0.1)  # be polite: one MAGNA probe at a time
    try:
        req = urllib.request.Request(url, headers={"User-Agent": MAGNA_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read())
        results = d.get("results", [])
        if not results:
            return None, None, "no coverage"
        attrs = results[0].get("attributes", {})
        text = attrs.get("descripción litológica", "")
        hoja = attrs.get("nº de hoja", "")
        if not text:
            return None, None, "no coverage"
        return text, hoja, _classify_magna(text)
    except Exception:
        return None, None, "error"


def _magna_promotable(zone_id, magna):
    """True only when MAGNA answered clearly and the zone is not on review hold."""
    return (zone_id not in MAGNA_REVIEW_HOLDS
            and magna.get("covered")
            and magna.get("class") in ("calcareous", "siliceous"))


def _negative_cache_usable(rec):
    """Whether a cached provider answer may be reused.

    Genuine "no coverage" is permanent. A transient "error" is retried after
    CACHE_ERROR_RETRY_S instead of marking the point as uncovered forever.
    """
    values = (rec or {}).get("values") or {}
    if values.get("covered") is not False or values.get("reason") != "error":
        return True
    retry_at = rec.get("retry_at")
    return isinstance(retry_at, (int, float)) and time.time() < retry_at


def _store_negative(entry, key, source, values, status):
    rec = {"source": source, "timestamp": _now(), "values": values}
    if status == "error":
        rec["retry_at"] = time.time() + CACHE_ERROR_RETRY_S
    entry[key] = rec


def _magna50_sample(cache, lat, lon):
    """Cached MAGNA 50 sample → dict {covered, dlo, hoja, class, reason}.

    A "no coverage" answer is cached too (covered=False) so re-runs do not
    re-query the 12 Pyrenean gaps on every run; a transient error is retried
    after CACHE_ERROR_RETRY_S.
    """
    entry = cache.setdefault(cache_key(lat, lon), {})
    rec = entry.get("magna50")
    if (rec and rec.get("source") == MAGNA_SOURCE
            and isinstance(rec.get("values"), dict)
            and _negative_cache_usable(rec)):
        # Re-classify from the stored legend text: a mapping-table fix must
        # apply to already-sampled points without clearing the cache.
        values = dict(rec["values"])
        if values.get("dlo"):
            values["class"] = _classify_magna(values["dlo"])
        return values
    text, hoja, cls = _igme_magna50(lat, lon)
    values = {
        "covered": text is not None,
        "dlo": text,
        "hoja": hoja,
        "class": cls if text is not None else "mixed",
        "reason": "ok" if text is not None else cls,
    }
    _store_negative(entry, "magna50", MAGNA_SOURCE, values, cls)
    return values


def _magna_fallback_reason(magna):
    """Human-readable reason the 1:1M lithology was kept instead of MAGNA 50."""
    if not magna:
        return "MAGNA 50 not sampled"
    if not magna.get("covered"):
        return f"MAGNA 50 {magna.get('reason')} at this point"
    return f"MAGNA 50 legend ambiguous/mixed ({magna.get('dlo', '')[:60]})"


# ── Step 7.6: ICGC MSC25M 1:25,000 soil (WFS) ────────────────────────────────
#
# The intended 1:25k soil layer is the ICGC "Mapa de sòls de Catalunya 1:25.000
# (MSC25M)", served as a WFS at the edafologia service. Each polygon carries the
# soil unit (`tipus_sol`), its Soil-Taxonomy class (`soil_taxon`) and a
# `descripcio` that names the parent material ("S'han format sobre calcàries…").
# The parent material is what determines the calcareous/siliceous reaction the
# score uses, so we classify it with the same conservative keyword rule as MAGNA
# 50: a clear carbonate/evaporite parent → calcareous, a clear igneous/metamorphic
# or siliceous-sedimentary parent → siliceous, a detrital/ambiguous parent →
# "mixed" (keep the coarser fallback). Coverage is NOT Catalonia-wide yet — the
# MSC25M is published by sheet and the mountain sheets are still missing — so a
# no-coverage answer records "no coverage" and falls back exactly like 7.4.

SOIL_1_25K_WFS = "https://geoserveis.icgc.cat/servei/catalunya/edafologia/wfs"
SOIL_1_25K_LAYER = "icgc_sols:sols-25000"
SOIL_1_25K_SOURCE = "ICGC MSC25M (1:25k) soil map"
SOIL_1_25K_UA = "BoletsForecast/1.0 (soil 1:25k enrichment; step 7.6)"

_MSC25_CALC_KW = [
    "calcari", "calcàri", "calcària", "calcàries", "calcaris", "calcaria",
    "calcaries", "dolomia", "dolomía", "dolomies", "dolomías", "marga",
    "margues", "guix", "guixos", "evaporita", "carbonat", "creta", "cretaci",
    "travertí", "traverti",
]
_MSC25_SIL_KW = [
    "granit", "granits", "granito", "esquist", "esquistos", "pissarra",
    "pissarres", "pizarra", "gneis", "quarsita", "quarsites", "cuarcita",
    "sílice", "silici", "silicícol", "lidita", "pòrfir", "porfir", "basalt",
    "andesita", "riolita", "tuf", "conglomerat silícic",
]
_MSC25_DETRITAL_KW = [
    "sediments detrítics", "detrític", "detritic", "terrígens", "terrigen",
    "al·luvial", "al·luvials", "al.luvial", "col·luvial", "col.luvial",
    "col·luvió", "fluvial", "fluvià", "eòlic", "eolic", "duna", "dunes",
    "glaciar", "till", "morrena", "torrencial", "pedregós", "pedregos",
    "còdols", "codols", "graves", "sorres", "sorrenc", "llims", "argiles",
]


def _classify_msc25_parent(text):
    """Classify an MSC25M parent-material description → calcareous/siliceous/mixed.

    Conservative, mirroring `_classify_magna`: only an unambiguous bedrock parent
    promotes. A detrital/transported parent ("sediments detrítics", "al·luvial",
    …) is "mixed" because it does not say whether the clasts/cement are carbonate
    or siliceous. Returns "unknown" for empty text.
    """
    if not text:
        return "unknown"
    t = text.lower()
    if any(k in t for k in _MSC25_DETRITAL_KW):
        return "mixed"
    has_cal = any(k in t for k in _MSC25_CALC_KW)
    has_sil = any(k in t for k in _MSC25_SIL_KW)
    if has_sil and not has_cal:
        return "siliceous"
    if has_cal and not has_sil:
        return "calcareous"
    return "mixed"


def _point_in_ring(x, y, ring):
    """Ray-casting point-in-polygon for a closed ring of [x, y, ...] coords."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def _point_in_geom(x, y, geom):
    """True when (x, y) is inside a GeoJSON Polygon/MultiPolygon (holes honoured)."""
    if not isinstance(geom, dict):
        return False
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if gtype == "Polygon" and coords:
        if not _point_in_ring(x, y, coords[0]):
            return False
        return not any(_point_in_ring(x, y, hole) for hole in coords[1:])
    if gtype == "MultiPolygon" and coords:
        for poly in coords:
            if poly and _point_in_ring(x, y, poly[0]) \
                    and not any(_point_in_ring(x, y, hole) for hole in poly[1:]):
                return True
        return False
    if gtype == "GeometryCollection":
        return any(_point_in_geom(x, y, g) for g in geom.get("geometries", []))
    return False


def _msc25_wfs(lat, lon):
    """ICGC MSC25M 1:25k soil polygon at a point → (values dict, status).

    Returns a dict with `tipus_sol`, `soil_taxon`, `codi_cas`, `descripcio` and
    the derived `class`, or `(None, status)` where status is "no coverage" (the
    polygon layer does not answer here — the sheet has not been published yet) or
    "error" (the request failed). Coordinates are converted to UTM 31N because
    the WFS serves geometry in EPSG:25831 and rejects EPSG:4326 BBOX filters.

    The WFS BBOX filter returns every polygon that *intersects* the box, in
    server order, so taking the first feature is wrong near a boundary. The query
    asks for a small set of candidates and keeps only the polygon that actually
    contains the point (ray casting); no containing polygon means "no coverage".
    """
    x, y = _to_utm31(lat, lon)
    d = 50  # metres; a point-containing polygon is returned if it intersects
    url = (
        f"{SOIL_1_25K_WFS}?SERVICE=WFS&VERSION=1.1.0&REQUEST=GetFeature"
        f"&TYPENAME={SOIL_1_25K_LAYER}"
        f"&BBOX={x-d},{y-d},{x+d},{y+d}"
        "&OUTPUTFORMAT=application/json&MAXFEATURES=50"
    )
    time.sleep(0.1)  # be polite: one WFS probe at a time
    try:
        req = urllib.request.Request(url, headers={"User-Agent": SOIL_1_25K_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except Exception:
        return None, "error"
    for feat in data.get("features", []):
        if not _point_in_geom(x, y, feat.get("geometry")):
            continue
        p = feat.get("properties", {})
        desc = p.get("descripcio") or ""
        values = {
            "tipus_sol": p.get("tipus_sol"),
            "soil_taxon": p.get("soil_taxon"),
            "codi_cas": p.get("codi_cas"),
            "descripcio": desc,
            "class": _classify_msc25_parent(desc),
        }
        return values, "ok"
    return None, "no coverage"


def _msc25_sample(cache, lat, lon):
    """Cached MSC25M sample → dict {covered, class, ...}."""
    entry = cache.setdefault(cache_key(lat, lon), {})
    rec = entry.get("soil_1_25k_wfs")
    if (rec and rec.get("source") == SOIL_1_25K_SOURCE
            and isinstance(rec.get("values"), dict)
            and _negative_cache_usable(rec)):
        # Re-classify from the stored parent-material text so a keyword fix
        # applies without clearing the cache.
        values = dict(rec["values"])
        if values.get("descripcio"):
            values["class"] = _classify_msc25_parent(values["descripcio"])
        return values
    values, status = _msc25_wfs(lat, lon)
    if values is None:
        # Cache the negative answer too, so a re-run never re-queries the many
        # mountain gaps (an "error" is retried after CACHE_ERROR_RETRY_S).
        neg = {"covered": False, "reason": status, "class": "unknown"}
        _store_negative(entry, "soil_1_25k_wfs", SOIL_1_25K_SOURCE, neg, status)
        return neg
    values = dict(values)
    values["covered"] = True
    entry["soil_1_25k_wfs"] = {"source": SOIL_1_25K_SOURCE,
                               "timestamp": _now(), "values": values}
    return values


def _to_utm31(lat, lon):
    """WGS84 → UTM zone 31N (ETRS89/ETRS89-compatible transverse mercator).

    Only used for the ICGC soil WFS BBOX (geometry is served in EPSG:25831);
    good to well under a metre over Catalonia, which is far finer than the ~400 m
    query box.
    """
    a = 6378137.0
    f = 1 / 298.257223563
    k0 = 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    latr = math.radians(lat)
    lonr = math.radians(lon)
    lon0 = math.radians(3.0)
    N = a / math.sqrt(1 - e2 * math.sin(latr) ** 2)
    T = math.tan(latr) ** 2
    C = ep2 * math.cos(latr) ** 2
    A = math.cos(latr) * (lonr - lon0)
    M = a * ((1 - e2 / 4 - 3 * e2 * e2 / 64 - 5 * e2 ** 3 / 256) * latr
             - (3 * e2 / 8 + 3 * e2 * e2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * latr)
             + (15 * e2 * e2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * latr)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * latr))
    x = k0 * N * (A + (1 - T + C) * A ** 3 / 6
                  + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000.0
    y = k0 * (M + N * math.tan(latr) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
              + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720))
    return x, y


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


def _corine(lat, lon, cache=None):
    """CORINE CLC 2018 forest class code, or 'unknown'.

    When `cache` is given, the result is cached under the `corine` key (the same
    rounded-lat/lon scheme) so repeated enrichment runs and the self-test never
    re-query the WMS for the same cell.
    """
    if cache is not None:
        rec = get_sample(cache, lat, lon, "corine")
        if rec:
            return rec["values"].get("code", "unknown")

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
    code = "unknown"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BoletsForecast/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            html = r.read().decode("utf-8", errors="replace")
        rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
        for row in rows[1:]:
            cells = [c.strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)]
            if len(cells) >= 3:
                code = cells[2]
                break
    except Exception:
        code = "unknown"
    if cache is not None:
        put_sample(cache, lat, lon, "corine", "CORINE CLC 2018 (WMS)", {"code": code})
    return code


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
    """Step 3.4 + 7.4 + 7.6: soil type + pH, finest available source first.

    Preference order (each step only promotes an unambiguous class):
      1. ICGC MSC25M 1:25k WFS (step 7.6) — the intended source; records the
         soil unit, Soil-Taxonomy class and parent-material class. Coverage is
         sheet-by-sheet, so most Pyrenean/interior zones get "no coverage" and
         fall through unchanged.
      2. IGME MAGNA 50 (1:50k) lithology (step 7.4).
      3. IGME 1:1M lithology + SoilGrids v2 pH (step 3.4).

    Returns (values, source): the source is resolution-specific so a fallback
    sample is never misread as a finer layer. The step-3.4 `soil_1_25k` cache
    entry is reused verbatim (its `ph`, even `null`, is the recorded SoilGrids
    result) so a re-run only re-queries the finer layers and never re-storms the
    slow SoilGrids service.
    """
    msc25 = _msc25_sample(cache, lat, lon)
    legacy = get_sample(cache, lat, lon, "soil_1_25k")
    leg_vals = legacy["values"] if legacy else {}
    hold_reason = MAGNA_REVIEW_HOLDS.get(zone.get("id"))

    # 1. MSC25M 1:25k: promote only an unambiguous calcareous/siliceous parent.
    if msc25.get("covered") and msc25.get("class") in ("calcareous", "siliceous"):
        values = {
            "type": msc25["class"],
            "texture": None,
            "ph": leg_vals.get("ph") if legacy else None,
            "litho_text": msc25.get("descripcio"),
            "resolution": "1:25k",
            "fallback_reason": None,
            "soil_1_25k": {
                "tipus_sol": msc25.get("tipus_sol"),
                "soil_taxon": msc25.get("soil_taxon"),
                "codi_cas": msc25.get("codi_cas"),
                "class": msc25.get("class"),
                "source": SOIL_1_25K_SOURCE,
            },
        }
        return values, "ICGC MSC25M (1:25k) soil + SoilGrids v2 (pH)"

    magna = _magna50_sample(cache, lat, lon)

    # 2. MAGNA 50 (1:50k) — unchanged from step 7.4.
    if _magna_promotable(zone.get("id"), magna):
        values = {
            "type": magna["class"],
            "texture": None,
            "ph": leg_vals.get("ph") if legacy else None,
            "litho_text": magna.get("dlo"),
            "resolution": "1:50k",
            "magna_hoja": magna.get("hoja"),
            "fallback_reason": None,
        }
        return values, "IGME MAGNA 50 (1:50k) lithology + SoilGrids v2 (pH)"

    if legacy:
        litho = leg_vals.get("litho_text", "unknown")
        soil_type = leg_vals.get("type")
        ph = leg_vals.get("ph")
    else:
        litho, soil_type = _igme_litho(lat, lon)
        ph = None
        if soil_type not in ("unknown",):
            ph = _soilgrids_ph(lat, lon)
    if soil_type == "unknown":
        return None
    values = {
        "type": soil_type,
        "texture": None,
        "ph": round(ph, 1) if ph is not None else None,
        "litho_text": litho,
        "resolution": "1:1M",
        "fallback_reason": (f"MAGNA 50 held for review: {hold_reason}"
                            if hold_reason else _magna_fallback_reason(magna)),
    }
    if hold_reason:
        # Keep the withheld proposal visible so a reviewer can decide without
        # re-querying; the promoted value itself stays 1:1M.
        values["magna_review"] = {
            "class": magna.get("class"),
            "litho_text": magna.get("dlo"),
            "hoja": magna.get("hoja"),
            "status": "held",
        }
    return values, "IGME 1:1M (litho) + SoilGrids v2 (pH)"


# ── Step 7.6: CHC50 / CHC3 habitat at 1:25k (SITMUN WMS) ─────────────────────
#
# The intended habitat layer is the Cartografia dels hàbitats de Catalunya. The
# UB "geoveg" CHC50 WMS has been down (README limitation #4); the version 3
# cartography ("CHC3", 1:25k, 2019-2022) is the current successor and is served
# for the Barcelona counties by the Diputació de Barcelona SITMUN WMS as layer
# `SITXELL_MN340` ("Hàbitats -polígons- (CHC3 - 2022)"). It carries the full
# CORINE list code and name (e.g. 42.5921+ "Boscos de pi roig (Pinus sylvestris),
# calcícoles i xeròfils, dels Pirineus"), which resolves stand-level tree species
# — the exact distinction CORINE CLC (100 m) cannot make. Coverage is the
# Barcelona province only, so most zones fall back to CORINE unchanged.

HABITAT_CHC3_WMS = "http://sitmun.diba.cat/wms/servlet/SITXELL"
HABITAT_CHC3_LAYER = "SITXELL_MN340"
HABITAT_CHC3_SOURCE = "DIBA SITMUN CHC3 (1:25k) habitat, 2019-2022"
HABITAT_CHC3_UA = "BoletsForecast/1.0 (habitat 1:25k enrichment; step 7.6)"

# CORINE list "grup" codes (first two digits of the CORINE-list code) → the
# coarse forest group the score already uses, so a CHC3 answer can be checked
# against the curated `forest.type` without changing the score (the shadow value
# stays reporting-only).
_CHC3_GROUP_TO_FOREST = {
    "41": "broadleaf",   # Boscos caducifolis
    "42": "conifer",     # Boscos aciculifolis
    "43": "mixed",       # Boscos mixtos
    "44": "broadleaf",   # boscos de ribera (riparian broadleaf)
    "45": "broadleaf",   # boscos esclerofil·les (alzinar/sureda)
}


def _chc3_habitat(lat, lon):
    """CHC3 1:25k habitat polygon at a point → (values dict, status).

    Returns {cod_corine, corine_ca, cod_grup, grup_ca, tipus_ca, subtip_ca} or
    (None, "no coverage" / "error"). Geometry is served in EPSG:25831, so the
    query box is in UTM 31N.
    """
    x, y = _to_utm31(lat, lon)
    d = 300  # ~300 m box centred on the centroid → the enclosing polygon
    url = (
        f"{HABITAT_CHC3_WMS}?service=WMS&version=1.3.0&request=GetFeatureInfo"
        f"&layers={HABITAT_CHC3_LAYER}&query_layers={HABITAT_CHC3_LAYER}"
        f"&CRS=EPSG:25831&BBOX={x-d},{y-d},{x+d},{y+d}"
        "&WIDTH=101&HEIGHT=101&I=50&J=50&INFO_FORMAT=text/html"
    )
    time.sleep(0.1)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": HABITAT_CHC3_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception:
        return None, "error"

    rows = re.findall(r"<tr>(.*?)</tr>", html, re.DOTALL)
    for row in rows[1:]:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL)]
        if len(cells) > 27 and cells[0].isdigit():
            # Column map (see SITMUN MN340 GetFeatureInfo): 3 COD_GRUP, 7 COD_TIPUS,
            # 11 COD_SUBTIP, 15 COD_CORINE, 16 CORINE_CA, 8 TIPUS_CA, 12 SUBTIP_CA.
            cod_corine = cells[15] if len(cells) > 15 else ""
            corine_ca = cells[16] if len(cells) > 16 else ""
            cod_grup = cells[3] if len(cells) > 3 else ""
            return {
                "cod_corine": cod_corine,
                "corine_ca": corine_ca,
                "cod_grup": cod_grup,
                "grup_ca": cells[4] if len(cells) > 4 else "",
                "tipus_ca": cells[8] if len(cells) > 8 else "",
                "subtip_ca": cells[12] if len(cells) > 12 else "",
                "cod_eunis": cells[24] if len(cells) > 24 else "",
            }, "ok"
    return None, "no coverage"


def _chc3_sample(cache, lat, lon):
    """Cached CHC3 habitat sample → {covered, ...}."""
    entry = cache.setdefault(cache_key(lat, lon), {})
    rec = entry.get("habitat_chc3")
    if (rec and rec.get("source") == HABITAT_CHC3_SOURCE
            and isinstance(rec.get("values"), dict)
            and _negative_cache_usable(rec)):
        return rec["values"]
    values, status = _chc3_habitat(lat, lon)
    if values is None:
        neg = {"covered": False, "reason": status}
        _store_negative(entry, "habitat_chc3", HABITAT_CHC3_SOURCE, neg, status)
        return neg
    values = dict(values)
    values["covered"] = True
    entry["habitat_chc3"] = {"source": HABITAT_CHC3_SOURCE,
                             "timestamp": _now(), "values": values}
    return values


# ── Step 7.7: GeoVeg / SIVIM (dormant provider) ────────────────────────────────
#
# The YouTuber's key vegetation source is the UB/CREAF interactive map ("GeoVeg"
# / SIVIM), which returns free-text vegetation polygons — e.g. "Pineda de pi roig
# (Pinus sylvestris) calcícola i xeròfila" — resolving the stand-level tree
# species and soil reaction that CORINE CLC (100 m) cannot. The host has been down
# for the whole project (README limitation #4; step 7.6 recorded the ArcIMS
# endpoint 161.116.68.143/…/UB_Geobotanica_habitats_fulls50m_1 timing out and
# geoveg.creaf.cat no longer resolving). Rather than invent a value, step 7.7 adds
# the provider **dormant**: `_geoveg` returns (None, "unavailable") and is never
# called by the pipeline, `_parse_geoveg` normalises its free text with a reviewed
# keyword table, and `_geoveg_shadow` diff-computes the parsed result against the
# CORINE group the score uses. Wiring `_geoveg` into `_habitat_compute` is a
# one-line change once the host returns; until then the score is byte-identical.

GEOVEG_SOURCE = "GeoVeg / SIVIM (UB-CREAF) vegetation polygon (dormant)"
GEOVEG_UA = "BoletsForecast/1.0 (habitat enrichment; step 7.7)"

# Reviewed soil-reaction keywords. The GeoVeg text names the stand's ecology, so
# "calcícola" (lime-loving) → calcareous and "acidòfil" (acid-loving) →
# siliceous. Both present is "mixed"; neither is None (no invented reaction).
_GEOVEG_CALC_KW = [
    "calcícola", "calcicoles", "calcícoles", "calcària", "calcaries",
    "calcàries", "calcari", "calcaris", "calcícol", "calcic", "calci",
]
_GEOVEG_SIL_KW = [
    "acidòfil", "acidofil", "acidòfila", "acidòfiles", "acidofiles",
    "silicícola", "silicicoles", "silicícoles", "silicícol", "silícic",
]

# Reviewed tree-species keywords → (forest group, canonical species). "roure" /
# "quercus" resolve to the ambiguous "Quercus spp." (oaks are more than one
# species — the step's documented ambiguity), never a single invented species.
_GEOVEG_TREE_SPECIES = {
    # conifer
    "pi roig": ("conifer", "Pinus sylvestris"),
    "pinus sylvestris": ("conifer", "Pinus sylvestris"),
    "pi negre": ("conifer", "Pinus uncinata"),
    "pinus uncinata": ("conifer", "Pinus uncinata"),
    "pinassa": ("conifer", "Pinus nigra"),
    "pinus nigra": ("conifer", "Pinus nigra"),
    "pi blanc": ("conifer", "Pinus halepensis"),
    "pinus halepensis": ("conifer", "Pinus halepensis"),
    "avet": ("conifer", "Abies alba"),
    "abies alba": ("conifer", "Abies alba"),
    "avetosa": ("conifer", "Abies alba"),
    "picea": ("conifer", "Picea abies"),
    "pinus": ("conifer", "Pinus spp."),
    # broadleaf
    "faig": ("broadleaf", "Fagus sylvatica"),
    "fagus sylvatica": ("broadleaf", "Fagus sylvatica"),
    "fageda": ("broadleaf", "Fagus sylvatica"),
    "roure": ("broadleaf", "Quercus spp."),
    "quercus": ("broadleaf", "Quercus spp."),
    "alzina": ("broadleaf", "Quercus ilex"),
    "quercus ilex": ("broadleaf", "Quercus ilex"),
    "sureda": ("broadleaf", "Quercus suber"),
    "quercus suber": ("broadleaf", "Quercus suber"),
    "castanyer": ("broadleaf", "Castanea sativa"),
    "castanea sativa": ("broadleaf", "Castanea sativa"),
    "bedoll": ("broadleaf", "Betula pendula"),
    "betula": ("broadleaf", "Betula spp."),
    "pollancre": ("broadleaf", "Populus spp."),
    "freixe": ("broadleaf", "Fraxinus spp."),
    # "verned" (not "vern") so the winter word "hivern" is not matched as alder.
    "verned": ("broadleaf", "Alnus glutinosa"),
    "alnus": ("broadleaf", "Alnus spp."),
}


def _geoveg(lat, lon):
    """GeoVeg vegetation description at a point → (text, status). Dormant.

    The UB geoveg host has been down and its exact query shape cannot be verified
    offline, so this provider does not fabricate a request. Returns
    (None, "unavailable"); the parser (`_parse_geoveg`) and shadow diff
    (`_geoveg_shadow`) are the testable core and are exercised in the self-test.
    """
    return None, "unavailable"


def _parse_geoveg(text):
    """Normalise GeoVeg free-text vegetation → {soil_reaction, tree_species,
    forest_group} or None.

    A reviewed keyword rule, not a model: soil reaction from the stand's
    "calcícola"/"acidòfil" ecology words; tree species from the reviewed keyword
    table (ambiguous "roures" → "Quercus spp."); forest group from the matched
    trees (one group → that group, more than one → "mixed"). Returns None when
    nothing recognisable is present, so a manual/free-text note is never turned
    into a confident value.
    """
    if not text:
        return None
    t = text.lower()
    has_cal = any(k in t for k in _GEOVEG_CALC_KW)
    has_sil = any(k in t for k in _GEOVEG_SIL_KW)
    if has_sil and not has_cal:
        soil_reaction = "siliceous"
    elif has_cal and not has_sil:
        soil_reaction = "calcareous"
    elif has_cal and has_sil:
        soil_reaction = "mixed"
    else:
        soil_reaction = None

    species = []
    groups = set()
    for kw, (grp, sci) in _GEOVEG_TREE_SPECIES.items():
        if kw in t:
            groups.add(grp)
            if sci not in species:
                species.append(sci)
    if len(groups) == 1:
        forest_group = next(iter(groups))
    elif len(groups) > 1:
        forest_group = "mixed"
    else:
        forest_group = None

    if soil_reaction is None and forest_group is None and not species:
        return None
    return {
        "soil_reaction": soil_reaction,
        "tree_species": species or None,
        "forest_group": forest_group,
    }


def _corine_forest_group(code):
    """Coarse tree group for a CORINE CLC 2018 code (311/312/313/324)."""
    return {
        "311": "broadleaf",
        "312": "conifer",
        "313": "mixed",
    }.get(code)  # 324 → None: transitional shrub, no clear tree group


def _geoveg_shadow(parsed, corine_code):
    """Shadow-diff a parsed GeoVeg result against the CORINE group the score uses.

    Returns None when there is nothing parsed to compare. The `matches_corine`
    flag is the audit signal: it is `None` when either side has no clear tree
    group, so a disagreement is never silently treated as agreement.
    """
    if not parsed:
        return None
    corine_group = _corine_forest_group(corine_code)
    matches = None
    if corine_group and parsed.get("forest_group"):
        matches = parsed["forest_group"] == corine_group
    return {
        "soil_reaction": parsed.get("soil_reaction"),
        "tree_species": parsed.get("tree_species"),
        "forest_group": parsed.get("forest_group"),
        "corine_group": corine_group,
        "matches_corine": matches,
    }


def _habitat_compute(lat, lon, zone, cache):
    """Step 3.4 + 7.6: dominant tree group, CHC3 1:25k first, CORINE fallback.

    When the CHC3 1:25k layer answers at the centroid, the habitat block records
    `resolution: "1:25k"` and the finer CORINE-list code/name in a `chc3` shadow
    block, while the score keeps using the coarse CORINE `dominant`/`corine_code`
    (step 7.6 keeps the old value during a shadow period). Where CHC3 has no
    coverage (outside the Barcelona province) the CORINE CLC 2018 fallback is
    unchanged.
    """
    chc3 = _chc3_sample(cache, lat, lon)
    code = _corine(lat, lon, cache)
    if code == "unknown":
        return None
    out = {
        "dominant": _CORINE_TREE_GROUP.get(code, "non-forest"),
        "corine_code": code,
    }
    if chc3.get("covered") and chc3.get("cod_corine"):
        out["resolution"] = "1:25k"
        out["chc3"] = {
            "cod_corine": chc3.get("cod_corine"),
            "corine_ca": chc3.get("corine_ca"),
            "cod_grup": chc3.get("cod_grup"),
            "grup_ca": chc3.get("grup_ca"),
            "tipus_ca": chc3.get("tipus_ca"),
            "subtip_ca": chc3.get("subtip_ca"),
            "cod_eunis": chc3.get("cod_eunis"),
            "forest_group": _CHC3_GROUP_TO_FOREST.get(str(chc3.get("cod_corine", ""))[:2]),
            "source": HABITAT_CHC3_SOURCE,
        }
        # Per-sample source: only a zone where CHC3 actually answered may claim
        # the 1:25k layer (the confidence anchor parses this).
        return out, HABITAT_CHC3_SOURCE
    return out, "CORINE CLC 2018 (100 m)"


PROVIDERS = {
    "dem":      {"step": "3.2", "source": DEM_SOURCE, "compute": _dem_compute},
    "lidar":    {"step": "3.3", "source": CANOPY_SOURCE,      "compute": _lidar_compute},
    "soil":     {"step": "7.6", "source": "ICGC MSC25M (1:25k) → IGME MAGNA 50 (1:50k) → IGME 1:1M fallback + SoilGrids v2 (pH)", "compute": _soil_compute},
    "habitat":  {"step": "7.6", "source": "DIBA SITMUN CHC3 (1:25k) → CORINE CLC 2018 fallback", "compute": _habitat_compute},
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
    # A provider may return (values, source) to record a per-sample source (the
    # soil provider does — the 1:50k vs 1:1M source differs per sample).
    source = PROVIDERS[provider_key]["source"]
    if isinstance(values, tuple) and len(values) == 2 and isinstance(values[1], str):
        values, source = values
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
    soil_vals, soil_src, soil_at = _sample(cache, lat, lon, "soil")
    hab_vals, hab_src, hab_at = _sample(cache, lat, lon, "habitat")

    # The cached "soil" record is derived from the raw MAGNA/1:1M samples. When
    # a MAGNA record exists, rebuild it from the current classifier and review
    # holds so a mapping/hold change applies without clearing the cache.
    entry = cache.get(cache_key(lat, lon)) or {}
    if isinstance(entry.get("magna50"), dict) or isinstance(entry.get("soil_1_25k_wfs"), dict):
        rebuilt, rebuilt_src = _soil_compute(lat, lon, zone, cache)
        if rebuilt:
            soil_vals, soil_src = rebuilt, rebuilt_src
            legacy = get_sample(cache, lat, lon, "soil_1_25k")
            soil_at = legacy["timestamp"] if legacy else soil_at
    # Same for habitat: the step-3.4 cache entry predates CHC3, so always
    # recompute the habitat block. `_habitat_compute` samples CHC3 via its own
    # cache and merges the finer resolution/chc3 fields when it answers; the
    # CORINE fallback part reuses the cached `corine` value.
    rebuilt_hab = _habitat_compute(lat, lon, zone, cache)
    if rebuilt_hab:
        hab_vals, hab_src = rebuilt_hab
        if hab_vals.get("chc3"):
            chc3_rec = (cache.get(cache_key(lat, lon)) or {}).get("habitat_chc3") or {}
            hab_at = chc3_rec.get("timestamp") if isinstance(chc3_rec, dict) else None
        else:
            corine_rec = get_sample(cache, lat, lon, "corine")
            hab_at = corine_rec["timestamp"] if corine_rec else hab_at

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
        pending.append("soil (MAGNA 50 / 1:1M type, pH) and habitat (dominant tree)")

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
        "status": "complete" if soil_done else "pending",  # step 7.4 (soil)
        "source": soil_src,
        "sampled_at": soil_at,
        "type": None,
        "texture": None,
        "ph": None,
        "resolution": None,
    }
    if soil_done:
        soil.update({
            "type": soil_vals["type"],
            "texture": soil_vals.get("texture"),
            "ph": soil_vals.get("ph"),
            "litho_text": soil_vals.get("litho_text"),
            "resolution": soil_vals.get("resolution"),
            "magna_hoja": soil_vals.get("magna_hoja"),
            "fallback_reason": soil_vals.get("fallback_reason"),
            "note": ("type from ICGC MSC25M (1:25k) parent material, pH from SoilGrids v2"
                     if soil_vals.get("resolution") == "1:25k" else
                     "type from IGME MAGNA 50 (1:50k), pH from SoilGrids v2"
                     if soil_vals.get("resolution") == "1:50k" else
                     "type from IGME 1:1M lithology (MAGNA 50 fell back), pH from "
                     "SoilGrids v2; 1:25k soil upgrade recorded where the MSC25M "
                     "sheet covers the point (step 7.6)"),
        })
        if soil_vals.get("soil_1_25k"):
            soil["soil_1_25k"] = soil_vals["soil_1_25k"]
        if soil_vals.get("magna_review"):
            soil["magna_review"] = soil_vals["magna_review"]

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
            "resolution": hab_vals.get("resolution"),
            "note": ("dominant tree group from CORINE CLC 2018; CHC3 1:25k habitat "
                     "recorded in `chc3` for the Barcelona province (step 7.6)"
                     if hab_vals.get("resolution") == "1:25k" else
                     "dominant tree group from CORINE CLC 2018 (fallback for "
                     "the ICGC/CREAF CHC50 habitat map, source unavailable)"),
        })
        if hab_vals.get("chc3"):
            habitat["chc3"] = hab_vals["chc3"]

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
            "generator": "enrich_zones.py (Phase 7.6)",
            "generated_at": _now(),
            "source_zones": os.path.basename(ZONES_FILE),
            "stations": n_stations,
            "zones": n_zones,
            "providers": {
                "dem":       {"step": "3.2", "status": "done" if n_dem else "pending"},
                "lidar":     {"step": "3.3", "status": "done" if n_lidar else "pending"},
                "soil":      {"step": "7.6", "status": "done" if n_soil else "pending",
                              "note": "ICGC MSC25M (1:25k) WFS where the sheet covers the point, else IGME MAGNA 50 (1:50k) → IGME 1:1M + SoilGrids"},
                "habitat":   {"step": "7.6", "status": "done" if n_habitat else "pending",
                              "note": "DIBA SITMUN CHC3 (1:25k) for the Barcelona province, else CORINE CLC 2018 fallback"},
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
    put_sample(cache, 42.1546, 1.9025, "soil", "self-test",
               {"type": "calcareous", "resolution": "1:50k",
                "litho_text": "Calizas (Sec. Areny)", "fallback_reason": None})
    put_sample(cache, 42.1546, 1.9025, "habitat", "self-test", {"dominant": "conifer"})
    # Offline CORINE + CHC3 seeds so `_habitat_compute` (always recomputed) and
    # the enrichment shape stay deterministic in the self-test.
    put_sample(cache, 42.1546, 1.9025, "corine", "self-test", {"code": "312"})
    put_sample(cache, 42.1546, 1.9025, "habitat_chc3", "self-test",
               {"covered": False, "reason": "no coverage"})

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

    # ── Step 7.4 MAGNA 50 legend normalisation (offline) ──────────────────────
    assert _classify_magna("Calizas (Sec. Areny)") == "calcareous"
    assert _classify_magna("Dolomías, calizas y margas") == "calcareous"
    assert _classify_magna("Granodiorita") == "siliceous"
    assert _classify_magna("Gneises ocelares (Núria y Carancá)") == "siliceous"
    assert _classify_magna("Pizarras laminadas, cuarcitas, porfiroides y calizas") == "mixed"
    # Detrital-only must NOT promote to siliceous (a carbonate-cemented
    # conglomerate is calcareous) → "mixed" (fall back to 1:1M).
    assert _classify_magna("Conglomerados masivos") == "mixed"
    assert _classify_magna("Areniscas y arcillas rojas") == "mixed"
    # A carbonate keyword alongside a detrital one is transitional → mixed.
    assert _classify_magna("Calizas niveles de carbón areniscas y lutitas rojas") == "mixed"
    # Surficial/transported deposits are not bedrock → mixed.
    assert _classify_magna("Bloques y arenas (desmantelamiento glaciar)") == "mixed"
    assert _classify_magna("DUNAS FIJADAS. Arenas y limos eólicas fijados") == "mixed"
    assert _classify_magna("") == "unknown"
    # Fallback reason text.
    assert _magna_fallback_reason({"covered": False, "reason": "no coverage"}) \
        .startswith("MAGNA 50 no coverage")
    assert "ambiguous" in _magna_fallback_reason(
        {"covered": True, "class": "mixed", "dlo": "Conglomerados masivos"})
    # Review holds: an unambiguous MAGNA answer is still not promoted on hold.
    assert _magna_promotable("synthetic-zone", {"covered": True, "class": "siliceous"})
    assert not _magna_promotable("synthetic-zone", {"covered": True, "class": "mixed"})
    assert not _magna_promotable("synthetic-zone", {"covered": False, "class": "siliceous"})
    for held in MAGNA_REVIEW_HOLDS:
        assert not _magna_promotable(held, {"covered": True, "class": "siliceous"}), held
    assert set(MAGNA_REVIEW_HOLDS) == {"colldepal-cresta-alta", "baga-obaga-pi"}

    # ── Step 7.6 MSC25M parent-material classification (offline) ───────────────
    assert _classify_msc25_parent("S'han format sobre calcàries.") == "calcareous"
    assert _classify_msc25_parent("S'han format sobre roques calcàries que afloren.") == "calcareous"
    assert _classify_msc25_parent("S'han format sobre granits i esquistos.") == "siliceous"
    # Detrital/transported parents are NOT promoted (unknown carbonate/siliceous).
    assert _classify_msc25_parent("S'han format sobre sediments detrítics terrígens.") == "mixed"
    assert _classify_msc25_parent("S'han format sobre dipòsits al·luvials.") == "mixed"
    assert _classify_msc25_parent("") == "unknown"
    # UTM 31N conversion: Rasos de Peguera (42.1546, 1.9025) → ~(409327, 4667524).
    ux, uy = _to_utm31(42.1546, 1.9025)
    assert abs(ux - 409327.44) < 1.0 and abs(uy - 4667524.38) < 1.0, (ux, uy)
    # CHC3 group → forest group mapping.
    assert _CHC3_GROUP_TO_FOREST["42"] == "conifer"
    assert _CHC3_GROUP_TO_FOREST["41"] == "broadleaf"
    assert _CHC3_GROUP_TO_FOREST["43"] == "mixed"

    # ── Step 7.7 GeoVeg keyword parser + shadow diff (offline) ─────────────────
    p = _parse_geoveg("Pineda de pi roig (Pinus sylvestris) calcícola i xeròfila")
    assert p["soil_reaction"] == "calcareous", p
    assert p["forest_group"] == "conifer", p
    assert "Pinus sylvestris" in p["tree_species"], p
    p2 = _parse_geoveg("Fageda acidòfila amb roures (Fagus sylvatica)")
    assert p2["soil_reaction"] == "siliceous", p2
    assert p2["forest_group"] == "broadleaf", p2
    # "roures" is ambiguous → Quercus spp., never a single invented species.
    assert "Quercus spp." in p2["tree_species"], p2
    assert "Fagus sylvatica" in p2["tree_species"], p2
    # One conifer + one broadleaf tree → mixed.
    p3 = _parse_geoveg("Bosc mixt de pi roig i faig")
    assert p3["forest_group"] == "mixed", p3
    # No recognisable signal → None (never a confident value from free text).
    assert _parse_geoveg("") is None
    assert _parse_geoveg("herbassar de muntanya") is None
    # Substring guard: "hivern" (winter) must not be read as "vern" (alder).
    assert _parse_geoveg("obaga d'hivern") is None
    # The alder grove form still matches.
    p4 = _parse_geoveg("verneda de ribera")
    assert p4["forest_group"] == "broadleaf", p4
    assert "Alnus glutinosa" in p4["tree_species"], p4
    # Shadow diff against CORINE.
    sh = _geoveg_shadow(_parse_geoveg("Pineda de pi roig calcícola"), "312")
    assert sh["matches_corine"] is True, sh
    assert sh["corine_group"] == "conifer", sh
    sh2 = _geoveg_shadow(_parse_geoveg("Pineda de pi roig calcícola"), "311")
    assert sh2["matches_corine"] is False, sh2
    # 324 has no clear tree group → match is None (never silently "agree").
    sh3 = _geoveg_shadow(_parse_geoveg("Pineda de pi roig calcícola"), "324")
    assert sh3["matches_corine"] is None, sh3
    # Dormant provider records "unavailable", never a fabricated query.
    text, status = _geoveg(42.0, 1.9)
    assert text is None and status == "unavailable", (text, status)

    # Point-in-polygon selection (the MSC25M WFS returns intersecting polygons,
    # so the containing one must be chosen, not the first in server order).
    square = {"type": "Polygon",
              "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}
    assert _point_in_geom(5, 5, square)
    assert not _point_in_geom(15, 5, square)
    holed = {"type": "Polygon",
             "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                             [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]}
    assert not _point_in_geom(5, 5, holed)      # in the hole
    assert _point_in_geom(7, 5, holed)
    multi = {"type": "MultiPolygon", "coordinates": [square["coordinates"],
                                                     [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]]]}
    assert _point_in_geom(25, 5, multi) and not _point_in_geom(15, 5, multi)

    # Cache policy: no-coverage is permanent, transient errors retry after a TTL.
    assert _negative_cache_usable({"values": {"covered": False, "reason": "no coverage"}})
    assert _negative_cache_usable({"values": {"covered": False, "reason": "error"},
                                   "retry_at": time.time() + 60})
    assert not _negative_cache_usable({"values": {"covered": False, "reason": "error"},
                                       "retry_at": time.time() - 60})
    assert not _negative_cache_usable({"values": {"covered": False, "reason": "error"}})


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
    assert e["soil"]["resolution"] == "1:50k"      # MAGNA 50 resolution recorded
    assert e["soil"]["fallback_reason"] is None    # MAGNA answered clearly
    assert e["habitat"]["dominant"] == "conifer (pi/avet)"  # CORINE 312 via cache
    assert t["source"] == "ICGC 5m LiDAR DEM (2021-2023)"
    assert len(e["pending_steps"]) == 2  # only 3.2 + 3.3 remain for this partial sample

    # A review-held zone must not use a promoted 1:50k soil answer, even when the
    # provider cache already holds one; the MAGNA proposal is kept for review.
    held_lat, held_lon = 42.296, 1.8772
    put_sample(cache, held_lat, held_lon, "dem", "self-test", {})
    put_sample(cache, held_lat, held_lon, "lidar", "self-test", {})
    put_sample(cache, held_lat, held_lon, "corine", "self-test", {"code": "312"})
    put_sample(cache, held_lat, held_lon, "habitat_chc3", "self-test",
               {"covered": False, "reason": "no coverage"})
    put_sample(cache, held_lat, held_lon, "habitat", "self-test", {"dominant": "conifer"})
    put_sample(cache, held_lat, held_lon, "soil", "self-test", {
        "type": "siliceous", "resolution": "1:50k",
        "litho_text": "Liditas y alternancia de areniscas y lutitas",
        "magna_hoja": "255", "fallback_reason": None,
    })
    put_sample(cache, held_lat, held_lon, "soil_1_25k", "self-test", {
        "type": "calcareous", "ph": 6.4,
        "litho_text": "Dolomías, calizas y margas. Areniscas",
    })
    # Offline MSC25M negative so the held-zone rebuild never touches the WFS.
    put_sample(cache, held_lat, held_lon, "soil_1_25k_wfs", SOIL_1_25K_SOURCE,
               {"covered": False, "reason": "no coverage", "class": "unknown"})
    cache[cache_key(held_lat, held_lon)]["magna50"] = {
        "source": MAGNA_SOURCE, "timestamp": "self-test",
        "values": {"covered": True, "dlo": "Liditas y alternancia de areniscas y lutitas",
                   "hoja": "255", "class": "siliceous", "reason": "ok"},
    }
    held_out = enrich_zone({
        "id": "baga-obaga-pi", "name": "Held", "lat": held_lat, "lon": held_lon,
        "alt_m": 1400, "slope_deg": 20, "aspect_deg": 10, "aspect": "north",
        "forest": {"type": "conifer", "dominant": "Pinus sylvestris"},
        "sources": [],
    }, cache)["enrichment"]["soil"]
    assert held_out["resolution"] == "1:1M", held_out
    assert held_out["type"] == "calcareous", held_out
    assert "held for review" in held_out["fallback_reason"], held_out
    assert held_out["magna_review"]["class"] == "siliceous", held_out
    assert held_out["magna_review"]["status"] == "held", held_out

    print("self-test OK: cache round-trip + DEM + canopy + soil/habitat + MAGNA hold + MSC25M + CHC3 + enrichment shape")


def main():
    if "--self-test" in sys.argv:
        self_test()
        return
    enrich_all()


if __name__ == "__main__":
    main()
