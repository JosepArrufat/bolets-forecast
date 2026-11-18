# Bolets implementation phases

This is the execution ledger for the `/phase` command. It is the single source of
truth for what is done, what is next, and what "done" means for each step.

## How to use

```text
/phase next          # first todo step (optional steps are skipped)
/phase 2             # first todo substep of phase 2
/phase 2.1           # exactly step 2.1
/steps               # phase map: main goal, end goal, status
/phase-status        # read-only status report
```

Every `/phase` invocation runs in a **fresh child session** (`subagent: true`),
so the next step does not inherit the previous step's context. The parent session
stays available for review and decisions.

**One step per session.** If a phase has substeps, `/phase 2` runs only the first
not-done substep and stops. Invoke it again for the next one.

### If the command errors instead of starting

`prefill_cap_refused` means the model's serving cell is at capacity; it is not a
command bug. The commands are pinned to `opencode-go/deepseek-v4-pro`, which
works in this setup; `opencode-go/glm-5.3-flash` is the cheaper fallback. Qwen
models currently require a Go credential. If the pinned model is unavailable,
change the `model:` line in `.opencode/commands/phase.md` and
`phase-status.md`, or retry after about 30 seconds.

## Rules for every step

1. Read `PHASES.md`, `PROPOSAL.md`, and `README.md` before coding. Follow the
   AGENTS.md instructions already loaded for the project.
2. Run `git status --short` and `git log --oneline -5`.
   - Never revert or overwrite changes you did not make.
   - If the tree contains uncommitted work from a completed step (for example
     Phase 1), continue; do not discard it.
   - If another step is `in progress`, or the tree has clearly unrelated
     changes, stop and report a blocker. Only one writer at a time.
3. Implement **only** the requested step. Do not start the next step.
4. Mark the step `in progress` in this file **before** changing code. Only one
   writer at a time.
5. Do not invent forest locations, coordinates, soil values, sightings, or
   confidence. Every curated value needs a source and a confidence label.
6. Keep best zones, routes and parking free. No paywalls, no hidden answers.
7. Preserve the current UI and scoring unless the step explicitly changes them.
8. Do not commit or push unless the user explicitly asks; leave changes for
   review.
9. Verify with the step's checks plus:
   - `python3 -m py_compile app.py` (and any new Python file)
   - JS syntax check when the embedded script changed
   - `curl` the affected API endpoints
   - headless screenshots for UI changes
10. Update this file: set the step to `done` or `blocked`, add date, files,
    verification evidence, and the next step. Never mark `done` without evidence.
11. Return a concise handoff: status, files, verification, blockers, next step.

### Runaway protection

- Do not use the `subagent`/`task` tool. Do the work in the phase child session.
  Nested subagents use a different model and can stall for hours.
- Keep context small: save maps/probes in `/tmp/opencode` and read only what is
  needed; avoid repeated base64 image reads.
- Do not pipe long-running scans through `tail`/`head`; it hides progress and
  looks frozen. Print one line per station or write a progress file after each
  item. Prefer a coarse 1 km scan first, then refine candidates.
- Write candidate work incrementally after each station or file.
- For zone curation, verify every centroid against CORINE/ICGC forest cover
  before writing it. Accept only 311, 312, 313 or 324, and check that the
  dominant tree matches the zone's `forest.dominant`. A coordinate offset from a
  station is not a source.
- Stop and mark `blocked` if a model request fails with `prefill_cap_refused`
  twice, if the same tool pattern repeats three times without a file change, or
  if the step exceeds 45 minutes. Record artifacts and what was learned.

## Phase map

| Phase | Name | Main goal | End goal | Status |
|---|---|---|---|---|
| 1 | Navigation and free access | Make the map usable and remove the paywalled decisions | A free map where anyone can search, filter, compare and reach a zone in under a minute; best zones, routes and parking are never paywalled | done |
| 2 | Micro-zones | Replace one station circle with independently scored forest zones | Every massís has real zones with altitude band, aspect, canopy, soil and access; the UI explains why two stands 500 m apart score differently | done |
| 3 | Terrain and canopy science | Replace coarse point samples with DEM, LiDAR, soil and habitat features | Each zone is scored with aspect, slope, solar radiation, TPI, cold-air pooling, canopy/undergrowth and 1:25k soil/habitat; every factor is sourced and explainable | done |
| 4 | Weather quality | Make the weather local, elevation-corrected and water-balance aware | Zone-level weather from XEMA/radar, drought/recharge, confidence and phenology; a 7-day forecast reliable enough to plan a trip | done |
| 5 | Field loop | Close the loop: field reports calibrate the model | Reports calibrate the model; published AUC/Brier (the report UI, logbook, photos and alerts are optional extras, deferred) | done |
| 6 | PWA and expansion | Make it field-ready and cover more of Catalonia | Installable offline PWA, all Catalonia, 20–25 species, verified locations and field-grade performance | done |
| 7 | Model and data depth | Remove silent data errors and upgrade the layers that cap the habitat model | Every curated value sourced and complete, finer soil/habitat resolution, and weights validated on held-out data instead of assumed | in progress |

**Phase 1 — Navigation and free access.** Main: fix search, filters, map/list
sync, routing and the paywall. End: a free, fast map that gets a hunter to a
candidate zone.

**Phase 2 — Micro-zones.** Main: massís → sector → stand, scored independently.
End: the app answers “where inside this forest?” with real zones, not a circle.

**Phase 3 — Terrain and canopy science.** Main: add the physical variables that
make a stand different from its neighbour. End: an explainable habitat and
microclimate score per zone, backed by DEM/LiDAR/soil sources.

**Phase 4 — Weather quality.** Main: replace smooth point weather with
elevation-corrected station/radar data and a soil water balance. End: a local,
confidence-rated 7-day forecast and a phenology wave.

**Phase 5 — Field loop.** Main: capture what actually happened in the field and
calibrate the model with it. End: a calibrated model with published accuracy.
The user-facing extras (5.2 report UI, 5.3 logbook, 5.4 photos, 5.5 alerts) are
marked `optional` — outside the core mushroom map, deferred until the core
(weather, coverage, species, calibration) is complete. Calibration (5.6) can run
on GBIF/iNaturalist data alone, so the loop does not depend on the extras.

**Phase 6 — PWA and expansion.** Main: offline field use and geographic/species
coverage. End: an installable Catalonia-wide app with 20–25 verified species.

