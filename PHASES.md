# Bolets implementation phases

This is the execution ledger for the `/phase` command. It is the single source of
truth for what is done, what is next, and what "done" means for each step.

## How to use

```text
/phase next          # first step that is not done
/phase 2             # first not-done substep of phase 2
/phase 2.1           # exactly step 2.1
/phase-status        # read-only status report
```

Every `/phase` invocation runs in a **fresh child session** (`subagent: true`),
so the next step does not inherit the previous step's context. The parent session
stays available for review and decisions.

**One step per session.** If a phase has substeps, `/phase 2` runs only the first
not-done substep and stops. Invoke it again for the next one.

### If the command errors instead of starting

`prefill_cap_refused` means the model's serving cell is at capacity; it is not a
command bug. The commands are pinned to `github-copilot/claude-sonnet-4.6` for
this reason. If that model is also unavailable, change the `model:` line in
`.opencode/commands/phase.md` and `phase-status.md` to another working model, or
retry after about 30 seconds.

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
| 2.2 | Curate Berguedà zones | todo | — | — |
| 2.3 | Curate Ripollès zones | todo | — | — |
| 2.4 | Curate Cerdanya zones | todo | — | — |
| 2.5 | Curate Montseny, Garrotxa, Pallars zones | todo | — | — |
| 2.6 | Zone UI: map, list, detail, comparison | todo | — | — |
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
  - Embedded JS unchanged, so no new `node --check` run; `/` returned HTTP 200.
- Screenshots: none; this step does not change the UI.
- Notes / sources: no curated zone data was invented. `mushrooms.json` station
  definitions and `geo_cache.json` remain the only location/soil sources until
  step 2.2 documents real stands.
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

### Step 2.3 — Curate Ripollès zones

Same rules, 5 stations × 3 zones: Ogassa – Ripoll, Planoles, Queralbs – Núria,
Setcases, Camprodon.

### Step 2.4 — Curate Cerdanya zones

Same rules, 3 stations × 3 zones: Tossa d'Alp, Bagà – carena, La Canya.

### Step 2.5 — Curate Montseny, Garrotxa and Pallars zones

Same rules, 9 stations × 3 zones. Montseny is siliceous broadleaf; Garrotxa is
volcanic/mixed; Pallars is high-altitude fir/pine. Expect different species.

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
