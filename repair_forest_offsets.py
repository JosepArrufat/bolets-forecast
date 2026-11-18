#!/usr/bin/env python3
"""Forest-offset gate and repair (Phase 7.1).

Every station in ``mushrooms.json`` is a forest point: the coordinates drive the
station's IGME/CORINE sample (habitat, soil, canopy) and, for stations without
zones, its score.  This tool re-gates all of them against CORINE CLC 2018 and
only moves a point when the replacement centroid lands in a forest class
(311/312/313/324).  A point that cannot be repaired is flagged for human review
and left untouched.

Policy (Phase 7.1 risk note):
  * read-only by default; ``--apply`` is required to write ``mushrooms.json``,
  * a move is written only after the candidate passes the same forest gate,
  * the previous coordinates, date and reason are kept on the station
    (``forest_offset_history``) *and* in the report file,
  * altitude is never changed silently: the candidate's DEM altitude is
    recorded for review, ``alt_m`` is left as curated.

Usage::

    python3 repair_forest_offsets.py                # gate report (no writes)
    python3 repair_forest_offsets.py --check-zones  # also re-gate all zones
    python3 repair_forest_offsets.py --apply        # apply passing moves

Sources: CORINE CLC 2018 WMS (forest class), ICGC 5m LiDAR DEM (candidate
altitude, only for a candidate that needs review).
"""

import json
import math
import os
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MUSHROOMS_FILE = os.path.join(BASE_DIR, "mushrooms.json")
ZONES_FILE = os.path.join(BASE_DIR, "zones.json")
REPORT_FILE = os.path.join(BASE_DIR, "forest_offset_report.json")

FOREST_CODES = ("311", "312", "313", "324")
FOREST_CLASS = {
    "311": "broadleaf",
    "312": "conifer",
    "313": "mixed",
    "324": "shrub",
}
CORINE_SOURCE = "CORINE CLC 2018 WMS (forest classes 311/312/313/324)"
DEM_SOURCE = "ICGC 5m LiDAR DEM (2021-2023)"

# Candidate search: rings are >=500 m from the original point (the Phase 6.2
# spacing rule), so a "repair" cannot simply nudge a point by a few metres.
CANDIDATE_RINGS_M = (600, 1000, 1500)
EARTH_R_M = 6371000.0


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _distance_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(min(1.0, math.sqrt(a)))


def _offset(lat, lon, dn_m, de_m):
    m = 111320.0
    return (lat + dn_m / m,
            lon + de_m / (m * math.cos(math.radians(lat))))