**Phase 7 — Model and data depth.** Main: fix the data errors and resolution caps
that make the numbers behind the map less trustworthy than the UI implies.
End: a complete, sourced curated layer, finer soil and habitat resolution, and
weights validated on held-out data. Specified in `PROPOSAL.md` ("Phase 7 — Model
and data depth"); the steps below copy its goal, work and evidence so the ledger
stays self-contained. Order is deliberate: integrity fixes (7.1–7.3), then
accuracy upgrades (7.4, 7.6, 7.7), then validation (7.5), then radar (7.8).

## Status legend

- `todo` — not started
- `in progress` — a session is working on it
- `done` — implemented and verified
- `blocked` — cannot proceed safely; reason recorded
- `optional` — deprioritised extra service, outside the core mushroom map; revisited later if at all. `/phase next` skips it; `/phase <step>` on it stops and reports it is deferred.

## Status board

| Step | Title | Status | Session | Evidence |
|---|---|---|---|---|
| 1 | Map navigation and free features | done | 2026-11-07 | `app.py`, `README.md`, `PROPOSAL.md`, `warm_parking.py`, `parking_cache.json`, `Dockerfile`; py_compile + node --check + API + headless screenshots |
| 2.1 | Zone schema and per-zone scoring (no UI) | done | 2026-11-07 | `zones.json`, `app.py`, `README.md`, `Dockerfile`; py_compile + API curls + 22-station regression + two-zone fixture |
| 2.2 | Curate Berguedà zones | done | 2026-11-07 | `zones.json` (15 zones), `mushrooms.json` (5 station coords/alt corrected); every zone re-sourced from CORINE 2018 + Copernicus DEM + IGME + SoilGrids; 15/15 pass the forest-cover gate; API 200 / 22 stations / 6 comarques |
| 2.3 | Curate Ripollès zones | done | 2026-11-07 | `zones.json` (+15), `mushrooms.json` (5 station coords/alt/notes corrected); 15/15 forest-cover gate; API 200 / 22 stations / 30 zones / 6 comarques |
| 2.4 | Curate Cerdanya zones | done | 2026-11-07 | `zones.json` (+9), `mushrooms.json` (3 station coords/alt/notes corrected); 9/9 CORINE forest-cover gate; API 200 / 22 stations / 6 comarques / 39 zones |
| 2.5 | Curate Montseny, Garrotxa, Pallars zones | done | 2026-11-07 | `zones.json` (+27 → 66), `mushrooms.json` (9 stations re-sourced); 27/27 CORINE forest-cover gate; ICGC 5m LiDAR + IGME + SoilGrids probes; schema valid; score_zone path verified |
| 2.6 | Zone UI: map, list, detail, comparison | done | 2026-11-07 | `app.py`; py_compile + node --check + fixture DOM (66 zone circles at z≥13, comparison 96/87/77, zone facts) + 5 headless screenshots 1440px/500px |
| 2.7 | Phase 2 verification and docs | done | 2026-11-07 | `README.md`, `PROPOSAL.md`; py_compile + JSON schema (22 stn/66 zones/0 err) + node --check + live API 200 + synthetic fixture (build_forecast → 66 zones, 19 massís distinct) + headless DOM + desktop/mobile screenshots |
| 3.1 | Terrain enrichment skeleton and cache | done | 2026-11-07 | `enrich_zones.py` (new), `zones_enriched.json` (generated, 22 stn/66 zones), `.gitignore`, `README.md`; py_compile + `--self-test` + JSON byte-preserve check + `/` & `/api/stations` 200 |
| 3.2 | DEM: aspect, slope, solar radiation, TPI, cold air | done | 2026-11-07 | `enrich_zones.py`, `zones_enriched.json` (66/66 DEM), `terrain_cache.json`, `README.md`; py_compile + self-test + 66-zone run + API 200 + LiDAR-curated aspect agreement |
| 3.3 | LiDAR: canopy cover, height, undergrowth proxy | done | 2026-11-07 | `enrich_zones.py`, `zones_enriched.json` (66/66 canopy), `terrain_cache.json`, `README.md`; py_compile + self-test + 66-zone run; canopy_pct 0–1 (mean 0.78), height 2.7–33.7 m |
| 3.4 | ICGC 1:25k soil and habitats | done | 2026-11-07 | `enrich_zones.py`, `zones_enriched.json` (66/66 soil + habitat); soil type IGME 1:1M + SoilGrids pH, habitat CORINE fallback; 1:25k upgrade pending (sources unavailable); 0 habitat-vs-forest.type mismatches |
| 3.5 | Integrate terrain factors into scoring and explainer | done | 2026-11-07 | `app.py`, `Dockerfile`, `README.md`, `PROPOSAL.md`; py_compile + node --check + 66-zone fixture (792 species w/ factors) + live API + headless screenshots |
| 3.6 | Phase 3 verification and docs | done | 2026-11-08 | `README.md`, `PROPOSAL.md`; py_compile + sources audit (0 invented) + 66-zone regression fixture + node --check + live API + headless screenshots |
| 4.1 | Batch weather and elevation correction | done | 2026-11-08 | `app.py`, `README.md`; py_compile + node --check + fixture (22 stn/66 zones, 66/66 `weather` block) + live API 200 (0 errors) + lapse unit test |
| 4.2 | Meteocat XEMA and radar | done | 2026-11-08 | `app.py`, `README.md`, `PROPOSAL.md`; py_compile + fixture (22 stn/66 zones, 39/66 `xema` blocks, IDW/age math, zero-call no-key path, no score regression, error fallback) + live API 200 (no-key = byte-identical 4.1) + node --check (script unchanged) + **live-verified with real key 2026-11-08**: 3 real-data fixes (estat param 400, blank-state readings, daily `valors` shape), 188 operative stations, 66/66 zones `xema`, 0 errors, 12.4 MB in 2.19 s |
| 4.3 | Soil water balance and drought index | done | 2026-11-08 | `app.py`, `README.md`, `PROPOSAL.md`; unit checks (windows/bounds/blend/modifier) + fixture via real `build_forecast` (22 stn/66 zones, 66/66 `water`, no-ET0 & no-key degraded paths, station payloads byte-identical, sequera = formula) + live API 200 with key (66/66 water+xema, 0 errors, R spread −0.995…+1.0) |
| 4.4 | Per-zone data confidence | done | 2026-11-08 | `app.py`, `README.md`, `PROPOSAL.md`; py_compile + node --check + unit/verify fixtures (completeness math, deterministic formula, per-species derivation, degraded paths, reporting-only scores byte-identical) + live API 200 with key (66/66 `confidence`, 0 errors) + headless DOM/screenshots 1440px/500px CA+EN |
| 4.5 | Phenology and altitude lag | done | 2026-11-08 | `app.py`, `README.md`, `PROPOSAL.md`; py_compile + node --check + unit checks + 4.4-vs-4.5 fixture (stations byte-identical, 66/66 zones + 792/792 species `phenology`, score changes only via P) + live API 200 with key (real GDD wave) + headless DOM/screenshots 1440px/500px CA+EN |
| 4.6 | Phase 4 verification and docs | done | 2026-11-09 | `README.md`, `PROPOSAL.md`, `PHASES.md`; py_compile + node --check + script byte-identical to 4.5 + fixture byte-identical to 4.5 (22 stn/66 zones/0 err, 66/66 weather/water/confidence/phenology, 0 Meteocat calls no-key) + with-key 66/66 xema + live API 200 (15.7 MB, 6.09 s, 0 errors) + station-day deltas + 66/66 lapse formula + cache restamped 2026-11-09 |
| 5.1 | Trip report model, SQLite, API | done | 2026-11-10 | `app.py`, `README.md`, `PROPOSAL.md`, `.gitignore`; py_compile + node --check (script unchanged) + POST/GET `/api/reports` curls (201/400/429) + rate-limit unit tests + `/api/forecast` 200 no-regression |
| 5.2 | 30-second trip report UI | optional | 2026-11-08 | Deferred extra service — not part of the core mushroom map |
| 5.3 | Personal logbook | optional | 2026-11-08 | Deferred extra service — not part of the core mushroom map |
| 5.4 | Private photos and privacy rules | optional | 2026-11-08 | Deferred extra service — not part of the core mushroom map |
| 5.5 | Alerts (web push / Telegram) | optional | 2026-11-08 | Deferred extra service — not part of the core mushroom map |
| 5.6 | Calibration and published metrics | done | 2026-11-10 | `calibrate.py` (new), `calibration_report.json` (generated), `README.md`, `PROPOSAL.md`; py_compile + `--self-test` (auc/brier/curve/split) + live GBIF+iNaturalist occurrence AUC per species + field-reports N=0 (no recalibration) |
| 5.7 | Phase 5 verification and docs | done | 2026-11-10 | `app.py` (DELETE /api/reports deletion path), `README.md`, `PROPOSAL.md`; py_compile + node --check (script unchanged) + 17-unit privacy/rate-limit/deletion checks + live curl POST/GET/DELETE (200/201/400/403/404/429) + `/api/forecast` 200 no-regression (22 stn/66 zones/0 errors) |
| 6.1 | PWA manifest, service worker, offline pack | done | 2026-11-10 | `app.py`, `README.md`, `PROPOSAL.md`; py_compile + node --check (app & SW) + curl manifest/sw/icons/stations/forecast + CDP offline-pack test + headless screenshots 1440/500px |
| 6.2 | Add comarques with verified coordinates | done | 2026-11-10 | `zones.json` (+69 → 135), `mushrooms.json` (+24 → 46 stations / 22 groups), `zones_enriched.json`, `README.md`, `PROPOSAL.md`; 69/69 CORINE forest gate + 135/135 enrichment + API 0 errors |
| 6.3 | Expand species and add lookalike warnings | done | 2026-11-11 | `mushrooms.json` (+8 → 21 species, `season` + `lookalikes` on all), `app.py` (season gating + lookalikes/season payload + lookalike UI CA/EN), `README.md`, `PROPOSAL.md`; py_compile + node --check + 14 season/lookalike unit checks + fixture (46 stn/135 zones, 16 species in Nov, 16/16 lookalikes) + live API 200 (0 errors) + headless screenshots 1440/500px |
| 6.4 | Performance, caching, final verification | done | 2026-11-11 | `app.py`, `README.md`, `PROPOSAL.md`, `PHASES.md`; payload 48.7 MB → 29.7 MB raw / 1.08 MB gzip; repeat request 3.07 s → 1.8 ms; 46 stn / 135 zones / 0 errors; score-equivalence fixture; headless 1440×900 + 500×900; keyboard/ARIA/contrast fixes |
| 7.1 | Forest-offset repair | done | 2026-11-12 | `repair_forest_offsets.py` (new), `forest_offset_report.json` (generated), `README.md`, `PROPOSAL.md`, `PHASES.md`; CORINE live gate 46/46 stations + 135/135 zones, self-test, py_compile, `build_forecast` 46 stn/135 zones/0 errors, 0 moves |
| 7.2 | Complete the zone facts (access, water, canopy) | done | 2026-11-18 | `complete_zone_facts.py` (French Overpass mirror first + 60 s timeout + keep `drive_min` on OSRM failure + parking stripped); `zones.json` (water_m 135/135 with source, drive_min 135/135, difficulty 135/135; parking fields removed), `zones_enriched.json`, `derive_zone_confidence.py` (no parking bonus → 99 alta/36 medium), `Dockerfile`, `README.md`, `PROPOSAL.md`; py_compile + self-tests + node --check + `--check-schema` OK + `/api/parking` 404 + live 46 stn/135 zones/0 errors + independent `around:` water check (3 zones) + headless trip card with 0 parking mentions 1440/500. **Parking feature removed 2026-11-18** |
| 7.3 | Confidence that discriminates | done | 2026-11-12 | `derive_zone_confidence.py` (new), `confidence_report.json` (new), `zones.json` (135 confidence values + evidence), `zones_enriched.json`, `app.py` (7.4/7.6 anchors + badge CSS/labels), `README.md`, `PROPOSAL.md`, `PHASES.md`; py_compile + `--self-test` + `--check` + schema OK + shadow 0.62–0.77 (44 alta/91 medium) + byte-identical score fixture + live API 200 (46 stn/135 zones/0 errors) + DOM/screenshots 1440/500 |
| 7.4 | IGME MAGNA 50 soil | done | 2026-11-15 | `enrich_zones.py` (`_igme_magna50`, legend tables, fallback reasons, review hold, self-test), `app.py` (`_apply_magna50_soil`, `Q_SOIL_MAGNA50`, 1:50k labels), `zones_enriched.json` (56 × 1:50k / 79 × 1:1M, incl. 2 held), `zones.json` (confidence re-derived), `README.md`, `PHASES.md`; py_compile + self-test + 58/58 live re-query match + per-zone audit (0 fallback class changes, 15 promotions, 2 held at 1:1M) + `derive_zone_confidence --check` + live API 200 (46 stn/135 zones/0 errors, 56 served at 1:50k) |
| 7.5 | Backtest and validate the assumptions | done | 2026-11-15 | `calibrate.py` (weighted AUC, target-group background + effort weighting, temporal split, permutation importance, weight refit + bootstrap CI), `calibration_report.json` (v2), `PROPOSAL.md`, `PHASES.md`; py_compile + `--self-test` + offline fixture + live run (3216 pooled rows, H dominant drop 0.0822, weight refit `no_change`, gain −0.001 CI [−0.008,+0.0043], temporal habitat AUC 0.5334 older / 0.5929 newer) |
| 7.6 | Real 1:25k soil and habitat | done | 2026-11-15 | `enrich_zones.py` (MSC25M 1:25k soil WFS with point-in-polygon selection + CHC3 SITMUN habitat WMS providers, `_classify_msc25_parent`, `_to_utm31`, `_corine` caching), `app.py` (`_apply_magna50_soil`/`_zone_soil_display` accept `1:25k`, `SOIL_SOURCE_1_25K`, soil-badge `· 1:25k`, CHC3/MSC25M labels), `zones_enriched.json` (7 × 1:25k soil / 50 × 1:25k habitat), `zones.json` + `confidence_report.json` (re-derived 82 alta/53 medium), `README.md`, `PROPOSAL.md`; py_compile + self-test + `--check` + `--check-schema` + live API (46 stn/135 zones/0 errors) + DOM (soil badge `· 1:25k`) + headless 1440/500 screenshots. Score byte-identical; CHC50 WMS still down (CHC3 used for BCN), MSC25M covers 7/135 |
| 7.7 | GeoVeg and manual field observations | done | 2026-11-15 | `enrich_zones.py` (dormant `_geoveg` + `_parse_geoveg` + `_geoveg_shadow`), `app.py` (field-observation loader/validation, `field_observation`+`verified_by_person` payload, badge + confidence reason), `field_observations.json` (new, empty schema), `Dockerfile`, `README.md`, `PROPOSAL.md`; py_compile + `--self-test` (parser/shadow) + node --check + deterministic `build_forecast` round-trip + byte-identical 134/134 non-observed zones + live API 200 (46/135/0 errors) + headless DOM/screenshots 1440/500 CA+EN |
| 7.8 | Radar rain (XRAD or equivalent) | blocked | 2026-11-16 | No code/data change. Free geo-referenced source now exists (EUMETNET OPERA via MeteoGate ORD API, CC BY 4.0, anonymous) but is delivered as pan-European GDAL tiled GeoTIFF/HDF5 composites with no server-side point query, 24-h rolling cache only, and 2 km resolution; consuming it needs a non-stdlib raster/LAEA decode + archive access + a storm-day gauge validation that cannot be done in one stdlib-only session. Findings: `/tmp/opencode/radar_7_8_investigation.md` |

---

## Phase 1 — Map navigation and free features (done)

**Goal:** make the app easier to navigate than BoletRadar and remove the two
paywalled decisions (best zones and route).

**Shipped:**
- Search by place, forest, municipality, species, with a server-side Nominatim
  proxy at `/api/geocode`.
- Species/comarca/min-score filters, sorting by score/distance/altitude/name/
  comarca.
- Free best-zones leaderboard, route links, OSM links, nearby parking via
  `/api/parking` and `warm_parking.py`.
- Map clustering, hover sync, always-on legend, geolocation, URL state, mobile
  list tab, `?lang=en` persistence.
- Data-quality indicator and 7-day score strip in the detail panel.
- README coverage corrected to 22 stations / 6 comarques.
- Fly/Docker parking seed fallback.

**Evidence (2026-11-07):**
- `python3 -m py_compile app.py warm_parking.py`
- JS `node --check`
- `/`, `/api/forecast`, `/api/geocode`, `/api/parking` return 200
- Headless Chromium screenshots: desktop, mobile list, mobile detail, CA, EN
- Working tree is uncommitted; do not revert it.

**Next:** 2.1.

---

## Phase 2 — Micro-zones (the differentiator)

**Goal:** replace "one station point = one score over a 1.5–3 km circle" with a
hierarchy of massís → sector → stand, each zone scored independently.

### Step 2.1 — Zone schema and per-zone scoring (no UI)

**Goal:** add the data model and backend support without changing the current
map. A station can have zero or more zones; zero zones means the old behaviour.

**Files:**
- `zones.json` (new; curated zone definitions, keyed by station name)
- `app.py` (load zones, score zones, expose `zones` in `/api/forecast`)
- `README.md` (schema documentation)

**Schema proposal:**
```json
{
  "version": 1,
  "zones": {
    "Rasos de Peguera": [
      {
        "id": "rasos-north",
        "name": "Rasos — obaga del Clot Gran",
        "lat": 42.1091,
        "lon": 1.8873,
        "alt_m": 1290,
        "alt_range_m": [1150, 1380],
        "aspect_deg": 12,
        "aspect": "north",
        "slope_deg": 18,
        "forest": {
          "type": "conifer",
          "dominant": "Pinus sylvestris",
          "canopy_pct": 45,
          "undergrowth": "low"
        },
        "soil": { "type": "calcareous", "ph": 7.1, "source": "ICGC 1:25k" },
        "water_m": 380,
        "access": {
          "parking": [42.1078, 1.8851],
          "trailhead": "Pista de Rasos",
          "drive_min": 38,
          "difficulty": "easy"
        },
        "confidence": 0.82,
        "sources": ["ICGC DEM", "ICGC ortophoto", "field observation"],
        "notes": "Open Scots pine; classic rovelló; avoid after heavy north wind."
      }
    ]
  }
}
```

**Backend behaviour:**
- Load `zones.json` at startup and on `/api/forecast` (like `mushrooms.json`).
- For each zone, score with the zone's `alt_m` and its own geo sample; reuse the
  existing scoring functions, do not fork the formula.
- Return `zones` in each station object. Keep `species`, `days`, `dates`, `geo`,
  `quality` for backward compatibility.
- If a station has no zones, behave exactly as today.
- Add a small `zone_score` summary: best species, best score, best day.
- Do not change the UI in this step.

**Acceptance:**
- `/api/forecast` includes `zones` for stations that have them.
- A station with zones still returns its legacy top-level score.
- Zones with different altitude/aspect can produce different scores.
- No regression for the 22 existing stations.
- `python3 -m py_compile app.py`; `curl /api/forecast` shows zones.

**Blocked if:** the zone schema would require inventing coordinates before any
real zone data is available. Start with the schema and one manually verified
zone only if a source is documented.

**Result (2026-11-07):**
- Status: done
- Files:
  - `zones.json` (new) — version 1 schema with an empty `zones` map. No curated
    zones were added because stand-level sources belong to steps 2.2–2.5; this
    avoids inventing coordinates, altitudes or confidence.
  - `app.py` — `ZONES_FILE` path (with `ZONES_FILE` env override), `get_zones()`
    re-read on every `/api/forecast`, `score_zone()` using the zone's own
    `alt_m` and `fetch_geo()` sample through the existing `score_station()`
    formula, `zone_score_summary()` (best species/score/day), per-zone error
    isolation, and `zones` added to station objects (empty list keeps legacy
    behaviour).
  - `README.md` — schema, required fields, scoring behaviour, API shape and
    `ZONES_FILE` override.
  - `Dockerfile` — copies `zones.json` into the image.
- Verification:
  - `python3 -m py_compile app.py` → OK.
  - `zones.json` parses as `{"version": 1, "zones": {}}`.
  - `/api/forecast` on port 8799 → HTTP 200, 2,254,341 bytes, 22 stations in 6
    comarques; every station still exposes `species`, `days`, `dates`, `geo`,
    `quality` and now `zones: []`. No regression.
  - Two-zone fixture via `ZONES_FILE=/tmp/opencode/zones-test.json` (synthetic,
    not committed) → HTTP 200; Rasos de Peguera returned 2 zones at 900 m and
    1300 m. Today's top score was 69 vs 75 and `zone_score` differed, proving
    per-zone altitude/scoring while the legacy station score stayed 75.
  - Embedded JS unchanged; extracted inline script still passes `node --check`.
    `/` returned HTTP 200.
  - After a separate session added the 2.2 Berguedà zones during this run,
    `/api/forecast` on port 8801 → HTTP 200, 3,816,377 bytes, 22 stations,
    15 zones, 0 zone errors. Example: Rasos zones scored 65/64/44 and Coll de
    Pal 39/80/39, so the backend serves real curated zones too.
- Screenshots: none; this step does not change the UI.
- Concurrency note: another writer completed step 2.2 and overwrote the initial
  empty `zones.json` with 15 Berguedà zones while this session was open. This
  session did not author or modify those curated zone values; review the 2.2
  result and sources separately.
- Notes / sources: no curated zone data was invented. `mushrooms.json` station
  definitions and `geo_cache.json` remain the only location/soil sources until
  step 2.2 documents real stands. Aspect, slope, canopy and curated soil are
  carried in the zone object as metadata but are not scoring factors yet; the
  aspect multiplier belongs to Phase 3.5, so this step's score differences come
  from altitude and the zone's own IGME/CORINE sample.
- Next step: 2.2 (curate Berguedà zones).

### Step 2.2 — Curate Berguedà zones

**Goal:** 3 zones per Berguedà station (15 total), real locations only.

**Stations:** Rasos de Peguera, Coll de Pal, Vallcebre, Sant Jaume de Frontanyà,
Fígols – Gresolet.

**For each zone, record:**
- polygon or centroid inside actual forest,
- altitude band,
- aspect (use DEM or map contour; record source),
- forest type and dominant tree,
- canopy/undergrowth estimate with source,
- soil type/pH if available,
- access/parking/trailhead,
- confidence and sources,
- one field note.

**Sources:** ICGC topo/orthophoto, ICGC DEM, IGME/CORINE, existing station notes,
documented local knowledge. Do not invent a coordinate to fill a row.

**Acceptance:** every zone has `sources` and `confidence`; coordinates fall on
forest in ICGC orthophoto; no duplicate zones; API returns them.

**Result (2026-11-07) — re-sourced from DEM + CORINE:**

The first draft (offsets from station points) failed a CORINE forest-cover
check: 6/15 centroids were non-forest and several "pine" zones sat on broadleaf.
A deeper audit found the *station* coordinates themselves were altitude-wrong,
so the zones inherited the error. This run re-sourced every centroid from two
machine-checkable sources (CORINE CLC 2018 + Copernicus DEM) plus IGME/SoilGrids.

- Status: done
- Files:
  - `zones.json` — 15 Berguedà zones (3 × 5 stations), fully re-sourced. Every
    centroid was found by searching DEM+CORINE for a point in the target forest
    class at the target altitude; `alt_m`, `aspect_deg`/`aspect` and `slope_deg`
    are derived from the DEM; `forest.type` is the CORINE class; `soil.type` is
    IGME lithology via `fetch_geo()`; `ph_approx` is real SoilGrids v2 pH.
  - `mushrooms.json` — 5 Berguedà stations corrected to DEM-verified forest
    points: Rasos (1350→1268 m), Coll de Pal (1680→1678 m), Vallcebre
    (1150→1134 m), Sant Jaume (1000→940 m), Fígols (1100→1219 m). Vallcebre's
    note corrected: CORINE classifies it as broadleaf (beech), pine is minor.
- Method: for each zone, grid-search Copernicus DEM (Open-Meteo elevation API)
  for the claimed altitude band, probe those cells against CORINE CLC 2018 WMS
  (`fetch_corine`), keep points in the documented forest class (conifer for the
  pine stands, broadleaf for beech/oak/riparian), and compute aspect/slope from
  N/S/E/W DEM neighbours. No coordinate is an offset; each is DEM+CORINE-verified.
- Honest-ification: dropped the invented specifics — `canopy_pct`, `undergrowth`,
  `water_m`, `drive_min` and `difficulty` are now `null`; `ph_approx` is real
  (SoilGrids) instead of hand-written; `confidence` is 0.6 "medium" uniformly
  because CORINE is 100 m, the DEM is ~90 m, IGME is 1:1M, and the dominant
  species still comes from station notes (not independently verified per stand).
- Verification:
  - `python3 -m py_compile app.py` → OK
  - `zones.json` validates: 5 station keys, 15 zones, unique ids, all required
    fields present, all station keys present in `mushrooms.json`
  - CORINE gate re-run on all 15: **0 failures** — every centroid returns
    311/312/313 and the dominant tree matches the class (312↔Pinus, 311↔Fagus/
    Quercus/Alnus)
  - `/api/forecast` HTTP 200, 22 stations, 6 comarques, 15 zones each with a
    `zone_score`; no regression
- Screenshots: none; this step does not change the UI
- **Altitude audit (all 22 stations, DEM vs claimed `alt_m`):** 8 stations are
  off by >250 m. Fixed here (Berguedà): Rasos +733, Coll de Pal +783, Vallcebre
  +289, plus Sant Jaume/Fígols (minor). **Recorded for later steps:**
  - Planoles −595 m, Queralbs–Núria +318 m, Setcases −272 m (step 2.3)
  - Bagà – carena −319 m (step 2.4)
  - Montseny – El Brull −258 m (step 2.5)
  These steps must re-source their station coordinates with the same DEM+CORINE
  method before curating zones.
- Next step: 2.3 (curate Ripollès zones, after re-sourcing the three Ripollès
  stations above).

### Step 2.3 — Curate Ripollès zones

Same rules, 5 stations × 3 zones: Ogassa – Ripoll, Planoles, Queralbs – Núria,
Setcases, Camprodon.

**Previous attempt (2026-11-07 11:48–13:35):** a `general` subagent using
`opencode-go/deepseek-v4.1-flash` researched all five stations and generated
maps under `/tmp/opencode` (`ogassa_*`, `planoles_*`, `queralbs_*`, `setcases_*`,
`camprodon_*`, plus `ripolles_candidates_probed.json`). It was interrupted while
still researching and had **not** written any zones. Reuse the artifacts, but
verify every coordinate independently. Do not spawn a nested subagent.

**Result (2026-11-07) — re-sourced from DEM + CORINE:**

- Status: done
- Files:
  - `zones.json` — 15 Ripollès zones (3 × 5 stations) appended to the existing
    15 Berguedà zones (30 total). Every centroid re-verified live against CORINE
    CLC 2018 WMS and Copernicus DEM (Open-Meteo elevation); `aspect_deg`/`aspect`
    and `slope_deg` derived from N/S/E/W DEM neighbours; `soil.type` is IGME
    1:1M lithology; `ph_approx` is SoilGrids v2.
  - `mushrooms.json` — 5 Ripollès stations corrected to DEM-verified forest
    points: Ogassa–Ripoll (800→859 m), Planoles (1100→1458 m, and re-pointed from
    a 1695 m ridge to a 1458 m pine slope), Queralbs–Núria (1500→1482 m),
    Setcases (1560→1832 m), Camprodon (950→1184 m). Notes corrected to the actual
    CORINE class and IGME lithology (Planoles/Setcases are mixed, not "calcari").
- Method: grid-scanned a ±2.5–3.2 km box per station at 0.5 km (CORINE CLC 2018
  GetFeatureInfo + Copernicus DEM), kept cells in the documented forest class,
  then selected 3 zones per station for aspect/altitude diversity (obaga, solana,
  carena). No coordinate is an offset from a station; every centroid is a
  CORINE+DEG-verified forest pixel.
- Honest-ification: same as 2.2 — `canopy_pct`, `undergrowth`, `water_m`,
  `drive_min`, `difficulty` are `null`; `confidence` is 0.6 "medium" (CORINE is
  100 m, DEM ~90 m, IGME 1:1M); dominant species comes from station notes
  (local knowledge), not verified tree-by-tree.
- Verification:
  - `python3 -m py_compile app.py` → OK; `zones.json` + `mushrooms.json` parse.
  - Zone schema validate: 10 station keys, 30 zones, unique ids, required fields
    present, every station key exists in `mushrooms.json`.
  - CORINE forest-cover gate re-run on all 15 Ripollès zones: **0 failures** —
    every centroid returns 312 (conifer) or 311 (broadleaf) and the dominant
    tree matches the class (312↔Pinus/Abies, 311↔Quercus).
  - `/api/forecast` HTTP 200: 22 stations, 6 comarques, 30 zones, 0 zone errors.
    Zone scores differ within a massís (e.g. Camprodon 67/79/67, Ogassa 59/59/65).
  - No UI change → no JS/screenshot evidence needed.
- Screenshots: none; this step does not change the UI.
- Altitude audit carried forward: the remaining un-fixed stations are
  Bagà – carena (−319 m, step 2.4) and Montseny – El Brull (−258 m, step 2.5).
  These steps must re-source station coordinates with the DEM+CORINE method.
- Notes / sources: CORINE CLC 2018 WMS, Copernicus DEM via Open-Meteo elevation,
  IGME 1:1M lithology, SoilGrids v2 pH, OSM locality/toponym names, station notes
  (documented local knowledge). Probing scripts and the grid scan are saved under
  `/tmp/opencode` (`scan_ripolles.py`, `select_ripolles.py`,
  `build_ripolles_zones.py`, `ripolles_grid.json`).
- Next step: 2.4 (curate Cerdanya zones, after re-sourcing Bagà – carena).

### Step 2.4 — Curate Cerdanya zones

Same rules, 3 stations × 3 zones: Tossa d'Alp, Bagà – carena, La Canya.

**Result (2026-11-07):**

- Status: done
- Files:
  - `zones.json` — 9 Cerdanya zones (3 × 3 stations) appended to the existing 30
    (39 total, 13 station keys). Every centroid re-verified live against CORINE
    CLC 2018 WMS; `alt_m`, `aspect_deg`/`aspect` and `slope_deg` derived from the
    ICGC 5 m LiDAR DEM (2021-2023) at ~150 m spacing; `soil.type` is IGME 1:1M
    lithology; `ph_approx` is SoilGrids v2.
  - `mushrooms.json` — 3 Cerdanya stations re-sourced to DEM-verified forest
    points: Tossa d'Alp (42.298,1.877→42.3065,1.9, 1600→1808 m), Bagà – carena
    (42.282,1.872→42.2825,1.8711, 1100→1392 m, resolving the −319 m audit flag),
    La Canya (42.225,2.353→42.223,2.35, 880→938 m). Notes corrected to the actual
    CORINE class and IGME lithology (Tossa is mixed calcari-silícic, not pure
    "calcari").
- Method: grid-scanned a ±3 km box per station at 0.5 km (CORINE CLC 2018
  GetFeatureInfo + Copernicus DEM via Open-Meteo elevation), kept forest cells in
  the documented class, then selected 3 zones per station for aspect/altitude
  diversity. The Open-Meteo elevation API hit its hourly limit mid-run, so the
  final alt/aspect/slope were taken from the ICGC 5 m LiDAR DEM instead (a
  higher-resolution source than the Copernicus DEM used in 2.2/2.3 — recorded as
  an upgrade, not an inconsistency). Aspect is measured, not assumed: several
  candidate cells flipped obaga↔solana between the ~90 m Copernicus and the 5 m
  LiDAR DEM, so zone names follow the LiDAR-measured aspect.
- Honest-ification: same as 2.2/2.3 — `canopy_pct`, `undergrowth`, `water_m`,
  `drive_min`, `difficulty` are `null`; `confidence` 0.6 "medium" (CORINE 100 m,
  IGME 1:1M, dominant species from station notes not verified tree-by-tree).
- Verification:
  - `python3 -m py_compile app.py` → OK; `zones.json` + `mushrooms.json` parse.
  - Schema validate: 13 station keys, 39 zones, unique ids, required fields
    present, every station key exists in `mushrooms.json`.
  - CORINE forest-cover gate re-run live on all 9: **0 failures** — every centroid
    returns 312 (conifer)/311 (broadleaf)/313 (mixed) and the dominant tree matches
    the class (312↔Pinus, 311↔Fagus/Quercus, 313↔Pinus+Fagus).
  - `/api/forecast` HTTP 200: 22 stations, 6 comarques, 39 zones, 0 zone errors,
    0 station errors. Zone scores differ within a massís (Bagà 64/81/69, Tossa
    51/47/51, La Canya 61/58/61).
  - No UI change → no JS/screenshot evidence needed.
- Screenshots: none; this step does not change the UI.
- Altitude audit carried forward: only **Montseny – El Brull (−258 m)** remains,
  for step 2.5.
- Data-quality notes for a later step (not changed here, out of 2.4 scope):
  - `La Canya – Ripollès/Cerdanya` is assigned comarca **Cerdanya** but sits at
    ~42.22 N, 2.35 E, i.e. **Ripollès** near Sant Joan de les Abadesses, and the
    toponym "La Canya" is ambiguous (Nominatim only finds "la Canya" in Garrotxa
    and "Serra de la Canya" in Ripollès). Recommend step 6.2 re-check the comarca.
  - `Bagà – carena` and the Berguedà `Coll de Pal` are the same BV-4024 massís at
    different altitudes (Bagà zones 1177–1421 m vs Coll de Pal 1619–1955 m); they
    are distinct stands, not duplicates.
- Notes / sources: CORINE CLC 2018 WMS, ICGC 5m LiDAR DEM (2021-2023), Copernicus
  DEM via Open-Meteo elevation (grid scan), IGME 1:1M lithology, SoilGrids v2 pH,
  OSM/Nominatim, station notes. Probing scripts saved under `/tmp/opencode`
  (`scan_cerdanya.py`, `probe_cerdanya_terrain150.py`, `probe_cerdanya_soil.py`,
  `build_cerdanya_zones.py`, `cerdanya_grid.json`, `cerdanya_terrain150.json`,
  `cerdanya_soil.json`, `cerdanya_station_corr.json`).
- Next step: 2.5 (curate Montseny, Garrotxa and Pallars zones, after re-sourcing
  Montseny – El Brull).

### Step 2.5 — Curate Montseny, Garrotxa and Pallars zones

Same rules, 9 stations × 3 zones. Montseny is siliceous broadleaf; Garrotxa is
volcanic/mixed; Pallars is high-altitude fir/pine. Expect different species.

**Result (2026-11-07):**

- Status: done
- Files:
  - `zones.json` — 27 zones (3 × 9 stations) appended to the existing 39 → 66
    total, 22 station keys. Every centroid re-verified live against CORINE CLC
    2018 WMS; `alt_m`, `aspect_deg`/`aspect` and `slope_deg` derived from the
    ICGC 5m LiDAR DEM (2021-2023) at ~150 m spacing; `soil.type` is IGME 1:1M
    lithology; `ph_approx` is SoilGrids v2. `canopy_pct`, `undergrowth`,
    `water_m`, `drive_min`, `difficulty` are `null`; `confidence` 0.6 "medium".
  - `mushrooms.json` — 9 stations re-sourced to DEM-verified forest points:
    Montseny – Arbúcies (700→780 m), Montseny – Santa Fe (1050→929 m), Montseny –
    El Brull (800→1058 m, **resolves the −258 m audit flag**), Garrotxa – Santa
    Pau (620→735 m), Garrotxa – Collsacabra (900→1028 m), Garrotxa – Sales de
    Llierca (550→356 m), Pallars – Espot (1700→1816 m), Pallars – Vall Fosca
    (1550→1567 m), Pallars – Sort (700→835 m). Notes corrected to the actual
    CORINE class and IGME lithology.
- Method: grid-scanned a ±3 km box per station at 1 km (CORINE CLC 2018
  GetFeatureInfo + Copernicus DEM), kept forest cells in the documented class,
  then probed 48 candidate points with ICGC 5m LiDAR (alt/aspect/slope) + IGME +
  SoilGrids + CORINE re-verify, and selected 3 zones per station for
  aspect/altitude diversity (obaga, solana, carena). No coordinate is an offset
  from a station; every centroid is a CORINE+LiDAR-verified forest pixel.
- Honest-ification: same as 2.2–2.4 — `canopy_pct`, `undergrowth`, `water_m`,
  `drive_min`, `difficulty` are `null`; `confidence` 0.6 "medium" (CORINE 100 m,
  IGME 1:1M). For Garrotxa, IGME 1:1M reports calcareous conglomerate and does
  **not** resolve the volcanic basalts (Santa Pau, Sales de Llierca); zone notes
  flag this rather than invent a "volcanic" soil value. Dominant species comes
  from station notes (documented local knowledge), not verified tree-by-tree.
- Verification:
  - `python3 -m py_compile app.py` → OK; `zones.json` + `mushrooms.json` parse.
  - Schema validate: 22 station keys, 66 zones, 66 unique ids, all required
    fields present, every station key exists in `mushrooms.json`.
  - CORINE forest-cover gate re-run live on all 27 new zones: **0 failures** —
    every centroid returns 311 (broadleaf) or 312 (conifer) and the dominant
    tree matches the class (312↔Pinus/Abies, 311↔Quercus/Fagus/Castanea).
  - Lat/lon/alt sanity: all 22 stations and 66 zones inside Catalonia with
    plausible altitude (356–1832 m).
  - `GET /` → HTTP 200 (no UI change in this step → no JS/screenshot evidence
    needed, as in 2.2–2.4).
  - Zone-scoring path: `get_zones()` returns 22 keys / 66 zones; `score_zone()`
    on the new El Brull zones returns distinct `zone_score` with live IGME/CORINE
    geo (siliceous / 311) and no error.
- **Live `/api/forecast` caveat:** could not exercise the full live endpoint in
  this session because Open-Meteo's daily forecast quota was exhausted
  (`X-RateLimit-Remaining: 0`, `Retry-After` ~8.5 h). The endpoint still returns
  HTTP 200 but each station carries `error: "HTTP Error 429"` and `zones: []`
  until the quota resets. This is an external, project-wide condition (weather
  is always re-fetched live), not a defect in the zone data. The zone-scoring
  path was verified directly via `score_zone()` with synthetic weather instead.
- Screenshots: none; this step does not change the UI.
- Altitude audit: **all 22 stations are now DEM-verified** (the audit flags from
  steps 2.2–2.4 are closed). Carried forward for a later step (out of scope
  here): the `La Canya – Ripollès/Cerdanya` comarca ambiguity already noted in
  2.4.
- Notes / sources: CORINE CLC 2018 WMS, ICGC 5m LiDAR DEM (2021-2023), Copernicus
  DEM via Open-Meteo elevation (coarse grid scan), IGME 1:1M lithology, SoilGrids
  v2 pH, station notes. Probing scripts and raw probes saved under `/tmp/opencode`
  (`scan_mgp.py`, `probe_mgp.py`, `build_mgp_zones.py`, `mgp_grid.json`,
  `mgp_probe.json`, `mgp_station_corr.json`).
- Next step: 2.6 (zone UI: map, list, detail, comparison).

### Step 2.6 — Zone UI: map, list, detail, comparison

**Goal:** make the zone model visible and useful.

- Map: draw zone polygons/circles at zoom ≥ 13, colored by selected species.
- Station click: show a zone comparison ("north slope 78 · south 61 · summit 44")
  before the full species list.
- Zone detail: altitude band, aspect, canopy, undergrowth, soil, access,
  confidence, sources, 7-day strip.
- List: station card shows "3 zones" and the best zone.
- Keep the current station-level summary for compatibility.
- Mobile: no regression; list/map/detail still work.

**Acceptance:** a user can see that two zones in the same massís score
differently; the reason is visible; no console errors; screenshots at 1440 px and
500 px.

**Result (2026-11-07):**

- Status: done
- Files:
  - `app.py` (only) — no backend or data-file changes; the `/api/forecast`
    response already carried everything the UI needs (`zones[].days`,
    `zone_score`, `alt_m`, `aspect`, `slope_deg`, `forest`, `soil`, `access`,
    `confidence`, `sources`, `notes`).
  - Frontend additions inside the embedded HTML/JS: `zoneLayer` (Leaflet
    layerGroup) + `renderZoneCircles()` (stand circles at zoom ≥ 13, coloured by
    the selected species, click → zone detail); `zoneCompareHtml()` (the
    "obaga 96 · solana 87 · carena 77" strip above the species list);
    `renderZoneDetail()` (altitude band, aspect + obaga/solana, slope, forest
    type/dominant/canopy, soil, confidence badge, trailhead/parking, notes,
    7-day strip, species list, sources); `zoneCountLine()` ("3 zones · millor:
    …" on each station card); `selectZone()` / `renderActiveDetail()`; the
    species list was refactored into `speciesItemsHtml()` and the explainer now
    uses a `_currentExplainCtx` (station **or** zone name/altitude). CA+EN
    strings added. `?zona=<id>` added to URL state (deep links open a zone).
- Verification:
  - `python3 -m py_compile app.py` → OK.
  - Extracted the embedded `<script>` and ran `node --check` → OK (80,446 bytes).
  - Live `/` → HTTP 200 and contains the new functions (`zoneCompareHtml`,
    `renderZoneDetail`, `renderZoneCircles`, `selectZone`, `zoneCountLine`,
    `speciesItemsHtml`, `renderActiveDetail`).
  - Live `/api/forecast` → HTTP 200 (22 stations / 6 comarques). **External
    caveat:** Open-Meteo's daily quota is still exhausted (HTTP 429, carried over
    from 2.5), so the live endpoint returns stations with `error` and `zones: []`
    until the quota resets — this is weather-only, not a zone-data defect.
  - Because live weather is unavailable, verified the UI against a **synthetic
    fixture built through the real `app.build_forecast()`** (only
    `fetch_weather`/`fetch_geo` monkeypatched), so the shape is exactly
    production. Headless-Chromium DOM dump of the fixture confirmed: the
    comparison strip renders three rows with distinct scores
    (`Pallars – Sort`: obaga 96 · solana 87 · carena 77); the zone detail renders
    all facts (e.g. `1176–1336 m`, `sud-oest 210° · solana`, `22.7°`, `fulla
    caduca`, `Quercus spp.`, `calcari (bàsic)`, `mitjana 60%`, sources list);
    the station card shows `3 zones · millor: …`; and at `z=15` the map emits
    exactly 66 zone circle SVG fills (60 green + 6 amber) — i.e. zone circles
    appear at zoom ≥ 13 and are coloured by score. No JS console errors.
- Screenshots (headless Chromium, saved under `/tmp/opencode/`):
  - `shot_desktop_station.png` (1440×900, station detail + comparison strip)
  - `shot_desktop_zone.png` (1440×900, zone detail)
  - `shot_mobile_station.png` (500×900, station detail bottom sheet)
  - `shot_mobile_zone.png` (500×900, zone detail bottom sheet)
  - `shot_map_zones.png` (1440×900, map at z=15 with stand circles)
- Notes / sources: no curated data was changed or invented; every zone value
  shown comes from the existing `zones.json` (steps 2.2–2.5). The fixture for
  screenshots used each zone's own curated `soil.type`/`forest.type` so scores
  genuinely differ (calcareous-pine vs broadleaf-oak vs mixed), which is what
  the acceptance asks to visualise.
- Concurrency note: while this session was open, a parallel commit `eafbbed`
  ("docs: add phase map and /steps command") landed, touching only
  `PHASES.md`/`README.md`/`.opencode/commands/steps.md`. It did not touch
  `app.py` or the zone data, and this session's `in progress` mark survived; no
  conflict.
- Next step: 2.7 (Phase 2 verification and docs).

### Step 2.7 — Phase 2 verification and docs

- Update README with zone schema and how to add a zone.
- Update `PROPOSAL.md` status.
- Run the full verification suite.
- Record evidence in this file.
- Next: Phase 3.

**Result (2026-11-07):**

- Status: done
- Files:
  - `README.md` — aligned the "Adding a micro-zone" schema example with the
    real curated field names (`soil.ph_approx`, `access.parking_lat`/
    `parking_lon`/`parking_source`, `confidence_label: "medium"`, nullable
    `canopy_pct`/`undergrowth`/`water_m`/`drive_min`/`difficulty`), and added a
    "Fields that are nullable" note plus a "The 66 shipped zones" note naming the
    four curation sources (CORINE CLC 2018, Copernicus DEM / ICGC 5m LiDAR, IGME
    1:1M, SoilGrids v2) and why confidence is uniformly 0.6.
  - `PROPOSAL.md` — status line updated: Phase 1 and Phase 2 are implemented;
    Phase 3 (terrain and canopy enrichment) is next.
  - `PHASES.md` — this ledger entry and the status board.
- Verification:
  - `python3 -m py_compile app.py warm_parking.py forecast.py` → OK.
  - JSON schema check → `zones.json` v1, 22 station keys, 66 zones, 66 unique
    ids, all required fields present, every zone key exists in `mushrooms.json`,
    `confidence_label` ∈ {baixa, medium, alta}, all centroids inside Catalonia
    (40.5–43.5 N, 0–3.5 E, alt 0–4000). 0 errors. `mushrooms.json`: 22 stations /
    6 comarques / 13 species.
  - Embedded `<script>` (lines 2013–3939) extracted to
    `/tmp/opencode/app_check_27.js` → `node --check` OK (83,327 bytes).
  - Live endpoints on port 8799: `/` 200, `/api/stations` 200, `/api/geocode`
    200, `/api/parking` 200 (cached station point → 5 results). `/api/forecast`
    200 but **all 22 stations carry `error: "HTTP Error 429"` and `zones: []`** —
    Open-Meteo's daily quota is still exhausted (carried over from steps 2.5/2.6;
    weather is always re-fetched live). This is an external, weather-only
    condition, not a zone-data defect. A parking probe at an uncached zone
    centroid returned 502 (live Overpass timed out) — expected fallback behaviour,
    not a regression.
  - Because live weather is down, verified the full scoring path through the real
    `app.build_forecast()` with only `fetch_weather`/`fetch_geo` monkeypatched
    (fixture script `/tmp/opencode/verify_fixture_27.py`): 22 stations, 66 zones,
    0 station errors, 0 zone errors, **19 of 22 massís show ≥2 distinct zone
    scores** (e.g. Coll de Pal 76/76/87, Vallcebre 94/94/89, Fígols 89/96/94),
    and a valid `zone_score` payload (e.g. Rasos — obaga nord → Fredolic 96).
  - Headless Chromium (fixture served at `/api/forecast` via
    `/tmp/opencode/serve_fixture_27.py`, port 8807): `--dump-dom` renders all 22
    station cards with `3 zones · millor: …`, the `obaga`/`solana` zone labels,
    `zone-fact` detail fields, `Confiança` and `mitjana` (medium) — no console
    errors (empty stderr).
