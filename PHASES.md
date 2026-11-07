# Bolets implementation phases

This is the execution ledger for the `/phase` command. It is the single source of
truth for what is done, what is next, and what "done" means for each step.

## How to use

```text
/phase next          # first step that is not done
/phase 2             # first not-done substep of phase 2
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
| 2 | Micro-zones | Replace one station circle with independently scored forest zones | Every massís has real zones with altitude band, aspect, canopy, soil and access; the UI explains why two stands 500 m apart score differently | in progress |
| 3 | Terrain and canopy science | Replace coarse point samples with DEM, LiDAR, soil and habitat features | Each zone is scored with aspect, slope, solar radiation, TPI, cold-air pooling, canopy/undergrowth and 1:25k soil/habitat; every factor is sourced and explainable | todo |
| 4 | Weather quality | Make the weather local, elevation-corrected and water-balance aware | Zone-level weather from XEMA/radar, drought/recharge, confidence and phenology; a 7-day forecast reliable enough to plan a trip | todo |
| 5 | Field loop | Close the loop with trip reports, logbook and alerts | Reports calibrate the model; published AUC/Brier; private logbook, photos, yield stats and alerts that improve every season | todo |
| 6 | PWA and expansion | Make it field-ready and cover more of Catalonia | Installable offline PWA, all Catalonia, 20–25 species, verified locations and field-grade performance | todo |

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

**Phase 5 — Field loop.** Main: capture what actually happened in the field.
End: a calibrated model with published accuracy, a private logbook and alerts.

**Phase 6 — PWA and expansion.** Main: offline field use and geographic/species
coverage. End: an installable Catalonia-wide app with 20–25 verified species.

## Status legend

- `todo` — not started
- `in progress` — a session is working on it
- `done` — implemented and verified
- `blocked` — cannot proceed safely; reason recorded

## Status board

| Step | Title | Status | Session | Evidence |
|---|---|---|---|---|
| 1 | Map navigation and free features | done | 2026-11-07 | `app.py`, `README.md`, `PROPOSAL.md`, `warm_parking.py`, `parking_cache.json`, `Dockerfile`; py_compile + node --check + API + headless screenshots |
| 2.1 | Zone schema and per-zone scoring (no UI) | done | 2026-11-07 | `zones.json`, `app.py`, `README.md`, `Dockerfile`; py_compile + API curls + 22-station regression + two-zone fixture |
| 2.2 | Curate Berguedà zones | done | 2026-11-07 | `zones.json` (15 zones), `mushrooms.json` (5 station coords/alt corrected); every zone re-sourced from CORINE 2018 + Copernicus DEM + IGME + SoilGrids; 15/15 pass the forest-cover gate; API 200 / 22 stations / 6 comarques |
| 2.3 | Curate Ripollès zones | done | 2026-11-07 | `zones.json` (+15), `mushrooms.json` (5 station coords/alt/notes corrected); 15/15 forest-cover gate; API 200 / 22 stations / 30 zones / 6 comarques |
| 2.4 | Curate Cerdanya zones | done | 2026-11-07 | `zones.json` (+9), `mushrooms.json` (3 station coords/alt/notes corrected); 9/9 CORINE forest-cover gate; API 200 / 22 stations / 6 comarques / 39 zones |
| 2.5 | Curate Montseny, Garrotxa, Pallars zones | done | 2026-11-07 | `zones.json` (+27 → 66), `mushrooms.json` (9 stations re-sourced); 27/27 CORINE forest-cover gate; ICGC 5m LiDAR + IGME + SoilGrids probes; schema valid; score_zone path verified |
| 2.6 | Zone UI: map, list, detail, comparison | in progress | 2026-11-07 | — |
| 2.7 | Phase 2 verification and docs | todo | — | — |
| 3.1 | Terrain enrichment skeleton and cache | todo | — | — |
| 3.2 | DEM: aspect, slope, solar radiation, TPI, cold air | todo | — | — |
| 3.3 | LiDAR: canopy cover, height, undergrowth proxy | todo | — | — |
| 3.4 | ICGC 1:25k soil and habitats | todo | — | — |
| 3.5 | Integrate terrain factors into scoring and explainer | todo | — | — |
| 3.6 | Phase 3 verification and docs | todo | — | — |
| 4.1 | Batch weather and elevation correction | todo | — | — |
| 4.2 | Meteocat XEMA and radar | todo | — | — |
| 4.3 | Soil water balance and drought index | todo | — | — |
| 4.4 | Per-zone data confidence | todo | — | — |
| 4.5 | Phenology and altitude lag | todo | — | — |
| 4.6 | Phase 4 verification and docs | todo | — | — |
| 5.1 | Trip report model, SQLite, API | todo | — | — |
| 5.2 | 30-second trip report UI | todo | — | — |
| 5.3 | Personal logbook | todo | — | — |
| 5.4 | Private photos and privacy rules | todo | — | — |
| 5.5 | Alerts (web push / Telegram) | todo | — | — |
| 5.6 | Calibration and published metrics | todo | — | — |
| 5.7 | Phase 5 verification and docs | todo | — | — |
| 6.1 | PWA manifest, service worker, offline pack | todo | — | — |
| 6.2 | Add comarques with verified coordinates | todo | — | — |
| 6.3 | Expand species and add lookalike warnings | todo | — | — |
| 6.4 | Performance, caching, final verification | todo | — | — |

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

### Step 2.7 — Phase 2 verification and docs

- Update README with zone schema and how to add a zone.
- Update `PROPOSAL.md` status.
- Run the full verification suite.
- Record evidence in this file.
- Next: Phase 3.

---

## Phase 3 — Terrain and canopy science

**Goal:** replace coarse point samples with terrain- and canopy-aware zone
features.

### Step 3.1 — Terrain enrichment skeleton and cache

- New `enrich_zones.py`.
- Read `zones.json`, enrich each zone, write `zones_enriched.json` (or a cache).
- Cache by rounded lat/lon and record source + timestamp.
- No scoring changes yet.

### Step 3.2 — DEM features

- ICGC 5 m DEM or SRTM 30 m fallback.
- Compute altitude, slope, aspect, curvature, TPI, cold-air pooling proxy, and
  solar radiation (annual/seasonal).
- Store all values with units and source.

### Step 3.3 — LiDAR canopy

- ICGC LiDAR canopy height model.
- Compute canopy cover %, canopy height, undergrowth proxy, edge density.
- Mark coverage gaps as unknown, not zero.

### Step 3.4 — ICGC 1:25k soil and habitats

- Query ICGC soil WMS/ArcGIS at each zone.
- Map calcareous/siliceous/pH/texture.
- Query ICGC habitats/land cover for dominant tree group.
- Keep IGME/CORINE as fallback.

### Step 3.5 — Integrate factors into scoring and explainer

- Add `H` (habitat), `M` (microclimate), `W` (weather), `P` (phenology) and `C`
  (confidence) to the score breakdown.
- Keep the existing factor names for compatibility where possible.
- Update the "why this score" explainer with the new values and sources.
- Do not claim probability; call it a relative index.

### Step 3.6 — Phase 3 verification and docs

- Regression test the 22 stations and all zones.
- Verify no invented values: every field has a source.
- Update README/PROPOSAL/PHASES.
- Next: Phase 4.

---

## Phase 4 — Weather quality

### Step 4.1 — Batch weather and elevation correction

- Batch Open-Meteo requests for zones (multiple coordinates per call).
- Apply lapse-rate correction from the station/grid altitude to the zone
  altitude.
- Cache per day.

### Step 4.2 — Meteocat XEMA and radar

- Add optional `METEOCAT_API_KEY`.
- Fetch XEMA station observations and XRAD radar accumulation.
- Interpolate to zones; record station distance and data age.
- Keep Open-Meteo fallback.

### Step 4.3 — Soil water balance and drought index

- Track precipitation minus evapotranspiration over the season.
- Add a drought/recharge index; do not rely only on 7-day mm.
- Calibrate thresholds per species.

### Step 4.4 — Per-zone data confidence

- Separate data completeness from prediction confidence.
- Confidence reasons: nearest station distance, data age, DEM/LiDAR/soil
  coverage, number of field reports.
- Show confidence per zone and per species.

### Step 4.5 — Phenology and altitude lag

- Growing-degree days, season, altitude lag.
- Show the "rovelló wave" moving up/down with altitude and date.

### Step 4.6 — Phase 4 verification and docs

- Verify weather values against a known station day.
- Record sources/timestamps.
- Update docs. Next: Phase 5.

---

## Phase 5 — Field loop

### Step 5.1 — Trip report model, SQLite, API

- SQLite table for reports: rounded 1 km cell, comarca, species, found/not found,
  quantity, duration, date, time, model score at the time, device hash, created_at.
- `POST /api/reports`, `GET /api/reports?bbox=&days=`.
- Moderation and abuse limits.
- Never store or expose exact coordinates by default.

### Step 5.2 — 30-second trip report UI

- Species multi-select, found/not found, quantity, duration, date.
- GPS current location or map point.
- Privacy note; exact position rounded before saving.
- Works on mobile, one hand.

### Step 5.3 — Personal logbook

- Local-first trips and finds; optional account later.
- Yield stats by zone/species/season.
- Private by default.

### Step 5.4 — Private photos and privacy rules

- Optional photo upload, EXIF stripped client and server.
- Private storage; no public map by default.
- Explicit consent for social sharing without location.

### Step 5.5 — Alerts

- Web push or Telegram/email digest.
- Rule: "Rovelló window opened at <zone>".
- Include confidence, data date, and unsubscribe.

### Step 5.6 — Calibration and published metrics

- Train/validate on reports + GBIF/iNaturalist with held-out data.
- Publish AUC/Brier and calibration curve.
- Do not overfit to single reports.

### Step 5.7 — Phase 5 verification and docs

- Privacy review, rate limits, deletion path.
- Update docs. Next: Phase 6.

---

## Phase 6 — PWA and expansion

### Step 6.1 — PWA manifest, service worker, offline pack

- Installable app, icons, offline fallback.
- Save one zone's map/forecast/access notes for the day.
- Clear "offline snapshot, coarse" messaging.

### Step 6.2 — Add comarques with verified coordinates

- Priority: Alt Urgell, Solsonès, Osona, La Selva, Alta Ribagorça, Val d'Aran,
  Noguera, Priorat, Terra Alta, Montsià, Baix Empordà, Maresme, Garraf.
- For each station: real forest point, altitude, source, confidence.
- Add zones, not just stations.
- No invented coordinates; if a source is missing, leave it out.

### Step 6.3 — Expand species and add lookalike warnings

- Target 20–25 species, including spring/summer/winter.
- For each edible: habitat, season, altitude, soil, trees, notes, lookalikes.
- Lookalike warnings are safety-critical; verify with a trusted source.

### Step 6.4 — Performance, caching, final verification

- Batch/cached weather and static scores.
- Zone GeoJSON/PMTiles if needed.
- Mobile performance, accessibility, keyboard.
- Final README/PROPOSAL/PHASES update.

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
