#!/usr/bin/env python3
"""Phase 7.3 — confidence that discriminates.

The curated `confidence` in `zones.json` used to be a constant `0.6` ("medium")
on all 135 zones, so the diagnosis could not rank one stand above another and
the `C` factor in the explainer was inert. This script derives a per-zone
confidence from evidence that already exists, without inventing anything:

- how many independent source labels the zone records,
- whether SoilGrids v2 returned a pH,
- the resolution of the soil layer (`1:25k` / MAGNA 50 `1:50k` / IGME `1:1M`),
  read from `zones_enriched.json` so steps 7.4/7.6 raise the value when they
  land,
- whether the soil class is known (`calcareous`/`siliceous`) or `mixed`,
- the habitat resolution (CHC50 `1:25k` vs CORINE `100 m`),
- the DEM resolution actually used (ICGC 5 m LiDAR vs Copernicus ~90 m),
- the LiDAR canopy sample coverage,
- whether the 7.1 CORINE forest gate passed for the zone,
- whether access facts are present (`drive_min` + `difficulty`); a trailhead
  name adds evidence but its absence is not a failure,
- whether `water_m` is known. A null `water_m` means "unknown", **never**
  "no water": it earns no bonus but is not penalised.

The value is bounded to [0.30, 0.80] and stays reporting-only: it feeds the
Phase 4.4 `confidence` block and the explainer's `C` factor, never a score.
That is why `--shadow` prints the old/new distribution and the score
equivalence check (see PHASES.md 7.3) shows the forecast is byte-identical
apart from `confidence`/`C`.

Usage:
    python3 derive_zone_confidence.py            # shadow report, no write
    python3 derive_zone_confidence.py --apply    # write zones.json
    python3 derive_zone_confidence.py --self-test
    python3 derive_zone_confidence.py --check    # zones.json matches derivation
"""

import argparse
import json
import os
import re
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZONES_FILE = os.environ.get("ZONES_FILE") or os.path.join(BASE_DIR, "zones.json")
ENRICHED_FILE = (os.environ.get("ZONES_ENRICHED_FILE")
                 or os.path.join(BASE_DIR, "zones_enriched.json"))
REPORT_FILE = os.path.join(BASE_DIR, "confidence_report.json")
FOREST_REPORT = os.path.join(BASE_DIR, "forest_offset_report.json")

# Additive evidence model. The base is the value every curated zone gets for
# having a sourced centroid, altitude and forest class at all (Phases 2–6).
# Bonuses are capped so a 1:1M/CORINE-only zone can never look field-verified.
BASE = 0.45
CAP = 0.80
FLOOR = 0.30

# Evidence bonuses (documented modelling choices, not field-calibrated).
B_SOURCES = {4: 0.02, 5: 0.04}       # 4 = the Phase-2/6.2 minimum, 5 = with a
                                     # station-note source; >5 keeps 0.04
B_SOIL_PH = 0.05                     # SoilGrids v2 pH answered
B_SOIL_1_25K = 0.10                  # real 1:25k soil (step 7.6/7.4)
B_SOIL_MAGNA50 = 0.07                # IGME MAGNA 50 1:50k (step 7.4)
B_SOIL_CLASS_KNOWN = 0.05            # calcareous/siliceous, not "mixed"
B_HABITAT_1_25K = 0.10               # CHC50 1:25k habitat (step 7.6)
B_TERRAIN_LIDAR = 0.04               # ICGC 5 m LiDAR DEM
B_TERRAIN_COPERNICUS = 0.02          # Copernicus ~90 m DEM
B_CANOPY_GOOD = 0.03                 # LiDAR sample coverage ≥ 0.90
B_CANOPY_OK = 0.015                  # LiDAR sample coverage ≥ 0.75
B_FOREST_GATE = 0.04                 # 7.1 CORINE gate passed
B_ACCESS_ROUTE = 0.04                # drive_min + difficulty present
B_WATER_KNOWN = 0.03                 # water_m sourced; null = unknown, no bonus