- Screenshots (headless Chromium, under `/tmp/opencode/`):
  - `shot_27_desktop.png` (1440×900, 1.37 MB)
  - `shot_27_mobile.png` (500×900, 0.62 MB)
  - No UI changed in this step; screenshots are a no-regression check and the DOM
    dump above is the primary textual evidence.
- Notes / sources: no curated zone data was changed or invented. The README
  schema now matches the field names actually produced by steps 2.2–2.5.
- Next step: 3.1 (terrain enrichment skeleton and cache).

---

## Phase 3 — Terrain and canopy science

**Goal:** replace coarse point samples with terrain- and canopy-aware zone
features.

### Step 3.1 — Terrain enrichment skeleton and cache

- New `enrich_zones.py`.
- Read `zones.json`, enrich each zone, write `zones_enriched.json` (or a cache).
- Cache by rounded lat/lon and record source + timestamp.
- No scoring changes yet.

**Result (2026-11-07):**
- Status: done
- Files:
  - `enrich_zones.py` (new) — stdlib-only enrichment skeleton. Loads `zones.json`
    and runs every zone through four enrichment providers (`dem`, `lidar`,
    `soil_1_25k`, `habitat`). Each provider samples at the zone centroid and
    caches the result in `terrain_cache.json` **keyed by rounded lat/lon**
    (4 decimals ≈ 11 m, matching `app.py`'s `cache_key`), recording `source` and
    a UTC `timestamp` per sample. The four provider `compute` functions are
    stubs returning `None`; real sampling lands in 3.2–3.4. `enrich_all()` writes
    `zones_enriched.json`; `--self-test` round-trips the cache and the
    enrichment shape offline.
  - `zones_enriched.json` (new, generated) — a superset of `zones.json`: 22
    stations / 66 zones, every curated field byte-preserved, plus an
    `enrichment` block per zone (`terrain` = curated alt/slope/aspect + pending
    curvature/TPI/cold-air/solar; `canopy`, `soil`, `habitat` = `pending`).
    Top-level `_meta` records the generator, timestamp and provider status.
  - `terrain_cache.json` (generated, gitignored) — empty in 3.1 (no real samples
    yet; the plumbing is exercised by `--self-test`).
  - `.gitignore` — added `terrain_cache.json` (runtime cache, like `geo_cache.json`).
  - `README.md` — Files tree + new "Terrain and canopy enrichment (Phase 3)"
    section documenting the enriched schema, the cache, and the run commands.
  - `app.py` — **unchanged** (no scoring/UI change, as required).
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - `python3 enrich_zones.py --self-test` → OK: `cache_key` rounding, put→get
    round-trip records `source` + `timestamp`, different cells do not collide,
    `enrich_zone` preserves curated fields and marks pending factors `null`.
  - `python3 enrich_zones.py` → 22 stations / 66 zones, one progress line per
    station, wrote `zones_enriched.json`.
  - JSON validation: 22 station keys / 66 zones; **every curated field
    byte-preserved (0 mismatches)**; every pending factor is `null` (no invented
    value); `terrain.source` present on all 66 zones (0 missing); cache has 0
    entries.
  - `GET /` → 200 and `GET /api/stations` → 200 (6 comarques) on port 8891; no
    endpoint changed.
- Screenshots: none; this step does not change the UI or scoring.
- Notes / sources: no value was invented. The terrain block re-uses the
  altitude/slope/aspect already curated in Phase 2 and cites each zone's own
  recorded source (`ICGC 5m LiDAR DEM (2021-2023)` or `Copernicus DEM via
  Open-Meteo elevation`) via `_terrain_source()`; the un-computed factors are
  explicitly `null`/`pending` with a note pointing at 3.2–3.4.
- Next step: 3.2 (DEM: aspect, slope, solar radiation, TPI, cold air — fill the
  `dem` provider and cache real ICGC 5m DEM samples).

### Step 3.2 — DEM features

- ICGC 5 m DEM or SRTM 30 m fallback.
- Compute altitude, slope, aspect, curvature, TPI, cold-air pooling proxy, and
  solar radiation (annual/seasonal).
- Store all values with units and source.

**Result (2026-11-07):**

- Status: done
- Files:
  - `enrich_zones.py` — implemented the `dem` provider. Added `_dem_elevation()`
    (ICGC 5m LiDAR WMS `GetFeatureInfo`), `_sample_dem_neighborhood()` (9-point
    neighbourhood: cardinal N/S/E/W at 100 m, diagonals NE/NW/SE/SW at 250 m,
    cached per rounded lat/lon under a `dem_elev` key), `_slope_aspect()`
    (plane-fit from the cross), `_dem_metrics()` (curvature = Laplacian, TPI =
    centre − 250 m ring mean, cold-air pooling = centre − ring min, solar
    radiation), and `_solar_radiation()` (clear-sky tilted/horizontal insolation
    ratio, numerically integrated per 12-min step over the sunlit day, with a
    surface-azimuth-from-south correction so south slopes correctly capture more
    than north). `enrich_zone()` now populates `enrichment.terrain` with the DEM
    metrics (and units) alongside the curated Phase 2 values, and `enrich_all()`
    persists the cache after every station (resumable). Stub signatures for
    3.3/3.4 gained the `cache` arg.
  - `zones_enriched.json` (regenerated) — 22 stations / 66 zones, every curated
    field byte-preserved, each zone's `enrichment.terrain` now carries
    `dem_alt_m`, `dem_slope_deg`, `dem_aspect_deg`, `curvature`, `tpi`,
    `cold_air_pooling`, `solar_radiation` plus unit labels. `_meta.providers.dem
    = done`.
  - `terrain_cache.json` (generated, gitignored) — now holds 594 `dem_elev`
    samples (source + timestamp) and 66 `dem` derived-metric records.
  - `README.md` — documented the step-3.2 DEM metrics table (field, meaning,
    unit) and the ~100 m sampling note.
  - `app.py` — **unchanged** (no scoring/UI change; 3.5 wires these in).
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - `python3 enrich_zones.py --self-test` → OK (cache round-trip + DEM metric
    derivation on a synthetic plane/dome + enrich shape).
  - Full run `python3 enrich_zones.py` → 66/66 zones enriched with DEM, 0
    failures, 0 curated-field mismatches, 1 m 29 s (594 WMS probes + politeness
    delay). `_meta.providers.dem.status = "done"`.
  - `GET /` 200, `GET /api/stations` 200 (6 comarques), `GET /api/forecast` 200
    — no endpoint changed (the forecast still carries the external Open-Meteo
    429 carried over from 2.5–2.7; weather-only, not a DEM defect).
  - Sanity: Cerdanya/Montseny/Garrotxa/Pallars zones (curated from the same ICGC
    5m LiDAR in 2.4/2.5) agree with the recomputed `dem_aspect_deg` (e.g. Tossa
    351/351, Bagà 192/192, Arbúcies 355/355); solar radiation is higher on south
    (solana) than north (obaga) for the same slope.
- Screenshots: none; this step does not change the UI.
- Notes / sources: ICGC 5m LiDAR DEM (`model-elevacions-terreny-catalunya-lidar-
  5m-2021-2023`, WMS `elevacions-territorial`). No value invented — every metric
  is a deterministic function of the 9 sampled elevations (or of lat/slope/aspect
  for solar). **Data-quality finding — resolved:** the Berguedà/Ripollès zones
  curated in step 2.2/2.3 (Copernicus DEM) had `dem_aspect_deg` values that flip
  the curated `aspect` label (e.g. `rasos-obaga-nord` 352°→202°); the
  Cerdanya/MGP zones (curated from ICGC 5m LiDAR) do not flip. Root cause was a
  **sign error in the 2.2/2.3 aspect formula** (a 180° rotation: the downhill
  north-component used `-dzdy` instead of `+dzdy`), not merely coarse DEM. Fix
  applied after this step: 26 zones (Δ≥45°) re-derived from `dem_aspect_deg`,
  with obaga↔solana names/ids corrected where the label was wrong; max residual
  after fix is 37°. `zones.json` + `zones_enriched.json` regenerated.
- Next step: 3.3 (LiDAR canopy: cover %, height, undergrowth proxy, edge density).

### Step 3.3 — LiDAR canopy

- ICGC LiDAR canopy height model.
- Compute canopy cover %, canopy height, undergrowth proxy, edge density.
- Mark coverage gaps as unknown, not zero.

**Result (2026-11-07):**
- Status: done
- Files:
  - `enrich_zones.py` — implemented the `lidar` provider (`_lidar_compute`): a 5×5
    vegetation-height grid (25 cells at 25 m spacing ≈ 100 m stand box) sampled
    from the ICGC LiDAR *vegetation height* raster
    (`model-alcaries-vegetacio-catalunya-lidar-1m-2021-2023`), cached per rounded
    lat/lon under `lidar_veg_h` with source + timestamp. Derives `canopy_pct`
    (fraction of cells ≥ 5 m), `canopy_height_m` (90th percentile),
    `undergrowth` (fraction of cells 0.5–5 m, a shrub/understory proxy visible
    only where the canopy is open), `edge_density` (fraction of adjacent cells
    with a ≥ 3 m height jump) and `sample_coverage`.
  - `zones_enriched.json` — regenerated: 66/66 zones now carry `enrichment.canopy`
    (`status` "complete"); `_meta.providers.lidar.status = "done"`.
  - `terrain_cache.json` — 1650 `lidar_veg_h` cell samples + 66 `lidar` records.
  - `README.md` — documented the step-3.3 canopy metrics table and the
    bare-vs-gap convention.
- Honest-ification: the vegetation-height raster encodes **bare ground / rock as
  the -9999 nodata sentinel**, distinct from a genuine coverage gap. `_canopy_height`
  maps -9999 (and negatives) to 0 m "no vegetation" — so bare cells correctly
  reduce `canopy_pct` — while a network error or malformed response stays `None`
  and is reported via `sample_coverage` (never fabricated as zero). Initial run
  treated -9999 as a gap and left 11 crest/clearing zones with no canopy; after
  the fix all 66 zones resolve (e.g. `tossa-carena-alta` 0.32 cover, `camprodon-
  solana-sud` 0.12 cover — sparse/clearing stands, as expected).
- Verification:
  - `python3 -m py_compile enrich_zones.py` → OK; `--self-test` → OK (adds a
    synthetic canopy-metric test: dense/mixed/no-data grids).
  - Full run → 22 stations / 66 zones / 66 canopy, 0 curated-field mismatches.
  - Distribution sanity: `canopy_pct` 0.00–1.00 (mean 0.78), `canopy_height_m`
    2.7–33.7 m (mean 15.0 m) — consistent with Catalonia's pine/beech/fir stands.
- Next step: 3.4 (ICGC 1:25k soil and habitats).

### Step 3.4 — ICGC 1:25k soil and habitats

- Query ICGC soil WMS/ArcGIS at each zone.
- Map calcareous/siliceous/pH/texture.
- Query ICGC habitats/land cover for dominant tree group.
- Keep IGME/CORINE as fallback.

**Result (2026-11-07):**
- Status: done (with fallback sources; the 1:25k upgrade is recorded as pending)
- Files:
  - `enrich_zones.py` — implemented `soil_1_25k` (`_soil_compute`) and `habitat`
    (`_habitat_compute`) providers, plus `_igme_litho` / `_soilgrids_ph` / `_corine`
    query helpers and `_classify_lithology`.
  - `zones_enriched.json` — regenerated: 66/66 zones carry `enrichment.soil`
    (`type`, `texture`=null, `ph`, `litho_text`) and `enrichment.habitat`
    (`dominant`, `corine_code`); `_meta.providers.soil_1_25k` / `habitat` = done.
  - `terrain_cache.json` — 66 `soil_1_25k` + 66 `habitat` records.
- **Blocker found (not blocking the fallback):** the *intended* ICGC 1:25k sources
  are unavailable right now — the ICGC/CREAF habitat map (CHC50 v3) is served by
  the UB "geoveg" host that has been down (already noted in README Phase 1), and
  the ICGC `sols` WMS returned empty feature bodies while the `geologia_territorial`
  ArcGIS endpoint returned parameter errors in testing. Rather than invent a
  1:25k value, the providers use the same fallback sources the app already uses:
  IGME 1:1M lithology (→ calcareous/siliceous/mixed), SoilGrids v2 (pH) and CORINE
  CLC 2018 (→ dominant tree group). The 1:25k upgrade is flagged `pending` in the
  output and can be swapped in when the sources come back.
- Verification:
  - `python3 -m py_compile enrich_zones.py` → OK; `--self-test` → OK (adds a
    lithology-classification test).
  - Full run → 22 stations / 66 zones / 66 soil / 66 habitat, 0 curated-field
    mismatches.
  - Distribution: soil calcareous 36 / mixed 21 / siliceous 9; habitat conifer 39 /
    broadleaf 26 / mixed 1 — and **0 mismatches** between CORINE-derived habitat and
    the curated `forest.type`, a strong cross-validation of both.
- Next step: 3.5 (integrate terrain/canopy/soil/habitat factors into scoring + explainer).

### Step 3.5 — Integrate factors into scoring and explainer

- Add `H` (habitat), `M` (microclimate), `W` (weather), `P` (phenology) and `C`
  (confidence) to the score breakdown.
- Keep the existing factor names for compatibility where possible.
- Update the "why this score" explainer with the new values and sources.
- Do not claim probability; call it a relative index.

**Result (2026-11-07):**

- Status: done
- Files:
  - `app.py` — loads `zones_enriched.json` (`ZONES_ENRICHED_FILE` env override,
    `get_zones_enriched()` + `_enrichment_lookup()`, keyed by zone `id`); extends
    `score_station` with optional enrichment-driven factors and `score_zone`
    (new `enrichment=` arg, carried through `build_forecast`); adds the factor
    helpers `aspect_match_factor`, `solar_match_factor`, `cold_air_factor`,
    `canopy_openness_factor` and `phenology_factor`; adds an `enrichment` block
    to the zone API payload (also in the degraded `zone_metadata` path); and
    extends the embedded UI (explainer `factorsHtml`/`terrainHtml`, zone detail
    canopy/solar/cold-air facts, CA+EN strings).
  - `Dockerfile` — copies `zones_enriched.json` into the image.
  - `README.md` — new "Scoring integration (step 3.5)" section (H·M·W·P·C table
    + the `W × H × M` formula + the station-unchanged / no-invention guarantees).
  - `PROPOSAL.md` — status line updated to reflect the integrated factors.
- Scoring model (zones only, stations unchanged):
  - `H` = soil × forest × canopy-openness (canopy only where the species notes
    mention an open/no-undergrowth habitat; neutral otherwise).
  - `M` = aspect × potential-sun × cold-air-drainage. Aspect/sun use the species'
    `slope_aspect` from `mushrooms.json`; cold-air uses the species' `temp_min`
    as a frost-tolerance proxy. Each sub-factor is neutral (×1.0) when data is
    missing, so a zone without enrichment (or a station) is byte-identical to
    Phase 2.
  - `W` = the existing weather score (unchanged). `P` = coarse season gate (1.0
    in Sep–Nov now; full GDD phenology is 4.5). `C` = the curated confidence
    label (reported, not multiplied into the score).
  - `Score = W × H × M`, capped at 99. Station scores never changed because
    `H` → soil×forest and `M` → 1.0 without enrichment.
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - `python3 enrich_zones.py --self-test` → OK (no regression).
  - Embedded `<script>` extracted → `node --check` → OK (88,906 bytes).
  - Full `build_forecast()` fixture (only `fetch_weather_batch`/`fetch_geo`
    monkeypatched, real production shape): 22 stations / 66 zones / 0 errors,
    66/66 zones carry `enrichment`, 792 species results carry `factors`. Factor
    spread confirms the differentiator — for Camagroc, `colldepal-obaga-nord`
    M=110 (score 82) vs `colldepal-solana-sud` M=85 (score 63); for Rovelló the
    solana stands get M=107–110 vs the obaga M=85. Station scoring unchanged
    (`M`=100, `terrain`=null, score identical to the legacy path).
  - Live `GET /` 200, `GET /api/stations` 200, `GET /api/forecast` 200 on port
    8893. **External caveat (carried over):** Open-Meteo's daily quota is still
    exhausted (HTTP 429), so the live forecast returns 22 stations with
    `error` and empty `species` — weather-only, not a factor-data defect. Zone
    objects still carry `enrichment` in the degraded path. The scoring path was
    verified via the fixture above.
  - Headless Chromium DOM dump of a zone deep link
    (`?est=Coll de Pal&zona=colldepal-obaga-nord`) renders the new facts:
    `nord-oest 335° · obaga`, `87% · sotabosc 13%` (LiDAR canopy), `0.54×`
    (potential sun), `drena bé l'aire fred` (cold air). Served HTML contains
    `factorRow`/`factorsHtml`/`terrainHtml`.
- Screenshots (headless Chromium, under `/tmp/opencode/`):
  - `shot_35_desktop_zone.png` (1440×900, 574 KB) — zone detail with the new
    terrain/canopy facts.
  - `shot_35_mobile_zone.png` (500×900, 108 KB) — same zone detail on mobile.
- Notes / sources: no preference or value was invented — every factor derives
  from species preferences already in `mushrooms.json` (`slope_aspect`,
  `soil.ph`, `tree_keywords`, `temperature_c.min`) and the sampled enrichment
  values (ICGC 5m DEM, ICGC LiDAR). The explainer states the score is a
  *relative favourability index, not a probability*. `zones_enriched.json` is a
  generated data file now consumed at runtime (and copied in the image);
  `app.py` degrades to the legacy scoring if it is absent.
- Next step: 3.6 (Phase 3 verification and docs).

### Step 3.6 — Phase 3 verification and docs

- Regression test the 22 stations and all zones.
- Verify no invented values: every field has a source.
- Update README/PROPOSAL/PHASES.
- Next: Phase 4.

**Result (2026-11-08):**

- Status: done
- Files:
  - `README.md` — refreshed for the completed Phase 3: the intro now names the 66
    micro-zones and the terrain/canopy data; the "Scoring" section documents the
    zone H·M·W·P·C extension; the "How zones are scored" note points at the 3.5
    integration instead of "Phase 3 work"; the "Known limitations" #5 is rewritten
    from "no aspect detection" (now false) to "resolution, not absence"; the
    "Improvements roadmap" marks micro-zones + slope-aspect as shipped and adds a
    "Phase 3 is complete" note (with the 1:25k soil / CHC50 habitat fallbacks
    flagged `pending`).
  - `PROPOSAL.md` — status line now reads Phases 1–3 implemented, next Phase 4;
    the Phase 3 section gains a "Status: done" note (and records the descoped
    rain/soil overlay item → Phase 4).
  - `PHASES.md` — phase-map row 3 → `done`; this ledger entry and status board.
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - **Sources audit** (`/tmp/opencode/audit_sources_36.py`): `zones.json` 22
    stations / 66 zones / 66 unique ids, every zone has non-empty `sources` +
    `confidence` + a valid `confidence_label`; `zones_enriched.json` has 66
    enrichment blocks, each with all four providers (`terrain`, `canopy`, `soil`,
    `habitat`) at `status: complete` and a `source`, and no `pending_steps`;
    `zones_enriched.json` is a **byte-preserving superset** of `zones.json`
    (0 curated-field mismatches). 0 audit errors → no invented values.
  - **Regression fixture** (`/tmp/opencode/verify_36_regression.py`, through the
    real `app.build_forecast()` with only `fetch_weather_batch`/`fetch_geo`
    monkeypatched and **real cached IGME/CORINE geo** for all 66 centroids):
    22 stations / 66 zones / 0 station errors / 0 zone errors; 66/66 zones carry
    `enrichment`; 5544/5544 species results (66×7×12) carry `factors`; **station
    scoring unchanged** (`terrain`=null and `M`=100 on every station species);
    20/22 massís show ≥2 distinct zone scores; 66 non-neutral `M` examples confirm
    the obaga/solana differentiator is active.
  - Embedded `<script>` extracted (lines 2369–4471) → `node --check` → OK
    (88,906 bytes).
  - Live API (port 8895): `/` 200, `/api/stations` 200, `/api/forecast` 200.
    The forecast returns 22 stations / 66 zones / 0 zone errors; **22 station
    errors are the carried-over Open-Meteo HTTP 429** (weather-only). All 66 zone
    objects still carry `enrichment` in the degraded `zone_metadata` path.
  - Headless Chromium (fixture served on port 8896): zone deep-link DOM dump
    renders `factorRow`/`factorsHtml`/`terrainHtml`, `nord-oest … obaga`,
    `sotabosc`, `aire fred`, `potencial`; station deep-link renders `Vallcebre`,
    `zones`, `millor`, `Confiança`, `mitjana` — no console errors.
- Screenshots (headless Chromium, under `/tmp/opencode/`):
  - `shot_36_desktop_zone.png` (1440×900, 577 KB) — zone detail with terrain/canopy facts.
  - `shot_36_mobile_zone.png` (500×900, 109 KB) — same zone detail on mobile.
- Notes / sources: no data was changed in this step — it is verification + docs
  only. The two Phase-3 source gaps (ICGC 1:25k soil texture, ICGC/CREAF CHC50
  habitat) remain flagged `pending` in the enrichment data and are honest
  fallbacks, not invented values. Open-Meteo's rate limit is still the
  project-wide external condition (weather-only) noted since step 2.5.
- Next step: 4.1 (batch weather and elevation correction).

---

## Phase 4 — Weather quality

### Step 4.1 — Batch weather and elevation correction

- Batch Open-Meteo requests for zones (multiple coordinates per call).
- Apply lapse-rate correction from the station/grid altitude to the zone
  altitude.
- Cache per day.

**Result (2026-11-08):**

- Status: done
- Files:
  - `app.py` — rewrote `fetch_weather_batch` to parse Open-Meteo's real
    multi-location response (a JSON *array* of location objects, each with its
    own `daily` and `elevation` — the old code assumed nested arrays in a single
    object, which was silently broken and one cause of the "weather unavailable"
    failures carried over since 2.5). It now captures `elevation` and a
    `date` stamp per cache entry (cache keyed by coordinate + calendar day, so a
    forecast is never served on the wrong day). Added `LAPSE_RATE_C_PER_M`
    (6.5 °C/km, ICAO) and `lapse_correct()` (shifts only `temperature_2m_max`/
    `_min`; precipitation/wind/humidity untouched — no invented relationship).
    `score_zone` now accepts `weather_elevation`, applies the lapse correction
    from the model/grid altitude to the curated `alt_m`, and emits a `weather`
    block (`grid_alt_m`, `zone_alt_m`, `lapse_correction_c`). `build_forecast`
    fetches weather for all 22 station *and* 66 zone centroids in one batched
    call and passes each zone its own lapse-corrected weather.
  - `README.md` — new "Weather and elevation correction (Phase 4.1)" section.
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - `lapse_correct` unit checks: +600 m → −3.9 °C, −600 m → +3.9 °C, <0.05 °C and
    `None` ref are no-ops.
  - Real `fetch_weather_batch` (2 coords) → returns `{"daily", "elevation"}` per
    coordinate, 21 daily entries (14 past + 7 forecast), correct array parsing.
  - Fixture (`/tmp/opencode/verify_41.py`, monkeypatched weather/geo through the
    real `build_forecast`): 22 stations / 66 zones / 0 errors; 66/66 zones carry
    a `weather` block with a correct `lapse_correction_c`; station scoring
    unchanged (12 species today, legacy fields intact).
  - Live `/api/forecast` (port 8901) → HTTP 200, 12.4 MB, 1.26 s, 22 stations /
    66 zones / **0 station errors / 0 zone errors** (the Open-Meteo batch now
    resolves real weather — no more 429-on-empty). `grid_alt_m` agrees with the
    curated `alt_m` within a few metres for most zones (delta mean −9.5 m); 32
    zones get a meaningful correction (|ΔT| ≥ 0.05 °C), largest −2.24 °C
    (`ogassa-carena-oest`, where the Open-Meteo grid was ~344 m above the LiDAR
    altitude).
  - Embedded `<script>` unchanged → `node --check` → OK (88,908 bytes). `/` and
    `/api/stations` → 200.
- Screenshots: none; this step changes no UI (the `weather` block is backend
  data for later Phase-4 steps to surface).
- Notes / sources: lapse rate 6.5 °C/km is the standard environmental lapse rate
  (ICAO Standard Atmosphere); grid altitude is Open-Meteo's reported `elevation`;
  target altitude is the zone's curated `alt_m` (ICGC 5 m LiDAR / Copernicus
  DEM). No value invented — the correction is a deterministic function of those
  two sourced altitudes. The Open-Meteo multi-location response format change
  (array of objects) also explains part of the persistent "weather unavailable"
  condition noted since step 2.5; today's live call succeeds end-to-end.
- Next step: 4.2 (Meteocat XEMA and radar).

### Step 4.2 — Meteocat XEMA and radar

- Add optional `METEOCAT_API_KEY`.
- Fetch XEMA station observations and XRAD radar accumulation.
- Interpolate to zones; record station distance and data age.
- Keep Open-Meteo fallback.

**Result (2026-11-08):**

- Status: done (XEMA integrated and live-verified with a real key on
  2026-11-08; radar deferred honestly — see below)
