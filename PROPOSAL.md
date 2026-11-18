# Proposal: How Bolets can surpass BoletRadar

_Audit of boletradar.cat, audit of the current Bolets app, and a phased implementation plan._

> **Status:** Phase 1 (map navigation and free features), Phase 2 (micro-zones) and Phase 3 (terrain and canopy science) are implemented. Phase 1 shipped search, filters, sorting, map↔list sync, clustering, URL state, the free best-zones leaderboard, route links, geolocation, legend and the data-quality indicator. Phase 2 added the `zones.json` micro-zone model: 66 independently scored zones across the 22 stations (massís → obaga/solana/carena stands), the zone comparison strip, the zone detail panel, and zone circles on the map. Phase 3 added the full enrichment pipeline (`enrich_zones.py` → `zones_enriched.json`: ICGC 5m DEM aspect/slope/solar/TPI/cold-air, ICGC LiDAR canopy/undergrowth, IGME/SoilGrids soil, CORINE habitat) and integrated those factors into the zone score and the "why this score" explainer as a five-factor H·M·W·P·C breakdown. Phase 4 is complete (4.1–4.6): 4.1 shipped batched Open-Meteo weather with lapse-rate elevation correction per zone; 4.2 shipped the optional Meteocat XEMA integration (observed station data interpolated to each zone with distance/data-age recorded; Open-Meteo stays the fallback and the score source; radar deferred — the API has no XRAD product, rain accumulation uses XEMA gauges); 4.3 shipped the soil water balance and drought index (per-zone P−ET0 14/30/60/90-day windows from the 92-day Open-Meteo ET0 series, a bounded FAO-56-style recharge index with a documented 100 mm storage cap, a documented XEMA observed-rain blend, and a per-species drought/recharge modifier on the zone rain term — station scores byte-identical). 4.4 added per-zone data confidence (completeness + deterministic prediction-confidence score with reasons, per zone and per species, reporting-only). 4.5 shipped phenology and the altitude-lag wave: per-species growing-degree-day states (GDD = Σ max(0, T − `temperature_c.min`) over the stored 14-day temperature series, lapse-corrected 6.5 °C/km to each zone's altitude), window open/close thresholds derived from the documented temperature band, `P` wired into the zone score (stations byte-identical), `altitude_lag_days` vs the warmest zone of each species, and the "rovelló wave" visual (altitude strip + 7-day forecast strip, CA/EN) in the zone detail and explainer. 4.6 verified the phase end to end (known-station-day temperature deltas, 66/66 lapse formula, day-rollover cache stamps, sources/timestamps audit, 4.5-identical regression and script) and recorded the honest limitations in README "Phase 4 verification (4.6)". Phase 5 is implemented (5.1 report model + API, 5.6 calibration + published AUC/Brier, 5.7 privacy/rate-limit/deletion verification and docs; the report UI, logbook, photos and alerts are deferred optional extras). Phases 1–5 are implemented. Phase 6 is complete: 6.1 shipped the PWA/offline pack, 6.2 expanded coverage to 46 stations / 135 zones, 6.3 expanded to 21 species with seasons and lookalike warnings, and 6.4 deduplicated the forecast payload, added gzip and a built-forecast cache, and closed the keyboard/contrast/mobile accessibility defects. Phases 1–6 are implemented. Phase 7 (model and data depth) is in progress: step 7.1 (forest-offset repair) is done — all 46 station points and 135 zone centroids re-gated against CORINE (46/46 and 135/135 pass) with a repeatable `repair_forest_offsets.py` gate. 7.2 is complete (drive_min + difficulty + canopy de-dup; `water_m` 135/135). Parking — a Phase-1/7.2 feature — was **removed on 2026-11-18**: the nearest-OSM-lot points were often a village square, not a trailhead, and routing drive time to them understated real access; the parking UI, `/api/parking`, seed cache, `warm_parking.py` and `access.parking_*` fields are gone, and drive time now targets the zone. 7.3 (confidence that discriminates), 7.4 (IGME MAGNA 50 soil), 7.5 (backtest, decision `no_change`), 7.6 (real 1:25k soil + habitat) and 7.7 (dormant GeoVeg + manual field observations) are done. 7.8 (radar rain) is **blocked**: the "no XRAD product" premise is stale — EUMETNET OPERA now publishes free geo-referenced composites (MeteoGate ORD API, CC BY 4.0, 2 km, 1-hour GeoTIFF accumulation) — but consuming them needs a non-stdlib raster decode and archive access, and the step's storm-day gauge validation could not run in the available 24-hour window. The unblock path is recorded in `README.md` and `PHASES.md`.
>
> **Execution:** `PHASES.md` is the step-by-step ledger. Run `/phase next` or `/phase 2.1` to execute one step in a fresh child session.

---

## 1. What BoletRadar does today

### Their strengths

- One map for all of Catalonia, species cards at the bottom, daily update from Meteocat XEMA.
- A 0–100 "favorability index" painted only over forest at 100 m cartographic resolution.
- Two-stage model that is at least honest about its structure: a spatial habitat model (altitude, temperature, forest fraction, sclerophyll vegetation) × a temporal rain gate.
- Per-cell confidence, visible data date, clear legal/safety disclaimers.
- Crowd-sourced "how was your trip" reports on a 1 km grid, used to retrain the model.
- PWA install and a coarse offline snapshot.
- Good Catalan copy and a real identity.

### Their weaknesses (the openings for us)

| # | Weakness | What it means for a user |
|---|---|---|
| 1 | **Map navigation is weak.** Only a comarca dropdown, a geolocate button and a layer switch. No search by place, peak, forest track, parking or municipality. No filtering by drive time, species, date or confidence. No list ↔ map synchronisation. | You know roughly where you want to go, but not how to find it or compare it. |
| 2 | **Two key features are paywalled.** "Millors zones avui" (top 3 × 5 km zones per species) and "Com arribar-hi" (route) cost €4.99/12 months. | The two things that actually get a user into the forest are behind a wall. |
| 3 | **One score per 100 m pixel, but weather interpolated smoothly from stations.** They admit 100 m is representation, not precision. | Within a single forest, a north-facing gully and a south-facing ridge can behave very differently; their model cannot express that. |
| 4 | **Habitat is coarse.** Forest fraction + sclerophyll fraction + altitude. They cannot distinguish Scots pine reforestation from black pine, fir from spruce, or open canopy from dense young scrub. | Exactly the distinction that matters for rovelló, cep, camagroc and fredolic. |
| 5 | **No slope aspect, no cold-air pooling, no solar radiation, no canopy structure.** | Obaga/solana — the single most repeated field rule in Catalan mushroom lore — is missing. |
| 6 | **No soil chemistry.** No calcareous/siliceous layer, no pH. | Rovelló vs rossinyol is largely a soil question. |
| 7 | **No trip planning.** No parking, trailhead, access difficulty, elevation profile, drive time, or "is this a sensible family outing". | The score stops at the map edge. |
| 8 | **No personal layer.** No logbook, no yield history, no private spots, no alerts. | Every season starts from zero. |
| 9 | **No field-first UI.** The mobile app is a map with small species cards; reporting a trip is a long form. | Poor experience where it matters: standing in the forest with one hand free. |
| 10 | **No species depth.** Ten species, no lookalike warnings, no seasonal calendar per altitude. | Safety and education are thin. |

---

## 2. Where Bolets stands today

### What exists

- Single-file Python app, Leaflet map, 22 stations in 6 comarques (the README still says 3 comarques / 13 stations — it is out of date).
- 21 species in `mushrooms.json` (autumn, plus spring/summer/winter) with temperature, rain window, altitude, soil, tree preferences and lookalike warnings.
- Weather from Open-Meteo (14 past days + 7 forecast), geology from IGME 1:1M, land cover from CORINE.
- Per-station score = weather (rain 35%, temp 25%, wind 20%, altitude 10%, humidity 10%) × soil multiplier × forest multiplier.
- 7-day forecast selector, CA/EN toggle, "why this score" explainer, ICGC topo overlay.
- Geo results cached permanently in `geo_cache.json`.

### The structural problem

A station is **one point with one altitude and one soil/forest sample**, rendered as a 1.5–3 km circle. Every pixel inside that circle gets the same score. Two forests 800 m apart on opposite sides of a ridge — one obaga, one solana, one on limestone, one on granite — are indistinguishable.

That is the gap BoletRadar has too, and it is our biggest opportunity.

### Other current gaps

- Weather is fetched at the town station, not at the forest point; altitude correction is absent.
- No aspect, slope, solar radiation, canopy cover or undergrowth density.
- No rain-shadow / orographic correction, no soil water balance (only summed mm).
- No confidence value, no last-updated timestamp per layer.
- No field reports, no calibration, no user accounts or logbook.
- No route, parking, access or regulations layer.
- No PWA / offline mode.
- Map has no search, no filters, no URL state, no clustering, no date slider on the map.

---

## 3. Product thesis

> **"The most local, most explainable, completely free mushroom forecast in Catalonia — down to the stand, with the route to get there."**

Four pillars, in order:

1. **Hyperlocal** — massís → sector → stand → micro-habitat, not one circle per town.
2. **Free** — everything a hunter needs (best zones, route, parking, forecast) is free. Money comes from optional convenience and donations, never from hiding the answer.
3. **Explainable** — every score shows its factors, its confidence and its data age. No black box.
4. **Field-calibrated** — trip reports close the loop and improve the model every season.

---

## 4. Feature proposal

### A. Fix map navigation first (the complaint that started this)

This is the cheapest, highest-impact work.

1. **Global search** — one search box for municipality, massís, peak, forest, trailhead, parking, comarca, or lat/lon. Use the ICGC geocoder / Nominatim proxy, with fuzzy Catalan matching (`rovelló` → `Rovelló`, `Vallcebre` → Berguedà).
2. **Command palette** (⌘K / Ctrl+K) — search places, species, stations and actions ("best rovelló today", "zones within 45 min").
3. **Filter rail** — species chips, comarca, max drive time, altitude band, soil, forest type, minimum score, minimum confidence, date. Filters apply to map and list simultaneously.
4. **Map ↔ list sync** — hover a card highlights its zone; click a zone scrolls the list. No more two separate worlds.
5. **Sort control** — best score, closest, highest confidence, most recent report, altitude.
6. **Date slider / timeline** — Today → +6 days, with a small sparkline per zone showing the best day in the window.
7. **"Best zones today" free leaderboard** — top 10 zones for the selected species, with score, confidence, drive time and a route button. No paywall.
8. **URL state** — `?lat=42.1&lon=1.9&z=12&species=rovello&day=2&zone=vallcebre-nord`. Shareable links, back button works, deep links open the right zone.
9. **Map layers panel** — topo, orthophoto, forest cover, soil, recent rain, burned areas, protected areas, parking, trails. One clear control, not hidden toggles.
10. **Legend always visible**, with "not evaluated" clearly distinct from "score 0".
11. **Zone clustering** at low zoom; individual stands appear at zoom ≥ 13.
12. **Geolocate + "near me"** — sort by drive time from current position, show what is within 30/60/90 minutes.
13. **Mobile** — bottom sheet with three snap points, large tap targets, offline-tolerant.
14. **Keyboard and screen-reader support** — focusable zones, ARIA labels, no map-only navigation.

### B. The micro-zone model (the real differentiator)

Replace "one station = one circle" with a hierarchy:

```
Massís (e.g. Rasos de Peguera)
└── Sector (e.g. north slopes / south reforestation)
    └── Stand (e.g. "Pi roig clar, solana, 1,150–1,300 m")
        └── Micro-habitat band (aspect × altitude × canopy)
```

Each **zone** is a small forest polygon or a 100–200 m cell cluster with its own:

- centroid and polygon,
- altitude band (min/max),
- aspect (degrees + obaga/solana label),
- slope,
- forest type and **dominant tree species**,
- canopy cover % and undergrowth density,
- soil type and pH,
- distance to water / drainage,
- access point (parking, trailhead, track quality),
- confidence.

**Example schema** (extension of `mushrooms.json`):

```json
{
  "id": "rasos-peguera-nord",
  "massis": "Rasos de Peguera",
  "comarca": "Berguedà",
  "name": "Rasos — obaga del Clot Gran",
  "lat": 42.1091, "lon": 1.8873,
  "polygon": [[42.108,1.884],[42.111,1.889],[42.107,1.892]],
  "alt_m": 1290, "alt_range_m": [1150, 1380],
  "aspect_deg": 12, "aspect": "north", "slope_deg": 18,
  "forest": { "type": "conifer", "dominant": "Pinus sylvestris", "canopy_pct": 45, "undergrowth": "low" },
  "soil": { "type": "calcareous", "ph": 7.1, "source": "ICGC 1:25k" },
  "water_m": 380,
  "access": { "parking": [42.1078,1.8851], "trailhead": "Pista de Rasos", "drive_min": 38, "difficulty": "easy" },
  "confidence": 0.82,
  "notes": "Open Scots pine on south-west edge; classic rovelló; avoid after heavy north wind."
}
```

Then score **each zone independently**, and show the user:

> Rasos de Peguera → **north slope** 78 (high confidence) · south reforestation 61 (medium) · summit 44 (low)

That is the "same forest, very different conditions" answer BoletRadar cannot give.

**How to generate zones without inventing data:**

- **DEM** (ICGC 5 m / SRTM 30 m): altitude, slope, aspect, curvature, topographic position index, cold-air pooling, solar radiation (`r.sun`-style).
- **ICGC land cover / habitats 1:25k** + **CORINE**: forest type, canopy group.
- **ICGC LiDAR** (available for Catalonia): canopy height model, canopy cover %, undergrowth proxy, edge density.
- **ICGC soil map 1:25k**: calcareous/siliceous, pH, texture.
- **OSM / ICGC**: tracks, parking, trailheads.
- **Field knowledge**: manually seed the first 3–5 zones per massís, then expand with the raster.

Start manual (fast, trustworthy), automate later.

### C. Better weather and microclimate

1. **Forest-point weather, not town weather** — fetch at the zone centroid and apply a lapse-rate correction to the zone's altitude.
2. **Batch forecast** — Open-Meteo supports multiple coordinates in one request; Meteocat XEMA when a key is available.
3. **Rain interpolation** — XEMA stations + radar (XRAD) + elevation correction; show a rain-accumulation layer (24 h / 72 h / 7 d / 14 d).
4. **Soil water balance** — track precipitation minus evapotranspiration over the season instead of summing mm. This is what actually matters for fruiting.
5. **Aspect-adjusted drying** — south-facing slopes dry faster; apply a solar-radiation multiplier.
6. **Cold-air pooling** — valleys frost earlier; penalise frost-sensitive species in pooling zones.
7. **Phenology** — growing-degree days + altitude lag; show "the rovelló wave is at 900 m now, moving up 100 m/week".
8. **Wind exposure** — combine wind direction with aspect and canopy; north wind after rain = rapid drying on exposed ridges.
9. **Confidence** — per zone, derived from distance to nearest weather station, data age, model coverage, and number of field reports.

### D. Trip planning and field use

1. **Route button on every zone, free** — open Google/Apple Maps or an in-app OSRM route.
2. **Drive time from the user** — isochrone filter (30/60/90 min).
3. **Parking + trailhead** — exact access point, track condition, barrier/gate warnings.
4. **Route card** — distance, elevation gain, estimated walk time, difficulty, water, phone coverage, sunset time.
5. **Elevation profile** and "where to leave the track" hint.
6. **Offline pack** — save a zone's map + forecast + access notes for the day (PWA).
7. **Field mode** — big type, high contrast, one-hand controls, GPS dot, compass, "mark my find".
8. **Trip report** — 30-second form: species, found/not found, quantity, time spent, photo. Position rounded to 1 km by default; private exact position optional.
9. **Logbook** — personal trips, finds, photos, yield by zone/species/season. Private by default.
10. **Alerts** — "Rovelló window opened at Vallcebre north slope" via web push / Telegram / email.
11. **Share a trip** — link with zone, date, score and forecast (no exact private location).

### E. Community and calibration

1. **Found / not found reports** — both are valuable; weight by recency and contributor reliability.
2. **Photos** — private by default, EXIF stripped, optional public sharing without location.
3. **Zone notes** — "parking barrier closed", "track washed out", "logged area", "new fence".
4. **Model calibration** — logistic regression / gradient boosting on reports + GBIF/iNaturalist, validated with AUC and Brier score. Publish the accuracy honestly.
5. **Pressure layer** — recent reports and popular zones, to warn "this area has been picked hard this week".
6. **Contributor reputation** — lightweight, privacy-preserving, anti-abuse.
7. **Season recap** — "your best zone this autumn", "your first cep", personal stats.

### F. Trust, safety and regulations

1. **Explainable score** — already partially present; extend to every factor with the zone's real numbers.
2. **Data freshness** — "weather updated 06:12 today", "soil 1:25k", "satellite 2024".
3. **Confidence badge** — low/medium/high with the reason.
4. **Lookalike warnings** — for each edible species, the dangerous lookalikes and the key differences.
5. **Regulations layer** — protected areas, natural parks, municipal collection rules, 6 kg/day limit, commercial permits.
6. **Respect reminders** — private land, gates, no raking, leave small specimens.
7. **Emergency card** — 112, nearest hospital, phone coverage warning.
8. **"Not evaluated" honesty** — crops, towns, water, rock and burned areas are not zero; they are outside the model. BoletRadar does this well; keep it.

### G. Monetisation without hidden answers

- **Never paywall**: best zones, route, parking, scores, forecast, safety.
- **Optional supporter tier**: offline packs, unlimited history, advanced alerts, multiple saved areas, no "supporter" badge? Keep it cosmetic/convenience.
- **Donations / season pass** — "adopt a weather station", transparent costs.
- **No ads, no data selling** — state it plainly.
- **B2B / tourism** — curated routes for rural hotels and tourist offices, clearly separate from the free tool.

---

## 5. Data and architecture

### Current vs proposed

| Layer | Current | Proposed |
|---|---|---|
| Spatial unit | 22 station points, 1.5–3 km circles | 100–300 zones (polygons/cells) across all comarques |
| Weather | Open-Meteo at town point | Batch Open-Meteo + Meteocat XEMA, elevation-corrected, radar |
| Geology | IGME 1:1M | ICGC soil 1:25k + IGME |
| Vegetation | CORINE 100 m | ICGC habitats 1:25k + LiDAR canopy + CORINE |
| Terrain | altitude only | DEM: aspect, slope, solar radiation, TPI, cold-air pooling |
| Score | one per station | per zone, with confidence |
| Validation | none | field reports + GBIF, AUC/Brier |
| Storage | JSON files | JSON for config, SQLite for reports, precomputed GeoJSON/PMTiles for zones |
| Frontend | server-rendered HTML + Leaflet | same stack initially; PWA + offline later |

### Scoring model (per zone, per species)

```
Habitat  H = f(tree match, soil pH match, altitude band, aspect, canopy openness, slope)
Micro    M = f(solar radiation, cold-air pooling, water proximity, edge effect)
Weather  W = f(rain window, soil water balance, temperature, wind, humidity)
Season   P = f(month, growing-degree days, altitude lag)
Pressure D = f(recent reports, zone popularity)        # optional, small weight
Confidence C = f(station distance, data age, model coverage, report count)

Score = 100 × H^a × W^b × P × D      (a, b tuned; cap 99)
```

Keep the current factor breakdown UI, but show **H, M, W, P and C separately**. That is more honest and more useful than a single opaque number, and it is a direct improvement over BoletRadar's two-factor display.

### New backend endpoints

```
GET  /api/zones?bbox=&comarca=&species=&date=
GET  /api/forecast?date=&species=&min_score=&max_drive=
GET  /api/top-zones?species=&date=&limit=10
GET  /api/zone/{id}
GET  /api/geocode?q=
GET  /api/layers/{rain|soil|forest|burned}
POST /api/reports
GET  /api/reports?bbox=&days=
GET  /api/me/logbook            (optional auth)
```

### New files

```
zones.json                 # curated zone definitions + polygons
enrich_zones.py            # DEM/LiDAR/soil/land-cover sampling, writes zones_enriched.json
weather_grid.py            # batch weather + water balance
reports.py                 # SQLite + moderation
pwa/                       # manifest, service worker, icons
```

---

## 6. Implementation phases

### Phase 1 — Map navigation and free features (1–2 days)

- Search box + command palette.
- Species/comarca/score/confidence filters.
- Map ↔ list sync, sorting, clustering.
- Date slider + per-zone best-day sparkline.
- Free "best zones today" leaderboard.
- Route + parking links on every zone.
- URL state and share links.
- Legend, confidence badge, data-freshness line.

**Outcome:** immediately more navigable than BoletRadar, with none of its paywalls.

### Phase 2 — Micro-zones (2–3 days)

- Extend `mushrooms.json` with `zones` (3–6 per massís, ~100 total).
- Score per zone; keep backward-compatible station API.
- Draw zone polygons; show "sector" comparison inside a massís.
- Add zone detail: altitude band, aspect, forest structure, soil, access, notes.
- Manual curation for the classic areas first (Vallcebre, Rasos, Sant Jaume, Coll de Pal, Setcases, Montseny…).

**Outcome:** the "same forest varies" promise becomes visible.

### Phase 3 — Terrain and canopy enrichment (3–5 days)

- `enrich_zones.py`: ICGC DEM + LiDAR + soil 1:25k + habitats.
- Compute aspect, slope, solar radiation, TPI, cold-air pooling, canopy cover, undergrowth proxy.
- Add these factors to the score and the explainer.
- Add rain and soil overlay layers.

**Outcome:** a scientific edge BoletRadar cannot match with coarse land cover.

> **Status: done** (steps 3.1–3.6 in `PHASES.md`). The 1:25k soil-texture and
> CHC50 habitat sources were unavailable, so soil/habitat use the IGME 1:1M +
> SoilGrids + CORINE fallbacks (flagged `pending`). The "rain and soil overlay
> layers" item was descoped to Phase 4 (weather quality); it is not part of the
> shipped Phase 3 scoring.

### Phase 4 — Weather quality (3–5 days)

- Batch weather, elevation correction, Meteocat key.
- Soil water balance and drought index.
- Confidence per zone.
- Phenology and altitude-lag wave.

> **Status: done (4.1–4.6).** 4.1 batches
> Open-Meteo weather for all stations and zones and lapse-corrects temperatures
> to each zone's verified altitude. 4.2 adds the optional Meteocat XEMA
> integration (`METEOCAT_API_KEY`): observed temperature/precipitation from the
> official station network, IDW-interpolated to each zone with nearest-station
> distance and data age recorded; Open-Meteo remains the fallback and the
> source of every score. Radar (XRAD) is deferred — the Meteocat API exposes no
> radar product — and rain accumulation uses XEMA gauges (variable 1300).
> Live-verified with a real key on 2026-11-08 (see `PHASES.md` step 4.2): three
> live-data fixes landed (station-state filtering, blank-state readings,
> daily-stats shape), 188 operative stations, 66/66 zones with an `xema`
> block, 0 errors. 4.3 adds the soil water balance and drought index: per-zone
> `water` blocks with 14/30/60/90-day P−ET0 balances (Open-Meteo
> `et0_fao_evapotranspiration`, 92 past days), a bounded recharge index
> (documented 100 mm storage cap, FAO-56 bucket concept), an explicit XEMA
> observed-rain blend for the published days, and a per-species
> drought/recharge modifier on the zone rain term (drought damps, recharge
> boosts; sensitivity from the documented `rain_trigger_mm`; station scores
> byte-identical). 4.4 adds per-zone data confidence: `data_completeness`
> (fraction of the score's inputs present, degrading gracefully without a
> Meteocat key) and a deterministic `prediction_confidence` score + reasons
> (XEMA station distance/data age, Open-Meteo ~11 km grid, DEM/LiDAR/soil/
> habitat source resolutions, curated zone confidence, field reports honestly
> 0 until Phase 5), shown per zone and per species, never multiplied into
> scores. 4.5 adds phenology and the altitude-lag wave (see README "Phenology
> and altitude lag"): per-species growing-degree days over the stored 14-day
> temperature series with `temperature_c.min` as the documented base,
> lapse-corrected to each zone's altitude, window open/close derived from the
> documented temperature band, `P` multiplied into the zone score only
> (station scores byte-identical), `altitude_lag_days` vs the species' wave
> front, and the "rovelló wave" strips in the zone detail/explainer (CA/EN).
> See `PHASES.md` steps 4.3–4.5 for the evidence.

### Phase 5 — Field loop (1–2 weeks)

- Trip reports, photos, zone notes.
- Logbook.
- Alerts (web push / Telegram).
- Calibration pipeline and published accuracy.

> **Status: Phase 5 complete (5.1 + 5.6 + 5.7, 2026-11-10); the user-facing
> extras deferred.** The core of this phase is the calibration loop: the report
> model + API (5.1), published AUC/Brier metrics (5.6), and the privacy /
> rate-limit / deletion verification and docs (5.7). Step 5.1 shipped a SQLite
> trip-report store and the `POST /api/reports` / `GET /api/reports` endpoints,
> with 1 km location rounding, salted device/IP hashes (no raw identity or
> exact coordinates stored or exposed), input validation and rolling abuse
> limits. Step 5.6 shipped `calibrate.py` (AUC / Brier / calibration curve,
> held-out split) and published the first metrics: field reports are still
> `n = 0` (no recalibration applied — nothing to overfit), and a per-species
> occurrence AUC against GBIF + iNaturalist data (e.g. trompeta 0.75, cep 0.67,
> rovelló 0.65; camagroc 0.32 and bolet de tinta 0.42 are published as honest
> negative results — see `calibration_report.json`). Step 5.7 added the
> `DELETE /api/reports` right-to-erasure path (delete all, or one `id` owned by
> the same salted device hash), and re-verified the privacy design and abuse
> limits end-to-end. The user-facing extras — report UI (5.2), logbook (5.3),
> photos (5.4) and alerts (5.5) — are marked `optional` in `PHASES.md`: outside
> the core mushroom map, deferred.

### Phase 6 — PWA and scale (1 week)

- Installable app, offline pack, coarse fallback.
- Expand from 6 comarques to all of Catalonia, in order of mushroom value:
  Alt Urgell, Solsonès, Osona, Vallès Oriental, La Selva, Garrotxa, Alta Ribagorça, Val d'Aran, Noguera, Priorat, Terra Alta, Montsià, Baix Empordà, Maresme, Garraf.
- Species expansion (20–25), including per-season and toxic lookalikes.

> **Status: 6.1–6.4 done (2026-11-11).** The PWA is installable: manifest,
> generated icons, theme colour and a service worker (`/sw.js`) that precaches
> the app shell and serves it offline. An explicit "save zone for the day"
> offline pack stores a zone's location, terrain/forest/soil facts, access
> notes, 7-day strip and top species in `localStorage`, surfaced through a
> header button and a clearly-labelled offline-snapshot view.
>
> Coverage now spans **22 station groups / 46 stations / 135 zones**: the six
> Phase 1–2 groups plus 24 new stations in the 13 priority comarques (Alt Urgell,
> Solsonès, Osona, La Selva, Alta Ribagorça, Val d'Aran, Noguera, Priorat, Terra
> Alta, Montsià, Baix Empordà, Maresme, Garraf) and three adjacent comarques
> (Gironès, Vallès Oriental, Alt Penedès). Every new zone centroid is a
> CORINE-verified forest cell with ICGC DEM altitude/aspect/slope and IGME soil;
> no coordinate is invented.
>
> Species expanded from 13 to **21** (6.3): each carries an optional `season`
> (`spring`/`summer`/`winter` are filtered to their months; `autumn`/unset stays
> year-round and is damped out of season) and a safety-critical `lookalikes`
> list (confusable species, severity `mortal`/`toxic`/`inedible`/`none`, and the
> key differences), surfaced as a prominent "Perill de confusió" section in the
> explainer and a warning line in each species row.
>
> Phase 6.4 (2026-11-11) finished the performance and field-readiness pass:
> static species fields now travel once in `species_meta` (29.7 MB raw), responses
> are gzipped to **1.08 MB on the wire**, and a built-forecast cache makes repeat
> requests ~2 ms instead of ~3 s (with stale-on-error). Keyboard focus, the
> explainer dialog, mobile tab semantics, touch targets, reduced motion and
> score-pill contrast were fixed and verified at 1440×900 and 500×900. No
> GeoJSON/PMTiles were added because zones are curated points, not polygons.

### Phase 7 — Model and data depth (proposed)

Phases 1–6 made the map complete. Phase 7 makes the numbers behind it
trustworthy: remove silent data errors, upgrade the layers that cap the habitat
model, and validate the hand-chosen assumptions before adding more features.

The order is deliberate: cheap data-integrity fixes first (7.1–7.3), then the
accuracy upgrades (7.4, 7.6, 7.7), then the validation that tells us whether the
upgrades were worth it (7.5), and finally radar (7.8), which is the largest and
most uncertain dependency. Each step is independently shippable and ends with
the same evidence standard as Phases 2–6: a live run, a zone-by-zone diff, and a
documented "no invented data" audit.

#### Step 7.1 — Forest-offset repair

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

> **Status: done (2026-11-12).** The premise was partly stale: the separate
> `forest_lat/forest_lon` offsets were removed when the original 22 stations were
> re-sourced (2.2–2.5) and Phase 6.2 sourced the new 24, so station `lat/lon`
> *is* the forest point. `repair_forest_offsets.py` now gates all 46 station
> points and (with `--check-zones`) all 135 zone centroids against CORINE CLC
> 2018. Live run: **46/46 stations forest, 135/135 zones forest and matching
> their curated class, 0 candidates, 0 moves**. `--apply` moves a point only on
> a passing candidate, keeps the previous coordinates in
> `forest_offset_history`, and never rewrites `alt_m` silently. Report:
> `forest_offset_report.json`. Ribes de Freser and Puigcerdà are not station
> points, so the old non-forest note no longer applies.

#### Step 7.2 — Complete the zone facts (access, water, canopy consistency)

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

> **Status: partially complete / blocked on water (2026-11-12).** `complete_zone_facts.py`
> ships and, on this run, filled `access.drive_min` (135/135, OSRM from the comarca
> capital) and `access.difficulty` (135/135, a documented slope + walk-distance rule),
> removed the duplicated `forest.canopy_pct`/`undergrowth` null placeholders (canopy
> now lives only in `zones_enriched.json` `enrichment.canopy`), and added
> `--check-schema` (zones.json ↔ zones_enriched.json agree). `water_m` and the 69 new
> zones' `access.parking_*` remain null because every public Overpass instance was
> unreachable during the session (502 / timeouts / `duplicate_query` on
> overpass-api.de, kumi.systems, private.coffee and osm.ch); they were not
> hand-written. Re-running `python3 complete_zone_facts.py` after Overpass recovers
> fills them from `water_cache.json`/`route_cache.json`.
>
> **Update (2026-11-16):** Overpass recovered and the retry filled `water_m`
> 135/135 (independent `around:` queries confirm the distances) and parked 53 of
> the 69 zones. **Update (2026-11-18):** parking was removed from the app — the
> OSM points were often village squares, so using them as the drive destination
> and walk origin understated real access. Drive time is now to the zone and
> difficulty uses the station forest point; the parking mentions in this
> proposal's earlier sections are the original plan, not current behaviour.

#### Step 7.3 — Confidence that discriminates

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

> **Status: done (2026-11-12).** `derive_zone_confidence.py` derives the curated
> confidence per zone from sourced evidence (source count, pH, soil/habitat/DEM
> resolution, canopy coverage, the 7.1 forest gate, access facts; a null
> `water_m` means "unknown" and is never penalised). The 135 zones moved from a
> flat `0.6` to **0.62–0.77** with **44 alta / 91 medium**; the 4.4 prediction
> score now spans 0.631–0.678 and completeness stays 100 %. A shadow diff was
> reviewed before applying. The score-equivalence fixture is **byte-identical**
> after removing `confidence`/`C`, proving the value is reporting-only. The
> formula and per-zone evidence are in `confidence_report.json`; each zone also
> stores `confidence_evidence`. The 1:25k / MAGNA 50 bonuses are already wired
> into both the derivation and app.py `_conf_quality`, so 7.4/7.6 raise the
> value when they land. Also fixed the badge CSS/translation mapping for the
> schema labels `alta`/`baixa` (it only understood `high`/`low`).

#### Step 7.4 — IGME MAGNA 50 soil

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

> **Shipped 2026-11-15.** MAGNA 50 answers unambiguously for **58/135 zones**
> (17 sheets); **56 are promoted to 1:50k** and the 1:1M sample is kept for 79
> (12 no coverage, 65 ambiguous legend, **2 held for field review**). The soil
> distribution moves from 76 calcareous / 22 siliceous / 37 mixed to
> **83 / 30 / 22**; 15 zones change class (8 mixed→siliceous, 7
> mixed→calcareous), 41 keep their class and only gain resolution/confidence.
> The 2 calcareous→siliceous flips on the reproducible Liditas unit at Coll de
> Pal/Bagà are recorded in `soil.magna_review` but stay at 1:1M until checked.
> All 58 legends were re-queried live (58/58 identical), 0 fallback zones
> changed, and the live API serves 56 zones at 1:50k. Confidence re-derivation
> keeps `0.62–0.80` (63 alta / 72 medium; the held zones drop 0.80→0.77). See
> `PHASES.md` 7.4 for the per-zone audit.

#### Step 7.5 — Backtest and validate the assumptions

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

> **Status: done (2026-11-15), decision `no_change`.** `calibrate.py` now runs a
> Phase 7.5 backtest and writes it into `calibration_report.json` (version 2):
> pseudo-absences via target-group background, recorder-effort weighting
> (`w = 1 / (1 + neighbours within 5 km)`), a deterministic temporal split
> (split year 2025; only the time-invariant habitat signal H × M × altitude is
> temporally splittable because `W` and `P` are current-day values), permutation
> importance of the stored `W`/`H`/`M`/`P` factors, and a held-out refit of the
> five weather weights with a bootstrap 95 % CI on the gain. On the live
> 2026-11-15 run (3216 pooled rows): `H` is the dominant discriminator
> (permutation drop 0.0822 vs `W` 0.0082, `M` 0.0039, `P` −0.0003), and the
> weight refit is **not** promoted — held-out AUC 0.631 (current) vs 0.6299
> (refit), gain −0.001, CI [−0.008, +0.0043]. The temporal split evaluates the
> older and newer eras separately: habitat AUC 0.5334 older vs 0.5929 newer
> (759/431 presences; 1232/778 background), with only 3.5 % of newer presences
> above the older-era 95th-percentile threshold. The hand weights stay; `app.py`
> scoring is unchanged. See `PHASES.md` step 7.5 for the full evidence.

#### Step 7.6 — Real 1:25k soil and habitat

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

> **Status: done (2026-11-15), score byte-identical, coverage partial by sheet.**
> `enrich_zones.py` now retries both intended layers first and records them with
> `resolution: "1:25k"` where they answer:
> - **Soil** — the ICGC *Mapa de sòls de Catalunya 1:25.000* (MSC25M) WFS
>   (`geoserveis.icgc.cat/…/edafologia/wfs`, layer `icgc_sols:sols-25000`). The
>   parent-material text is classified calcareous/siliceous with the same
>   conservative keyword rule as MAGNA 50. It answers for **7/135 zones** (the
>   mountain sheets are not published yet): all 7 are calcareous and match the
>   MAGNA/1:1M class, so **no soil class changed and the score is byte-identical**
>   (only resolution/source moved, e.g. `Montplà`, `Garraf-Afloraments`). The WFS
>   returns intersecting polygons, so the provider keeps only the one containing
>   the centroid; Serra de la Figuera has no containing polygon and falls back.
> - **Habitat** — the CHC50 (UB "geoveg") WMS is **still down** (no response;
>   `geoveg.creaf.cat` does not resolve). The current successor, the version-3
>   cartography (**CHC3, 1:25k, 2019-2022**), is served for the Barcelona counties
>   by the Diputació de Barcelona SITMUN WMS (`SITXELL`, layer `SITXELL_MN340`):
>   it answers for **50/135 zones** with a full CORINE-list code/name (e.g.
>   `42.5921+` "Boscos de pi roig (Pinus sylvestris), calcícoles i xeròfils, dels
>   Pirineus"), which resolves stand-level tree species. This finer habitat is
>   recorded in an `enrichment.habitat.chc3` shadow block while the score keeps
>   the CORINE forest group (the step's "keep the old value" rule). The remaining
>   85 zones stay on CORINE CLC 2018.
> Confidence re-derivation (7.3) reflects the new layers: **82 `alta` / 53
> `medium`** (was 63/72). The score is unchanged (the 1:25k layers only raise the
> reporting confidence and add shadow detail). See `PHASES.md` 7.6.

#### Step 7.7 — GeoVeg and manual field observations

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

> **Status: done (2026-11-15), dormant provider + manual path shipped.** The
> UB/CREAF "geoveg" host is still down, so `enrich_zones.py` adds a **dormant**
> `_geoveg(lat, lon)` provider (mirrors `_corine`; returns `(None, "unavailable")`
> rather than fabricate a query), a reviewed keyword parser `_parse_geoveg(text)`
> (soil reaction from `calcícola`/`acidòfil`, tree species from a reviewed table
> with "roures" → `Quercus spp.` to respect the ambiguity, forest group
> conifer/broadleaf/mixed) and `_geoveg_shadow(parsed, corine_code)` that
> diff-computes the parsed result against the CORINE group with an explicit
> `matches_corine`/`null` flag. None of it is wired into the score, so the score
> is byte-identical. Separately, `app.py` gains a manual **field-observation
> path** (`field_observations.json`, keyed by zone `id`): a trusted person records
> tree species, undergrowth, soil reaction and water, each entry with `source`,
> `verified_at`, `observer` and the observer's `confidence`; the loader drops any
> entry without provenance and never overwrites a sourced value. The zone payload
> carries `field_observation` + `verified_by_person`, and the zone detail renders a
> "✓ Verificat per una persona" badge with the observed facts and a
> `field_observation` confidence reason. Verified by parser/shadow self-tests, a
> deterministic `build_forecast` round-trip (enter → store → display → confidence),
> a byte-identical check on the 134 non-observed zones, and headless DOM +
> screenshots at 1440/500 px in CA and EN. See `PHASES.md` step 7.7.

#### Step 7.8 — Radar rain (XRAD or equivalent)

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

---

## 7. What I would build in the next three commits

1. **`feat(map): search, filters, sync, URL state, legend, free best zones`** — Phase 1.
2. **`feat(zones): per-zone scoring and zone detail`** — Phase 2, starting with Berguedà, Ripollès and Cerdanya; add 3–5 zones per massís.
3. **`feat(terrain): aspect/slope/solar enrichment and explainer`** — Phase 3, with cached results.

This ordering fixes the user's actual complaint first, then delivers the differentiator, then deepens the science.

---

## 8. Success metrics

- **Navigation**: time to reach a zone map view < 10 s; search success rate; filter usage; deep-link shares.
- **Model**: AUC and Brier vs field reports; top-10 zone hit rate; calibration curve.
- **Engagement**: zones viewed per session, trip reports per week, return rate in season.
- **Trust**: explainer open rate, confidence badge interaction, no "why is there no color here?" confusion.
- **Reach**: comarques covered, zones covered, species covered.

---

## 9. Risks and how to handle them

| Risk | Mitigation |
|---|---|
| Micro-zones become invented precision | Label every zone with a confidence and data source; only show zones with real terrain/forest data; keep "representation, not precision" language. |
| Too many API calls / slow load | Precompute static habitat scores; batch weather; cache daily; serve zone GeoJSON as one file/PMTiles. |
| Private/picking pressure | Round report locations to 1 km by default; never publish exact spots; allow private zones. |
| Overfitting to reports | Keep a held-out validation set; publish metrics; do not chase single reports. |
| Scope creep | Ship Phase 1 first; keep the current UI shell and design language; add, do not rewrite. |
| Legal risk | Keep disclaimers, regulations layer, no identification claims, no navigation guarantee. |

---

## 10. One-line summary

BoletRadar gives one smooth number per 100 m pixel and charges for the route. We can give **a free, explainable score per forest stand, with aspect, canopy, soil, microclimate, route and field calibration** — and a map you can actually navigate.