# Confidence labels are the existing schema values (baixa / medium / alta).
# "alta" means every available evidence layer answered — not that the dominant
# tree was verified in the field (it still comes from CORINE/station notes).
LABEL_THRESHOLDS = ((0.75, "alta"), (0.55, "medium"), (0.0, "baixa"))


def _label(value):
    return next(lbl for th, lbl in LABEL_THRESHOLDS if value >= th)


def _resolution(text):
    """Normalise a source/resolution string to '1:25k', '1:50k' or '1:1M'.

    The scale digit groups are guarded (``1:250000`` must not read as 1:25k).
    """
    t = (text or "").lower().replace(" ", "")
    if re.search(r"1[:/]25(?!\d)", t):
        return "1:25k"
    if re.search(r"1[:/]50(?!\d)", t) or "magna" in t:
        return "1:50k"
    if "1:1m" in t or "1:1000000" in t:
        return "1:1M"
    return None


def _soil_resolution(soil, enriched_soil):
    return (_resolution((enriched_soil or {}).get("resolution"))
            or _resolution((enriched_soil or {}).get("source"))
            or _resolution((soil or {}).get("source"))
            or "1:1M")


def _habitat_resolution(enriched_habitat):
    h = enriched_habitat or {}
    # Only an explicit `resolution` counts as 1:25k. The provider `source` is a
    # chain description ("CHC3 (1:25k) → CORINE fallback") and must never be
    # parsed: that would credit CORINE-only zones with the 1:25k anchor.
    return _resolution(h.get("resolution")) or "100m"


def evidence_for(zone, enriched, gate_ok):
    """Per-component evidence and bonus for one zone. Deterministic, sourced."""
    enrich = (enriched or {}).get("enrichment") or {}
    soil_e = enrich.get("soil") or {}
    hab_e = enrich.get("habitat") or {}
    terr_e = enrich.get("terrain") or {}
    can_e = enrich.get("canopy") or {}
    soil = zone.get("soil") or {}
    access = zone.get("access") or {}

    sources = sorted(set(zone.get("sources") or []))
    n_sources = len(sources)
    b_sources = B_SOURCES.get(n_sources, B_SOURCES[5] if n_sources > 5 else 0.0)

    ph = soil_e.get("ph")
    if ph is None:
        ph = soil.get("ph_approx")
    soil_res = _soil_resolution(soil, soil_e)
    b_soil_res = {"1:25k": B_SOIL_1_25K,
                  "1:50k": B_SOIL_MAGNA50}.get(soil_res, 0.0)
    soil_type = soil_e.get("type") or soil.get("type")
    b_soil_class = (B_SOIL_CLASS_KNOWN
                    if soil_type in ("calcareous", "siliceous") else 0.0)

    hab_res = _habitat_resolution(hab_e)
    b_habitat = B_HABITAT_1_25K if hab_res == "1:25k" else 0.0

    dem_src = terr_e.get("dem_source") or terr_e.get("source") or ""
    if "LiDAR" in dem_src:
        b_terrain, dem_label = B_TERRAIN_LIDAR, "ICGC 5 m LiDAR"
    elif dem_src:
        b_terrain, dem_label = B_TERRAIN_COPERNICUS, "Copernicus ~90 m"
    else:
        b_terrain, dem_label = 0.0, "missing"

    cov = can_e.get("sample_coverage")
    if isinstance(cov, (int, float)) and cov >= 0.90:
        b_canopy = B_CANOPY_GOOD
    elif isinstance(cov, (int, float)) and cov >= 0.75:
        b_canopy = B_CANOPY_OK
    else:
        b_canopy = 0.0

    has_route = (access.get("drive_min") is not None
                 and access.get("difficulty") is not None)
    has_trailhead = bool(access.get("trailhead"))

    components = {
        "sources": {
            "n": n_sources, "bonus": b_sources,
            "detail": f"{n_sources} independent source label(s)",
        },
        "soil_ph": {
            "present": ph is not None, "bonus": B_SOIL_PH if ph is not None else 0.0,
            "detail": "SoilGrids v2 pH" if ph is not None else "no SoilGrids pH",
        },
        "soil_resolution": {
            "value": soil_res, "bonus": b_soil_res,
            "detail": f"soil layer {soil_res}",
        },
        "soil_class": {
            "value": soil_type, "bonus": b_soil_class,
            "detail": ("known class" if b_soil_class
                       else "mixed class (the model does not know)"),
        },
        "habitat_resolution": {
            "value": hab_res, "bonus": b_habitat,
            "detail": f"habitat layer {hab_res}",
        },
        "terrain_resolution": {
            "value": dem_label, "bonus": b_terrain,
            "detail": f"DEM {dem_label}",
        },
        "canopy_coverage": {
            "value": cov, "bonus": b_canopy,
            "detail": (f"LiDAR sample coverage {round(cov * 100)}%"
                       if isinstance(cov, (int, float)) else "no LiDAR canopy sample"),
        },
        "forest_gate": {
            "value": "pass" if gate_ok else ("unknown" if gate_ok is None else "fail"),
            "bonus": B_FOREST_GATE if gate_ok else 0.0,
            "detail": "CORINE forest gate (step 7.1)",
        },
        "access": {
            "route": has_route, "trailhead": has_trailhead,
            "bonus": B_ACCESS_ROUTE if has_route else 0.0,
            "detail": ("drive time + difficulty" if has_route else "no route facts")
                      + ("; named trailhead" if has_trailhead
                         else "; no named trailhead (not a failure)"),
        },
        "water": {
            "known": zone.get("water_m") is not None,
            "bonus": B_WATER_KNOWN if zone.get("water_m") is not None else 0.0,
            "detail": ("water distance sourced"
                       if zone.get("water_m") is not None
                       else "water unknown (not treated as failure)"),
        },
    }
    bonus = round(sum(c["bonus"] for c in components.values()), 3)
    value = round(min(CAP, max(FLOOR, BASE + bonus)), 2)
    return value, _label(value), {
        "version": 1, "computed_at": date.today().isoformat(),
        "base": BASE, "bonus": bonus, "cap": CAP, "floor": FLOOR,
        "components": components,
    }


