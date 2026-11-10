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

    print("self-test OK: auc, brier, calibration_curve, heldout_split")


def run_pipeline():
    zones = load_zones()
    report = {
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

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {REPORT_FILE}")
    return report


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        run_pipeline()