def _expected_class(zones, station_name):
    """Majority curated forest type for the station's zones, or None."""
    counts = {}
    for zone in zones.get(station_name, []):
        ftype = str((zone.get("forest") or {}).get("type") or "").lower()
        if ftype in ("conifer", "coniferous"):
            counts["conifer"] = counts.get("conifer", 0) + 1
        elif ftype in ("broadleaf", "frondós", "frondos"):
            counts["broadleaf"] = counts.get("broadleaf", 0) + 1
        elif ftype in ("mixed", "mixt"):
            counts["mixed"] = counts.get("mixed", 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


# ── Live sources ──────────────────────────────────────────────────────────────

def _corine_live(lat, lon):
    """CORINE CLC 2018 forest code via the app's existing WMS query."""
    import app  # imported lazily so --self-test never touches the network
    return app.fetch_corine(lat, lon)


def _dem_live(lat, lon):
    """ICGC 5m LiDAR DEM elevation, reusing the Phase 3 implementation."""
    import enrich_zones
    return enrich_zones._dem_elevation(lat, lon)


# ── Gate and candidate search ─────────────────────────────────────────────────

def find_candidate(lat, lon, expected_class, corine_fetch):
    """Nearest forest cell in the candidate rings, preferring the curated class.

    Returns ``None`` when no ring cell passes the CORINE forest gate.  The
    caller decides whether to apply it; this function never writes anything.
    """
    fallback = None
    for ring in CANDIDATE_RINGS_M:
        matches = []
        for i in range(8):
            angle = math.radians(i * 45.0)
            clat, clon = _offset(lat, lon, math.cos(angle) * ring,
                                 math.sin(angle) * ring)
            code, label = corine_fetch(clat, clon)
            if code not in FOREST_CODES:
                continue
            cand = {
                "lat": round(clat, 6),
                "lon": round(clon, 6),
                "forest_code": code,
                "forest_label": label,
                "forest_class": FOREST_CLASS.get(code),
                "class_match": (expected_class is None or
                                FOREST_CLASS.get(code) == expected_class),
                "offset_m": round(_distance_m(lat, lon, clat, clon)),
            }
            matches.append(cand)
            if cand["class_match"]:
                return cand
        if matches and fallback is None:
            # Keep the nearest forest cell even if it changes forest class; it
            # is reported with class_match=false and needs human review before
            # --apply would accept it.
            fallback = matches[0]
    return fallback


def gate_stations(data, zones, corine_fetch=None, dem_fetch=None):
    """Gate every station forest point. Returns a report body (no file writes)."""
    corine_fetch = corine_fetch or _corine_live
    dem_fetch = dem_fetch or _dem_live
    rows = []
    total = 0
    for comarca, stations in data.get("target_stations", {}).items():
        for station in stations:
            total += 1
            name = station.get("name", "?")
            lat, lon = station.get("lat"), station.get("lon")
            code, label = corine_fetch(lat, lon)
            row = {
                "name": name,
                "comarca": comarca,
                "old": {"lat": lat, "lon": lon, "alt_m": station.get("alt_m")},
                "gate_code": code,
                "gate_label": label,
                "zone_count": len(zones.get(name, [])),
            }
            if code in FOREST_CODES:
                row["status"] = "pass"
                row["forest_class_match"] = (
                    _expected_class(zones, name) in (None,
                                                     FOREST_CLASS.get(code)))
                print(f"{name:<34} {code:<4} pass", flush=True)
            else:
                expected = _expected_class(zones, name)
                cand = find_candidate(lat, lon, expected, corine_fetch)
                if cand is None:
                    row["status"] = "needs_review"
                    row["reason"] = "no forest cell found within 1.5 km"
                    print(f"{name:<34} {code:<4} NO CANDIDATE", flush=True)
                else:
                    cand["dem_alt_m"] = dem_fetch(cand["lat"], cand["lon"])
                    cand["expected_class"] = expected
                    cand["alt_m_unchanged"] = station.get("alt_m")
                    row["candidate"] = cand
                    row["status"] = ("candidate" if cand["class_match"]
                                     else "needs_review")
                    if not cand["class_match"]:
                        row["reason"] = ("nearest forest cell changes the "
                                         "curated forest class")
                    print(f"{name:<34} {code:<4} "
                          f"{row['status']} → {cand['lat']},{cand['lon']} "
                          f"({cand['forest_code']}, {cand['offset_m']} m)",
                          flush=True)
            rows.append(row)
    return rows, total


def gate_zones(zones, corine_fetch=None):
    """Cross-check every curated zone centroid against CORINE."""
    corine_fetch = corine_fetch or _corine_live
    checked = forest = 0
    mismatches = []
    for station_name, zlist in zones.items():
        for zone in zlist:
            checked += 1
            code, label = corine_fetch(zone["lat"], zone["lon"])
            expected = str((zone.get("forest") or {}).get("type") or "")
            expected = {"conifer": "conifer", "broadleaf": "broadleaf",
                        "mixed": "mixed"}.get(expected)
            got = FOREST_CLASS.get(code)
            ok = code in FOREST_CODES and (expected is None or expected == got)
            if code in FOREST_CODES:
                forest += 1
            if not ok:
                mismatches.append({
                    "station": station_name,
                    "zone_id": zone.get("id"),
                    "code": code,
                    "expected": expected,
                    "got": got,
                })
            print(f"zone {zone.get('id', '?'):<40} {code:<4} "
                  f"{'ok' if ok else 'MISMATCH'}", flush=True)
    return {
        "source": CORINE_SOURCE,
        "checked": checked,
        "forest": forest,
        "mismatches": mismatches,
    }


def apply_moves(data, rows, apply=False):
    """Apply gate-passing candidate moves; keep the previous coordinates."""
    changes = []
    by_name = {}
    for comarca, stations in data.get("target_stations", {}).items():
        for station in stations:
            by_name[station.get("name")] = station
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for row in rows:
        cand = row.get("candidate")
        if row.get("status") != "candidate" or cand is None:
            continue
        change = {
            "name": row["name"],
            "comarca": row["comarca"],
            "old": row["old"],
            "new": {"lat": cand["lat"], "lon": cand["lon"]},
            "forest_code": cand["forest_code"],
            "forest_label": cand["forest_label"],
            "offset_m": cand["offset_m"],
            "dem_alt_m": cand.get("dem_alt_m"),
            "applied": bool(apply),
        }
        if apply:
            station = by_name[row["name"]]
            station.setdefault("forest_offset_history", []).append({
                "date": stamp,
                "step": "7.1",
                "old_lat": row["old"]["lat"],
                "old_lon": row["old"]["lon"],
                "new_lat": cand["lat"],
                "new_lon": cand["lon"],
                "reason": (f"CORINE CLC 2018 forest gate: "
                           f"{cand['forest_code']} {cand['forest_label']}; "
                           f"previous point was {row['gate_code']} "
                           f"{row['gate_label']}"),
                "source": CORINE_SOURCE,
            })
            station["lat"] = cand["lat"]
            station["lon"] = cand["lon"]
        changes.append(change)
    return changes


def build_report(rows, total, zones, zones_report=None):
    passed = sum(1 for r in rows if r["status"] == "pass")
    candidates = sum(1 for r in rows if r["status"] == "candidate")
    review = sum(1 for r in rows if r["status"] == "needs_review")
    return {
        "step": "7.1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate": {"source": CORINE_SOURCE, "forest_codes": list(FOREST_CODES)},
        "candidate_source": DEM_SOURCE,
        "stations_checked": total,
        "passed": passed,
        "candidates": candidates,
        "needs_review": review,
        "stations": rows,
        "zone_gate": zones_report,
        "changes": [],
    }


# ── Offline self-test ─────────────────────────────────────────────────────────

def _self_test():
    data = {
        "target_stations": {
            "Comarca A": [
                {"name": "Pass", "lat": 42.0, "lon": 1.0, "alt_m": 1000},
                {"name": "Repair", "lat": 42.1, "lon": 1.1, "alt_m": 1200},
                {"name": "NoFix", "lat": 42.2, "lon": 1.2, "alt_m": 800},
            ]
        }
    }
    zones = {
        "Pass": [{"id": "p1", "lat": 42.0, "lon": 1.0,
                  "forest": {"type": "conifer"}}],
        "Repair": [{"id": "r1", "lat": 42.1, "lon": 1.1,
                    "forest": {"type": "broadleaf"}}],
        "NoFix": [],
    }

    def at(lat, lon, plat, plon):
        return abs(lat - plat) < 1e-9 and abs(lon - plon) < 1e-9

    def fake_corine(lat, lon):
        if at(lat, lon, 42.1, 1.1):
            return ("321", "Natural grasslands")
        if at(lat, lon, 42.2, 1.2):
            return ("211", "Arable land")
        if at(lat, lon, 42.0, 1.0):
            return ("312", "Coniferous forest")
        # Every candidate ring around "Repair" is broadleaf forest.
        if abs(lat - 42.1) < 0.04 and abs(lon - 1.1) < 0.04:
            return ("311", "Broadleaf forest")
        return ("332", "Bare rock")

    rows, total = gate_stations(data, zones, fake_corine, lambda a, b: 1210.0)
    assert total == 3, total
    by = {r["name"]: r for r in rows}
    assert by["Pass"]["status"] == "pass"
    assert by["Repair"]["status"] == "candidate"
    assert by["Repair"]["candidate"]["forest_code"] == "311"
    assert by["Repair"]["candidate"]["class_match"] is True
    assert by["Repair"]["candidate"]["offset_m"] >= 500
    assert by["NoFix"]["status"] == "needs_review"

    # Dry run: no station is touched.
    changes = apply_moves(data, rows, apply=False)
    assert len(changes) == 1 and changes[0]["applied"] is False
    assert data["target_stations"]["Comarca A"][1]["lat"] == 42.1
    assert "forest_offset_history" not in data["target_stations"]["Comarca A"][1]

    # Apply: the passing candidate moves, the previous point stays on record.
    changes = apply_moves(data, rows, apply=True)
    moved = data["target_stations"]["Comarca A"][1]
    assert changes[0]["applied"] is True
    assert (moved["lat"], moved["lon"]) != (42.1, 1.1)
    hist = moved["forest_offset_history"][0]
    assert (hist["old_lat"], hist["old_lon"]) == (42.1, 1.1)
    assert moved["alt_m"] == 1200  # altitude is never rewritten silently
    assert data["target_stations"]["Comarca A"][2]["lat"] == 42.2

    report = build_report(rows, total, zones)
    assert report["stations_checked"] == 3
    assert report["passed"] == 1
    assert report["candidates"] == 1
    assert report["needs_review"] == 1
    print("self-test: OK (gate, candidate, dry-run, apply, history, report)")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv):
    if "--self-test" in argv:
        return 0 if _self_test() else 1

    apply = "--apply" in argv
    check_zones = "--check-zones" in argv

    with open(MUSHROOMS_FILE) as f:
        data = json.load(f)
    try:
        with open(ZONES_FILE) as f:
            zones = json.load(f).get("zones", {})
    except Exception:
        zones = {}

    rows, total = gate_stations(data, zones)
    report = build_report(rows, total, zones)
    if check_zones:
        report["zone_gate"] = gate_zones(zones)
    else:
        # A plain read-only run must not erase the last zone gate: the confidence
        # derivation (step 7.3) uses it, and zone centroids are unaffected by a
        # station re-gate. `--check-zones` refreshes it; the consumer validates
        # the zone count before trusting it.
        try:
            with open(REPORT_FILE) as f:
                previous = json.load(f)
            if previous.get("zone_gate"):
                report["zone_gate"] = previous["zone_gate"]
        except (OSError, ValueError):
            pass

    changes = apply_moves(data, rows, apply=apply)
    report["changes"] = changes
    report["applied"] = bool(apply and changes)

    if apply and changes:
        with open(MUSHROOMS_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n{total} stations · {report['passed']} pass · "
          f"{report['candidates']} candidate · "
          f"{report['needs_review']} needs review · "
          f"{len(changes)} move(s) {'applied' if apply else 'not applied'}")
    if report.get("zone_gate"):
        zg = report["zone_gate"]
        print(f"zones: {zg['checked']} checked · {zg['forest']} forest · "
              f"{len(zg['mismatches'])} mismatch")
    print(f"report: {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
