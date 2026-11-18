#!/usr/bin/env python3
"""
Bolets calibration (Phase 5.6) — stdlib-only.

Computes and publishes the model's accuracy metrics:

1. **Field reports** (the real binary loop, from step 5.1's `reports.db`):
   `found`/`not_found` against the model's `score_at_time`, evaluated on a
   deterministic held-out split → AUC, Brier score and a binned calibration
   curve. These are the only labels with a true match between "what the model
   said" and "what actually happened".

2. **Occurrence discrimination** (GBIF / iNaturalist presence-only, sourced):
   per-species AUC of the model's *current* score at occurrence sites versus
   random background points across Catalonia. Presence-only data has no true
   absences, so this is a rank-discrimination metric (standard in species
   distribution modelling), not a prevalence-calibrated probability.

No recalibration is applied to the score unless there is enough held-out data
to justify it — the published numbers are honest descriptive/validation
metrics, which is the point of "do not overfit to single reports".

Usage:
  python3 calibrate.py              # full pipeline → calibration_report.json
  python3 calibrate.py --self-test  # offline metric-math checks (no network)
"""

import bisect
import json
import math
import os
import random
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

import app  # reuse species/zones/forecast + the reports store

CAT_BBOX = (40.5, 0.0, 43.5, 3.5)   # south, west, north, east (Catalonia)
MAX_ZONE_KM = 20.0                  # occurrences farther than this from a zone are out of coverage
BACKGROUND_N = 200                  # random background points per species
BACKGROUND_TRY = 2000               # max random draws to find in-coverage background points
GBIF_LIMIT = 500
REPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "calibration_report.json")

# ── Phase 7.5: backtest & validate the assumptions ─────────────────────────────
#
# The hand weights (rain 35 / temperature 25 / wind 20 / altitude 10 / humidity
# 10, inside the weather score `W`) and the multiplicative `H`/`M`/`P` factors are
# modelling choices. This section validates them instead of assuming them:
#
#   - temporal split: train on older occurrences, test on newer (see
#     `choose_split_year`); applies only to the time-invariant habitat signal
#     because every point is scored with *today's* weather,
#   - pseudo-absences: target-group background (background drawn from the pooled
#     occurrence set of all species, so it reflects recorder effort),
#   - recorder-effort weighting: each point is weighted by the inverse of its
#     local occurrence density, so over-sampled stands do not dominate the rank
#     statistic,
#   - factor sensitivity / model-fit: permutation importance of W/H/M/P and a
#     held-out refit of the five weather weights, with a bootstrap CI on the gain.
#
# The honest default is "no change": ship new weights only on a stable held-out
# gain (positive gain with a bootstrap 95% CI entirely above zero).

REPORT_VERSION = 2
WEATHER_FACTOR_NAMES = ("pluja", "temperatura", "vent", "altitud", "humitat")
# Must match the `base` line in app.py::score_station (the five weather weights).
CURRENT_WEATHER_WEIGHTS = (0.35, 0.25, 0.20, 0.10, 0.10)
TOP_FACTORS = ("W", "H", "M", "P")
EFFORT_RADIUS_KM = 5.0        # local recorder-effort radius (documented choice)
BG_PER_SPECIES = 200          # target-group background points per species
MIN_SPLIT_PRESENCE = 8        # minimum dated occurrences per side for a temporal split
WEIGHT_HOLDOUT_FRAC = 0.3     # hold-out fraction for the weight refit
WEIGHT_HOLDOUT_SEED = 11
BOOTSTRAP_N = 200             # bootstrap resamples for the gain CI
BOOTSTRAP_SEED = 2026


# ── Metric math ────────────────────────────────────────────────────────────────

def auc(scores_pos, scores_neg):
    """Area under the ROC curve via the Mann–Whitney U statistic (ties = 0.5)."""
    if not scores_pos or not scores_neg:
        return None
    pos = sorted(scores_pos)
    n1, n2 = len(pos), len(scores_neg)
    total = 0.0
    for s in scores_neg:
        gt = n1 - bisect.bisect_right(pos, s)
        eq = bisect.bisect_right(pos, s) - bisect.bisect_left(pos, s)
        total += gt + 0.5 * eq
    return total / (n1 * n2)


def brier(y_true, p_pred):
    """Mean squared error between binary labels and predicted probabilities."""
    if not y_true:
        return None
    return sum((p - y) ** 2 for y, p in zip(y_true, p_pred)) / len(y_true)