def forest_gate_by_zone(report, total_zones):
    """Zone ids that failed the 7.1 gate, or None when the report is unusable.

    A single failing zone must not remove the evidence bonus from zones that
    passed, so the aggregate report is attributed through its mismatch list.
    None means "unknown" (missing/stale/unattributable aggregate) and earns no
    bonus, matching the previous honest behaviour.
    """
    zg = (report or {}).get("zone_gate") or {}
    checked = zg.get("checked")
    forest = zg.get("forest")
    mismatches = zg.get("mismatches") or []
    if not isinstance(checked, int) or checked != total_zones:
        return None
    if not isinstance(forest, int):
        return None
    failed = {m.get("zone_id") for m in mismatches if m.get("zone_id")}
    if forest + len(failed) != total_zones:
        return None  # aggregate cannot be attributed to zone ids
    return failed


def derive(zones, enriched, report):
    z_stations = zones.get("zones", {})
    e_by_id = {}
    for zs in (enriched.get("zones") or {}).values():
        for z in zs:
            e_by_id[z.get("id")] = z
    total = sum(len(zs) for zs in z_stations.values())
    gate_failed = forest_gate_by_zone(report, total)
    rows = []
    for station, zs in z_stations.items():
        for z in zs:
            gate_ok = (None if gate_failed is None
                       else z.get("id") not in gate_failed)
            value, label, evidence = evidence_for(z, e_by_id.get(z.get("id")), gate_ok)
            rows.append({
                "station": station, "id": z.get("id"),
                "old": {"value": z.get("confidence"),
                        "label": z.get("confidence_label")},
                "new": {"value": value, "label": label},
                "evidence": evidence,
            })
    return rows


def apply_rows(zones, rows):
    by_id = {r["id"]: r for r in rows}
    for zs in zones.get("zones", {}).values():
        for z in zs:
            r = by_id.get(z.get("id"))
            if not r:
                continue
            z["confidence"] = r["new"]["value"]
            z["confidence_label"] = r["new"]["label"]
            z["confidence_evidence"] = r["evidence"]


