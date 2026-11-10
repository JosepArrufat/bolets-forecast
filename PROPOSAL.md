# Proposal: How Bolets can surpass BoletRadar

_Audit of boletradar.cat, audit of the current Bolets app, and a phased implementation plan._

> **Status:** Phase 1 (map navigation and free features), Phase 2 (micro-zones) and Phase 3 (terrain and canopy science) are implemented. Phase 1 shipped search, filters, sorting, map↔list sync, clustering, URL state, the free best-zones leaderboard, route links, nearby parking, geolocation, legend and the data-quality indicator. Phase 2 added the `zones.json` micro-zone model: 66 independently scored zones across the 22 stations (massís → obaga/solana/carena stands), the zone comparison strip, the zone detail panel, and zone circles on the map. Phase 3 added the full enrichment pipeline (`enrich_zones.py` → `zones_enriched.json`: ICGC 5m DEM aspect/slope/solar/TPI/cold-air, ICGC LiDAR canopy/undergrowth, IGME/SoilGrids soil, CORINE habitat) and integrated those factors into the zone score and the "why this score" explainer as a five-factor H·M·W·P·C breakdown. Phase 4 is complete (4.1–4.6): 4.1 shipped batched Open-Meteo weather with lapse-rate elevation correction per zone; 4.2 shipped the optional Meteocat XEMA integration (observed station data interpolated to each zone with distance/data-age recorded; Open-Meteo stays the fallback and the score source; radar deferred — the API has no XRAD product, rain accumulation uses XEMA gauges); 4.3 shipped the soil water balance and drought index (per-zone P−ET0 14/30/60/90-day windows from the 92-day Open-Meteo ET0 series, a bounded FAO-56-style recharge index with a documented 100 mm storage cap, a documented XEMA observed-rain blend, and a per-species drought/recharge modifier on the zone rain term — station scores byte-identical). 4.4 added per-zone data confidence (completeness + deterministic prediction-confidence score with reasons, per zone and per species, reporting-only). 4.5 shipped phenology and the altitude-lag wave: per-species growing-degree-day states (GDD = Σ max(0, T − `temperature_c.min`) over the stored 14-day temperature series, lapse-corrected 6.5 °C/km to each zone's altitude), window open/close thresholds derived from the documented temperature band, `P` wired into the zone score (stations byte-identical), `altitude_lag_days` vs the warmest zone of each species, and the "rovelló wave" visual (altitude strip + 7-day forecast strip, CA/EN) in the zone detail and explainer. 4.6 verified the phase end to end (known-station-day temperature deltas, 66/66 lapse formula, day-rollover cache stamps, sources/timestamps audit, 4.5-identical regression and script) and recorded the honest limitations in README "Phase 4 verification (4.6)". Phase 5 is implemented (5.1 report model + API, 5.6 calibration + published AUC/Brier, 5.7 privacy/rate-limit/deletion verification and docs; the report UI, logbook, photos and alerts are deferred optional extras). Phases 1–5 are implemented. Next: Phase 6 (PWA and expansion, step 6.1).
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
- 13 species in `mushrooms.json` with temperature, rain window, altitude, soil and tree preferences.
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