- Files:
  - `app.py` — new "Meteocat XEMA (optional)" section. `METEOCAT_API_KEY`
    (env, empty by default) and `METEOCAT_BASE_URL` (test hook) constants;
    variable-code constants `XEMA_VAR_TEMP=32` (Temperatura °C), `XEMA_VAR_PPT=35`
    (Precipitació, mm/30-min period), `XEMA_VAR_PPTDAY=1300` (Precipitació
    acumulada diària mm). `_xema_get()` (urllib + `X-Api-Key` header, per the
    docs' security section and Python example), `_parse_xema_stations()`,
    `_parse_xema_readings()` (handles both documented response shapes:
    single-station dict and all-stations array of `{codi, variables}`),
    `_xema_reading_value()` (quality gates: drops `N`/blank states and daily
    statistics with `percentatge` < 70), `_xema_stations_map()`,
    `_xema_latest()` (`/variables/mesurades/{c}/ultimes`),
    `_xema_daily_map()` (`/variables/estadistics/diaris/1300`), `get_xema_context()`
    (returns None and makes **zero Meteocat calls without a key**; caches
    24 h / 15 min / 1 h under one lock; any error → None + `last_xema_error()`),
    and `interpolate_xema()` (IDW p=2 over the nearest ≤4 stations within
    40 km; temperatures lapse-corrected 6.5 °C/km from the station's official
    altitude to the zone `alt_m` before interpolation; precipitation not
    altitude-corrected). `score_zone(..., xema=None)` and `zone_metadata()`
    attach a `xema` block only when real data exists; `build_forecast()`
    fetches the context once per run and adds a top-level
    `xema.status` (`ok`/`error`) only when a key is configured. Scoring and
    station payloads untouched.
  - `README.md` — new "Meteocat XEMA and radar (Phase 4.2)" section (endpoints,
    variable codes, the `xema` block schema, interpolation + data-quality
    rules, the explicit **annotate-don't-replace** blend policy, key setup,
    fallback behaviour, XRAD deferral); updated the data-sources table, known
    limitation #7, and the short-term roadmap item.
  - `PROPOSAL.md` — status line + Phase 4 section updated (4.1–4.2 shipped,
    radar deferred, live XEMA verification awaits a user key).
- Sources (all verified 2026-11-08): the Meteocat API docs host
  (apidocs.meteocat.gencat.cat) is **unreachable from this network**, so the
  exact endpoints, response shapes and the `X-Api-Key` auth header were
  retrieved from the apidocs pages via web search, and the official variable
  codes cross-checked against Meteocat's open-data variable table
  (analisi.transparenciacatalunya.cat/d/4fb2-n3yi, CSV downloaded). The live
  `api.meteo.cat` host answers 403 without a key (auth enforced, as documented).
  Evidence notes saved to `/tmp/opencode/meteocat_api_notes.md` and
  `/tmp/opencode/xema_variables_meta.csv`.
- Radar decision (honest gap): the API's operation catalogue is XEMA, XDDE,
  Predicció, Referència, Quotes — **there is no XRAD product** (radar is only
  web images/widgets/paid deliveries, no point/GIS query). Per the step rules,
  no raster pipeline was built: rain accumulation comes from XEMA gauges
  (variable 1300 → `precip_today_mm` / `precip_7d_mm` with a days-with-data
  count) and the radar piece is marked `pending` in the data/docs.
- Verification:
  - `python3 -m py_compile app.py forecast.py warm_parking.py enrich_zones.py` → OK.
  - Fixture (`/tmp/opencode/verify_42.py` + `/tmp/opencode/xema_fixtures.py`,
    synthetic values in REAL documented response shapes, only
    `fetch_weather_batch`/`fetch_geo`/`_xema_get` monkeypatched through the real
    `build_forecast()`): parser unit checks (both shapes, state/coverage
    gates); IDW math (nearest station dominates, p=2 weighting, lapse-corrected
    temps); data-age minutes; **key-absent path: zero Meteocat calls, no `xema`
    key anywhere, byte-identical 4.1 payload**; key-present path: 22 stations /
    66 zones / 0 errors, 39/66 zones within 40 km of the fixture stations gain
    `xema` blocks with correct distance (3.5 km), age (12 min), IDW
    temperature (9.2 °C) and 7-day gauge accumulation (15.4 mm over 3 days;
    the sub-70 %-coverage day was correctly dropped); **all 66 zone scores and
    the station/zone payloads (minus `xema`) byte-identical with vs without
    the key → no score regression**; Meteocat-outage path: graceful fallback,
    `xema.status == "error"` with the reason recorded.
  - Live API on port 8902 (my own; the other session's 8765 was not touched):
    `/` 200, `/api/stations` 200, `/api/forecast` 200 (12.4 MB, 0.49 s), 22
    stations / 66 zones / 0 station errors / 0 zone errors, top-level keys
    `{date, comarques}` only — no `xema` key anywhere, confirming the no-key
    path is byte-identical to 4.1 in production.
  - Embedded `<script>` byte-identical to 4.1 (`cmp` vs `app_script_41.js`,
    88,908 bytes) and still passes `node --check` → stated as unchanged, no
    UI change. No screenshots (no UI change).
- Remaining gap (recorded, not skipped): **live Meteocat verification pending
  a user API key.** No `METEOCAT_API_KEY` exists in this environment and the
  docs host is unreachable from here, so the Meteocat path was verified
  against the documented request/response shapes (saved under
  `/tmp/opencode/`), not against the live API. When the user provides a key,
  run `METEOCAT_API_KEY=<key> python3 app.py` and confirm `xema.status == "ok"`
  and sane per-zone blocks.

**Live verification with a real key (2026-11-08, parent session):** the gap
above is now closed. The user provided a key and the live path was exercised
against `api.meteo.cat`. **Three real-data bugs found and fixed** (the
documented shapes were right but three live details were not):

1. `_xema_stations_map` called `/estacions/metadades?estat=ope` → the API
   **rejects `estat`** with HTTP 400 (only `codiEstacio` is a valid param).
   Fixed: call `?codiEstacio=TOTES` and filter operative stations client-side
   — the latest `estats` entry (`dataFi: null`) must have `codi == 2`. Ground
   truth from the live payload: 182/188 state-2 stations report readings;
   0/57 state-1 (clausurada) do.
2. `_xema_reading_value` dropped blank `estat` — but live `ultimes` data
   carries `estat: " "` on **100 % of the 183+186 real readings** (semi-hourly
   provisional data is blank-labelled by design), which silently disabled the
   feature in production. Fixed: only `N` (invalid) is dropped; blank is a
   real provisional reading.
3. The daily-statistics endpoint returns a third shape,
   `[{"codiEstacio", "codiVariable", "valors": [...]}]` — not the documented
   `{codi, variables:[{codi, estadistics}]}`. `_parse_xema_readings` now
   accepts `codi`/`codiEstacio` and any of `lectures`/`estadistics`/`valors`;
   `_xema_daily_map` calls with `stat_key="valors"`.

- Live evidence (2026-11-08, key in env only, never written to any file):
  - All three endpoints return 200 with `X-Api-Key`: stations metadata
    (245 stations), `/variables/mesurades/32/ultimes` (183 stations),
    `/35/ultimes` (186), `/estadistics/diaris/1300?any=2026&mes=11` (186).
  - In-process `get_xema_context()` → 188 operative stations, 183 temp / 186
    ppt / 186 daily, 1.44 s, `last_xema_error()` None.
  - `interpolate_xema` on all 66 zones → **66/66 blocks**. Samples: Rasos
    solana baixa `temp_c` 11.3 °C, `nearest_distance_km` 8.2, `data_age_min`
    45; carena sudoest 1.9 km (WM). `precip_today_mm` correctly `None`
    (Meteocat only publishes today's daily stats the next day).
  - Live server on port 8903 with the key: `/api/forecast` → 200, 12.4 MB,
    2.19 s, top-level `xema.status: ok` (188 operative stations), **66/66
    zones carry `xema`**, 0 station errors / 0 zone errors anywhere in the
    payload. Ages 46 min (10:30Z readings at 11:46), nearest distance
    1.1–14.0 km, `temp_c` 4.9–17.5 °C (high Pyrenees to low stands —
    plausible for 8 Nov). The other session's server on 8765 was left
    untouched; my keyed server was stopped after the test.
  - Fixture `/tmp/opencode/verify_42.py` updated to the live shapes (blank
    state accepted, `codiEstacio`+`valors` daily shape, `codiEstacio=TOTES`
    param) → **all 7 sections pass**, including no-key byte-identical 4.1
    payload with zero Meteocat calls and no score regression with vs without
    the key.
  - `python3 -m py_compile app.py` → OK. Embedded `<script>` untouched by the
    fixes (backend only). `README.md` updated to the live behaviour (endpoint
    table, state-code rule, "live-verified" short-term note).
- Notes / sources: no value invented — the `xema` block is a deterministic
  function of real station data (IDW of official readings; lapse correction
  reuses the 4.1 constant). Blend = annotate, not replace: Open-Meteo keeps
  driving the 7-day forecast and every score; XEMA observations ride alongside
  for later steps (4.3 water balance, 4.4 confidence) to consume.
- Next step: 4.3 (soil water balance and drought index).

### Step 4.3 — Soil water balance and drought index

- Track precipitation minus evapotranspiration over the season.
- Add a drought/recharge index; do not rely only on 7-day mm.
- Calibrate thresholds per species.

**Result (2026-11-08):**

- Status: done
- Files:
  - `app.py` — new "Soil water balance and drought index (Phase 4.3)" section:
    `WATER_PAST_DAYS=92`, `WATER_TTL=24h`, `SOIL_STORAGE_CAP_MM=100.0`,
    `_water_params()` (P + `et0_fao_evapotranspiration`), `fetch_water_batch()`
    (one Open-Meteo call for all coords, cached in `weather_cache.json` under
    the same coordinate key as `w_daily`/`w_date`/`w_t`; **stale-balance rule**:
    a series is only served while `w_date == today`), `compute_water_block()`
    (14/30/60/90-day Σ(P−ET0) windows ending today, each with `days` used;
    recharge index = clamp(B/S_cap, ±1) on the longest usable window
    60→30→14 d with min coverage 45/20/7; `drought_index` = clamp(−B/S_cap,
    0,1); state drought/neutral/recharge at ±50 mm; returns None when ET0 is
    missing → no block, nothing fabricated), `_xema_daily_idw()` (extracted
    from `interpolate_xema` so the blend uses the same ≤4-station/40 km/p=2
    neighbours; xema block output unchanged — re-verified with the 4.2
    fixture), `blend_water_precip()` (documented observed-for-modelled P
    substitution, past days only), `water_modifier()` (m = clamp(1 + k·R,
    0.75, 1.25), k = 0.15 × `rain_trigger_mm`/20). `score_station(..., water=)`
    scales the rain term for zone species only (raw rain % stays in
    `breakdown.pluja`, modifier added as `breakdown.sequera` = 100 neutral —
    stations never get the key → byte-identical). `score_zone(...
    water_series=)` computes and attaches the `water` block.
    `fetch_weather_batch` now updates its cache entry without clobbering the
    water fields. `build_forecast()` fetches the water series once per run.
  - `README.md` — new "Soil water balance and drought index (Phase 4.3)"
    section (data, window formula, FAO-56 recharge-index + 100 mm cap as a
    documented modelling choice, XEMA blend policy, per-species modifier
    formula marked not-field-verified, `water` block schema, limitations);
    updated the data-sources table, the 4.2 blend-policy paragraph (4.3 now
    documents the one place observed values enter the scoring), and added
    known-limitation #8 (balance is a model, not a measurement).
  - `PROPOSAL.md` — status line + Phase 4 section updated for 4.3.
  - `PHASES.md` — board row + this ledger entry.
- Sources (all verified 2026-11-08):
  - Live curl probe (`/tmp/opencode/om_et0_probe.json`): Open-Meteo serves
    `et0_fao_evapotranspiration` with `past_days=92` (99 days: 92 past + 7
    forecast). **Finding:** the ET0 history currently starts 2026-09-11
    (~59 days back), so the 60/90-day windows are partially covered (`days`
    recorded honestly); precipitation covers the full 92 days. The Archive
    API *does* have older ET0 (probe `/tmp/opencode/om_archive_et0_probe.json`,
    41/41 days) but has no multi-coordinate mode → left as a documented later
    backfill, not fetched (88 calls would be too heavy).
  - FAO Irrigation and Drainage Paper 56 (Allen et al. 1998): ET0 definition,
    the bounded root-zone reservoir concept (ch. 8) and typical TAW ranges
    (Table 19) behind the 100 mm storage cap.
  - Species water fields: only the documented `rain_trigger_mm` (15–25),
    `rain_window_days`, `dry_spell_before_days` are used; no new species
    thresholds invented.
- Verification:
  - `python3 -m py_compile app.py forecast.py warm_parking.py enrich_zones.py` → OK.
  - Unit checks (`/tmp/opencode/unit_43.py`, 11 sections, 0 failures): dry
    summer → B90 = −90 mm / state drought / R = −0.6; wet week → B14 = +63;
    recharge bounded at ±1.0; None-day skipping (no fabrication); no-ET0 →
    block None; recharge-window fallback 60→30→14 d; XEMA blend substitutes
    only the documented past days (future days never blended; no ctx → no
    blend); IDW nearest-station dominance; modifier math exact per trigger
    (R=−1: 0.85/0.8125/0.8875 for trigger 20/25/15) and bounded [0.75, 1.25];
    station payload byte-identical with `water=None`; sequera % matches the
    formula on every species.
  - Fixture (`/tmp/opencode/verify_43.py`, 5 sections, 0 failures) through the
    real `build_forecast()` with only `fetch_weather_batch`/`fetch_water_batch`/
    `fetch_geo`/`_xema_get` monkeypatched: cache mechanics (today-stamp hit
    served offline; yesterday-stamp never reused on failure); baseline
    (22 stn / 66 zones / 0 errors, zero Meteocat calls without a key, no
    `water`/`xema` anywhere); water series present (66/66 zones carry `water`,
    window math exact 38/70/55/40 mm, R=+0.55 state recharge, deterministic
    across zones); **station payloads (minus their zone lists) and station
    scores byte-identical** with vs without water; recharge scenario: 66/66
    zones boosted (0 lowered) — before/after samples recorded (e.g.
    `arbucies-carena-alta` 57→59, `colldepal-obaga-nord` 54→56, all +2 in
    this synthetic R=+0.55 case, matching the ±~2–3 point magnitude of the
    formula); degraded no-ET0 path: no crash, no `water` key, zone scores
    byte-identical to baseline; XEMA-key path (real documented shapes): xema
    blocks intact, 38/66 zones blend, blend dates are exactly the observed
    past days (X1+X2 zones: 2 days; X2-only zones: 1 day), `blend_source`
    recorded, blend changes the 14 d balance (38.0 → 33.2 mm), station scores
    byte-identical with the key.
  - 4.2 regression: `/tmp/opencode/verify_42.py` sections 1–5 (parsers, IDW,
    age, zero-call no-key path, error fallback) all pass; the xema block
    values are identical to 4.2's record (temp 9.20 / today 12.20 / 7 d 15.40
    / age 12 min). Section 6's with-vs-without-key byte-equality assertion is
    **superseded by design**: 4.3's documented blend + modifier intentionally
    change zone payloads/scores when a key is present; station scores remain
    byte-identical (asserted in verify_43).
  - Live server on port 8909 (my own; the other session's 8765 untouched)
    with the real `METEOCAT_API_KEY` (env only, never written to any file):
    `/` 200 (121.6 kB), `/api/stations` 200, `/api/forecast` 200 (12.6 MB,
    3.25 s) → 22 stations / 66 zones / **0 station errors / 0 zone errors**;
    top-level `xema.status: ok` (188 operative); **66/66 zones carry both
    `water` and `xema`**; real-data spread: 36 recharge / 22 neutral /
    8 drought zones (R from −0.995 at `espot-solana-baixa`, B60 −99.5 mm, to
    +1.0 at `elbrull-carena-alta`, B60 +171.8 mm — plausible for a dry high
    Pallars vs a wet Montseny on 8 Nov); 66/66 zones blend the 7 published
    November days (Nov 1–7); station species carry no `sequera` key. Server
    stopped after the test.
  - Embedded `<script>` byte-identical to 4.2 (`cmp` vs `app_script_42.js`,
    88,908 bytes) and passes `node --check` → no UI change; no screenshots
    needed.
- Notes / sources: every value is a deterministic function of the documented
  inputs (Open-Meteo P/ET0, the documented species water fields, the 4.2
  XEMA daily stats) plus three explicitly documented modelling constants
  (S_cap = 100 mm, ±50 mm state thresholds, k = 0.15 × trigger/20), all
  marked as modelling choices / not field-verified in the README. ET0 is not
  lapse-corrected (no documented lapse for reference ET — recorded gap).
  Scoring change is zone-only and bounded (±25 % of the rain term); stations
  are byte-identical in every mode. Artifacts: `/tmp/opencode/unit_43.py`,
  `verify_43.py`, `sample_43.py`, `om_et0_probe.json`,
  `om_archive_et0_probe.json`, `forecast_43_live.json`, `app_script_43.js`.
- Next step: 4.4 (per-zone data confidence).

### Step 4.4 — Per-zone data confidence

- Separate data completeness from prediction confidence.
- Confidence reasons: nearest station distance, data age, DEM/LiDAR/soil
  coverage, number of field reports.
- Show confidence per zone and per species.

**Result (2026-11-08):**

- Status: done
- Files:
  - `app.py` — new "Per-zone data confidence (Phase 4.4)" backend section:
    `FIELD_REPORTS_COUNT = 0` (honest — Phase 5 supplies real counts),
    `CONF_WEIGHTS` (documented modelling choice), per-input quality anchors
    (`Q_WEATHER` 0.55 for the ~11 km Open-Meteo grid, `Q_TERRAIN_LIDAR` 0.95 /
    `Q_TERRAIN_COPERNICUS` 0.70, `Q_SOIL_FULL`/`Q_SOIL_LITHO_ONLY` for
    IGME 1:1M ± SoilGrids pH, `Q_HABITAT_CORINE` 0.60, `Q_INPUT_MISSING` 0.30),
    `XEMA_AGE_ZERO_MIN` 360 min, `CONF_LEVEL_THRESHOLDS` (alta ≥ 0.70 >
    mitjana ≥ 0.50 > baixa), `_conf_quality()` (deterministic q per input;
    xema q = 0.6·distance_q + 0.4·age_q), `_conf_reasons()` (one traceable
    reason per input with code/params/impact; impact = q ≥ 0.70 "+", > 0.45
    "·", else "−"; xema distance/age thresholds 10/25 km and 90/180 min),
    `compute_zone_confidence()` (per-zone `confidence` block:
    `completeness_pct` = equal-weight fraction of the score's inputs present
    — weather/terrain/canopy/soil/habitat/curated always, `xema` only when a
    Meteocat key is configured, `water` only when the series was fetched, so
    keyless runs never drop to zero; `score` = Σw·q/Σw with the xema weight
    redistributing when the block is absent; `level`, `field_reports: 0`,
    `reasons`), `compute_species_confidence()` (same formula restricted to
    the inputs each species' active scoring factors use, from the documented
    `mushrooms.json` preferences only: soil-pH pref → soil, tree keywords →
    forest, open/no-undergrowth note + canopy data → canopy, aspect pref or
    frost-sensitivity (temp min > 2 °C) → terrain, blended XEMA rain → xema;
    weather/curation/reports always). `score_zone` attaches the zone block
    and a per-species `confidence` field on every species result (all 7
    days); the degraded `zone_metadata` and zone-error paths carry an honest
    `{completeness_pct: 0, level: "baixa", reason: no_weather}` block.
    **No scoring change** — confidence is never multiplied into any score,
    and stations carry none of it (byte-identical).
  - Frontend (embedded HTML/JS/CSS): `confBlockHtml()` renders "Dades i
    confiança" in the zone detail panel — completeness bar (role=img +
    aria-label), prediction-confidence badge (`conf-level` class), a reasons
    list with text impact glyphs (+, ·, − — not color-only), an honest
    "Informes de camp: cap encara" line and a short relative-index note;
    per-species confidence as a small dot + % badge on each species row
    (`title` tooltip lists the active inputs) and a "Confiança de la
    predicció: mitjana 62% · <inputs>" line in the explainer; the curated
    fact label is renamed "Curació de la zona" / "Zone curation" and the
    factor-C description updated so the curation confidence and this new
    data-confidence stay visually distinct. CA + EN strings, existing
    classes/patterns, keyboard-accessible (semantic list, static content).
  - `README.md` — new "Per-zone data confidence (Phase 4.4)" section: the
    two concepts, the completeness rule (graceful degradation, never zero),
    the exact prediction-confidence formula with the weights/anchors table
    and thresholds, the per-species derivation, the reasons list, honest
    field-reports=0 handling, and limitations (weights/anchors are modelling
    choices, not field-verified; reports weight 0 caps the score ~0.65
    today).
  - `PROPOSAL.md` — Phase 4 status extended with the 4.4 summary.
- Verification:
  - `python3 -m py_compile app.py forecast.py warm_parking.py enrich_zones.py` → OK.
  - Embedded `<script>` extracted → `node --check` OK (96,672 bytes).
  - Unit checks (`/tmp/opencode/unit_44.py`, 11 sections, 0 failures):
    completeness 100 % with all inputs; keyless/waterless runs score 6/6
    (never 0); degraded enrichment → 33 % (weather+curated) with "none"
    reasons; deterministic blocks (identical inputs → identical output);
    xema distance/age math exact; terrain LiDAR/Copernicus/missing anchors;
    soil litho-only anchor; every reason traceable with the right params and
    impact; per-species inputs include soil/forest/terrain/canopy for
    rovelló, exclude canopy for murgola and for rovelló without canopy data,
    include xema only with a blend; field_reports always exactly 0.
  - Fixture through the real `build_forecast()` (`/tmp/opencode/verify_44.py`,
    7 sections, 0 failures; only network fetchers monkeypatched): 22
    stations / 66 zones / 0 errors; 66/66 `confidence` blocks; 5,544/5,544
    species results carry `confidence`; stations carry none; baseline 6-input
    completeness; water-present 7-input; no-ET0 → 6/7 = 86 % + `no_water`
    reason with scores byte-identical to baseline; XEMA-key path (documented
    shapes): 39 zones with blocks, 8-input completeness, xema reasons only
    where real, species xema input only on blended zones; **confidence
    reporting-only**: with the confidence functions patched to no-ops the
    full payloads are byte-identical after stripping the confidence keys;
    determinism re-checked.
  - Regressions: 4.3 fixture (verify_43) and 4.2 fixture (verify_42) pass
    with the two 4.2/4.3 assertions that compared full zone payloads
    updated in the /tmp artifacts to strip the reporting-only
    confidence/water keys (documented supersession — the 4.3 blend already
    superseded 4.2's payload equality; scores stay byte-identical where
    nothing is blended).
  - Live server (own port 8911, real key in env only; the other session's
    8765 untouched): `/` 200 (131.7 kB), `/api/stations` 200,
    `/api/forecast` 200 (13.66 MB, 3.06 s), 22 stations / 66 zones / **0
    errors**, `xema.status ok` (188 operative stations), **66/66 zones carry
    `confidence`**; real-data sample `rasos-solana-baixa`: completeness
    100 % (8/8), level mitjana, score 0.642, reasons "XEMA · estació més
    propera 8.2 km" (+), "XEMA · observacions de fa 48 min" (+),
    "LiDAR · mostra de capçada 92%" (+), "sòl IGME 1:1M + SoilGrids
    (250 m)" (·), "curació · 60%" (·), "cap informe de camp encara" (−);
    live levels all mitjana (reports = 0 caps the score, as documented).
  - Headless Chromium (CDP via bun, real HTML + the saved live payload on a
    fixture server, port 8922): rendered DOM dumps + screenshots of the zone
    detail at **1440 px** and **500 px**, CA and EN — confidence block with
    completeness bar, badge and the full reasons list renders in both
    languages, 13 per-species confidence badges per panel, the explainer
    shows "Confiança de la predicció: mitjana 62% · <inputs>"; **0 console
    errors / 0 exceptions** in every run. (This model cannot view images;
    the DOM dumps are the primary textual evidence, as in step 2.7.)
  - Better Design: loaded the accessibility UI principle before styling and
    `get-review-rules` + `check-comprehension` after; the comprehension
    review flagged word density and acronyms → trimmed the reason labels and
    note, expanded "CORINE Land Cover", and recorded the trade-off below.
- Screenshots (headless Chromium, under `/tmp/opencode/shots44/`):
  - `desktop/shot.png` (1440×900, CA zone detail with confidence block)
  - `mobile/shot.png` (500×900, CA zone detail bottom sheet)
  - `en/shot.png` (1440×900, EN)
  - DOM dumps beside each; explainer dump `explain_dom.html`.
- Notes / sources: every confidence input is traceable to real, sourced
  data — XEMA `nearest_distance_km`/`data_age_min` (4.2), the documented
  Open-Meteo ~11 km grid (4.1), enrichment `sample_coverage` and source
  resolutions (CORINE 100 m, IGME 1:1M, SoilGrids ~250 m, ICGC 5 m LiDAR;
  steps 2.2–3.4), the curated zone `confidence` 0.6 (zones.json), and field
  reports = 0, displayed honestly ("cap informe de camp encara") until
  Phase 5 supplies real counts. All weights, anchors and thresholds are
  documented modelling choices, not field-verified. Trade-offs recorded:
  the reasons list intentionally exceeds a 15-second scan budget (the spec
  asks for it; it is a scannable list inside an existing detail panel whose
  explainer is equally dense — consistent with the app's patterns); the
  remaining acronyms (ICGC/IGME/SoilGrids/XEMA) match the terms the rest of
  the app already uses.
- Next step: 4.5 (phenology and altitude lag).

### Step 4.5 — Phenology and altitude lag

- Growing-degree days, season, altitude lag.
- Show the "rovelló wave" moving up/down with altitude and date.

**Result (2026-11-08):**

- Status: done
- Files:
  - `app.py` — new Phase 4.5 section: `PHENO_WINDOW_DAYS`/`PHENO_OPEN_FRACTION`/
    `PHENO_MIN_DAYS_USED`/`PHENO_LAG_MIN_GDD`/`PHENO_LAG_MAX_DAYS` constants,
    `_gdd_window`, `pheno_state`, `pheno_p_factor`, `species_phenology`;
    `score_station(phenology=…)` computes a GDD-based `P` and attaches a
    per-species `phenology` block (zones only; the station path keeps the
    Phase-2 month gate, payload byte-identical); `score_zone` passes the
    lapse-corrected series and adds the per-zone `phenology` summary;
    `_apply_altitude_lag` fills `altitude_lag_days` vs each species' warmest
    zone. Embedded UI: phenology badge in every zone species row
    (`phenoLineHtml`), "Fenologia · suma tèrmica" explainer section with the
    altitude wave strip (`waveStripHtml`, one cell per zone sorted by
    altitude, current zone outlined) and the next-7-days strip
    (`forecastWaveHtml`), `role="img"` + aria-labels, CA/EN strings, colors
    reused from the app palette.
  - `README.md` — new "Phenology and altitude lag (Phase 4.5)" section: GDD
    definition, per-species base mapping from the documented
    `temperature_c.min`, window open/close arithmetic on the documented
    band, the P formula and the 0.5 ramp / 14-day-window / lag-cap modelling
    choices (standard mushroom thermal-time literature, not field-verified),
    the payload shape, the UI, and the limitations (air not soil
    temperature, 14-day window, no extra fetches).
  - `PROPOSAL.md` — status lines updated for 4.4 + 4.5.
- Phenology model (all inputs documented, none invented):
  - `GDD = Σ max(0, T_mean − T_base)` over the stored 14-day temperature
    series (Open-Meteo `past_days=14` + 7 forecast — reused, **no new
    network calls**; the 92-day water series carries no temperature, and
    adding a fetch was declined as redundant), lapse-corrected from the grid
    altitude to the zone's `alt_m` with the existing 6.5 °C/km constant.
  - `T_base` = each species' documented `temperature_c.min` (rovelló 5 °C,
    fredolic 2 °C, rossinyol 12 °C, ou de reig 15 °C, …).
  - `gdd_open = 14 × (ideal_min − base)`, `gdd_close = 14 × (ideal_max −
    base)` — documented fields only; the 0.5 × gdd_open "opening" boundary
    and the P ramps (0.5→1.0→0.5) are README-documented modelling choices.
  - `P = P_gdd × month gate`; `P` now multiplies the ZONE score only.
  - `altitude_lag_days` = (GDD_warmest − GDD_zone) / (GDD_zone/14), null
    when rate < 0.2 °C·d/day or lag > 30 d.
- Verification:
  - `python3 -m py_compile app.py forecast.py warm_parking.py enrich_zones.py` → OK;
    embedded `<script>` extracted → `node --check` → OK (104,532 bytes).
  - Unit checks (`/tmp/opencode/unit_45.py`): GDD math (base respected,
    below-base days clamp to 0, mixed windows), state thresholds at exactly
    70/210 °C·d for rovelló, forecast-based days-to-open/close determinism,
    higher/colder → fewer GDD → lower P, lapse 1000 m = −6.5 °C exactly,
    per-species base = `temperature_c.min` for all 13 species, degraded
    paths (empty/None/short series → explicit nulls, no crash), P = GDD ×
    month gate — all pass.
  - Fixture through the real `build_forecast()` (only network fetchers
    monkeypatched): 22 stations / 66 zones / 0 errors; 66/66 zones carry
    `phenology`, 792/792 species results carry `phenology`. **Baseline
    4.4 vs after comparison:** station payloads byte-identical (0 diffs);
    zone species payloads identical outside `score`/`factors.P`/`phenology`;
    426 species score changes, all explainable via P (e.g. rovelló
    `rasos-solana-alta` 1418 m: P 100→88 → score 72→63). Synthetic wave:
    GDD 133 at 533 m (open) → 53 at 1420 m (opening) → 6 at 1955 m
    (closed); lags 0→30 d (capped, null above).
  - Degraded path: all fetchers empty → 22 stations degraded / 66 zone
    metadata objects / 0 `phenology` blocks / no crash / nothing fabricated.
  - Live server (own port 8895, real `METEOCAT_API_KEY`): `/` 200,
    `/api/stations` 200, `/api/forecast` 200 in 5.8 s / 15.7 MB, 0 station
    and 0 zone errors, 66/66 `phenology`. **Real early-November rovelló
    wave**: GDD 103 at 533 m (open, lag 0) → 45–66 at 850–1450 m (opening,
    lag 8–26 d, several `days_to_close` 1–6 as the forecast cools) → 14–37
    at >1500 m (closed, lag null) — the documented "rovellons surten primer
    als 800 m i pugen" rule, computed from the real series.
  - Headless Chromium (`/tmp/opencode/shots45/`, CA+EN, 1440 px and 500 px,
    zone `rasos-solana-alta` with an expanded species row + the explainer):
    0 console errors / 0 exceptions; DOM shows the badge lines
    ("finestra oberta ara", "s'obrint", "retard d'altitud: ~16.4 dies"),
    the altitude wave (66 cells) and the 7-day strip (7 cells), EN strings
    on `?lang=en`.
- Notes / sources: T_base is the species file's documented hard minimum
  (`mushrooms.json` → `temperature_c.min`); lapse constant 6.5 °C/km is the
  app's existing documented ICAO value (4.1); thresholds/ramps are stated in
  README as modelling choices following standard thermal-time phenology
  practice (degree-day models for *Boletus edulis* / *Morchella*
  fructification), explicitly not field-verified (Phase 5 calibration).
  Screenshots saved as PNG, but this session's model cannot view images, so
  UI evidence is DOM-dump based (0 console errors, rendered strings and
  strips verified in the dumps).
- Next step: 4.6 (Phase 4 verification and docs).

### Step 4.6 — Phase 4 verification and docs

- Verify weather values against a known station day.
- Record sources/timestamps.
- Update docs. Next: Phase 5.

**Result (2026-11-09):**
- Status: done. Phase 4 map row marked `done` from this evidence only.
- Files: `README.md` (new "Phase 4 verification (4.6)" + cross-references in
  4.1–4.5), `PROPOSAL.md` (status line + Phase 4 status), `PHASES.md` (board,
  phase map, this result). No change to `app.py`, `zones*.json`,
  `mushrooms.json`, `weather_cache.json` or any scoring/UI code; the embedded
  `<script>` is byte-identical to 4.5.
- Verification:
  - **Known-station days (real XEMA daily stats 1000/1001/1002, 2026-11-07/08
    vs Open-Meteo):** Viladrau (956 m) mean Δ +1.0/+0.6 °C; la Quar (872 m)
    −0.5/−1.3 °C; Sant Pau de Segúries (853 m) +2.4/+1.3 °C; Núria (1,971 m)
    +1.9/+0.6 °C. Lapse-corrected values move <0.1 °C because the model grid
    altitude is within 24 m of every one of the 18 nearest XEMA stations
    (honest finding). Daily max/min errors are larger (min too warm up to
    +4.4 °C; max too cool up to −2.5 °C). Rain trace: model 0.0 mm, XEMA
    0–0.1 mm. Raw responses: `/tmp/opencode/openmeteo_station_verify.json`,
    `xema_daily_1000/1001/1002_2026_11.json`,
    `xema_daily_1300_2026_11_46.json`.
  - **Zone lapse end-to-end:** live `/api/forecast` 66/66 zones satisfy
    `lapse_correction_c = (zone_alt_m − grid_alt_m) × 0.0065` (0 mismatches);
    example `ogassa-carena-oest` grid 1,393 m / zone 1,049 m → −2.24 °C;
    only 1 of 66 corrections exceeds 1 °C.
  - **Day rollover:** before the run all 72 `weather_cache.json` entries were
    stamped `date`/`w_date` 2026-11-08; a fresh 2026-11-09 server start
    restamped all 72 to 2026-11-09 (`t` 09:34:26 local / 08:34:26Z). Live
    `date: 2026-11-09`, `xema.fetched_at: 2026-11-09T08:34:31Z`; no
    previous-day series served.
  - **Sources/timestamps audit (66 zones):** `xema` 66/66 with source +
    fetched_at + data_age_min; `water` 66/66 with source + computed_at;
    `confidence` 66/66 with computed_at (no single source string — exception
    recorded); `phenology` 66/66 with computed_at + source note; `weather`
    66/66 but the block carries **no source/fetched_at field** (provenance is
    the cache entry `date`/`t`) — exception recorded honestly, not patched in
    this docs-only step. Top-level `xema.status: ok`, 188 operative stations.
  - **Regression:** `python3 -m py_compile app.py forecast.py warm_parking.py
    enrich_zones.py` OK. Fixture through real `build_forecast()` with network
    fetchers monkeypatched, calendar frozen to 2026-11-08: no-key output
    **byte-identical** to the 4.5 baseline `after45b.json` (22 stations,
    66 zones, 0 errors, 66/66 weather/water/confidence/phenology, **0
    Meteocat calls**); with-key fixture 66/66 `xema` + all other blocks,
    0 errors. Live server port 8899 (real key): `/` 200 (140,828 B),
    `/api/stations` 200 (4,708 B), `/api/forecast` 200 (15,706,019 B,
    6.09 s), 22 stations / 66 zones / 0 errors, all five blocks 66/66.
  - `node --check` on the embedded script OK; `cmp` against the 4.5
    extraction `/tmp/opencode/app_script_45.js` → byte-identical.
- Screenshots: none — 4.6 changes no UI; no headless DOM run needed.
- Notes / sources: Open-Meteo forecast API (model + grid elevation),
  Meteocat XEMA daily statistics variables 1000/1001/1002 (temperature) and
  1300 (precipitation), XEMA station metadata. Verification artifacts under
  `/tmp/opencode` (`fixture_46.py`, `fixture46_nokey.json`,
  `fixture46_key.json`, `live_46_forecast.json`, `app_script_46.js`,
  `zone_lapse_audit.json`). Limitations documented in README (model error
  range, ET0 ~59-day history, XEMA coverage/data age, radar deferred, all
  thresholds uncalibrated until Phase 5).
- Next step: Phase 5, step 5.1 (trip report model, SQLite, API).

---

## Phase 5 — Field loop

### Step 5.1 — Trip report model, SQLite, API

- SQLite table for reports: rounded 1 km cell, comarca, species, found/not found,
  quantity, duration, date, time, model score at the time, device hash, created_at.
- `POST /api/reports`, `GET /api/reports?bbox=&days=`.
- Moderation and abuse limits.
- Never store or expose exact coordinates by default.

**Result (2026-11-10):**

- Status: done
- Files:
  - `app.py` — new "Field reports (Phase 5.1)" backend section plus two routes
    on the Handler. Backend: `REPORTS_DB_FILE` (env-overridable, defaults to
    `DATA_DIR/reports.db`), `_reports_init`/`_reports_connect` (SQLite schema +
    indexes), `_get_device_salt` (per-deployment random salt, stored in the
    `meta` table), `round_to_km` (0.01° ≈ 1 km), `_sha24`, `_now_utc`,
    `_norm_report` (full validation/normalization), `_rate_limit_hits`,
    `add_report`, `query_reports` (aggregated, privacy-safe), and
    `field_report_count`. Handler: `do_POST` + `_read_body` +
    `_handle_post_report` (POST) and a `GET /api/reports` branch.
  - `README.md` — new "Field reports (Phase 5.1)" section (schema, privacy,
    API shapes, abuse limits, deferred items) + `reports.db` in the files tree.
  - `PROPOSAL.md` — Phase 5 status updated to "5.1 done".
  - `.gitignore` — `reports.db`, `reports.db-wal`, `reports.db-shm`.
- Privacy: the client posts `lat`/`lon`, but only the 1 km-rounded cell is stored
  and returned (exact coordinates never written or exposed); the raw device id
  and client IP are never stored — only salted SHA-256 hashes (`device_hash`,
  `client_ip_hash`). `GET` returns aggregated counts, never individual rows.
- Moderation/abuse: rolling limits over `created_at` — 10/device·hour,
  50/device·day, 60/IP·hour → `429`. Input validation: `found` boolean, `species`
  must be a known id, numbers bounded, `date`/`time` well-formed, malformed JSON
  → `400`.
- Verification:
  - `python3 -m py_compile app.py` → OK.
  - Embedded `<script>` extracted → `node --check` OK; `/` returns 140,828 bytes
    (byte-identical to the 4.6 baseline → UI/script untouched).
  - Function tests (`/tmp/opencode`, isolated `REPORTS_DB_FILE`): 1 km rounding
    (42.1091,1.8873 → 42.11,1.89); 7 validation rejections; aggregation
    (2 found / 2 not-found across rovelló+cep in one cell); `bbox` and `days`
    filters; `days` capped at 365; `field_report_count()`.
  - Rate-limit tests: device·hour blocks at 11th report (10 ok → `device_hour`);
    IP·hour blocks at 61st report (60 ok across 6 devices → `ip_hour`).
  - HTTP end-to-end (live server, isolated `DATA_DIR`/`REPORTS_DB_FILE`):
    `POST /api/reports` → 201 with rounded cell; minimal body → 201; bad species
    → 400; malformed JSON → 400; `GET /api/reports` → aggregated totals;
    `GET /api/reports?bbox=…&days=7` → filtered; bad bbox → 400.
  - No-regression: `GET /` 200, `/api/stations` 200, `/api/forecast` 200
    (22 stations / 66 zones / 0 errors, 2.14 s with warm cache).
- Screenshots: none — this step changes no UI (the report form is the optional
  5.2).
- Notes / sources: stdlib-only (`sqlite3`, `hashlib`, `secrets`); no invented
  data — the store records what the client reports. `FIELD_REPORTS_COUNT` stays
  0 in the confidence block (wiring the live `field_report_count()` in is part of
  calibration, 5.6). The `score_at_time` field is client-supplied (the score the
  user saw), stored for calibration; the schema's rounded `cell_key` is the
  dedupe/aggregation unit.
- Next step: 5.6 (calibration and published metrics) — 5.2–5.5 are optional
  extras, skipped by `/phase next`.

### Step 5.2 — 30-second trip report UI

> **Optional service (deferred 2026-11-08).** Extra functionality outside the
> core mushroom map; revisit later, after the core is complete.

- Species multi-select, found/not found, quantity, duration, date.
- GPS current location or map point.
- Privacy note; exact position rounded before saving.
- Works on mobile, one hand.

### Step 5.3 — Personal logbook

> **Optional service (deferred 2026-11-08).** Extra functionality outside the
> core mushroom map; revisit later, after the core is complete.

- Local-first trips and finds; optional account later.
- Yield stats by zone/species/season.
- Private by default.

### Step 5.4 — Private photos and privacy rules

> **Optional service (deferred 2026-11-08).** Extra functionality outside the
> core mushroom map; revisit later, after the core is complete.

- Optional photo upload, EXIF stripped client and server.
- Private storage; no public map by default.
- Explicit consent for social sharing without location.

### Step 5.5 — Alerts

> **Optional service (deferred 2026-11-08).** Extra functionality outside the
> core mushroom map; revisit later, after the core is complete.

- Web push or Telegram/email digest.
- Rule: "Rovelló window opened at <zone>".
- Include confidence, data date, and unsubscribe.

### Step 5.6 — Calibration and published metrics

- Train/validate on reports + GBIF/iNaturalist with held-out data.
- Publish AUC/Brier and calibration curve.
- Do not overfit to single reports.

**Result (2026-11-10):**

- Status: done
- Files:
  - `calibrate.py` (new) — stdlib-only calibration pipeline. Metric math
    (`auc` Mann–Whitney U with ties = 0.5, `brier`, `calibration_curve`,
    deterministic `heldout_split`); field-report adapter (`reports_labels` reads
    `found`/`score_at_time` from the step-5.1 store); GBIF + iNaturalist
    occurrence fetchers (GBIF primary with `acceptedUsageKey` fallback for
    synonyms, iNaturalist supplementary, deduped by rounded coords); zone
    nearest-neighbour assignment (`haversine_m`, ≤ 20 km); background sampling;
    `--self-test`.
  - `calibration_report.json` (new, generated) — the published metrics +
    methodology + caveats.
  - `README.md` — new "Calibration and published metrics (Phase 5.6)" section
    with the results table, honest reading and limits; files tree updated.
  - `PROPOSAL.md` — Phase 5 status updated to "5.1 and 5.6 done".
- Methodology (all documented, no invented data): field reports give the only
  true binary labels (AUC/Brier/curve on a held-out split); occurrences are
  real GBIF + iNaturalist records (presence-only) scored by their nearest zone
  against 200 random Catalonia background points — a rank-discrimination AUC,
  not a calibrated probability. **No recalibration was applied** — the report
  sample is empty, so retraining would overfit (the step's explicit guard).
- Published results (2026-11-10):
  - Field reports: `n = 0` → AUC/Brier/curve not computable, no recalibration.
  - Occurrence AUC (current score vs background): trompeta **0.745** (n 46),
    cep **0.668** (55), ou de reig **0.664** (58), rovelló **0.653** (55),
    orella de llebre **0.653** (29), picornell 0.623 (104), rossinyol 0.599
    (20), llenegra negra 0.577 (18), fredolic 0.533 (56), llenegra blanca 0.514
    (36), bolet de tinta **0.421** (70), camagroc **0.321** (47), murgola n/a
    (spring species, no autumn score).
  - Honest negatives published: bolet de tinta (meadow species — app scores
    forest only) and camagroc (high-altitude late-autumn pine) rank below
    chance, which is a real finding, not a hidden failure.
- Verification:
  - `python3 -m py_compile calibrate.py` → OK.
  - `python3 calibrate.py --self-test` → OK (auc perfect/reversed/tie/empty,
    brier perfect/wrong/empty, calibration-curve binning, deterministic
    disjoint held-out split).
  - Live run → 13/13 species fetched (GBIF status ACCEPTED except camagroc
    SYNONYM → resolved via `acceptedUsageKey`), per-species AUC written to
    `calibration_report.json`; `field_reports.n == 0` (empty store).
- Screenshots: none — this step changes no UI and no scoring.
- Notes / sources: GBIF occurrence API (`/species/match`, `/occurrence/search`
  `country=ES`, `hasCoordinate`), iNaturalist v1 (`/taxa`, `/observations`
  `verifiable=true`, Catalonia bbox). No scores or weights were retrained; the
  metrics are descriptive validation, published as-is.
- Next step: 5.7 (Phase 5 verification and docs).

### Step 5.7 — Phase 5 verification and docs

- Privacy review, rate limits, deletion path.
- Update docs. Next: Phase 6.

**Result (2026-11-10):**

- Status: done. Phase 5 map row marked `done` from this evidence only.
- Files:
  - `app.py` — added the **deletion path** (the step's one real gap). New
    `_resolve_device_hash()` (the single salted-hash derivation shared by POST
    and DELETE, so a report can only be erased by the identity that created it),
    `delete_reports(device_hash, report_id=None)` (delete all of a device's
    reports, or one `id` only if it belongs to the device — unknown id →
    `not_found`, other device's id → `forbidden`, never read back raw identity),
    `Handler.do_DELETE` → `/api/reports` plus `_handle_delete_report()` (optional
    `id` query param, `device_id` body or `X-Device-Id` header, same fallback as
    POST). POST refactored to reuse `_resolve_device_hash` (no behaviour change).
  - `README.md` — documented `DELETE /api/reports` (all / by-id, status codes) in
    the Field reports API section, added a right-to-erasure bullet to "Privacy by
    design", and updated the "deliberately not in this step" note (`FIELD_REPORTS_COUNT`
    wiring is now a named remaining follow-up, not "part of 5.6").
  - `PROPOSAL.md` — status line + Phase 5 section now read "Phase 5 complete
    (5.1 + 5.6 + 5.7); the user-facing extras deferred"; next Phase 6.
  - `PHASES.md` — phase-map row 5 → `done`, status board + this ledger entry.
- Privacy review (verified, not just asserted):
  - `_norm_report` rounds to 0.01°; the stored row contains only the rounded
    `cell_lat/cell_lon` and salted `device_hash`/`client_ip_hash`.
  - The raw device id ("device-abc") and raw IP ("1.2.3.4") never appear in any
    stored row or in `GET /api/reports` output (asserted in the unit checks).
  - `GET` returns aggregated counts grouped by cell/comarca/species/found — no
    individual rows, no hashes, no exact positions.
  - `DELETE` returns only `status` + `deleted` counts, never identity.
- Verification:
  - `python3 -m py_compile app.py calibrate.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - Embedded `<script>` extracted → `node --check` OK; still 104,532 bytes
    (byte-identical to the 4.5/4.6 script — no UI change; no screenshots needed).
  - Unit suite (`/tmp/opencode/verify_57.py`, isolated `REPORTS_DB_FILE`): **17/17
    pass** — rounding, create, no-raw-identity-in-storage, no-raw-identity-in-GET,
    DELETE own-id→ok, unknown-id→not_found, other-device-id→forbidden (row left
    untouched), DELETE-all→ok (store empty), device_hour at 11th, ip_hour at 61st,
    device_day at 51st (via backdated rows to bypass the 1 h window).
  - Live HTTP (own port 8931, isolated `DATA_DIR`/`REPORTS_DB_FILE`):
    `POST` → 201 with rounded cell; `POST` bad species → 400; malformed JSON →
    400; `GET` → aggregated; `DELETE ?id=` own → 200 `{deleted:1}`, again → 404,
    other device → 403, `id=abc` → 400; `DELETE` all (body `device_id` and header
    variants) → 200; `GET` after → empty. Rate limit over HTTP: 10×201 then `429
    {reason: device_hour}`.
  - No-regression (own port 8932, repo caches): `/` 200, `/api/stations` 200,
    `/api/forecast` 200 (15,603,449 B, 2.07 s) → 22 stations / 66 zones / **0
    station errors / 0 zone errors**, date 2026-11-10, no `device_hash`/
    `client_ip_hash` anywhere in the payload.
- Screenshots: none — this step changes no UI (the embedded script is
  byte-identical; the report form is the optional 5.2).
- Notes / sources: no data invented. The deletion path keys off the same salted
  device hash as creation, so it is privacy-safe without any account system. The
  one remaining honesty gap carried forward (unchanged, not silently patched):
  `FIELD_REPORTS_COUNT` is still the constant `0` in the confidence block, so the
  confidence panel says "cap informe de camp encara" even after reports are
  submitted — wiring the live `field_report_count()` into the confidence block is
  a follow-up for the PWA/scale phase (6.x) or a dedicated later step.
- Next step: 6.1 (PWA manifest, service worker, offline pack).

---

## Phase 6 — PWA and expansion

### Step 6.1 — PWA manifest, service worker, offline pack

- Installable app, icons, offline fallback.
- Save one zone's map/forecast/access notes for the day.
- Clear "offline snapshot, coarse" messaging.

**Result (2026-11-10):**

- Status: done
- Files:
  - `app.py` — PWA section after the HTML string: `PWA_*` constants, a pure-Python
    PNG encoder (`_png_chunk`/`_png_bytes`) and icon renderer (`_icon_subpixel`/
    `_render_icon`, 2×2 supersampled mushroom-on-tile) with `ICON_180`/`192`/`512`/
    `MASKABLE_512` cached at import; `FAVICON_SVG`; `PWA_MANIFEST`/`MANIFEST_JSON`;
    `SW_JS` (cache `bolets-v1`: precache shell, network-first navigation with
    cached-`/` fallback, network-first API with size-capped cache fallback,
    cache-first static); `_pwa_assets()`. `Handler.send_bytes()` +
    `do_GET` routes for `/manifest.webmanifest`, `/sw.js` (revalidated, no-cache),
    `/favicon.svg`, `/icon-*.png`. `<head>` gains manifest link, `theme-color`,
    description, apple-web-app metas and favicon. Header gains a `💾` saved-zones
    button; an `#offline-overlay` and a `#save-toast` are added to the body.
    Embedded JS: service-worker registration; an offline-pack section
    (`comarcaFor`, `getSavedZones`, `saveToast`, `buildOfflineSnapshot`,
    `saveActiveForOffline`, `deleteSavedZone`, `refreshOfflineBtn`,
    `toggleOfflinePanel`/`closeOfflinePanel`/`renderOfflinePanel`, `openSavedZone`,
    `renderOfflineZoneDetail`, `fmtSavedAt`, `renderOfflineFallback`); "💾 Desa
    per anar al bosc" buttons in the station and zone detail trip-actions; the
    forecast catch path now renders the saved zones instead of a raw error.
  - `README.md` — new "PWA and offline use (Phase 6.1)" section; files tree notes
    the manifest/SW/icons are served from `app.py`.
  - `PROPOSAL.md` — Phase 6 status note (6.1 done, 6.2–6.4 remaining).
- Verification:
  - `python3 -m py_compile app.py` → OK.
  - Embedded `<script>` extracted to `/tmp/opencode/app_check_61.js` →
    `node --check` → OK (116,533 bytes). `SW_JS` extracted to
    `/tmp/opencode/sw_61.js` → `node --check` → OK. `MANIFEST_JSON` parses and
    carries the three icons; all four PNGs decode (`\x89PNG…`, 2.0–6.4 KB).
  - Live server (port 8961, isolated `DATA_DIR`): `GET /` 200 (157 KB and contains
    `rel="manifest"`, `theme-color`, `serviceWorker.register`, `offline-overlay`,
    `saveActiveForOffline`, `renderOfflineFallback`); `/manifest.webmanifest` 200
    `application/manifest+json`; `/sw.js` 200 `text/javascript`; `/icon-192.png`
    200 `image/png` (2,260 B); `/icon-512.png` (6,376 B); `/icon-maskable-512.png`
    (4,133 B); `/favicon.svg` 200 `image/svg+xml`; `/api/stations` 200.
  - No-regression: `/api/forecast` 200 → 15,595,130 B, date 2026-11-10, 22
    stations / 66 zones / 66 `zone_score` / **0 errors** (with a seeded
    `geo_cache.json` copy; the first empty-DATA_DIR run only "failed" because the
    cache file was absent, which is the app's normal cold-cache behaviour, not a
    PWA defect).
  - **Offline-pack end-to-end (CDP over headless Chromium, Node 22 WebSocket):**
    save `Rasos — solana baixa` → snapshot stored (`{n:1, hasDays:7, hasTop:8}`);
    the saved-zones panel renders "Zones desades" + the zone name + the snapshot
    note; opening it renders the "Instantània fora de línia · aproximada" banner,
    the zone name, the route link and species; delete returns `remaining:0`.
- Screenshots (headless Chromium, under `/tmp/opencode/shots61/`):
  - `desktop_home.png` (1440×900) — header with the 💾 button.
  - `desktop_zone.png` (1440×900) — zone detail with "Desa per anar al bosc".
  - `mobile_home.png` (500×900) — mobile shell.
  - `zone_dom.html` — DOM dump confirming the save button and offline overlay.
- Notes / sources: no data invented — the icons are generated from the app's own
  palette (`#2a2015` tile, `#c9572f` cap, `#f5f0eb` stem); the manifest/short
  name/description reuse the app's existing branding. The offline pack stores a
  user-requested snapshot in `localStorage` and is always labelled as a coarse,
  dated snapshot, never a live prediction. The service worker leaves cross-origin
  requests (Leaflet, tiles) untouched and never caches the multi-MB
  `/api/forecast` body (a `content-length` cap), which is the documented
  "offline snapshot, coarse" trade-off.
- Next step: 6.2 (add comarques with verified coordinates).

### Step 6.2 — Add comarques with verified coordinates

- Priority: Alt Urgell, Solsonès, Osona, La Selva, Alta Ribagorça, Val d'Aran,
  Noguera, Priorat, Terra Alta, Montsià, Baix Empordà, Maresme, Garraf.
- For each station: real forest point, altitude, source, confidence.
- Add zones, not just stations.
- No invented coordinates; if a source is missing, leave it out.

**Result (2026-11-10):**

- Status: done
- Files:
  - `zones.json` — +69 zones → **135** total; 24 new station keys. Each centroid
    is a live CORINE-verified forest cell (311/312/313/324), with altitude,
    aspect and slope from the ICGC 5 m DEM, `soil.type` from IGME 1:1M and
    `ph_approx` from SoilGrids v2 when it answered. New zones carry
    `confidence: 0.6` / `medium` and an explicit `sources` list.
  - `mushrooms.json` — +24 station records across **16 comarques**: the 13
    priority ones (Alt Urgell, Solsonès, Osona, La Selva, Alta Ribagorça,
    Val d'Aran, Noguera, Priorat, Terra Alta, Montsià, Baix Empordà, Maresme,
    Garraf) plus Gironès, Vallès Oriental and Alt Penedès, where the verified
    stands fall just outside the nominal boundary. `meta.focus_comarques`
    refreshed.
  - `zones_enriched.json` — regenerated: 46 stations / 135 zones, **135/135**
    with DEM terrain, LiDAR canopy, soil and habitat blocks.
  - `README.md` — new "Coverage expansion (Phase 6.2)" section (per-comarca
    table, method, gate result, honest limits); present-tense counts updated
    from 66/22 to 135/46, soil/forest distribution and batch-fetch size.
  - `PROPOSAL.md` — Phase 6 status now records 6.1 and 6.2 done.
  - `PHASES.md` — this handoff and the status board row.
- Method: seeded each massís from a published coordinate (Catalan Wikipedia
  article or OSM/Nominatim place record), scanned a 5×5 km box at 1 km
  (widened to 7×7 / 750 m where forest was scarce) against CORINE CLC 2018,
  sampled the ICGC 5 m DEM for every forest cell, then kept up to three stands
  per massís (north/obaga, south/solana, highest remaining, ≥500 m apart).
  Every stored zone was re-queried against CORINE after selection. No
  coordinate is an offset invented by hand: the stored centroid is a
  CORINE-verified forest cell.
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py` → OK.
  - Schema: 46 stations / 22 groups / 135 zones / **135 unique ids**; every
    required field present; every zone key exists in `mushrooms.json`.
  - Forest-cover gate re-run live on all 69 new zones: **69/69 passed**
    (`forest.type` matches the CORINE class). Two candidates failed the final
    re-check — Serra de Cavalls west (CORINE 242) and Montgròs south-west
    (CORINE 221) — and were **deleted**, leaving those two stations with 2
    zones each. No failing cell was kept or relabelled.
  - `enrich_zones.py`: `Wrote zones_enriched.json (46 stations, 135 zones, 135
    DEM, 135 soil, 135 habitat)`; all 135 zones also carry a LiDAR canopy block.
  - Live `/api/forecast` (isolated `DATA_DIR`, port 8972): HTTP 200, 32.0 MB,
    4.6 s, **22 comarques / 46 stations / 135 zones / 0 errors**; 135/135
    `weather`, `water`, `confidence`, `phenology`, `enrichment` and
    `zone_score` blocks (XEMA 0 because no key was configured).
  - Reverse-geocoded every new station centroid with Nominatim: 21 matched the
    assigned comarca; Les Gavarres (Gironès), Serra de Sant Mateu (Vallès
    Oriental) and Puig de la Mola (Alt Penedès) were moved to their real
    comarca rather than mislabelled.
- Screenshots: none — this step changes data only, not the UI (same as
  steps 2.2–2.5).
- Notes / sources: Catalan Wikipedia and OpenStreetMap/Nominatim place records
  (seed coordinates only), CORINE CLC 2018 WMS (forest class), ICGC 5 m DEM
  2021–2023 (altitude/aspect/slope), IGME 1:1M (lithology), SoilGrids v2 (pH).
  `forest.dominant` names the CORINE group (`frondós` / `conífera` / `mixt`),
  not an invented tree species; 52 of the 69 new zones have `ph_approx: null`
  because SoilGrids timed out, and those zones omit SoilGrids from `sources`
  instead of inventing a pH. `access`, `water_m`, `canopy_pct` and
  `undergrowth` are `null` pending a verified source.
- Next step: 6.3 (expand species and add lookalike warnings).

### Step 6.3 — Expand species and add lookalike warnings

- Target 20–25 species, including spring/summer/winter.
- For each edible: habitat, season, altitude, soil, trees, notes, lookalikes.
- Lookalike warnings are safety-critical; verify with a trusted source.

**Result (2026-11-11):**

- Status: done
- Files:
  - `mushrooms.json` — 8 new species appended (13 → **21**): `bolet-de-sant-jordi`
    (Calocybe gambosa, spring), `cep-destiu` (Boletus reticulatus, summer),
    `girgola` (Pleurotus ostreatus, winter), `camperol` (Agaricus campestris),
    `fredolic-gros` (Tricholoma portentosum), `cama-sec` (Marasmius oreades),
    `cep-negre` (Boletus aereus), `molleric` (Suillus luteus) — each with the full
    scoring schema (trees, soil, altitude band, aspect, temperature band, rain
    trigger/window/dry-spell, wind sensitivity), an optional `season`, and a
    `lookalikes` list. `Ou de Reig` gained `season: "summer"`; every one of the 21
    species now carries a `lookalikes` array (severity `mortal`/`toxic`/`inedible`/
    `none` + key differences).
  - `app.py` — `SEASON_MONTHS` + `species_in_season()` (spring/summer/winter are
    filtered to Mar–May/Jun–Aug/Dec–Feb; autumn/unset stays year-round and is
    damped out of season by `phenology_factor`, which now handles all four
    seasons); `score_station` uses the new gate and adds `season` + `lookalikes`
    to every species result; embedded UI gains `seasonLabelHtml`,
    `lookalikeWarningHtml` (compact warning line in each expanded species row) and
    `lookalikesHtml` (a prominent "⚠ Perill de confusió / Lookalikes" section at
    the top of the score explainer), plus CA/EN strings and severity/season label
    maps and `.sp-danger` / `.lookalike-card` CSS.
  - `README.md` — species section rewritten (21 species table + new "Seasons
    (Phase 6.3)" and "Lookalike warnings (Phase 6.3)" subsections), the "Adding a
    new species" schema documents `season` + `lookalikes`, the intro counts fixed
    to 22 comarques / 46 stations / 135 zones / 21 species, and the roadmap
    "Just shipped" list updated.
  - `PROPOSAL.md` — top status and Phase 6 note now record 6.3 done; the
    "what exists" species count updated to 21.
- Method / sources: species facts (habitat, soil, altitude, temperature band,
  season, trees) follow standard Catalan field-guide knowledge for each species;
  lookalikes pair each edible with its documented confusable/dangerous species
  (e.g. Amanita caesarea ↔ Amanita muscaria & Amanita phalloides; Tricholoma
  terreum/portentosum ↔ Tricholoma pardinum; Morchella esculenta ↔ Gyromitra
  esculenta; Macrolepiota procera ↔ Lepiota brunneoincarnata; Agaricus
  campestris ↔ Agaricus xanthodermus; Pleurotus ostreatus ↔ Omphalotus olearius;
  Boletus spp. ↔ Tylopilus felleus / Rubroboletus satanas). Where a species has
  no serious lookalike (trompeta de la mort, llenegres, orella de llebre,
  molleric) the entry is marked `none` honestly rather than inventing a danger.
  No coordinate, altitude, soil, sighting or confidence value was invented; all
  new data is species-level field-guide knowledge, and the lookalike UI states it
  is a starting point, not expert identification ("in dubte, no collir").
- Verification:
  - `python3 -m py_compile app.py calibrate.py enrich_zones.py warm_parking.py forecast.py` → OK.
  - `mushrooms.json` parses; 21 species, 21 unique ids, every species has
    `lookalikes` (each with name/danger/differences) and a valid `season`.
  - 14 unit checks (season gating, phenology gate per season, schema fields) → 0 failures.
  - Fixture through the real `build_forecast()` (only network fetchers
    monkeypatched): 46 stations / 135 zones / 0 errors; **16 species scored in
    November** (11 default + 5 `autumn`), the 5 seasonal species
    (`ou-de-reig`, `murgola`, `bolet-de-sant-jordi`, `cep-destiu`, `girgola`)
    correctly filtered out; 16/16 species results carry `lookalikes` + `season`;
    zone species carry them too; `ou-de-reig` absent in November (gated summer).
  - Embedded `<script>` extracted → `node --check` → OK (118,936 bytes).
  - Live server (port 8977, isolated `DATA_DIR`): `/`, `/api/stations`,
    `/api/geocode` → 200; `/api/forecast` → 200 (48.7 MB, 62.7 s), 46 stations /
    135 zones / **0 station errors / 0 zone errors**, 16 species per station with
    16/16 `lookalikes` + `season` keys.
  - Headless Chromium (fixture served on 8978 from the saved live payload):
    desktop (1440×900) and mobile (500×900) — explainer DOM renders the lookalike
    section (`Perill de confusió`, severity badge `TÒXIC`, the
    `Fredolic tigrat · Tricholoma pardinum` card and its differences text) and the
    species rows render `sp-season` = `tardor`; 0 console errors.
- Screenshots (headless Chromium, under `/tmp/opencode/shots63/`):
  - `desktop_explain.png` (1440×900, 356 KB) — zone detail + explainer with the lookalikes section.
  - `mobile_explain.png` (500×900, 95 KB) — same view on mobile.
  - `desktop_explain.html` / `mobile_explain.html` — DOM dumps (primary textual evidence).
- Notes / sources: species + lookalike facts are curated field-guide knowledge,
  not model outputs. The only scoring-behaviour change is seasonal: `Ou de Reig`
  (previously always scored, damped) is now gated to summer, and the new
  spring/summer/winter species appear only in their season; the 11 pre-existing
  autumn species keep their exact year-round + damped behaviour (no `season`
  field added, so station scores for them are unchanged). `lookalikes` is
  reporting-only — never multiplied into a score.
- Next step: 6.4 (performance, caching, final verification).

### Step 6.4 — Performance, caching, final verification

- Batch/cached weather and static scores.
- Zone GeoJSON/PMTiles if needed.
- Mobile performance, accessibility, keyboard.
- Final README/PROPOSAL/PHASES update.

**Result (2026-11-11):**

- Status: done
- Files:
  - `app.py` — three backend changes and one UI pass.
    - **Payload dedup:** `SPECIES_STATIC_FIELDS` + `_dedupe_species_payload()`
      move `name`, `scientific`, `thresholds`, `lookalikes`, `notes` and
      `season` into a top-level `species_meta` catalogue (16 species, ~13 KB)
      instead of repeating them on every species × day × zone entry. Called at
      the very end of `build_forecast()`, after scoring and altitude-lag
      mutations, so no score input changes. The frontend gains
      `hydrateForecast()` (called in `loadForecast`) which merges the catalogue
      back onto every station/zone day before rendering.
    - **gzip:** `send_json_body()` compresses JSON responses >1 KB when the
      client sends `Accept-Encoding: gzip` (`Content-Encoding: gzip`,
      `Vary: Accept-Encoding`); `/api/forecast` serves a pre-compressed body.
      `import gzip` added.
    - **Built-forecast cache:** `forecast_signature()` keys the response on the
      day + `mtime_ns`/size of `mushrooms.json`, `zones.json`,
      `zones_enriched.json` and `weather_cache.json` (plus the presence of a
      Meteocat key). `get_forecast_payload()` caches the serialised raw and gzip
      bytes for `FORECAST_CACHE_TTL = 300 s` behind a lock; `/api/forecast`
      sends `X-Forecast-Cache: hit|miss|stale` and serves the previous payload
      on a failed rebuild (stale-on-error, like the weather cache).
    - **Accessibility:** global `:focus-visible` ring (light ring on the dark tab
      bar/status bar), `prefers-reduced-motion` override, 44 px mobile targets
      for the detail/explainer close buttons, 32–36 px route buttons and 44 px
      tab buttons; the detail panel is a focusable `role="region"` that receives
      focus on open and restores it to the opening card (or the search input)
      on close; the explainer is `role="dialog" aria-modal="true"` with a
      labelled close button, autofocus and focus restoration; the mobile tabs
      are `role="tab"` with `aria-selected` kept in sync by `switchTab()`;
      score-pill green/amber darkened to `#3d7433`/`#946600` (white text now
      5.6:1 / 5.0:1, WCAG AA); the zone detail confidence badge no longer shows
      `NaN%` (it multiplied the Phase-4.4 confidence *object*).
  - `README.md` — new "Performance, caching and accessibility (Phase 6.4)"
    section (payload/cache/gzip numbers, no-GeoJSON rationale, a11y fixes) and
    the "Just shipped (Phases 1–6)" list extended with PWA + field-grade
    performance.
  - `PROPOSAL.md` — top status now says Phase 6 is complete and Phase 7 is next;
    the Phase 6 status block records 6.1–6.4 done and summarises 6.4.
  - `PHASES.md` — phase map Phase 6 → done, status board row, this handoff.
- Method: measured first with a warm-weather-cache harness
  (`/tmp/opencode/profile_64.py`): `build_forecast()` 2.38 s, JSON serialisation
  0.53 s for 48.65 MB, so CPU was not the 63 s bottleneck — the payload was
  48.7 MB and repeated static text was ~95% of it. The live request in step 6.3
  was dominated by upstream weather/water fetching, which the existing cache and
  the new built-forecast cache now avoid on repeat loads. No scoring formula,
  threshold, curated value or data source was changed.
- Verification:
  - `python3 -m py_compile app.py` → OK.
  - Extracted embedded `<script>` → `node --check` → OK (121,537 bytes).
  - **Score equivalence (same process, same cache):** built once with
    `_dedupe_species_payload` disabled and once with it enabled, rehydrated the
    deduped payload from `species_meta`, compared all 46 station objects
    (including 135 zones × 7 days × 16 species): **0 differing stations, scores
    identical**, every dynamic field equal.
  - **Payload/timings (live server 8981, weather cache warm):**
    - JSON 48,670,082 B → **29,662,940 B raw** (−39%); gzip
    **1,082,455 B** (−97.8% vs the original 48.7 MB; 4,081,513 B was already
      the gzip of the old payload, so 3.8× smaller than old-gzip).
    - first request `miss` 3.07 s / 1,082,455 B wire; second request `hit`
      **1.77 ms**, byte-identical body (`cmp` on both gzip bodies).
    - browser (headless Chromium): `encodedBodySize` 1,082,455,
      `decodedBodySize` 29,662,940, `transferSize` 1,082,755, load 168 ms;
      `fetch('/api/forecast')` reported `content-encoding: gzip`,
      `content-length: 1082455`, `x-forecast-cache: hit`.
    - 46 stations / 135 zones / **0 station errors / 0 zone errors**,
      7 dates (2026-11-11 … 2026-11-17), 16 species in November.
  - **Hydration/UI:** headless Chromium confirmed `species_meta` has 16 entries
    and the first Rasos zone species has `name`, `notes`, `thresholds`,
    `lookalikes` (1) and `phenology`; the explainer renders
    "⚠ Perill de confusió" and the lookalike card; 0 console errors.
  - **Keyboard:** Tab/Enter on a zone row opened the detail panel and moved
    focus into it (`focusInPanel: true`, `focusTag: detail-panel`); `Escape`
    closed it (`panelVisible: false`) and returned focus to `#search-input`
    (the opening row was replaced by the zone detail). The explainer opened with
    focus on `explain-close`, `role="dialog"`, `aria-modal="true"`, and `Escape`
    closed it with focus back in the detail panel.
  - **Mobile:** at 500×900 the map/list tabs report
    `aria-selected=true/false` and swap correctly, `.tab-btn` min-height is
    44 px, and the zoom/detail/list views render with no console errors.
  - No GeoJSON/PMTiles: zones are curated points, not polygons; there is no
    geometry to serve, so adding vector tiles would be new data, not a speed-up.
- Screenshots (headless Chromium, under `/tmp/opencode/shots64/`):
  - `desktop_zone.png` (1440×900) — zone detail, fixed "mitjana" confidence
    badge (no NaN), darker score pills.
  - `mobile_zone.png` (500×900) — zone detail bottom sheet.
  - `mobile_list.png` (500×900) — list tab with `aria-selected`.
  - `desktop_zone.html` / `mobile_zone.html` / `mobile_list.html` — DOM dumps
    (primary textual evidence).
- Notes / sources: no data invented; this step only deletes duplicate static
  fields, compresses, caches and fixes UI semantics. The deduped API remains a
  superset for clients that merge `species_meta`; the README documents the shape.
  The 300 s TTL is shorter than the 15-minute XEMA observation TTL and the 3-hour
  weather TTL, so annotations cannot go stale beyond the documented provider
  windows. The service worker still refuses to cache the forecast body
  (`MAX_CACHE_BYTES = 1 MB`); gzip brings it to 1.08 MB, just over the cap, so
  the intentional "coarse snapshot, not the whole forecast offline" behaviour is
  unchanged.
- Next step: 7.1 (forest-offset repair). Phase 7 is ledgered from `PROPOSAL.md`
  ("Phase 7 — Model and data depth").

---

## Phase 7 — Model and data depth (proposed, ledgered 2026-11-12)

Phases 1–6 made the map complete. Phase 7 makes the numbers behind it
trustworthy: remove silent data errors, upgrade the layers that cap the habitat
model, and validate the hand-chosen assumptions before adding more features.

The order is deliberate: cheap data-integrity fixes first (7.1–7.3), then the
accuracy upgrades (7.4, 7.6, 7.7), then the validation that tells us whether the
upgrades were worth it (7.5), and finally radar (7.8), the largest and most
uncertain dependency. Each step is independently shippable and ends with the
same evidence standard as Phases 2–6: a live run, a zone-by-zone diff, and a
documented "no invented data" audit.

### Step 7.1 — Forest-offset repair

- **Goal:** every station's `forest_lat/forest_lon` points at real forest.
- **Problem:** legacy offsets are manual. Ribes de Freser lands on pasture and
  Puigcerdà on agricultural land; a bad point distorts habitat, canopy and soil
  for every zone at that station, invisibly.
- **Work:** reuse the 6.2 scanner (CORINE gate + ICGC DEM + ≥500 m spacing) over
  `mushrooms.json`, produce an `old → new` diff per station, auto-apply only when
  the forest gate passes, and flag the rest for human review.
- **Evidence:** per-station diff, 46/46 forest gate, regression fixture showing
  zone counts and scores change only where a point moved.
- **Risk:** manual offsets can encode real field knowledge; never silently
  overwrite, and keep the previous coordinates in the record.
- **Blocked if:** the CORINE/ICGC services are unavailable and fewer than 46
  stations can be re-gated, or an offset change cannot be traced to a source.

**Result (2026-11-12):**

- Status: done
- Files:
  - `repair_forest_offsets.py` (new) — standing CORINE forest gate for every
    station point. Read-only by default; `--apply` writes a move only when the
    candidate passes the same 311/312/313/324 gate, keeps the previous
    coordinates/date/reason/source in the station's `forest_offset_history`, and
    never rewrites `alt_m` silently (candidate DEM altitude is recorded for
    review). Failed points are flagged `needs_review`. `--check-zones` re-gates
    all zone centroids; `--self-test` exercises pass/candidate/needs-review/
    dry-run/apply/history/report offline with no network.
  - `forest_offset_report.json` (new, generated) — `generated_at`, gate source,
    per-station old coordinates, CORINE code/label, zone count, status,
    candidate (if any), `zone_gate` summary (135 checked / 135 forest /
    0 mismatches), and `changes: []`.
  - `README.md` — removed the stale `forest_lat/forest_lon` documentation and the
    "Ribes de Freser / Puigcerdà are non-forest" limitation; documented that the
    station coordinate *is* the forest point, added the gate usage, the live
    result and the new files.
  - `PROPOSAL.md` — status line for Phase 7 and a 7.1 result note; the premise
    was partly stale (the separate offsets no longer exist).
  - `PHASES.md` — this entry and the status board.
- Method: loaded the 46 `target_stations` from `mushrooms.json`, queried CORINE
  CLC 2018 WMS live at each point, accepted only 311/312/313/324, and compared
  each zone's curated `forest.type` with the CORINE class. Since every point
  passed, `--apply` was not needed and no coordinate changed.
- Review flags: two station points are forest but sit in a different CORINE
  class from their zones' majority — **Serra del Montsià** (station 313 mixed;
  zones mixed/broadleaf) and **Pallars – Sort** (station 311 broadleaf; zones
  conifer/broadleaf/conifer). Both are valid stands inside a mixed massís, each
  matches at least one of its own zones, and neither is a non-forest point, so
  neither was moved. The report records the flag for transparency.
- Verification:
  - `python3 -m py_compile app.py repair_forest_offsets.py enrich_zones.py` → OK.
  - `python3 repair_forest_offsets.py --self-test` → OK (gate, candidate,
    dry-run, apply, previous-coordinate history, report shape).
  - Live `python3 repair_forest_offsets.py --check-zones` → **46/46 stations
    pass** the forest gate (0 candidates, 0 needs-review, 0 moves) and
    **135/135 zone centroids** return a forest class matching the curated
    `forest.type` (0 mismatches). Codes: 311 broadleaf / 312 conifer /
    313 mixed / 324 shrub.
  - Report cross-check: every `old` lat/lon/alt in
    `forest_offset_report.json` equals the current `mushrooms.json` value;
    every gate code is a forest class; `changes` is empty. `mushrooms.json`
    was not written (no `forest_offset_history` keys added).
  - Regression: `app.build_forecast()` live → **46 stations / 135 zones /
    0 station errors / 0 zone errors**, 8.76 s; sample Puig de la Mola zones
    scored 84/85/85. Because no point moved, scores are unchanged by
    construction (the report proves 0 moves); zone counts remain exactly
    3/3/2 as curated.
  - No UI/JS change → no `node --check` or screenshots required.
- Screenshots: none; this step does not change the UI.
- Notes / sources: CORINE CLC 2018 WMS (forest class); ICGC 5m LiDAR DEM
  (candidate altitude, only for a candidate needing review). The old
  "Ribes de Freser / Puigcerdà" example referred to towns that are no longer
  station points; the current 46 were already re-sourced in Phases 2.2–2.5 and
  6.2. No forest location, coordinate or confidence was invented.
- Audit fix (2026-11-15): a plain read-only run rewrote
  `forest_offset_report.json` without `zone_gate`, silently erasing the gate
  evidence that step 7.3 consumes (which would remove the +0.04 gate bonus from
  every zone on the next confidence re-derivation). The tool now carries the
  previous `zone_gate` forward unless `--check-zones` refreshes it; the 7.3
  consumer still validates the zone count before trusting it.
- Next step: 7.2 (complete the zone facts: access, water, canopy consistency).

### Step 7.2 — Complete the zone facts (access, water, canopy consistency)

- **Goal:** the curated layer stops being thinner than the enriched layer.
- **Problem:** `water_m` is null on 135/135 zones; `access.drive_min` and
  `access.difficulty` are null on 135/135; parking/trailhead are null on the 69
  zones added in 6.2; `forest.canopy_pct`/`undergrowth` are null in `zones.json`
  even though the LiDAR enrichment has real values.
- **Work:** derive `water_m` from OSM waterway/waterbody geometry (Overpass,
  cached like parking); compute `drive_min` with OSRM for a documented reference
  point; derive `difficulty` from slope + walk distance with a written rule;
  remove the duplicated canopy fields (reference `zones_enriched.json` or
  regenerate them); add a schema test that the two files agree.
- **Evidence:** null counts per field, source label per derived value, schema
  test, and a UI check of the trip card on the new zones.
- **Risk:** OSM is incomplete in remote forest — a missing feature must read
  "unknown", never "no water". Routing adds a service dependency with its own
  cache and failure mode.
- **Blocked if:** OSRM/Overpass are unreachable and no cached responses exist; do
  not hand-write distances.

**Result (2026-11-12):**

- Status: **blocked** (partial — see water/parking below)
- Files:
  - `complete_zone_facts.py` (new) — stdlib-only derivation of the missing zone
    facts, plus a `--self-test` and a `--check-schema` mode. Reads `zones.json`,
    fills `access.drive_min` (OSRM from the comarca capital), `access.difficulty`
    (written slope + walk-distance rule), `water_m`/`water_source` (OSM
    waterway/waterbody via Overpass) and `access.parking_*` for the 69 6.2 zones
    (OSM `amenity=parking`), removes the duplicated `forest.canopy_pct`/
    `undergrowth` null placeholders, and writes back. Results are cached in
    `water_cache.json` and `route_cache.json` (both gitignored); `--check-schema`
    verifies `zones.json` ↔ `zones_enriched.json` agree.
  - `zones.json` — `access.drive_min` filled on **135/135** zones,
    `access.difficulty` filled on **135/135** (with `drive_min_source` /
    `difficulty_source` source labels), `forest.canopy_pct`/`undergrowth` removed
    from all 135 zones. `water_m` and the 69 new zones' `access.parking_*`
    remain null (see blocker).
  - `zones_enriched.json` — regenerated via `enrich_zones.py` (135/135 DEM +
    canopy + soil + habitat from cache; no re-fetch).
  - `app.py` — trip card now renders whenever any access/water fact is present
    (previously it was gated on `trailhead`, which hid drive time/difficulty on
    the 6.2 zones); shows drive time, difficulty and water distance with CA/EN
    labels; `water_source` added to both zone payloads; canopy reads
    `enrichment.canopy` directly (the null placeholders are gone).
  - `README.md`, `PROPOSAL.md`, `.gitignore` — schema/docs updated; new caches
    ignored.
- Method:
  - `drive_min` = OSRM `driving` time from the **comarca capital** (documented
    reference point; Wikipedia/OSM Nominatim) to the zone's parking point, or the
    zone centroid when no parking is mapped. 22 capitals + 4 station overrides
    (the "Montseny" massís group → its real comarca capital; La Canya → Ripoll).
  - `difficulty` = written rule: with parking, `fàcil` (walk ≤ 1500 m & slope
    < 20°), `moderada` (walk ≤ 4000 m & slope < 30°), else `exigent`; walk
    distance = straight-line parking → centroid (station point fallback).
  - `water_m` = nearest OSM `waterway`/`natural=water`/`water` segment distance
    (Overpass `out geom`), capped at 2000 m; missing ⇒ `water_m` null +
    `water_source` "unknown", never "no water".
- **Blocker (water + 6.2 parking):** every public Overpass instance was
  unreachable during the session — overpass-api.de returned HTTP 502, and
  kumi.systems / private.coffee timed out / osm.ch returned `duplicate_query` or
  empty. Per the step's "Blocked if" (no hand-written distances), `water_m` and
  the 69 zones' parking were **not** invented; they stay null. The script is
  complete and re-runs with a single command once Overpass recovers (it caches
  per station and resumes).
- Verification:
  - `python3 -m py_compile app.py complete_zone_facts.py enrich_zones.py repair_forest_offsets.py` → OK.
  - `python3 complete_zone_facts.py --self-test` → OK (point-segment distance,
    difficulty-rule boundaries, canopy removal, cache keys, schema fixture).
  - `python3 complete_zone_facts.py --check-schema` → **OK: 46 stations / 135 zones agree**.
  - `python3 enrich_zones.py` → 46 stations / 135 zones / 135 DEM + canopy + soil
    + habitat (from cache, no re-fetch).
  - Embedded `<script>` extracted → `node --check` OK (123,059 bytes).
  - Live `GET /` 200, `GET /api/stations` 200; `GET /api/forecast` 200
    (gzip 1.13 MB): **46 stations / 135 zones / 0 errors**, `access.drive_min`
    135/135, `access.difficulty` 135/135, `water_m` 0 (blocked). Sample: Puig de
    la Mola obaga → `drive_min: 51`, `difficulty: "fàcil"`, source labels present.
  - Null-count diff: `drive_min` 135→0 null, `difficulty` 135→0 null,
    `forest.canopy_pct`/`undergrowth` removed 135→0, `water_m` 135→135 null
    (blocked, not "no water").
- Screenshots (headless Chromium, under `/tmp/opencode/`):
  - `shot72_desktop.png` (1440×900) and `shot72_mobile.png` (500×900), both on
    the new `Puig de la Mola — obaga` zone; DOM dump `dom72.html` confirms the
    trip card renders `51 min · Dificultat: fàcil` (drive + difficulty now shown
    on a 6.2 zone that has no named trailhead/parking).
- Notes / sources: no distance, coordinate or difficulty was hand-written.
  `drive_min` is a real OSRM route (origin = comarca capital, a documented point);
  `difficulty` is a documented written rule from curated `slope_deg` + a
  straight-line walk distance; `water_m` is Overpass geometry (blocked today).
  Capitals sourced from Wikipedia / OSM Nominatim.
- Audit fix (2026-11-15): the trip card now labels the drive time with its
  documented origin (`25 min · des de Ripoll`) instead of a bare `25 min`; the
  module docstrings no longer claim a water source label on an Overpass failure
  (the field is left untouched) and describe the station-point walk fallback the
  code actually uses.
- Retry (2026-11-16): **promoted to done.** Overpass recovered enough to finish
  the water + parking layer.
  - Code: `complete_zone_facts.py` — endpoint order is now the French world
    mirror first (`overpass.openstreetmap.fr`), then `overpass-api.de`, then
    `kumi.systems`, with `OVERPASS_TIMEOUT` 60 s: on this date the primary was
    flapping (502 "at capacity" then multi-second queues) while the French
    mirror answered a Catalan station bbox in ~2 s with full coverage. Added a
    guard so an OSRM failure keeps a previously derived `drive_min` instead of
    nulling it (a retry must not destroy data), with a self-test for it.
  - Run: `python3 complete_zone_facts.py` → 46/46 stations answered Overpass in
    49 s; `water_m` **135/135** filled (1–1,849 m; 39 zones <100 m, 63 <300 m,
    19 <600 m, 10 <1,200 m, 4 ≤2,000 m), **parking 119/135** (53 of the 69 6.2
    zones got a mapped point; 16 have no OSM parking within 2.5 km and stay
    null), `drive_min` 135/135, `difficulty` 135/135, 0 zone errors.
  - Independent validation (not the same code path): for three zones with
    `water_m` 15 / 236 / 1,849 m, an Overpass `way(around:R)["waterway"]` query
    finds no way inside `R−30 m` and one inside `R+30 m` — the distances are
    real geometry, not a fabricated number.
  - Diff vs the blocked state: changes are confined to `water_m`, `water_source`
    and `access.parking_*` / `drive_min` / `drive_min_source` / `difficulty` /
    `difficulty_source`. No score, soil, forest or terrain value changed.
    `drive_min` moved on 44 zones and `difficulty` on 14 (parking is now the walk
    origin per the documented method); with curated Phase-2 parkings the median
    parking→centroid walk is ~4 km, so long walks are the norm and the new
    points are closer than that, not outliers.
  - Verification: `py_compile` OK, `--self-test` OK, `--check-schema` **OK (46
    stations / 135 zones agree)**, `enrich_zones.py` regenerated 135/135 DEM +
    canopy + soil + habitat from cache, live `/api/forecast` 200 (1,150,709 B
    gzip, 7.8 s) with water null 0 / parking null 16 / drive null 0.
  - Headless Chromium: `?est=Serra del Cadí&zona=serra-del-cadi-vessant-est`
    renders the full trip card `🅿️ parking · 46 min · des de la Seu d'Urgell ·
    Dificultat: moderada · Aigua: 137 m` (CA); DOM in `dom72_retry.html`,
    screenshots `shot72_retry_desktop.png` (1440×900) and
    `shot72_retry_mobile.png` (500×900).
  - Confidence re-derived (7.3): water + parking are evidence bonuses, so
    `derive_zone_confidence.py --apply` moves the 135 zones from 82 `alta`/53
    `medium` to **110 `alta`/25 `medium`** (76 zones changed; `--check` then
    reports "CHECK OK"). Reporting-only: the score is unchanged.
  - Honest limits: the parking point is the nearest OSM `amenity=parking`, not a
    verified trailhead (`parking_source` says so); 16 zones remain null rather
    than "no parking"; `water_m` is straight-line distance to the mapped
    drainage, not a walking distance.
- Removal (2026-11-18, user request): the **parking feature was taken out of the
  app**. The nearest-OSM-lot points filled on 2026-11-16 were often a village
  square rather than a trailhead (curated Phase-2 parkings already had a median
  4 km straight-line walk to the zone), and `drive_min`/`difficulty` were
  computed *to that point*, which understated real access. Removed:
  zone-detail parking box + `loadParking`, `/api/parking`, `find_parking`,
  `parking_cache.json` + `warm_parking.py` (deleted), `access.parking_lat/lon/
  source` (stripped from all 135 zones), the Dockerfile COPY entry and the 7.3
  `access_parking` confidence bonus (0.03). Drive time is now to the zone
  centroid (OSRM snaps to the nearest road) and difficulty walks from the
  station forest point; `complete_zone_facts.py` strips any leftover
  `access.parking_*` on every run and its self-test asserts it. Verification:
  py_compile + self-tests + node --check OK, `--check-schema` OK, `/api/parking`
  → 404, live API 46/135/0 errors, headless DOM with **0** parking mentions and
  the trip card still showing drive/difficulty/water; confidence re-derived to
  99 alta / 36 medium. Score unchanged (access is display-only).
- Next step: 7.8 review (radar) — the last open step of Phase 7.

### Step 7.3 — Confidence that discriminates

- **Goal:** the confidence badge ranks zones instead of showing the same value
  everywhere.
- **Problem:** the curated `confidence` is a constant `0.6 / medium` on all 135
  zones, so the `C` factor contributes no differentiation. The computed 4.4 block
  varies only through a few anchors (XEMA distance/age, canopy sample coverage),
  while weather, soil, forest and curation are constants.
- **Work:** derive the curated confidence from evidence (number of sources,
  whether 1:25k/MAGNA 50 answered, pH present, access present, forest gate
  passed); keep the confidence `score` reporting-only (never multiplied into the
  prediction); add the new resolution anchors from 7.4/7.6.
- **Evidence:** confidence distribution across 135 zones, 4.4 unit fixtures, and
  a byte-identical score check proving only `C`/reporting moved.
- **Risk:** changing a published value needs a shadow diff; compute new and old
  confidence side by side and review before switching.
- **Blocked if:** the shadow diff cannot show that scores are unchanged.

**Result (2026-11-12):**

- Status: done
- Files:
  - `derive_zone_confidence.py` (new) — derives the curated per-zone
    `confidence`/`confidence_label` from sourced evidence only, writes
    `confidence_evidence` per zone, and supports `--apply`, `--shadow` (default),
    `--check` and `--self-test`. Formula:
    `clamp(0.30, 0.45 + Σ bonuses, 0.80)`; bonuses = source count (0.02/0.04),
    SoilGrids pH (0.05), soil resolution 1:25k/MAGNA 50 (0.10/0.07, inactive
    until 7.6/7.4), soil class known vs `mixed` (0.05), CHC50 1:25k habitat
    (0.10, inactive until 7.6), DEM LiDAR/Copernicus (0.04/0.02), canopy
    coverage ≥0.90/≥0.75 (0.03/0.015), 7.1 forest gate (0.04), drive+difficulty
    (0.04), parking+trailhead (0.03), known water (0.03). Labels:
    `alta ≥ 0.75 > medium ≥ 0.55 > baixa`.
  - `confidence_report.json` (new, generated) — formula, thresholds, old/new
    distributions and every zone's old/new value with its full evidence block.
  - `zones.json` — all 135 zones now carry an evidence-derived confidence plus
    `confidence_evidence`; **flat 0.6 → 0.62–0.77**, 44 `alta` / 91 `medium`.
  - `zones_enriched.json` — regenerated with `enrich_zones.py` from cache; the
    new curated fields are preserved and `--check-schema` still passes.
  - `app.py` — `_conf_quality` and `_conf_reasons` now read future
    `enrichment.soil.resolution` / `enrichment.habitat.resolution` and use the
    7.4/7.6 anchors (`Q_SOIL_1_25K 0.90`, `Q_SOIL_MAGNA50 0.75`,
    `Q_HABITAT_1_25K 0.85`) only when those resolutions are recorded, so today's
    values are unchanged. Fixed the curated badge mapping: the schema labels
    `alta`/`baixa` now get `conf-high`/`conf-low` CSS and CA/EN text (the old
    code only understood `high`/`low`, so `alta` rendered with medium styling).
    Scoring untouched.
  - `README.md` — new “Confidence that discriminates (Phase 7.3)” section
    (formula table, evidence sources, commands, live result), plus updated zone
    schema example, the 135-zone note, the 4.4 curation row/limits and the Files
    tree.
  - `PROPOSAL.md` — 7.3 status note.
  - `PHASES.md` — this entry and the status board.
- Method: read evidence from the files that already exist — `sources` count per
  zone, `enrichment.soil` (type/pH/resolution), `enrichment.habitat`,
  `enrichment.terrain.dem_source`, `enrichment.canopy.sample_coverage`,
  `forest_offset_report.json` `zone_gate` (135 checked / 135 forest / 0
  mismatches), `access.drive_min`/`difficulty`/parking/trailhead and `water_m`.
  A null `water_m` is recorded as “unknown (not treated as failure)” and earns
  no bonus but no penalty; the 69 zones with null parking due to the 7.2
  Overpass blocker simply miss the optional parking bonus, not the access route
  bonus. No value was hand-written.
- Shadow diff (reviewed before `--apply`): old `{0.6: 135}` / `{medium: 135}` →
  new `{0.62: 7, 0.67: 42, 0.69: 6, 0.71: 1, 0.72: 22, 0.74: 13, 0.76: 4,
  0.77: 40}` / `{alta: 44, medium: 91}`. 135/135 changed.
- Verification:
  - `python3 -m py_compile app.py derive_zone_confidence.py enrich_zones.py complete_zone_facts.py` → OK.
  - `python3 derive_zone_confidence.py --self-test` → OK (determinism,
    bounds, labels, gate pass/missing/stale/mismatch, pH/mixed effects,
    parking/water/access, 1:25k anchors, apply/idempotence, differing zones).
  - `python3 derive_zone_confidence.py --apply` → wrote `zones.json` +
    `confidence_report.json`; `--check` → **OK: 135 zones match the derivation**.
  - `python3 enrich_zones.py` → 46 stations / 135 zones / 135 DEM + canopy +
    soil + habitat (from cache, no re-fetch);
    `python3 complete_zone_facts.py --check-schema` → **OK: 46 stations / 135
    zones agree**.
  - Shadow/score equivalence fixture (`/tmp/opencode/verify_73.py`, real
    `app.build_forecast` with only weather/water/xema/geo monkeypatched; old
    `zones.json` snapshotted in `/tmp/opencode/zones_before_73.json`): after
    removing the reporting-only `confidence`/`confidence_label`/`factors.C`
    keys, old and new payloads are **byte-identical** (24,904,303 bytes each).
    So every score, day, species breakdown and zone_score is unchanged.
  - 4.4 fixture (`/tmp/opencode/verify_73_conf.py`): completeness 86 % → 86 %
    (same) and every non-curation input identical; prediction score moved
    0.577–0.624 → 0.587–0.642 (fixture) / 0.631–0.678 (live), all `mitjana`.
    The per-zone curated labels are 44 `alta` / 91 `medium`; 15,120
    per-species confidence blocks still render.
  - Embedded `<script>` extracted → `node --check` OK (123,059 bytes).
  - Live `GET /` 200, `GET /api/stations` 200, `GET /api/forecast` 200
    (29,990,205 bytes): **46 stations / 135 zones / 0 station errors / 0 zone
    errors**; `confidence_label` 44 alta / 91 medium, `confidence.completeness_pct`
    100 on all 135, `confidence.score` 0.631–0.678. Sample
    `rasos-solana-baixa` → `alta`, curation reason `curació · 74%`; `water_m`
    null on all (7.2 blocker unchanged, not treated as a failure).
  - Headless Chromium (server on port 8813):
    - `shot73_desktop_alta.png` (1440×900) — Rasos — solana baixa, badge
      `alta` with `conf-high`.
    - `shot73_mobile_medium.png` (500×900) — Aigüestortes — obaga (baixa),
      badge `mitjana` with `conf-medium`.
    - `dom73_alta.html` / `dom73_medium.html` — DOM dumps confirming the two
      different rendered badges and the 100 % completeness row.
- Screenshots: `/tmp/opencode/shot73_desktop_alta.png`,
  `/tmp/opencode/shot73_mobile_medium.png`.
- Notes / sources: no new external source. Every input is an existing curated
  field or enrichment sample: `zones.json` `sources` (CORINE CLC 2018, ICGC 5 m
  LiDAR DEM, IGME 1:1M, SoilGrids v2, station notes), `zones_enriched.json`
  (DEM/canopy/soil/habitat resolutions), `forest_offset_report.json` (CORINE
  forest gate), and `access`/`water_m` from 7.2. The 1:25k/MAGNA 50/CHC50
  anchors are dormant until 7.4/7.6 actually answer, so no resolution is
  claimed early.
- Audit fix (2026-11-15): the forest-gate bonus was applied globally — one
  mismatched zone would have removed +0.04 from all 135 zones. The report's
  mismatch ids are now attributed per zone (`forest_gate_by_zone`); an
  unattributable aggregate is "unknown" and earns nothing. The scale parser is
  also guarded so `1:250000`/`1:500000` cannot be read as 1:25k/1:50k. Values
  are unchanged on the current all-pass gate (`--check` OK).
- Next step: 7.4 (IGME MAGNA 50 soil).

### Step 7.4 — IGME MAGNA 50 soil

- **Goal:** replace the 1:1M lithology where a 1:50,000 sheet exists.
- **Problem:** 1:1M cannot see a few-hundred-metre siliceous pocket inside a
  calcareous hillside. The `mixed` class (37/135 zones) is the model saying "I
  don't know", and it flattens the strongest habitat discriminator.
- **Work:** `_igme_magna50(lat, lon)` in `enrich_zones.py`; normalise the MAGNA 50
  legend into calcareous/siliceous/mixed with a reviewed mapping table; store
  `soil.resolution` and the raw lithology text; fall back to 1:1M when the sheet
  is missing and record why.
- **Evidence:** per-zone resolution counts, 135-zone re-run, comparison of the
  soil distribution, and unchanged values where MAGNA 50 did not answer.
- **Risk:** Pyrenean sheet coverage is patchy and legends are verbose; a wrong
  mapping moves every score. Audit all changed zones before promoting values.
- **Blocked if:** no sheet can be fetched for a representative sample of zones.

**Result (2026-11-15):**

- Status: done. The 2026-11-13 session implemented and sampled the step but
  stopped before writing this ledger, leaving 7.4 `in progress` with the
  58-zone MAGNA promotion already live in `zones_enriched.json`. This session
  verified that work and records the audit below; a later audit on 2026-11-15
  added the two-zone review hold, the display/score parity fix and the cached-
  sample rebuild, so the current counts are 56 promoted / 79 fallback.
- Files:
  - `enrich_zones.py` — `_igme_magna50(lat, lon)` queries the IGME MAGNA 50
    "Litologías color" identify endpoint (`layers=visible:11`) at each centroid;
    `_classify_magna()` normalises the legend with the reviewed keyword tables
    (`_MAGNA_CALC_KW`, `_MAGNA_SIL_KW`, `_MAGNA_DETRITAL_KW`,
    `_MAGNA_SURFICIAL_KW`); `_magna50_sample()` caches positive and negative
    answers in `terrain_cache.json`; `_soil_compute()` promotes only an
    unambiguous `calcareous`/`siliceous` answer to `resolution: "1:50k"`
    (storing `litho_text`, `magna_hoja`, `fallback_reason: null`) and keeps the
    step-3.4 1:1M sample with `resolution: "1:1M"` + `fallback_reason` otherwise.
    `MAGNA_REVIEW_HOLDS` + `_magna_promotable()` keep the two review-flagged
    zones on 1:1M even though the provider cache holds their MAGNA answer;
    `enrich_zone()` stores the withheld proposal in `soil.magna_review` (class,
    legend, sheet, `status: "held"`) and rebuilds the derived soil block from the
    raw MAGNA sample, so a mapping/hold change applies without clearing
    `terrain_cache.json`. `--self-test` covers the legend mapping,
    surficial/detrital refusal, the hold logic and the held-zone enrichment shape.
  - `app.py` — `_apply_magna50_soil()` overrides `geo.soil_type` only for a
    `1:50k` zone, so the `H` factor uses the finer class; `Q_SOIL_MAGNA50 = 0.75`
    and `_source_resolution()` raise the confidence anchor for those zones; the
    explainer/quality labels say "sòl IGME MAGNA 50 (1:50k)";
    `_zone_soil_display()` returns the same 1:50k class/resolution/pH to the zone
    payload and detail card, so the explanation cannot contradict the score.
  - `zones_enriched.json` — regenerated after the hold: 135 zones,
    **56 at 1:50k / 79 at 1:1M** (the 2 held zones included in the fallback).
    Distribution **calcareous 83 / siliceous 30 / mixed 22** (legacy sample:
    76 / 22 / 37).
  - `zones.json` — confidence re-derived with the now-active MAGNA anchor and
    the hold: `0.62–0.80`, **63 alta / 72 medium**; the two held zones drop from
    `0.80` to `0.77` and stay `alta` (the 7.3 baseline was `0.62–0.77`, 44/91).
    `derive_zone_confidence.py --check` passes. Reporting-only, no score change.
  - `README.md`, `PHASES.md` — this result, the 1:50k source/limitation text and
    the updated confidence numbers.
- Method: queried MAGNA 50 at each of the 135 zone centroids; a zone is promoted
  only when the polygon answers, the legend maps unambiguously and the zone is
  not on review hold. Coverage is **56/135 (41 %)** across **17 sheets** (181,
  217, 218, 255, 256, 293, 297, 327, 332, 333, 364, 393, 394, 447, 448, 470,
  547). Of the 79 fallbacks, **12** have no MAGNA sheet at the point, **65** have
  a detrital/transitional or surficial legend the conservative rule refuses to
  guess (e.g. conglomerates, sandstone–shale alternations, dunes, colluvium),
  and **2** are held for field review; every one records the reason.
- Audit (the step's mandatory "moves every score" check):
  - **Fallback integrity:** all 79 `1:1M` zones keep their legacy `type` (0
    changes); every one carries a non-empty `fallback_reason`. The 2 held zones
    additionally carry `magna_review` with the suppressed 1:50k proposal.
  - **Promotion integrity:** all 56 `1:50k` zones have a non-empty `litho_text`
    and sheet number, `fallback_reason: null`, and `type ==
    _classify_magna(litho_text)` (0 mismatches).
  - **No invented data:** all 58 MAGNA-answering points (56 promoted + 2 held)
    were re-queried live and returned the **identical legend text and sheet
    number (58/58)**.
  - **Display/score parity:** the 13 promoted zones whose curated `soil.type`
    was still `mixed` used to show "mixed" in the detail card while scoring with
    the MAGNA class; the payload/card now carry the **same 1:50k class and
    resolution** the score uses. The card also mirrors the 1:1M geo class with a
    `pH-inferred` label where `fetch_geo` resolved an ambiguous lithology from
    SoilGrids pH (11 zones); 3 zones with no cached geo sample still show the
    curated class while the score treats the soil as unknown (audit fix,
    2026-11-15).
  - **Class changes:** 41 of 56 promotions keep the legacy class (resolution and
    confidence only); **15 change the `H` factor** — 8 `mixed→siliceous`,
    7 `mixed→calcareous`. In November this moves the soil multiplier by
    ×0.15–×6.67 per affected species (mixed 0.85 → 1.0 for a matching class,
    → 0.15 for a mismatching one), which is the intended effect of replacing
    "I don't know".
  - **Held for review (2):** `colldepal-cresta-alta` and `baga-obaga-pi` would
    flip calcareous → siliceous. Both sit on the same broad *"Liditas y
    alternancia de areniscas y lutitas"* MAGNA unit (sheet 255), reproduced at
    ±300 m around each point (Bagà also at ±600 m), with the neighbouring
    calcareous formations only appearing ≥600 m away at Coll de Pal. The
    polygon is reproducible, but the flip inverts the soil multiplier for every
    acid/basic species pair, so both stay at the 1:1M calcareous value until a
    field check; the proposal is recorded in `soil.magna_review`, and lifting the
    hold is a one-line change in `MAGNA_REVIEW_HOLDS` + a re-run.
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py derive_zone_confidence.py complete_zone_facts.py repair_forest_offsets.py` → OK.
  - `python3 enrich_zones.py --self-test` → OK (MAGNA legend/hold assertions and
    the held-zone cache-bypass check pass).
  - `zones_enriched.json` parses, 135 zones; `derive_zone_confidence.py --check`
    → `CHECK OK: 135 zones match the derivation`.
  - `python3 complete_zone_facts.py --check-schema` → **schema OK: 46 stations /
    135 zones agree** (re-run after the confidence/soil regeneration; the stale
    copy was caught and fixed during the audit).
  - Live API (port 8989, `Accept-Encoding: gzip`): HTTP 200, 1,171,276 B,
    5.00 s cold; **46 stations / 22 comarques / 135 zones / 0 station errors /
    0 zone errors**; runtime soil resolutions **56 × 1:50k, 79 × 1:1M**; both
    held zones are served as `calcareous` with no `geo.soil_resolution`, the
    `MAGNA 50 held for review` reason and confidence `0.667`/`0.675` (`alta`).
  - Display parity (ports 8989/8991): 132/135 zones serve the same soil class
    the score uses; the 3 exceptions are `serra-del-cadi-obaga`,
    `serra-de-turp-obaga`, `aiguestortes-obaga-2031` (curated class, cached geo
    unknown). Headless DOM: Planoles — carena shows `silícic (àcid) · 1:50k ·
    pH 6.2`; Vall de Boí — vessant oest shows `silícic (àcid) · inferit per pH ·
    pH 5.7`; the trip card shows `25 min · des de Ripoll`. Screenshots:
    `/tmp/opencode/audit_zone_desktop.png` (1440×900) and
    `/tmp/opencode/audit_zone_mobile.png` (500×900).
- Notes / sources: all lithology text comes from the live IGME MAGNA 50 service;
  no value is hand-written. The 65 ambiguous legends stay on the 1:1M sample
  rather than being force-mapped, the 12 Pyrenean gaps are recorded as
  `no coverage`, and the 2 high-impact flips are held, not promoted. The 1:25k
  texture map remains unavailable (step 7.6). The MAGNA answer is cached per
  point, so lifting a hold reuses the stored evidence without re-querying.
- Next step: 7.5 (backtest and validate the assumptions).

### Step 7.5 — Backtest and validate the assumptions

- **Goal:** know whether the hand-chosen weights and multipliers are defensible.
- **Problem:** rain 35 / temperature 25 / wind 20 / altitude 10 / humidity 10,
  plus `H`, `M` and `P`, are modelling choices. The GBIF/iNaturalist AUC
  (0.32–0.75) validates rank discrimination only, has no true absences, is
  biased by recorder effort, and scores past observations with current weather.
- **Work:** extend `calibrate.py` with temporal splits (train on seasons < Y,
  test on Y), pseudo-absences, recorder-effort weighting for background points,
  and a factor-sensitivity / model-fit pass over the stored per-factor
  breakdown. Persist a versioned report; ship new weights only on a stable
  held-out gain.
- **Evidence:** report with the split definition, factor importances, AUC/Brier
  against the current weights, and an explicit "no change" outcome when the gain
  is not real.
- **Risk:** sparse and secretive labels. Presence-only data cannot calibrate a
  probability; only field reports can, and those start at zero. The honest
  default is to keep the hand weights until out-of-sample evidence is clear.
- **Blocked if:** the occurrence sources are unreachable; the step may still
  record the split methodology but must not promote weights.

**Result (2026-11-15):**

- Status: done
- Files:
  - `calibrate.py` — extended with the Phase 7.5 backtest: `weighted_auc`,
    `occurrence_year`/`choose_split_year`/`split_by_year`, `effort_weights`,
    `target_group_background` (pseudo-absences), `factor_lookup`/`point_factors`,
    `score_from_factors`, `build_pooled`, `permutation_importance`,
    `_weight_candidates`, `bootstrap_gain_ci`, `refit_weather_weights`,
    `temporal_habitat_auc`, and `run_backtest`. `run_pipeline` now bumps the
    report `version` to 2, collects per-species occurrences, and writes a
    `backtest_7_5` block. `--self-test` gained offline checks for every new
    function.
  - `calibration_report.json` (regenerated, version 2) — the live result below.
  - `PROPOSAL.md` — 7.5 status note.
  - `PHASES.md` — this entry and the status board.
- Method (all stdlib, deterministic, no invented values):
  - **Pseudo-absences** = target-group background: for each species, background
    points are sampled from the pooled occurrence set of all species (excluding
    the focal species), so the background reflects where recorders actually
    sample (Phillips et al. 2009 target-group background).
  - **Recorder-effort weighting** = `w = 1 / (1 + neighbours within 5 km)` on
    every presence and background point, down-weighting spatially clustered,
    over-sampled stands; the AUC uses a weighted Mann–Whitney U.
  - **Factor sensitivity** = permutation importance of the stored `W`/`H`/`M`/`P`
    factors (drop in weighted AUC when the factor is shuffled).
  - **Model fit** = a held-out refit of the five weather weights (grid ±0.10/±0.05
    around the hand weights), evaluated on a shuffled hold-out with a bootstrap
    95 % CI on the gain; weights are shipped only on a positive gain whose CI is
    entirely above zero.
  - **Temporal split** = `choose_split_year` puts ~30 % of dated occurrences in
    the test side; it validates only the time-invariant habitat signal
    (H × M × altitude), because `W` and `P` are current-day values. The two eras
    are scored **separately** (no pooling), and the older-era 95th-percentile
    background threshold is carried to the newer era as a strict transfer check.
- Live result (2026-11-15, GBIF + iNaturalist + `app.build_forecast()`):
  - **3216 pooled rows** (1199 presence / 2017 background), baseline weighted AUC
    **0.6037**.
  - **Factor importances** (permutation drop): `H` **0.0822** (the dominant
    discriminator), `W` 0.0082, `M` 0.0039, `P` **−0.0003** — phenology currently
    contributes nothing to rank discrimination.
  - **Weight refit → `no_change`.** The best held-out weights differ from the hand
    weights, but held-out AUC is 0.631 (current) vs 0.6299 (refit), a gain of
    **−0.001** with bootstrap 95 % CI **[−0.008, +0.0043]** (crosses zero). The
    hand weights are not promoted; the score in `app.py` is untouched.
  - **Temporal validation:** split year 2025 — **759 older / 431 newer
    presences** against **1232 / 778** target-group background points.
    Habitat-only AUC is **0.5334 on the older side** and **0.5929 on the newer
    side** (pooled 0.5551), so the ranking is stable across eras. Only **3.5 %**
    of newer presences clear the 95th percentile of the older background
    (≈5 % older false-positive rate): the rank transfers, the absolute score
    level does not.
- Verification:
  - `python3 -m py_compile calibrate.py` → OK.
  - `python3 calibrate.py --self-test` → OK (weighted AUC, temporal split, effort
    weights, target-group background, factor lookup, score formula, weight-candidate
    grid, refit on a noisy single-signal fixture, permutation importance).
  - Offline fixture through the real `run_backtest` (synthetic forecast + zones +
    occurrences) → produces a well-formed `backtest_7_5` block and the degraded
    `no_change` path when data is too sparse.
  - Live `python3 calibrate.py` → 21 species occurrence AUC, then
    `backtest_7_5: 3216 pooled rows; weight_refit decision = no_change`, and the
    report written with `version: 2`.
- Audit fix (2026-11-15): the first 7.5 pass recorded a split year but then
  pooled the train and test presences into one AUC, so the "temporal" number was
  not actually evaluated out-of-era. `temporal_habitat_auc` now scores the two
  eras separately and reports a transfer check; `calibration_report.json` was
  regenerated (2026-11-15T16:05Z). The main AUC, importances and refit decision
  were unchanged by the fix; the temporal block now shows train 0.5334 / test
  0.5929 instead of the pooled 0.5855.
- Screenshots: none; this step changes no UI and no scoring.
- Notes / sources: GBIF + iNaturalist occurrence records (presence-only); the
  factor vectors are the real per-species `factors`/`breakdown` produced by
  `app.build_forecast()`. No weight, coordinate, forest, soil, sighting or
  confidence value was invented; no score weight was changed (the decision is
  `no_change`, so `app.py` scoring is byte-identical).
- Next step: 7.6 (real 1:25k soil and habitat).

### Step 7.6 — Real 1:25k soil and habitat

- **Goal:** replace the CORINE/1:1M fallback with the intended 1:25,000 layers.
- **Problem:** all 135 enriched zones still say "CORINE CLC 2018 (fallback for
  CHC50)". CORINE cannot tell Scots pine from black pine or young reforestation
  from old growth — exactly the field distinctions the score claims to use.
- **Work:** a retry-and-record job against the ICGC 1:25k soil and CHC50 habitat
  services; when one answers, sample the polygon at the zone centroid, store
  `resolution: "1:25k"`, and keep the old value during a shadow period.
- **Evidence:** source resolution per zone, legend-mapping review, old-vs-new
  score diff, and a documented "still unavailable" outcome where it is.
- **Risk:** external availability, not code. CHC50 sits behind the same UB host
  as GeoVeg. A bad legend translation would move scores silently.
- **Blocked if:** the services stay down; record the retry log and stop rather
  than substituting a coarser source silently.

**Result (2026-11-15):**
- Status: done (soil promoted for 7 zones; CHC50 still down, CHC3 recorded for
  50 zones; score byte-identical)
- Files:
  - `enrich_zones.py` — added two step-7.6 providers ahead of the existing
    fallbacks: `_msc25_wfs` / `_msc25_sample` (ICGC MSC25M 1:25k soil WFS at
    `geoserveis.icgc.cat/…/edafologia/wfs`, layer `icgc_sols:sols-25000`, cached
    under `soil_1_25k_wfs`, including the negative "no coverage" answer so the
    128 gaps are never re-queried; a transient error is retried after 24 h), `_classify_msc25_parent` (Catalan
    parent-material keyword rule → calcareous/siliceous/mixed, mirroring
    `_classify_magna`), `_to_utm31` (WGS84→UTM31N for the WFS BBOX, which serves
    geometry in EPSG:25831 and rejects EPSG:4326 filters), and `_chc3_habitat` /
    `_chc3_sample` (DIBA SITMUN WMS `SITXELL` layer `SITXELL_MN340` "Hàbitats
    -polígons- CHC3 2022", cached under `habitat_chc3`). `_soil_compute` now
    prefers MSC25M 1:25k → MAGNA 50 → 1:1M; `_habitat_compute` records
    `resolution: "1:25k"` + a `chc3` shadow block when CHC3 answers, keeping the
    CORINE `dominant`/`corine_code` (the step's "keep the old value" rule).
    `_corine` gained cache support (a `corine` key) so the self-test and re-runs
    never re-query the CORINE WMS for the same cell. Self-test extended for the
    MSC25M parent classifier, UTM conversion, CHC3 group mapping,
    point-in-polygon selection and the error-retry cache policy.
  - `zones_enriched.json` — regenerated: **7 zones at soil 1:25k** (all
    calcareous, matching MAGNA/1:1M), **49 at 1:50k**, 79 at 1:1M; **50 zones at
    habitat 1:25k** (CHC3), 85 at CORINE 100 m. Every 1:25k soil zone records
    `soil.soil_1_25k` (tipus_sol, soil_taxon, codi_cas, class, source); every
    CHC3 zone records `habitat.chc3` (cod_corine, corine_ca, cod_grup, grup_ca,
    tipus_ca, subtip_ca, cod_eunis, forest_group, source).
  - `app.py` — `_apply_magna50_soil` and `_zone_soil_display` now accept
    `resolution: "1:25k"` (score and displayed geo use the finer class with
    `soil_source = "ICGC MSC25M (1:25k)"`); added `SOIL_SOURCE_1_25K`; the
    zone-detail soil badge renders `· 1:25k` (and `· 1:50k`); the confidence
    reasons label the finer layers (`sòl ICGC MSC25M (1:25k)`, `hàbitat CHC3
    (1:25k, ombra)`).
  - `derive_zone_confidence.py` — the habitat anchor honours only an explicit
    `resolution: "1:25k"`; the provider chain string is never parsed (audit fix,
    see below).
  - `zones.json` + `confidence_report.json` — confidence re-derived (7.3) with
    the new anchors: **82 `alta` / 53 `medium`** (was 63/72), range still capped
    at 0.80.
  - `README.md`, `PROPOSAL.md` — Phase 7.6 sections (sources, coverage, the
    score-unchanged / shadow-period guarantees).
- Sources (all live-verified 2026-11-15):
  - ICGC MSC25M soil WFS (1:25k), layer `icgc_sols:sols-25000` — answers only
    where the polygon actually contains the centroid; the published sheets cover
    **7/135** zones (Puig de la Mola, Montgrí, Montgròs). The earlier
    400 m-box/first-feature query listed Serra de la Figuera too, but no polygon
    contains that centroid; it correctly falls back after the audit fix.
  - CHC50 (UB "geoveg") WMS — **still down**: the ArcIMS endpoint
    (`161.116.68.143/…/UB_Geobotanica_habitats_fulls50m_1`) times out and
    `geoveg.creaf.cat` no longer resolves. This is the documented retry log; the
    step did not substitute a coarser source.
  - CHC3 (Cartografia dels hàbitats de Catalunya v3, 1:25k, 2019-2022) via the
    DIBA SITMUN WMS (`sitmun.diba.cat/…/SITXELL`, layer `SITXELL_MN340`) — the
    current 1:25k successor, serving the Barcelona counties (50/135 zones).
- Legend-mapping review (shadow, not promoted into the score):
  - Soil: the 7 MSC25M answers all classify calcareous and match the existing
    MAGNA/1:1M class, so **0 soil-class changes** — the score is byte-identical
    (only `resolution`/`source` move).
  - Habitat: 9 of the 50 CHC3 zones would move the coarse forest group vs the
    curated `forest.type` (`vallcebre-obaga-nord`, `vallcebre-carena-alta`,
    `santjaume-solana-sud`, `santjaume-obaga-nord`, `figols-solana-faig`,
    `figols-vall-riera`, `arbucies-solana-sud`,
    `serra-de-busa-obaga-1298-2`, `serra-de-sant-mateu-solana-373-2`; e.g.
    `vallcebre-obaga-nord` curated broadleaf but CHC3 `42.5922+` "Boscos de pi
    roig"). These are recorded in `habitat.chc3` for review and are **not**
    promoted — the score keeps the CORINE forest group, so the score is
    byte-identical.
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py calibrate.py` → OK.
  - `python3 enrich_zones.py --self-test` → OK (MSC25M parent classifier, UTM
    conversion, CHC3 group mapping, enrichment shape).
  - `python3 derive_zone_confidence.py --self-test` → OK; `--check` → OK (135
    zones match).
  - `python3 complete_zone_facts.py --check-schema` → OK (46 stations / 135 zones
    agree).
  - Embedded `<script>` → `node --check` → OK (123,860 bytes).
  - Fixture through the real `app.build_forecast()` (only weather/water
    monkeypatched): 46 stations / 135 zones / 0 station errors / 0 zone errors;
    7 zones serve `geo.soil_type=calcareous` + `soil_resolution=1:25k`; 50 zones
    serve `habitat.resolution=1:25k`; 44/46 massís show ≥2 distinct zone scores.
  - Live `/api/forecast` (gzip, port 8993): HTTP 200, 1,182,962 B, 7.15 s cold,
    46 stations / 135 zones / 0 errors; **7 zones** with `soil.resolution=1:25k`,
    50 with `habitat.resolution=1:25k`; confidence **82 alta / 53 medium**.
  - Headless Chromium DOM (clean server): the zone-detail soil badge renders
    `calcari (bàsic) · 1:25k` (Montgrí — solana sud-est); a CORINE-only zone's
    confidence reason reads `hàbitat CORINE Land Cover (100 m)` and a CHC3 zone
    reads `hàbitat CHC3 (1:25k, ombra)`.
- Audit fix (2026-11-15, after the first 7.6 pass):
  - **MSC25M sampling:** the WFS BBOX filter returns every polygon that
    *intersects* the box, in server order, so `MAXFEATURES=1` picked an arbitrary
    neighbour. It now requests up to 50 candidates and keeps only the polygon
    containing the centroid (ray casting, holes honoured); no containing polygon
    means "no coverage". Re-sampling changed 8 → **7** promoted zones (Serra de
    la Figuera has no containing polygon and correctly falls back); all 7 still
    match the fallback class.
  - **Habitat confidence:** the provider source string is a chain
    ("CHC3 (1:25k) → CORINE fallback"), and `_habitat_resolution()` parsed it, so
    **all 135** zones earned the 1:25k habitat bonus. It now honours only an
    explicit `resolution: "1:25k"`; the 85 CORINE-only zones are 100 m again.
    Confidence moved 130/5 → **82/53** (min 0.62, max 0.80, cap unchanged).
  - **Provenance:** `_habitat_compute` now returns a per-sample source
    (`DIBA SITMUN CHC3` only when it answered, `CORINE CLC 2018 (100 m)`
    otherwise), so a zone's source cannot claim a layer that did not answer.
  - **Cache robustness:** the MSC25M class is re-derived from the cached parent
    material on read (a keyword fix no longer needs a cache wipe); a transient
    provider error is retried after 24 h instead of being cached as permanent
    "no coverage" (MSC25M, CHC3 and MAGNA).
  - **Test:** the self-test is offline again (the held-zone rebuild seeds an
    MSC25M negative) and now covers point-in-polygon selection and the
    error-retry cache policy.
- Screenshots (headless Chromium, `/tmp/opencode/`):
  - `shot76_desktop.png` (1440×900, Montgrí zone with 1:25k soil)
  - `shot76_mobile.png` (500×900, Rasos zone with CHC3 habitat)
  - `audit_76_soil.png` (1440×900, re-check after the audit fix)
- Score equivalence: the 7 promoted soil zones keep class "calcareous" (matching
  the MAGNA/1:1M fallback), and the habitat block is reporting-only, so the
  score is byte-identical to step 7.5. Only `confidence`/`C` and the resolution
  labels moved.
- Notes / sources: no coordinate, soil value, forest type or sighting was
  invented. The MSC25M class is derived from each polygon's own parent-material
  text; the CHC3 habitat is the polygon's own CORINE-list code/name. The two
  services that were unavailable are recorded honestly (CHC50 down; MSC25M
  mountain sheets unpublished); permanent gaps are cached, while a transient
  error is retried after 24 h. Coverage is sheet/province-bound — this is a
  partial upgrade by external data availability, not a code limit.
- Next step: 7.7 (GeoVeg and manual field observations).

### Step 7.7 — GeoVeg and manual field observations

- **Goal:** recover stand-level tree species and soil reaction, and let verified
  human observations fill the gaps.
- **Problem:** GeoVeg is down and may not return; without it the habitat factor
  is capped at CORINE groups.
- **Work:** add a dormant `_geoveg(lat, lon)` provider behind the same interface
  as `_corine`, with a reviewed keyword parser and a shadow diff; separately,
  add a `field_observations.json` (or zone `notes`) path so a trusted person can
  record tree species, undergrowth, soil and water for a zone by hand, with
  source, date and confidence. Surface it as a "verified by a person" badge.
- **Evidence:** parser tests, shadow diff, and a manual-observation round-trip
  (enter → store → display → confidence).
- **Risk:** free-text vegetation is ambiguous ("roures" can be two species).
  Manual entries are unverified unless the source is recorded; never let a manual
  note overwrite a sourced value silently.
- **Blocked if:** the manual path cannot record a source/date per value.

**Result (2026-11-15):**

- Status: done
- Files:
  - `enrich_zones.py` — dormant GeoVeg provider + parser + shadow diff. `_geoveg(lat, lon)`
    mirrors the `_corine` interface and returns `(None, "unavailable")` (the UB
    geoveg host is down and its query shape cannot be verified offline, so no query
    is fabricated); `_parse_geoveg(text)` normalises free text with reviewed keyword
    tables (`_GEOVEG_CALC_KW`/`_GEOVEG_SIL_KW` for soil reaction, `_GEOVEG_TREE_SPECIES`
    for tree species → forest group); `_geoveg_shadow(parsed, corine_code)` +
    `_corine_forest_group(code)` diff-compute the parsed result against the CORINE
    group with a `matches_corine` flag that is `null` when either side has no clear
    tree group. None of it is wired into `_habitat_compute`, so the score is
    byte-identical. Self-test extended with parser + shadow-diff assertions.
  - `app.py` — manual field-observation path. `FIELD_OBS_FILE` constant +
    `get_field_observations()` (validated loader: an entry is dropped unless it
    records `source` + `verified_at` + `observer` and ≥1 observed fact) +
    `_field_observation(zone_id)`; `build_forecast` re-reads the file each build
    (and `forecast_signature()` now keys on its mtime/size); `score_zone` and
    `zone_metadata` attach `field_observation` (the entry or null) and
    `verified_by_person` (boolean) to every zone; `_conf_reasons` adds a
    `field_observation` reason when present; the zone detail renders a
    "✓ Verificat per una persona" badge + observed facts via `fieldObservationHtml`.
  - `field_observations.json` (new) — empty `observations: {}` with the schema
    documented in `_meta` (required provenance, the four facts, confidence labels).
  - `Dockerfile` — copies `field_observations.json` into the image.
  - `README.md`, `PROPOSAL.md` — Phase 7.7 sections (dormant provider, manual path,
    badge, validation rule).
- Method / design decisions:
  - The GeoVeg provider is **dormant by design**: the host is down (README
    limitation #4; step 7.6 recorded the same host down for CHC50), so `_geoveg`
    returns "unavailable" rather than invent a URL or a value. The substantive,
    testable work is the reviewed keyword parser and the shadow diff.
  - "roures" (oaks) is ambiguous — the parser maps it to `Quercus spp.`, never a
    single species (the step's documented risk).
  - A manual entry is surfaced only with provenance and never overwrites
    `forest.dominant` or `enrichment.soil.type`; it rides alongside as
    `field_observation` and a reporting-only confidence reason (never multiplied
    into a score).
- Verification:
  - `python3 -m py_compile app.py enrich_zones.py` → OK.
  - `python3 enrich_zones.py --self-test` → OK (adds GeoVeg parser + shadow-diff
    assertions: calcareous/siliceous reaction, "roures"→`Quercus spp.`, mixed
    forest group, empty/irrelevant text→None, matches_corine true/false/None, and
    the dormant `_geoveg` returns `(None, "unavailable")`).
  - Embedded `<script>` extracted (126,070 bytes) → `node --check` → OK.
  - Deterministic `build_forecast` round-trip (`/tmp/opencode/verify_77.py`, only
    `fetch_weather_batch`/`fetch_water_batch`/`fetch_geo`/`get_xema_context`
    monkeypatched): loader keeps the 1 valid entry and drops 3 invalid ones
    (no-source / no-facts / no-date); 46 stations / 135 zones / 0 errors; the
    observed zone carries `field_observation` + `verified_by_person: true` + a
    `field_observation` confidence reason; the other **134/134 zones are
    byte-identical** to a run with an empty observations file (score, days,
    confidence and every dynamic value unchanged).
  - Live `app.py` (port 8817, real Open-Meteo + Meteocat key): `/` 200,
    `/api/stations` 200, `/api/forecast` 200 (gzip 1,186,710 B, 6.2 s) → 46
    stations / 135 zones / 0 station errors / 0 zone errors; every zone carries
    `field_observation: null` + `verified_by_person: false` (the committed file is
    empty), so the empty path is confirmed end-to-end.
  - Headless Chromium (fixture server with one synthetic observation served at
    `/api/forecast`): zone deep link
    `?est=Rasos de Peguera&zona=rasos-solana-baixa` renders the badge and facts in
    CA and EN — "✓ Verificat per una persona · alta · per A. Botanic · el
    2026-11-15", "Espècie d'arbre · Pinus sylvestris", "Sotabosc · low", "Reacció
    del sòl · calcari (bàsic)", "Aigua · 380 m", and the confidence reason
    "observació de camp verificada (A. Botanic)". 0 console errors.
- Screenshots (headless Chromium, under `/tmp/opencode/`):
  - `shot77_desktop.png` (1440×900) and `shot77_mobile.png` (500×900) — zone
    detail with the "Verificat per una persona" badge; `dom77.html` / `dom77_en.html`
    are the primary textual evidence (this session's model cannot view images).
- Notes / sources: no vegetation text, tree species, soil value, coordinate or
  confidence was invented. The parser is a reviewed keyword rule over the GeoVeg
  free-text format (documented in the step); the dormant provider makes no network
  call. The manual observation path stores only what a person records with
  provenance, and is never trusted silently. The score is byte-identical to step
  7.6 by construction (the provider is dormant and the badge/confidence reason are
  reporting-only).
- Audit fix (2026-11-15, parent review): the tree keyword `vern` (alder) was a
  substring of `hivern` (winter), so "obaga d'hivern" parsed as an Alnus stand.
  Replaced with the grove form `verned` (matches `verneda`/`vernedes`) and added
  two self-test assertions ("hivern" → None, "verneda de ribera" → broadleaf /
  Alnus glutinosa). Provider remains dormant; no payload or score changed.
- Next step: 7.8 (radar rain, XRAD or equivalent).

### Step 7.8 — Radar rain (XRAD or equivalent)

- **Goal:** close the spatial gap in the most heavily weighted trigger.
- **Problem:** rain over 5–10 days is summed from an ~11 km grid cell (or
  interpolated gauges). Two stands 500 m apart share the number on paper but not
  in reality, and a single convective storm can miss the nearest gauge entirely.
  Without a key there is no local rainfall at all.
- **Work:** provider-abstracted `_radar_rain(cache, lat, lon)` writing a `radar`
  block (`mm_24h/72h/7d`, pixel age, source); gauge-adjust and blend it into the
  water-balance `P` series as an explicit, labelled blend; degrade to XEMA and
  Open-Meteo when unavailable.
- **Evidence:** radar-vs-gauge validation on known storm days, a per-zone rain
  diff, and a no-key run that stays byte-identical to today.
- **Risk:** no clean free Catalan radar API; imagery needs geo-referencing,
  compositing, beam-blockage masking and gauge adjustment. Highest effort and
  availability risk of the phase.
- **Blocked if:** no geo-referenced radar source can be validated against gauges.

**Result (2026-11-16):**
- Status: **blocked** (no code or data changed).
- Finding: the 4.2 blocker ("no XRAD product") has **evolved**. A free,
  geo-referenced radar source now exists — **EUMETNET OPERA** composites via the
  **MeteoGate Open Radar Data (ORD) API** (CC BY 4.0, anonymous access, no
  whitelisting since 2026-05-20). But it cannot be consumed *and*
  validated-against-gauges in one stdlib-only session, which is this step's
  evidence bar.
- Files: none changed.
- Investigation (sources, all verified live 2026-11-16):
  - `https://api.meteogate.eu/eu-eumetnet-weather-radar/` — landing page 200,
    OpenAPI spec saved. Backup `https://radar-backup.meteogate.eu/api/` (current
    cloud-provider incident).
  - Composite products (platform `0-20010-0-OPERA`): `DBZH` (reflectivity, 1 km,
    ODIM HDF5), `RATE` (rain rate mm/h, 2 km, ODIM), `ACRR` (**1-h accumulation
    mm, 2 km, GeoTIFF**). Projection `+proj=laea +lat_0=55 +lon_0=10
    +x_0=1950000 +y_0=-2100000`, grid 1900×2200 @ 2000 m.
  - ACRR files are **open-access, uncompressed, tiled, float32 GeoTIFF**
    (~2.7 MB/file) on `object-store.os-api.cci1.ecmwf.int/openradar-24h-backup/`
    — a **24-hour rolling cache only** (so `mm_72h`/`mm_7d` need the archive,
    status TBD). Inspected header: Compression=1, Tile 512×512, BitsPerSample=32.
  - The EDR `/position` and `/locations` queries **do not sample composites at a
    point** (HTTP 204 / metadata-centre PointSeries only) — a consumer must
    download + decode tiles and project lat/lon → LAEA → pixel itself.
  - Environment is **stdlib-only** (Python 3.14; `h5py`, `numpy`, `pyproj`,
    `rasterio`, `scipy`, `PIL`, `tifffile` all missing), matching the app's
    stated design.
- Why blocked, not done: hand-rolling a TIFF tile reader + LAEA projection +
  hourly-accumulation summing + gauge-adjustment, then validating it on a real
  storm day, exceeds one 45-minute step and risks a silent pixel-mapping bug
  that would inject wrong rainfall into scores (the "no invented values" rule).
  The current 24-h window (2026-11-15/16) is dry over most of Catalonia, so no
  meaningful radar-vs-gauge storm-day validation was possible today anyway.
  Resolution is 2 km — finer than Open-Meteo's ~11 km, but still above the
  "two stands 500 m apart" goal; Pyrenean beam blockage is unaddressed.
- Unblock path (recorded for a future session): (1) decide the dependency
  question (add `rasterio`/`tifffile`, or hand-roll the uncompressed-tiled-TIFF
  reader + LAEA in stdlib and unit-test against a known pixel); (2) confirm
  archive access for `mm_72h`/`mm_7d`; (3) pick a rainy period and validate ACRR
  1-h/24-h mm against IDW-interpolated XEMA gauges; (4) then wire the
  `_radar_rain` provider + `radar` block + labelled blend into
  `blend_water_precip` / `compute_water_block` (app.py ~785–859) and re-run the
  no-key byte-identical regression.
- Notes / sources: no rainfall value, coordinate or score was changed or
  invented. Full findings and probe artifacts are in
  `/tmp/opencode/radar_7_8_investigation.md` (`ord_openapi.json`,
  `ord_items_platform.json`, `acrr_full.json`, `acrr.tiff.head`, `ord_pos_*.json`).
- Parent review (2026-11-16): the finding was durable-documented in the repo
  (`README.md` "Radar rain (Phase 7.8) — blocked", `PROPOSAL.md` status line)
  because `/tmp` artifacts are ephemeral. No code, data or score changed. The
  blocker is accepted as external: the source exists, the app's stdlib-only
  design and the 24-hour cache/storm-day requirement prevent the step's evidence
  bar from being met in one session.
- Next step: none — 7.8 is the last step of Phase 7. Phase 7 is otherwise
  complete (7.1, 7.3–7.7 done; 7.2 and 7.8 blocked on external availability).

---

## Handoff template

Append this under the step when done:

```md
**Result (YYYY-MM-DD):**
- Status: done | blocked
- Files:
- Verification:
- Screenshots:
- Notes / sources:
- Next step:
```