def _distribution(keys, rows):
    out = {}
    for r in rows:
        k = r[keys]["value"] if isinstance(keys, str) else keys(r)
        out[str(k)] = out.get(str(k), 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (kv[0])))


def print_shadow(rows):
    old_vals = _distribution("old", rows)
    new_vals = _distribution("new", rows)
    old_labels = {}
    new_labels = {}
    for r in rows:
        old_labels[r["old"]["label"]] = old_labels.get(r["old"]["label"], 0) + 1
        new_labels[r["new"]["label"]] = new_labels.get(r["new"]["label"], 0) + 1
    print(f"zones: {len(rows)}")
    print("old confidence distribution:", old_vals)
    print("new confidence distribution:", new_vals)
    print("old labels:", old_labels)
    print("new labels:", new_labels)
    changed = sum(1 for r in rows if r["old"]["value"] != r["new"]["value"])
    print(f"changed zones: {changed}/{len(rows)}")
    return old_vals, new_vals, old_labels, new_labels


def build_report(rows, old_vals, new_vals, old_labels, new_labels):
    return {
        "step": "7.3",
        "generated_at": f"{date.today().isoformat()}T00:00:00Z",
        "formula": {
            "base": BASE, "cap": CAP, "floor": FLOOR,
            "bonuses": {
                "sources": B_SOURCES, "soil_ph": B_SOIL_PH,
                "soil_1_25k": B_SOIL_1_25K, "soil_magna50_1_50k": B_SOIL_MAGNA50,
                "soil_class_known": B_SOIL_CLASS_KNOWN,
                "habitat_1_25k": B_HABITAT_1_25K,
                "terrain_lidar": B_TERRAIN_LIDAR,
                "terrain_copernicus": B_TERRAIN_COPERNICUS,
                "canopy_good": B_CANOPY_GOOD, "canopy_ok": B_CANOPY_OK,
                "forest_gate": B_FOREST_GATE, "access_route": B_ACCESS_ROUTE,
                "water_known": B_WATER_KNOWN,
            },
            "label_thresholds": {str(t): l for t, l in LABEL_THRESHOLDS},
            "note": ("water_m null = unknown (no bonus, never a failure); "
                     "no named trailhead is not a failure; "
                     "1:25k/MAGNA 50 anchors activate when 7.4/7.6 land"),
        },
        "distribution": {
            "old_values": old_vals, "new_values": new_vals,
            "old_labels": old_labels, "new_labels": new_labels,
        },
        "zones": rows,
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

def _fixture_zone(zid="z1", **over):
    z = {
        "id": zid, "name": zid, "lat": 42.0, "lon": 2.0, "alt_m": 1000,
        "forest": {"type": "conifer", "dominant": "Pinus sylvestris"},
        "soil": {"type": "calcareous", "ph_approx": 6.5,
                 "source": "IGME 1:1M (litho) + SoilGrids v2 (pH)"},
        "water_m": None,
        "access": {"drive_min": 30, "difficulty": "fàcil"},
        "confidence": 0.6, "confidence_label": "medium",
        "sources": ["CORINE CLC 2018 (WMS)", "ICGC 5m LiDAR DEM (2021-2023)",
                    "IGME 1:1M (litho)", "SoilGrids v2 (pH)"],
        "notes": "",
    }
    z.update(over)
    return z


def _fixture_enriched(zid="z1", **over):
    e = {
        "id": zid,
        "enrichment": {
            "terrain": {"dem_source": "ICGC 5m LiDAR DEM (2021-2023)"},
            "canopy": {"status": "complete", "sample_coverage": 1.0},
            "soil": {"status": "complete", "type": "calcareous", "ph": 6.5,
                     "source": "IGME 1:1M (litho) + SoilGrids v2 (pH)"},
            "habitat": {"status": "complete", "source": "CORINE CLC 2018 (fallback for CHC50)"},
        },
    }
    e["enrichment"].update(over)
    return e


def self_test():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        if not cond:
            ok = False
            print(f"FAIL {name} {detail}")
        else:
            print(f"ok   {name}")

    gate = {"zone_gate": {"checked": 1, "forest": 1, "mismatches": []}}
    check("scale 1:25k", _resolution("ICGC 1:25k") == "1:25k")
    check("scale 1:50k", _resolution("IGME MAGNA 50 (1:50k)") == "1:50k")
    check("scale guard 1:250000", _resolution("ICGC 1:250000") is None)
    check("scale guard 1:500000", _resolution("ICGC 1:500000") is None)
    check("habitat source chain is not 1:25k",
          _habitat_resolution({"source": "DIBA SITMUN CHC3 (1:25k) → CORINE CLC 2018 fallback"})
          == "100m")
    check("habitat explicit 1:25k",
          _habitat_resolution({"resolution": "1:25k"}) == "1:25k")
    v, lbl, ev = evidence_for(_fixture_zone(), _fixture_enriched(), True)
    check("deterministic", evidence_for(_fixture_zone(), _fixture_enriched(), True)[:2]
          == (v, lbl))
    check("bounded", FLOOR <= v <= CAP, v)
    check("base zone label", lbl in ("baixa", "medium", "alta"), lbl)
    check("forest gate bonus", ev["components"]["forest_gate"]["bonus"] == B_FOREST_GATE)
    check("water unknown is neutral", ev["components"]["water"]["bonus"] == 0.0)

    z_mixed = _fixture_zone(soil={"type": "mixed", "ph_approx": 6.5,
                                  "source": "IGME 1:1M (litho) + SoilGrids v2 (pH)"})
    e_mixed = _fixture_enriched(soil={"status": "complete", "type": "mixed",
                                      "ph": 6.5, "source": "IGME 1:1M (litho)"})
    v_mixed = evidence_for(z_mixed, e_mixed, True)[0]
    check("mixed soil lowers confidence", v_mixed < v, (v_mixed, v))

    z_noph = _fixture_zone(soil={"type": "calcareous", "ph_approx": None,
                                 "source": "IGME 1:1M (litho)"})
    e_noph = _fixture_enriched(soil={"status": "complete", "type": "calcareous",
                                     "ph": None, "source": "IGME 1:1M (litho)"})
    check("pH raises confidence",
          evidence_for(_fixture_zone(), _fixture_enriched(), True)[0]
          > evidence_for(z_noph, e_noph, True)[0])

    e_25 = _fixture_enriched(
        soil={"status": "complete", "type": "calcareous", "ph": 6.5,
              "source": "ICGC 1:25k soil", "resolution": "1:25k"},
        habitat={"status": "complete", "source": "CHC50 1:25k", "resolution": "1:25k"})
    v_25 = evidence_for(_fixture_zone(), e_25, True)[0]
    check("1:25k soil/habitat anchors raise confidence", v_25 > v, (v_25, v))
    check("1:25k cap respected", v_25 <= CAP)

    z_head = _fixture_zone(access={"drive_min": 30, "difficulty": "fàcil",
                                   "trailhead": "pista"})
    check("an optional trailhead name neither adds nor subtracts evidence",
          evidence_for(z_head, _fixture_enriched(), True)[0] == v)
    z_noacc = _fixture_zone(access={"drive_min": None, "difficulty": None})
    check("missing access reduces, not zeroes",
          FLOOR <= evidence_for(z_noacc, _fixture_enriched(), True)[0] < v)

    v_water = evidence_for(_fixture_zone(water_m=120), _fixture_enriched(), True)[0]
    check("known water adds evidence", v_water > v, (v_water, v))

    check("gate report pass", forest_gate_by_zone(gate, 1) == set())
    check("gate report missing", forest_gate_by_zone(None, 1) is None)
    check("gate report stale", forest_gate_by_zone(gate, 2) is None)
    check("gate report mismatch attributed",
          forest_gate_by_zone({"zone_gate": {"checked": 1, "forest": 0,
                                             "mismatches": [{"zone_id": "z1"}]}}, 1)
          == {"z1"})
    check("gate report unattributable",
          forest_gate_by_zone({"zone_gate": {"checked": 2, "forest": 1,
                                             "mismatches": []}}, 2) is None)

    # One failing zone loses the gate bonus; the passing zone keeps it.
    zmix = {"version": 1, "zones": {"S": [_fixture_zone("z1"), _fixture_zone("z2")]}}
    rows_mix = derive(zmix, {"zones": {"S": [_fixture_enriched("z1"),
                                              _fixture_enriched("z2")]}},
                      {"zone_gate": {"checked": 2, "forest": 1,
                                     "mismatches": [{"zone_id": "z2"}]}})
    check("per-zone gate bonus", rows_mix[0]["new"]["value"] > rows_mix[1]["new"]["value"],
          [(r["id"], r["new"]["value"]) for r in rows_mix])

    zones = {"version": 1, "zones": {"S": [_fixture_zone("z1"), _fixture_zone("z2",
             access={"drive_min": None, "difficulty": None})]}}
    enr = {"zones": {"S": [_fixture_enriched("z1"), _fixture_enriched("z2")]}}
    rows = derive(zones, enr, {"zone_gate": {"checked": 2, "forest": 2,
                                             "mismatches": []}})
    apply_rows(zones, rows)
    check("apply writes new value", zones["zones"]["S"][0]["confidence"] == rows[0]["new"]["value"])
    check("apply writes label", zones["zones"]["S"][0]["confidence_label"] == rows[0]["new"]["label"])
    check("apply writes evidence", "components" in zones["zones"]["S"][0]["confidence_evidence"])
    check("derivation is idempotent",
          [r["new"] for r in derive(zones, enr, {"zone_gate": {
              "checked": 2, "forest": 2, "mismatches": []}})]
          == [r["new"] for r in rows])
    check("zones differ when evidence differs", rows[0]["new"]["value"] != rows[1]["new"]["value"])

    print("SELF-TEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load(path):
    with open(path) as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="write the derived confidence back to zones.json")
    ap.add_argument("--check", action="store_true",
                    help="verify zones.json matches the current derivation")
    ap.add_argument("--self-test", action="store_true", help="offline unit checks")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()

    zones = _load(ZONES_FILE)
    enriched = _load(ENRICHED_FILE) if os.path.exists(ENRICHED_FILE) else {"zones": {}}
    report = _load(FOREST_REPORT) if os.path.exists(FOREST_REPORT) else None
    rows = derive(zones, enriched, report)

    if args.check:
        errs = []
        for r in rows:
            z = next(z for zs in zones["zones"].values() for z in zs
                     if z.get("id") == r["id"])
            if z.get("confidence") != r["new"]["value"]:
                errs.append(f"{r['id']}: confidence {z.get('confidence')} != {r['new']['value']}")
            if z.get("confidence_label") != r["new"]["label"]:
                errs.append(f"{r['id']}: label {z.get('confidence_label')} != {r['new']['label']}")
            if not z.get("confidence_evidence"):
                errs.append(f"{r['id']}: confidence_evidence missing")
        if errs:
            print(f"CHECK FAILED ({len(errs)}):")
            for e in errs[:20]:
                print(" -", e)
            return 1
        print(f"CHECK OK: {len(rows)} zones match the derivation")
        return 0

    old_vals, new_vals, old_labels, new_labels = print_shadow(rows)

    if args.apply:
        apply_rows(zones, rows)
        with open(ZONES_FILE, "w") as f:
            json.dump(zones, f, ensure_ascii=False, indent=1)
            f.write("\n")
        with open(REPORT_FILE, "w") as f:
            json.dump(build_report(rows, old_vals, new_vals, old_labels, new_labels),
                      f, ensure_ascii=False, indent=1)
            f.write("\n")
        print(f"wrote {ZONES_FILE} and {REPORT_FILE}")
    else:
        print("shadow only (no write); re-run with --apply to keep")
    return 0


if __name__ == "__main__":
    sys.exit(main())