def calibration_curve(y_true, scores, n_bins=10):
    """Reliability diagram: bin by predicted score, report observed found-rate."""
    bins = [[] for _ in range(n_bins)]
    for y, s in zip(y_true, scores):
        idx = min(n_bins - 1, int(float(s) // (100.0 / n_bins)))
        bins[idx].append(y)
    curve = []
    for i, ys in enumerate(bins):
        if not ys:
            continue
        lo = round(i * (100.0 / n_bins), 1)
        hi = round((i + 1) * (100.0 / n_bins), 1)
        curve.append({
            "bin": i,
            "score_range": [lo, hi],
            "n": len(ys),
            "predicted_mean_score": round(sum(ys) / len(ys), 1),
            "observed_found_rate": round(sum(ys) / len(ys), 3),
        })
    return curve


def heldout_split(rows, frac=0.3, seed=7):
    """Deterministic hold-out split (shuffled index)."""
    rnd = random.Random(seed)
    idx = list(range(len(rows)))
    rnd.shuffle(idx)
    k = int(len(rows) * frac)
    test = sorted(idx[:k])
    train = sorted(idx[k:])
    return [rows[i] for i in train], [rows[i] for i in test]


# ── Field reports ──────────────────────────────────────────────────────────────

def reports_labels():
    """(found, score_at_time) pairs from the step-5.1 store (only scored rows)."""
    conn = app._reports_connect()
    try:
        rows = conn.execute(
            "SELECT found, score_at_time FROM reports "
            "WHERE score_at_time IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [(int(found), float(score)) for found, score in rows]


# ── Occurrences (GBIF primary, iNaturalist supplementary) ──────────────────────

def _http_json(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": "bolets-calibrate/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _in_bbox(lat, lon):
    return CAT_BBOX[0] <= lat <= CAT_BBOX[2] and CAT_BBOX[1] <= lon <= CAT_BBOX[3]


def gbif_usage_key(name):
    url = "https://api.gbif.org/v1/species/match?name=" + urllib.parse.quote(name)
    d = _http_json(url)
    key = d.get("usageKey")
    # When the queried name is a synonym, GBIF also returns the accepted taxon's
    # key (acceptedUsageKey); use it so occurrence search covers the full taxon.
    accepted = d.get("acceptedUsageKey")
    return (accepted or key), d.get("status"), d.get("confidence")


def gbif_occurrences(usage_key):
    url = ("https://api.gbif.org/v1/occurrence/search?"
           f"taxonKey={usage_key}&hasCoordinate=true&country=ES&limit={GBIF_LIMIT}")
    d = _http_json(url)
    pts = []
    for rec in d.get("results", []):
        lat, lon = rec.get("decimalLatitude"), rec.get("decimalLongitude")
        if lat is None or lon is None:
            continue
        if _in_bbox(lat, lon):
            pts.append((round(lat, 4), round(lon, 4), rec.get("year")))
    return pts


def inat_taxon_id(name):
    url = "https://api.inaturalist.org/v1/taxa?q=" + urllib.parse.quote(name)
    d = _http_json(url, timeout=30)
    for r in d.get("results", []):
        if r.get("rank") == "species" and r.get("name", "").lower() == name.lower():
            return r.get("id")
    return None


def inat_occurrences(taxon_id):
    s, w, n, e = CAT_BBOX
    url = ("https://api.inaturalist.org/v1/observations?"
           f"taxon_id={taxon_id}&verifiable=true&swlat={s}&swlng={w}"
           f"&nelat={n}&nelng={e}&per_page=200&order=desc&order_by=created_at")
    d = _http_json(url, timeout=30)
    pts = []
    for rec in d.get("results", []):
        lat = lon = None
        geo = rec.get("geojson") or {}
        coords = geo.get("coordinates")
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
        else:
            loc = rec.get("location")
            if loc:
                try:
                    lat, lon = (float(x) for x in loc.split(","))
                except (ValueError, TypeError):
                    lat = lon = None
        if lat is None or lon is None:
            continue
        if _in_bbox(lat, lon):
            pts.append((round(lat, 4), round(lon, 4), rec.get("observed_on")))
    return pts


def dedupe(pts, decimals=3):
    seen = set()
    out = []
    for lat, lon, meta in pts:
        key = (round(lat, decimals), round(lon, decimals))
        if key in seen:
            continue
        seen.add(key)
        out.append((lat, lon, meta))
    return out


# ── Zone ↔ score machinery ─────────────────────────────────────────────────────

def load_zones():
    """Flat list of {id, name, lat, lon, comarca} from zones.json."""
    z = json.load(open(app.ZONES_FILE, encoding="utf-8"))
    flat = []
    for comarca_station, zones in z.get("zones", {}).items():
        for zone in zones:
            flat.append({
                "id": zone.get("id"), "name": zone.get("name"),
                "lat": float(zone["lat"]), "lon": float(zone["lon"]),
                "comarca": comarca_station,
            })
    return flat


def nearest_zone(lat, lon, zones):
    best, best_d = None, None
    for z in zones:
        d = app.haversine_m(lat, lon, z["lat"], z["lon"]) / 1000.0
        if best_d is None or d < best_d:
            best, best_d = z, d
    return best, best_d


def score_lookup(forecast):
    """{zone_id: {species_id: score}} from a build_forecast() payload."""
    lookup = {}
    for comarca, stations in forecast.get("comarques", {}).items():
        for stn in stations:
            for zone in stn.get("zones") or []:
                if zone.get("error"):
                    continue
                sp_scores = {}
                for r in zone.get("species") or []:
                    if r.get("id") is not None and r.get("score") is not None:
                        sp_scores[r["id"]] = float(r["score"])
                if sp_scores:
                    lookup[zone.get("id")] = sp_scores
    return lookup


def background_points(zones):
    """Random Catalonia points within coverage of a zone, as (zone_id) list."""
    s, w, n, e = CAT_BBOX
    rnd = random.Random(42)
    ids = []
    for _ in range(BACKGROUND_TRY):
        if len(ids) >= BACKGROUND_N:
            break
        lat = rnd.uniform(s, n)
        lon = rnd.uniform(w, e)
        z, d = nearest_zone(lat, lon, zones)
        if z is not None and d <= MAX_ZONE_KM:
            ids.append(z["id"])
    return ids


# ── Phase 7.5 machinery ────────────────────────────────────────────────────────

def _round_key(lat, lon, decimals=3):
    return (round(lat, decimals), round(lon, decimals))


def weighted_auc(scores_pos, scores_neg, w_pos=None, w_neg=None):
    """Area under the ROC curve via the weighted Mann–Whitney U (ties = 0.5).

    With equal weights this is the same statistic as `auc()`. Weights let
    recorder-effort-down-weighted points contribute proportionally less.
    """
    if not scores_pos or not scores_neg:
        return None
    w_pos = [1.0] * len(scores_pos) if w_pos is None else list(w_pos)
    w_neg = [1.0] * len(scores_neg) if w_neg is None else list(w_neg)
    pairs = sorted(zip(scores_pos, w_pos))
    p_scores = [s for s, _ in pairs]
    p_weights = [w for _, w in pairs]
    prefix = [0.0]
    for w in p_weights:
        prefix.append(prefix[-1] + w)
    total_w_pos = prefix[-1]
    total_w_neg = sum(w_neg)
    if total_w_pos <= 0 or total_w_neg <= 0:
        return None
    total = 0.0
    for s, wn in zip(scores_neg, w_neg):
        r = bisect.bisect_right(p_scores, s)
        l = bisect.bisect_left(p_scores, s)
        w_gt = total_w_pos - prefix[r]
        w_eq = prefix[r] - prefix[l]
        total += wn * (w_gt + 0.5 * w_eq)
    return total / (total_w_pos * total_w_neg)


def occurrence_year(meta):
    """Year from a GBIF year int or an iNaturalist `observed_on` string."""
    if isinstance(meta, int):
        return meta
    if isinstance(meta, str):
        try:
            return int(meta[:4])
        except (ValueError, TypeError):
            return None
    return None


def choose_split_year(years, min_side=MIN_SPLIT_PRESENCE):
    """Deterministic temporal-split year: ~30 % of dated occurrences in the test
    (most recent) side, with both sides ≥ `min_side`. None when impossible."""
    known = sorted(y for y in years if y is not None)
    if len(known) < 2 * min_side:
        return None
    best_y, best_score = None, None
    for y in sorted(set(known)):
        train = sum(1 for k in known if k < y)
        test = sum(1 for k in known if k >= y)
        if train < min_side or test < min_side:
            continue
        score = abs(test / len(known) - 0.3)
        if best_score is None or score < best_score:
            best_score, best_y = score, y
    return best_y


def split_by_year(pts, split_year):
    """Split dated occurrence points by `split_year`; undated points are dropped."""
    train, test = [], []
    for pt in pts:
        y = occurrence_year(pt[2])
        if y is None:
            continue
        (train if y < split_year else test).append(pt)
    return train, test


def effort_weights(pool_pts, target_pts, radius_km=EFFORT_RADIUS_KM):
    """Inverse-effort weight per target point: w = 1 / (1 + k), where k is the
    number of OTHER pooled occurrence points within `radius_km`. Down-weights
    spatially clustered (over-sampled) records."""
    out = []
    for lat, lon in target_pts:
        k = 0
        for plat, plon in pool_pts:
            if plat == lat and plon == lon:
                continue
            if app.haversine_m(lat, lon, plat, plon) / 1000.0 <= radius_km:
                k += 1
        out.append(1.0 / (1.0 + k))
    return out


def _sp_seed(sp_id):
    return 1000 + sum((ord(c) * (i + 1)) for i, c in enumerate(sp_id))


def target_group_background(focal_pts, pool, n, seed, radius_km=EFFORT_RADIUS_KM):
    """Pseudo-absence background for one species: sampled from the pooled
    target-group occurrences (recorder-effort-biased background), excluding the
    focal species' own coordinates. Returns [(lat, lon, year, effort_weight)]."""
    focal_keys = {_round_key(lat, lon) for lat, lon, _m in focal_pts}
    cands = [p for p in pool if _round_key(p[0], p[1]) not in focal_keys]
    rnd = random.Random(seed)
    rnd.shuffle(cands)
    bg = cands[:min(n, len(cands))]
    weights = effort_weights([p[:2] for p in pool], [(p[0], p[1]) for p in bg],
                             radius_km)
    return [(p[0], p[1], p[2], w) for p, w in zip(bg, weights)]


def factor_lookup(forecast):
    """{zone_id: {species_id: factor-vector}} from a build_forecast() payload.

    Each vector carries the stored W/H/M/P and the five raw weather sub-scores
    (pluja/temperatura/vent/altitud/humitat) that `W` is built from.
    """
    lookup = {}
    for stations in forecast.get("comarques", {}).values():
        for stn in stations:
            for zone in stn.get("zones") or []:
                if zone.get("error"):
                    continue
                sp_map = {}
                for r in zone.get("species") or []:
                    sid = r.get("id")
                    if sid is None:
                        continue
                    f = r.get("factors") or {}
                    h = f.get("H") or {}
                    m = f.get("M") or {}
                    bd = r.get("breakdown") or {}
                    vec = {k: (float(bd[k]) if bd.get(k) is not None else None)
                           for k in WEATHER_FACTOR_NAMES}
                    vec.update({
                        "W": f.get("W"),
                        "H": h.get("score"),
                        "M": m.get("score"),
                        "P": f.get("P"),
                    })
                    sp_map[sid] = vec
                if sp_map:
                    lookup[zone.get("id")] = sp_map
    return lookup


def point_factors(lat, lon, sp_id, zones, lookup):
    """Factor vector for `sp_id` at the nearest zone within coverage, else None."""
    z, d = nearest_zone(lat, lon, zones)
    if z is None or d > MAX_ZONE_KM:
        return None
    sp_map = lookup.get(z["id"])
    if not sp_map:
        return None
    return sp_map.get(sp_id)


def _pct(v, default=100.0):
    return default if v is None else float(v)


def score_from_factors(vec, weights):
    """Recompute a 0–100 score from a factor vector + weather weights.

    W = Σ weight_i × sub-factor_i; score = W × H × M × P (H/M/P are 0–100
    multipliers). This is the shipped formula (app.py::score_station) apart from
    the Phase 4.3 drought/recharge modifier, which lives inside the *stored* W
    but not the raw sub-factors — so the refit isolates the five hand weights.
    """
    w = sum(wt * _pct(vec[k], 0.0) for wt, k in zip(weights, WEATHER_FACTOR_NAMES))
    h = _pct(vec["H"]) / 100.0
    m = _pct(vec["M"]) / 100.0
    p = _pct(vec["P"]) / 100.0
    return w * h * m * p


def _auc_of_rows(rows, weights):
    pos = [score_from_factors(r["vec"], weights) for r in rows if r["y"] == 1]
    neg = [score_from_factors(r["vec"], weights) for r in rows if r["y"] == 0]
    wp = [r["w"] for r in rows if r["y"] == 1]
    wn = [r["w"] for r in rows if r["y"] == 0]
    return weighted_auc(pos, neg, wp, wn)


def build_pooled(forecast, zones, occurrences):
    """Pooled factor rows across species: presence + target-group background.

    `occurrences` is {sp_id: [(lat, lon, meta), ...]}. Returns rows
    [{"sp", "y", "w", "vec"}] with a complete factor vector and effort weight.
    """
    lookup = factor_lookup(forecast)
    pool = dedupe([(lat, lon, meta) for pts in occurrences.values()
                   for lat, lon, meta in pts])
    rows = []
    for sp_id, pts in occurrences.items():
        for lat, lon, meta in pts:
            vec = point_factors(lat, lon, sp_id, zones, lookup)
            if vec is None:
                continue
            w = effort_weights([p[:2] for p in pool], [(lat, lon)])[0]
            rows.append({"sp": sp_id, "y": 1, "w": w, "vec": vec})
        for lat, lon, _meta, w in target_group_background(
                pts, pool, BG_PER_SPECIES, _sp_seed(sp_id)):
            vec = point_factors(lat, lon, sp_id, zones, lookup)
            if vec is None:
                continue
            rows.append({"sp": sp_id, "y": 0, "w": w, "vec": vec})
    return rows


def permutation_importance(rows, weights, seed=7):
    """AUC drop when each top factor is permuted (larger drop = more important)."""
    def shuffled_rows(factor):
        rnd = random.Random(seed + 1000 + TOP_FACTORS.index(factor))
        shuf = [{"sp": r["sp"], "y": r["y"], "w": r["w"], "vec": dict(r["vec"])}
                for r in rows]
        if factor == "W":
            subs = [tuple(r["vec"][k] for k in WEATHER_FACTOR_NAMES) for r in rows]
            rnd.shuffle(subs)
            for j, srow in enumerate(shuf):
                for k, kk in enumerate(WEATHER_FACTOR_NAMES):
                    srow["vec"][kk] = subs[j][k]
        else:
            vals = [r["vec"][factor] for r in rows]
            rnd.shuffle(vals)
            for j, srow in enumerate(shuf):
                srow["vec"][factor] = vals[j]
        return shuf

    base = _auc_of_rows(rows, weights)
    out = {}
    for factor in TOP_FACTORS:
        a = _auc_of_rows(shuffled_rows(factor), weights)
        out[factor] = {
            "auc_baseline": round(base, 4) if base is not None else None,
            "auc_permuted": round(a, 4) if a is not None else None,
            "drop": round(base - a, 4) if base is not None and a is not None else None,
        }
    return base, out


def _weight_candidates():
    """A small simplex grid of weather-weight vectors around the hand weights."""
    base = list(CURRENT_WEATHER_WEIGHTS)
    deltas = (-0.10, -0.05, 0.0, 0.05, 0.10)
    out = set()
    for d0 in deltas:
        for d1 in deltas:
            for d2 in deltas:
                for d3 in deltas:
                    w4 = [base[0] + d0, base[1] + d1, base[2] + d2, base[3] + d3]
                    w5 = 1.0 - sum(w4)
                    if all(0.0 <= x <= 1.0 for x in w4) and 0.0 <= w5 <= 1.0:
                        out.add(tuple(round(x, 4) for x in (w4[0], w4[1], w4[2],
                                                            w4[3], w5)))
    return sorted(out)


def bootstrap_gain_ci(rows, w1, w2, n=BOOTSTRAP_N, seed=BOOTSTRAP_SEED):
    """Bootstrap 95% CI of AUC(w2) − AUC(w1) on `rows`."""
    rnd = random.Random(seed)
    n_rows = len(rows)
    gains = []
    for _ in range(n):
        samp = [rows[rnd.randrange(n_rows)] for _ in range(n_rows)]
        a1, a2 = _auc_of_rows(samp, w1), _auc_of_rows(samp, w2)
        if a1 is not None and a2 is not None:
            gains.append(a2 - a1)
    if not gains:
        return None, None
    gains.sort()
    lo = gains[max(0, int(0.025 * (len(gains) - 1)))]
    hi = gains[min(len(gains) - 1, int(0.975 * (len(gains) - 1)))]
    return round(lo, 4), round(hi, 4)


def refit_weather_weights(rows):
    """Refit the shared weather weights on a held-out split of the pooled rows.

    Searches the candidate grid on the train side, evaluates on the test side,
    and ships only a stable held-out gain (positive gain, bootstrap CI > 0).
    """
    rnd = random.Random(WEIGHT_HOLDOUT_SEED)
    idx = list(range(len(rows)))
    rnd.shuffle(idx)
    k = int(len(rows) * WEIGHT_HOLDOUT_FRAC)
    test = [rows[i] for i in idx[:k]]
    train = [rows[i] for i in idx[k:]]

    current = tuple(CURRENT_WEATHER_WEIGHTS)
    best_w, best_train = current, _auc_of_rows(train, current)
    for w in _weight_candidates():
        a = _auc_of_rows(train, w)
        if a is not None and (best_train is None or a > best_train):
            best_train, best_w = a, w

    auc_current = _auc_of_rows(test, current)
    auc_refit = _auc_of_rows(test, best_w)
    gain = (auc_refit - auc_current) if (auc_current is not None
                                         and auc_refit is not None) else None
    lo, hi = bootstrap_gain_ci(test, current, best_w)
    ship = bool(gain is not None and lo is not None and gain > 0 and lo > 0)

    if ship:
        rationale = ("stable held-out gain (positive, bootstrap CI entirely "
                     "above zero) — candidate weights justified out-of-sample.")
    elif gain is None or lo is None:
        rationale = ("insufficient pooled data for a stable estimate — keep the "
                     "hand weights (honest default: no change).")
    else:
        rationale = ("no stable held-out gain over the hand weights — keep the "
                     "hand weights (honest default: no change).")

    return {
        "method": ("grid search over the five weather weights (±0.10, ±0.05 "
                   "steps) maximising weighted AUC on a held-out train side; "
                   "evaluated on the held-out test side with a bootstrap 95 % CI"),
        "holdout": {"frac": WEIGHT_HOLDOUT_FRAC, "seed": WEIGHT_HOLDOUT_SEED,
                    "n_train": len(train), "n_test": len(test)},
        "current_weights": {k: round(v, 4) for k, v in zip(WEATHER_FACTOR_NAMES,
                                                           CURRENT_WEATHER_WEIGHTS)},
        "best_weights": {k: round(v, 4) for k, v in zip(WEATHER_FACTOR_NAMES,
                                                        best_w)},
        "heldout_auc_current": round(auc_current, 4) if auc_current is not None else None,
        "heldout_auc_refit": round(auc_refit, 4) if auc_refit is not None else None,
        "gain": round(gain, 4) if gain is not None else None,
        "bootstrap_ci": [lo, hi],
        "decision": "ship" if ship else "no_change",
        "rationale": rationale,
    }


def temporal_habitat_auc(forecast, zones, occurrences):
    """Validate the time-invariant habitat signal (H × M × altitude) on a real
    temporal split, pooled across species.

    Presence and target-group background points are split by year at
    `choose_split_year`; the habitat AUC is then reported **separately** for the
    older (train) and newer (test) side, so the number is an out-of-era check
    rather than a fit on the same records. The only thing "learned" on the train
    side is a score threshold — its transfer is reported as the fraction of test
    presences above the 95th percentile of the train background (≈5 % train
    false-positive rate). Weather (W) and phenology (P) are current-day values
    and are excluded from both sides.
    """
    lookup = factor_lookup(forecast)
    years = [occurrence_year(m) for pts in occurrences.values()
             for _, _, m in pts]
    split_year = choose_split_year(years)
    if split_year is None:
        return {"split_year": None, "note": "insufficient dated occurrences"}

    pool = dedupe([(lat, lon, meta) for pts in occurrences.values()
                   for lat, lon, meta in pts])
    pool_xy = [p[:2] for p in pool]

    def hscore(lat, lon, sp_id):
        vec = point_factors(lat, lon, sp_id, zones, lookup)
        if vec is None:
            return None
        h = _pct(vec["H"]) / 100.0
        m = _pct(vec["M"]) / 100.0
        alt = _pct(vec["altitud"]) / 100.0
        return h * m * alt * 100.0

    pos_tr, pos_te, wpos_tr, wpos_te = [], [], [], []
    bg_tr, bg_te, wbg_tr, wbg_te = [], [], [], []
    for sp_id, pts in occurrences.items():
        train, test = split_by_year(pts, split_year)
        for lat, lon, _meta in train:
            s = hscore(lat, lon, sp_id)
            if s is not None:
                pos_tr.append(s)
                wpos_tr.append(effort_weights(pool_xy, [(lat, lon)])[0])
        for lat, lon, _meta in test:
            s = hscore(lat, lon, sp_id)
            if s is not None:
                pos_te.append(s)
                wpos_te.append(effort_weights(pool_xy, [(lat, lon)])[0])
        for lat, lon, meta, w in target_group_background(
                pts, pool, BG_PER_SPECIES, _sp_seed(sp_id)):
            s = hscore(lat, lon, sp_id)
            if s is None:
                continue
            y = occurrence_year(meta)
            if y is None:
                continue
            if y < split_year:
                bg_tr.append(s)
                wbg_tr.append(w)
            else:
                bg_te.append(s)
                wbg_te.append(w)

    auc_tr = weighted_auc(pos_tr, bg_tr, wpos_tr, wbg_tr)
    auc_te = weighted_auc(pos_te, bg_te, wpos_te, wbg_te)
    auc_pool = weighted_auc(pos_tr + pos_te, bg_tr + bg_te,
                            wpos_tr + wpos_te, wbg_tr + wbg_te)
    recall_te = None
    if bg_tr and pos_te:
        ordered = sorted(bg_tr)
        thr = ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]
        recall_te = sum(1 for s in pos_te if s > thr) / len(pos_te)

    return {
        "split_year": split_year,
        "n_dated_occurrences": len([y for y in years if y is not None]),
        "n_presence": len(pos_tr) + len(pos_te),
        "n_background": len(bg_tr) + len(bg_te),
        "n_presence_train": len(pos_tr),
        "n_presence_test": len(pos_te),
        "n_background_train": len(bg_tr),
        "n_background_test": len(bg_te),
        "habitat_auc": round(auc_pool, 4) if auc_pool is not None else None,
        "habitat_auc_train": round(auc_tr, 4) if auc_tr is not None else None,
        "habitat_auc_test": round(auc_te, 4) if auc_te is not None else None,
        "transfer_recall_at_5pct_train_fpr":
            round(recall_te, 4) if recall_te is not None else None,
        "note": ("time-invariant habitat signal (H × M × altitude) only, evaluated "
                 "separately on the older (train) and newer (test) sides; W and P "
                 "are current-day values and cannot be temporally split"),
    }


def run_backtest(forecast, zones, occurrences):
    """Phase 7.5: validate the hand weights and multipliers; return a report block."""
    try:
        rows = build_pooled(forecast, zones, occurrences)
    except Exception as e:
        return {"error": str(e)}

    if not rows:
        return {"error": "no pooled factor rows (forecast or occurrence data missing)"}

    base_auc, importances = permutation_importance(rows, tuple(CURRENT_WEATHER_WEIGHTS))
    refit = refit_weather_weights(rows)
    temporal = temporal_habitat_auc(forecast, zones, occurrences)

    return {
        "version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_pooled_rows": len(rows),
        "n_presence": sum(1 for r in rows if r["y"] == 1),
        "n_background": sum(1 for r in rows if r["y"] == 0),
        "background_method": (
            "target-group background (background sampled from the pooled "
            "occurrence set of all species, excluding the focal species) with "
            "recorder-effort weighting w = 1 / (1 + neighbours within %.0f km)" %
            EFFORT_RADIUS_KM),
        "auc_baseline": round(base_auc, 4) if base_auc is not None else None,
        "factor_importances": importances,
        "weight_refit": refit,
        "temporal_validation": temporal,
        "caveats": [
            "Presence-only data has no true absences; the AUC is rank "
            "discrimination against target-group background, not a calibrated "
            "probability.",
            "Occurrences are scored with the model's *current* (seasonal, "
            "weather-based) forecast, so W and P cannot be temporally split — "
            "only the time-invariant habitat factors (H, M, altitude) are.",
            "The weight refit isolates the five hand weights on the raw weather "
            "sub-scores; it does not include the Phase 4.3 drought/recharge "
            "modifier (which lives inside the stored W).",
            "No score weights are changed unless the report decision is 'ship' "
            "with a stable held-out gain; the default is 'no_change'.",
        ],
    }


# ── Pipeline ───────────────────────────────────────────────────────────────────

def self_test():
    """Offline checks of the metric math."""
    # AUC: perfect separation → 1.0, reversed → 0.0, overlap → in between
    assert auc([90, 80, 70], [10, 20, 30]) == 1.0, "auc perfect"
    assert auc([10, 20, 30], [90, 80, 70]) == 0.0, "auc reversed"
    mid = auc([60, 70, 80], [40, 50, 60])
    assert 0.5 < mid < 1.0, "auc mid"
    # ties count 0.5
    assert auc([50], [50]) == 0.5, "auc tie"
    assert auc([], [1, 2]) is None and auc([1], []) is None, "auc empty"

    # Brier: perfect → 0, always wrong → 1
    assert brier([1, 0], [1.0, 0.0]) == 0.0, "brier perfect"
    assert brier([1, 0], [0.0, 1.0]) == 1.0, "brier wrong"
    assert brier([], []) is None, "brier empty"

    # calibration curve: bins partition the data, found-rate == mean
    curve = calibration_curve([1, 1, 0, 0], [95, 55, 35, 5], n_bins=10)
    assert len(curve) == 4, "curve bins"
    assert sum(c["n"] for c in curve) == 4, "curve total"

    # held-out split is deterministic and disjoint
    rows = list(range(100))
    tr, te = heldout_split(rows)
    assert len(te) == 30 and len(tr) == 70, "split sizes"
    assert set(tr).isdisjoint(te), "split disjoint"
    tr2, te2 = heldout_split(rows)
    assert tr == tr2 and te == te2, "split deterministic"

    # ── Phase 7.5 checks ────────────────────────────────────────────────────────
    # weighted_auc: equal weights reduce to auc()
    assert weighted_auc([90, 80, 70], [10, 20, 30]) == 1.0, "weighted_auc perfect"
    assert weighted_auc([50], [50]) == 0.5, "weighted_auc tie"
    assert weighted_auc([], [1]) is None, "weighted_auc empty"
    assert weighted_auc([10, 20, 30], [90, 80, 70]) == 0.0, "weighted_auc reversed"

    # occurrence_year: int and ISO string
    assert occurrence_year(2019) == 2019, "occurrence_year int"
    assert occurrence_year("2021-09-30T10:00:00Z") == 2021, "occurrence_year str"
    assert occurrence_year(None) is None and occurrence_year("bad") is None, \
        "occurrence_year none"

    # choose_split_year / split_by_year
    years = [2000] * 8 + [2020] * 8
    assert choose_split_year(years, min_side=8) == 2020, "choose_split_year"
    assert choose_split_year([2000] * 5, min_side=8) is None, "split too small"
    pts = [(42.0, 2.0, 2000), (42.1, 2.1, 2020), (42.2, 2.2, None)]
    tr, te = split_by_year(pts, 2010)
    assert len(tr) == 1 and len(te) == 1, "split_by_year drops undated"

    # effort_weights: clustered points get down-weighted
    w_solo = effort_weights([(42.0, 2.0), (42.5, 2.5)], [(42.0, 2.0)])[0]
    w_clust = effort_weights([(42.0, 2.0), (42.0, 2.001), (42.0, 2.002),
                              (42.5, 2.5)], [(42.0, 2.0)])[0]
    assert w_clust < w_solo, "effort_weights down-weights clusters"

    # target_group_background excludes the focal species' own coordinates
    focal = [(42.0, 2.0, 2020)]
    pool = [(42.0, 2.0, 2020), (41.9, 1.9, 2021), (41.8, 1.8, 2021)]
    bg = target_group_background(focal, pool, 10, seed=1)
    assert bg and all(_round_key(lat, lon) != (42.0, 2.0) for lat, lon, _y, _w in bg), \
        "target_group_background excludes focal"

    # factor_lookup / point_factors / score_from_factors on a synthetic forecast
    zz = [{"id": "z1", "name": "z", "lat": 42.0, "lon": 2.0, "comarca": "C"}]
    fc = {"comarques": {"C": [{"zones": [{
        "id": "z1",
        "species": [{
            "id": "rovelló", "score": 60,
            "factors": {"W": 57, "H": {"score": 80}, "M": {"score": 90}, "P": 100},
            "breakdown": {"pluja": 60, "temperatura": 50, "vent": 40,
                          "altitud": 70, "humitat": 80},
        }, {
            "id": "camagroc", "score": 60,
            "factors": {"W": 57, "H": {"score": 80}, "M": {"score": 90}, "P": 100},
            "breakdown": {"pluja": 60, "temperatura": 50, "vent": 40,
                          "altitud": 70, "humitat": 80},
        }],
    }]}]}}
    lk = factor_lookup(fc)
    assert lk["z1"]["rovelló"]["W"] == 57, "factor_lookup W"
    assert lk["z1"]["rovelló"]["pluja"] == 60.0, "factor_lookup sub-factor"
    vec = point_factors(42.0, 2.0, "rovelló", zz, lk)
    assert vec is not None and vec["H"] == 80, "point_factors"
    assert point_factors(45.0, 3.0, "rovelló", zz, lk) is None, "point_factors ooc"
    # hand weights reproduce W from the raw sub-factors (no sequera here)
    w_hand = (0.35, 0.25, 0.20, 0.10, 0.10)
    assert abs(score_from_factors(vec, w_hand)
               - (0.35 * 60 + 0.25 * 50 + 0.20 * 40 + 0.10 * 70 + 0.10 * 80)
               * 0.80 * 0.90 * 1.00) < 1e-6, "score_from_factors formula"

    # _weight_candidates sums to 1 and includes the hand weights
    cands = _weight_candidates()
    assert all(abs(sum(c) - 1.0) < 1e-9 for c in cands), "weight candidates sum"
    assert tuple(round(x, 4) for x in w_hand) in cands, "hand weights included"

    # refit: a noisy single-signal dataset improves on the hand weights
    def _syn_rows(n=160):
        rnd = random.Random(42)
        rows = []
        for _ in range(n):
            v = {"pluja": 70.0 + rnd.gauss(0, 10), "temperatura": rnd.gauss(50, 20),
                 "vent": rnd.gauss(50, 20), "altitud": rnd.gauss(50, 20),
                 "humitat": rnd.gauss(50, 20), "W": None, "H": 100.0,
                 "M": 100.0, "P": 100.0}
            rows.append({"sp": "s", "y": 1, "w": 1.0, "vec": dict(v)})
            v0 = dict(v, pluja=30.0 + rnd.gauss(0, 10))
            rows.append({"sp": "s", "y": 0, "w": 1.0, "vec": v0})
        return rows
    refit = refit_weather_weights(_syn_rows())
    assert refit["decision"] in ("ship", "no_change"), "refit decision"
    assert refit["heldout_auc_refit"] > refit["heldout_auc_current"], \
        "refit improves on a noisy single signal"
    assert len(refit["bootstrap_ci"]) == 2, "refit CI"

    # permutation_importance returns one entry per top factor
    base_a, imp = permutation_importance(_syn_rows(40), w_hand)
    assert set(imp.keys()) == set(TOP_FACTORS), "permutation factors"
    assert all("drop" in imp[k] for k in TOP_FACTORS), "permutation drops"

    # temporal_habitat_auc: the two eras are evaluated separately (no pooling
    # of train+test into one side); background comes from the other species.
    occ = {
        "rovelló": [(42.0, 2.0, 2000)] * 10 + [(42.0, 2.0, 2020)] * 10,
        "camagroc": [(42.01, 2.01, 2000)] * 10 + [(42.02, 2.02, 2020)] * 10,
    }
    tv = temporal_habitat_auc(fc, zz, occ)
    assert tv["split_year"] == 2020, tv
    assert tv["n_presence_train"] == 20 and tv["n_presence_test"] == 20, tv
    assert tv["n_background_train"] >= 1 and tv["n_background_test"] >= 1, tv
    assert tv["habitat_auc_train"] is not None, tv
    assert tv["habitat_auc_test"] is not None, tv
    assert "transfer_recall_at_5pct_train_fpr" in tv, tv

    print("self-test OK: auc, brier, calibration_curve, heldout_split + "
          "phase 7.5 (weighted_auc, temporal split, effort weights, "
          "target-group background, factor lookup, weight refit, permutation)")


def run_pipeline():
    zones = load_zones()
    report = {
        "version": REPORT_VERSION,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": date.today().isoformat(),
        "methodology": (
            "Field reports (found/not-found vs score_at_time) → AUC/Brier/"
            "calibration curve on a held-out split. GBIF + iNaturalist "
            "occurrences (presence-only, deduped) vs random Catalonia "
            "background points → per-species AUC of the model's current score, "
            "each point scored by its nearest curated zone (≤ %.0f km). "
            "No recalibration is applied — the numbers are descriptive/"
            "validation, to avoid overfitting a tiny sample." % MAX_ZONE_KM
        ),
        "field_reports": {},
        "occurrence_auc": {},
        "caveats": [
            "Occurrence data is presence-only: no true absences, so the "
            "occurrence AUC is rank-discrimination against random background, "
            "not a calibrated probability.",
            "Occurrence AUC uses the model's current (seasonal, weather-based) "
            "score; historical occurrences cannot be scored with historical "
            "weather, so the discrimination is confounded by the present "
            "season.",
            "Both presence and background points are scored via their nearest "
            "zone, so the metric is at the model's zone resolution.",
            "The field-report sample is the only true binary calibration "
            "signal; until enough reports accumulate, no score recalibration "
            "is justified (avoid overfitting).",
        ],
    }

    # 1) Field reports
    labels = reports_labels()
    n = len(labels)
    report["field_reports"] = {
        "n": n,
        "n_found": sum(1 for y, _ in labels if y == 1),
        "n_not_found": sum(1 for y, _ in labels if y == 0),
    }
    if n >= 20:
        train, test = heldout_split(labels)
        y_test = [y for y, _ in test]
        s_test = [s for _, s in test]
        p_test = [s / 99.0 for s in s_test]
        y_all = [y for y, _ in labels]
        s_all = [s for _, s in labels]
        pos_test = [s for y, s in test if y == 1]
        neg_test = [s for y, s in test if y == 0]
        report["field_reports"]["heldout"] = {
            "n_train": len(train), "n_test": len(test),
            "auc": round(auc(pos_test, neg_test), 3)
            if pos_test and neg_test else None,
            "brier": round(brier(y_test, p_test), 3) if p_test else None,
        }
        report["field_reports"]["calibration_curve"] = calibration_curve(y_all, s_all)
    else:
        report["field_reports"]["heldout"] = None
        report["field_reports"]["calibration_curve"] = []
        report["field_reports"]["note"] = (
            "insufficient data (%d reports) — no recalibration applied" % n)

    # 2) Occurrence discrimination
    try:
        forecast = app.build_forecast()
    except Exception as e:  # network/rate-limit
        forecast = None
        report["forecast_error"] = str(e)

    sp_defs = {s["id"]: s for s in app.SPECIES_LIST}
    occurrences = {}
    if forecast is not None:
        lookup = score_lookup(forecast)
        bg_ids = background_points(zones)
        for sp_id, sp in sp_defs.items():
            name = sp["scientific_name"]
            try:
                key, status, _ = gbif_usage_key(name)
                gbif_pts = gbif_occurrences(key) if key else []
            except Exception as e:
                gbif_pts = []
                status = f"gbif error: {e}"
            inat_pts = []
            try:
                tid = inat_taxon_id(name)
                if tid:
                    inat_pts = inat_occurrences(tid)
            except Exception as e:
                pass
            pts = dedupe(gbif_pts + inat_pts)
            occurrences[sp_id] = pts

            presence_scores = []
            for lat, lon, _meta in pts:
                z, d = nearest_zone(lat, lon, zones)
                if z is None or d > MAX_ZONE_KM:
                    continue
                sp_map = lookup.get(z["id"])
                if sp_map and sp_map.get(sp_id) is not None:
                    presence_scores.append(sp_map[sp_id])

            background_scores = []
            for zid in bg_ids:
                sp_map = lookup.get(zid)
                if sp_map and sp_map.get(sp_id) is not None:
                    background_scores.append(sp_map[sp_id])

            a = auc(presence_scores, background_scores)
            report["occurrence_auc"][sp_id] = {
                "scientific_name": name,
                "auc": round(a, 3) if a is not None else None,
                "n_presence": len(presence_scores),
                "n_occurrences_raw": len(pts),
                "n_background": len(background_scores),
                "gbif_status": status,
            }
            print(f"  {sp_id}: occurrences={len(pts)} in_coverage={len(presence_scores)} "
                  f"auc={report['occurrence_auc'][sp_id]['auc']}")

    # 3) Phase 7.5 backtest: validate the hand weights and multipliers.
    if forecast is not None:
        report["backtest_7_5"] = run_backtest(forecast, zones, occurrences)
        print(f"\nbacktest_7_5: {report['backtest_7_5'].get('n_pooled_rows')} pooled rows; "
              f"weight_refit decision = "
              f"{report['backtest_7_5'].get('weight_refit', {}).get('decision')}")
    else:
        report["backtest_7_5"] = {"error": "no forecast (network/rate-limit)"}

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {REPORT_FILE}")
    return report


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        run_pipeline()
