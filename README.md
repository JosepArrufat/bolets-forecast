# Bolets Forecast

**Live demo:** https://bolets-forecast.fly.dev

A mushroom hunting forecast tool for Catalunya — covering **22 comarques** across Catalonia (**46 forest stations, 135 micro-zones**). It combines real-time weather data with geology, vegetation and terrain/canopy data (ICGC DEM + LiDAR) to score how likely each of the top 21 edible Catalan mushrooms is to appear at a set of key forest stands, today and for the next six days.

No hallucination. No invented forest locations. Every score is derived from publicly available scientific data sources, all free, none requiring registration.

---

## How to run

No dependencies beyond Python 3 (stdlib only).

```bash
cd bolets
python3 app.py
```

Then open **http://localhost:8765** in your browser.

The first run fetches geological and vegetation data for all stations (takes 10–30 seconds depending on SoilGrids fallback calls). Subsequent runs are fast — those results are cached in `geo_cache.json` permanently.

---

## Working on the roadmap

The roadmap is split into small steps in **`PHASES.md`**. Each step is designed to
run in its own fresh session so context stays small:

```text
/phase next        # first step not marked done
/phase 2.1         # one exact step
/phase 2           # first not-done substep of phase 2
/steps             # phase map: main goal, end goal, status
/phase-status      # read-only status report
```

`/phase` runs in a child session (`subagent: true`) and updates `PHASES.md` with
the result, verification evidence and the next step. Run one step at a time; do
not run two phase sessions in parallel on the same working tree.

The commands pin `opencode-go/deepseek-v4-pro` because the DeepSeek V4.1
Flash cell can return `prefill_cap_refused`. `opencode-go/glm-5.3-flash` is a
cheaper fallback. Qwen models currently need a Go credential. If the pinned
model is unavailable, change the `model:` line in
`.opencode/commands/phase.md`.

---

## What it does

### The UI

- **Search and filters** — search by place, forest, municipality or species (Enter geocodes any place name). Filter by species, comarca, minimum score, and sort by score, distance, altitude, name or comarca.
- **Free "best zones" leaderboard** — the top six zones for the selected species and day, visible to everyone, with a one-tap route link. No paywall.
- **Left sidebar** — all stations grouped by comarca. Each card shows altitude, last 7 days of rain, average temperature, max wind, the top 4 species by score, the best day in the 7-day window, and a route button.
- **Map** — Leaflet map with clustered markers, numbered and colored by the selected species' score. Click a marker to open the detail panel. Hover syncs the marker with its card. A legend is always visible.
- **Right panel** — opens on station click. Shows a data-quality bar (meteo + soil + forest completeness), 7-day score strip, soil type badge (calcareous/siliceous/mixed), forest type badge (from CORINE), raw lithology, weather summary, and the full ranked species list. Click any species row to expand its score breakdown and notes.
- **Trip planning** — free "Com arribar-hi" (Google Maps), OpenStreetMap link, nearby parking from OpenStreetMap/Overpass, and a shareable zone link.
- **Shareable URL state** — species, day, comarca, search, sort, active zone and map view are encoded in the URL. Back/forward and deep links work.
- **Topo ICGC toggle** — top-right map button overlays the official ICGC topographic tiles for terrain context.
- **Geolocate** — "Situa'm" centres the map and reorders zones by distance from you.

### The scoring

Each species gets a score from 0–99 built in two stages:

**Stage 1 — weather score (from Open-Meteo)**

| Factor | Weight | What it measures |
|---|---|---|
| Rain | 35% | Total mm in the species' trigger window (7–10 days). Bonus if preceded by a dry spell (activates mycelium). |
| Temperature | 25% | Average of last 5 days min/max vs species ideal range. Hard cutoff below minimum or above maximum. |
| Wind | 20% | Average max daily gust over last 3 days vs species wind sensitivity threshold (25/35/50 km/h). |
| Altitude | 10% | Station elevation vs species ideal altitude band. Gaussian falloff outside ideal, zero outside hard limits. |
| Humidity | 10% | Average max relative humidity last 5 days. Full score at ≥70%. |

**Stage 2 — geo multipliers (from IGME + CORINE)**

The weather score is then multiplied by two independent factors:

- **Soil multiplier** — does the detected lithology (calcareous/siliceous) match what the species needs? Correct match = 1.0×. Wrong match = 0.15× (strong penalty). Mixed/unknown = 0.85–0.9×.
- **Forest multiplier** — does the CORINE land cover code match the tree type the species needs? Conifer forest for Rovelló = 1.0×. Broadleaf for Rovelló = 0.2×. Non-forest for meadow species = 1.0×.

Final score = `(weather_score × soil_multiplier × forest_multiplier) × 100`, capped at 99.

Labels: **Molt bona** ≥75, **Bona** ≥55, **Possible** ≥35, **Baixa** <35.

**Zones add a H·M·W·P·C breakdown (Phase 3.5).** Each scored zone gets the same
two-stage score above, then multiplies it by two extra factors computed from the
enrichment data: `H` (habitat — soil × forest × canopy-openness) and `M`
(microclimate — aspect × potential sun × cold-air drainage), and reports `P`
(phenology gate) and `C` (confidence label) alongside `W` (the weather score
above). Station scores are unchanged — without an enrichment block `H` collapses
to the soil×forest multipliers and `M` is neutral, so the legacy number is
preserved exactly. See "Scoring integration (step 3.5)" for the full table.

---

## Data sources

| Source | What it provides | Key needed | Speed |
|---|---|---|---|
| [Open-Meteo](https://open-meteo.com) | Past 14 days + 7-day forecast: precipitation, temp min/max, wind gusts, humidity (this same series also feeds the Phase 4.5 GDD phenology — no extra fetch); plus a 92-day precipitation + FAO-56 ET0 series for the soil water balance (Phase 4.3) | None | ~0.3s |
| [IGME Litologías 1M](https://mapas.igme.es/gis/rest/services/Cartografia_Geologica/IGME_Litologias_1M/MapServer) | Spanish geological survey. Coarse 1:1M lithology text per point: "Dolomías, calizas…" vs "Cuarcitas, pizarras…" → calcareous or siliceous. Fallback when MAGNA 50 does not answer | None | ~0.1s |
| [IGME MAGNA 50](https://mapas.igme.es/gis/rest/services/Cartografia_Geologica/IGME_MAGNA_50/MapServer) | 1:50,000 lithology polygons ("Litologías color"), queried at each zone centroid. Preferred source (step 7.4): 56 zones promoted to calcareous/siliceous with the raw legend text and sheet number stored; 2 unambiguous flips are held for field review | None | ~0.2s |
| [CORINE Land Cover 2018](https://image.discomap.eea.europa.eu/arcgis/services/Corine/CLC2018_WM/MapServer/WMSServer) | EU land cover map. Codes: 311=broadleaf, 312=conifer, 313=mixed, 324=transitional shrub | None | ~0.5s |
| [SoilGrids v2 (ISRIC)](https://rest.isric.org/soilgrids/v2.0/properties/query) | Global soil pH at 250m resolution. Used as fallback only when IGME lithology is ambiguous | None | ~8s |
| [Meteocat API](https://api.meteo.cat) | Official Catalan Met Service: XEMA automatic-station observations (temperature, precipitation, daily accumulation), interpolated to each zone with distance/data-age recorded. Optional. | Free key (apply at apidocs.meteocat.gencat.cat) | fast |

IGME, MAGNA 50 and CORINE results are cached to `geo_cache.json` / `terrain_cache.json` on first fetch and never re-fetched (geology does not change). Weather is always re-fetched live.

---

## The species

21 edible mushrooms (autumn, plus spring, summer and winter species), each defined in `mushrooms.json` with:

| Species | Catalan name | Soil | Tree type | Key condition |
|---|---|---|---|---|
| *Lactarius sanguifluus* | Rovelló | Calcareous | Scots pine (red pine) | Open reforestation, no undergrowth, 800–1400m |
| *Boletus edulis* | Cep / Sureny | Neutral–acid | Pine, beech, oak | Sustained moisture, high altitude, obaga (N-facing) |
| *Tricholoma terreum* | Fredolic | Calcareous | Pine, fir | Cold tolerant, late autumn after rovellons |
| *Cantharellus cibarius* | Rossinyol | Siliceous | Beech, oak, chestnut | Consistent rain, broadleaf forest, obaga |
| *Craterellus cornucopioides* | Trompeta de la Mort | Siliceous | Beech, oak | Late autumn rains, humid broadleaf |
| *Hygrophorus olivaceoalbus* | Llenegra Negra | Siliceous | Fir, spruce | High altitude (1400–2000m), very cold |
| *Hygrophorus eburneus* | Llenegra Blanca | Calcareous | Beech, oak | Broadleaf calcareous forests |
| *Cantharellus lutescens* | Camagroc | Siliceous | Pine | High altitude Pyrenees, late autumn |
| *Amanita caesarea* | Ou de Reig | Siliceous | Oak, chestnut | Summer (June–Sept), warm, low altitude |
| *Coprinus comatus* | Bolet de Tinta | Any | Meadows, roadsides | No forest needed, open disturbed soil |
| *Otidea onotica* | Orella de Llebre | Siliceous | Pine, beech | Mixed/conifer forest, acid soil |
| *Morchella esculenta* | Murgola | Calcareous | Riverbanks, mixed | Spring only (March–May), filtered out in autumn |
| *Macrolepiota procera* | Picornell | Any | Forest edges | Open clearings, warm autumn |
| *Calocybe gambosa* | Bolet de Sant Jordi | Calcareous | Meadows, forest edges | Spring (April–May), classic Sant Jordi |
| *Boletus reticulatus* | Cep d'estiu | Neutral–acid | Oak, beech, chestnut | Summer (May–Aug), reticulated stem |
| *Pleurotus ostreatus* | Gírgola | Any | Dead broadleaf wood | Winter (Nov–Mar), on stumps |
| *Agaricus campestris* | Camperol | Any | Grassland | Autumn, pink gills that darken |
| *Tricholoma portentosum* | Fredolic gros | Siliceous | Pine | Late autumn, grey cap, acid pine forest |
| *Marasmius oreades* | Cama-sec | Any | Grassland | Autumn, fairy rings, dries well |
| *Boletus aereus* | Cep negre | Neutral–acid | Oak, chestnut, beech | Warm autumn, near-black cap |
| *Suillus luteus* | Molleric | Any | Pine | Autumn, slimy cap (peel before cooking) |

Full conditions (temperature ranges, rain triggers, altitude bands, dry spell requirements, wind sensitivity) are in `mushrooms.json` and can be edited without touching the code.

### Seasons (Phase 6.3)

Each species carries an optional `season` field. **Autumn** (or an unset `season`) is the app's default: those species are scored year-round and damped outside the September–November peak. **Spring** (Mar–May), **summer** (Jun–Aug) and **winter** (Dec–Feb) species are strictly seasonal and are filtered out of the forecast in the other months, so a summer `Ou de Reig` no longer scores in November and a winter `Gírgola` only appears in its season. Spring species behave exactly as `Murgola` always has.

### Lookalike warnings (Phase 6.3)

Every edible species now carries a `lookalikes` array — a safety-critical list of confusable mushrooms, each with a scientific/common name, a severity (`mortal`, `toxic`, `inedible`, or `none` when there is no serious lookalike) and the key field differences. These render as a prominent **"Perill de confusió" / "Lookalikes (do not confuse)"** section in the score explainer and a compact warning line in each expanded species row. Lookalike facts are drawn from reference field-guide knowledge, not from the scoring model, and are a starting point — they never replace expert identification: **when in doubt, do not pick.**

---

## PWA and offline use (Phase 6.1)

The app is an installable Progressive Web App. It ships a manifest
(`/manifest.webmanifest`), a programmatically drawn mushroom icon set
(`/icon-192.png`, `/icon-512.png`, `/icon-maskable-512.png` — no binary files
committed; they are rendered from `app.py` at startup), a theme colour and a
service worker (`/sw.js`).

- **Install:** "Add to home screen" / "Afegir a la pantalla d'inici" from the
  browser menu (Chromium/Android and iOS Safari). Runs standalone.
- **Offline shell:** the service worker precaches the app shell and icons, so
  the app opens and the map chrome loads without a connection. Map tiles and
  the live forecast are *not* cached wholesale (they are large and time-bound);
  this is the "coarse offline snapshot" trade-off.
- **Offline pack:** open a zone and tap **"💾 Desa per anar al bosc"** ("Save
  for offline"). The zone's location, terrain/forest/soil facts, access notes,
  7-day score strip and top species are stored locally (in `localStorage`) as a
  dated snapshot. The header **💾** button lists saved zones; each opens a
  clearly-labelled *"Instantània fora de línia · aproximada"* view with the
  route and OSM links, even with no connection. When the forecast cannot be
  fetched (offline), the sidebar falls back to the saved zones.
- **Honesty:** a saved zone is an explicit snapshot of the forecast *at the
  moment it was saved* — the UI labels it as such and never presents it as a
  live prediction. Reconnect to refresh scores.

---

## Performance, caching and accessibility (Phase 6.4)

The live forecast payload was the main performance risk: 46 stations × 135
zones × 16 species × 7 days repeated the same static species text thousands of
times, and the uncompressed JSON reached **48.7 MB**.

- **Static species catalogue.** `name`, `scientific`, `thresholds`, `lookalikes`,
  `notes` and `season` now travel once in a top-level `species_meta` object
  (16 species, ~13 KB) instead of on every score entry. The embedded UI
  rehydrates them in `hydrateForecast()` on load, so the panels, explainer and
  lookalike warnings render exactly as before. Scores and every dynamic value
  are untouched.
- **Compression.** `/api/forecast` (and other JSON endpoints over 1 KB) is
  gzipped when the client sends `Accept-Encoding: gzip`, with
  `Content-Encoding: gzip` and `Vary: Accept-Encoding`. The forecast falls from
  **29.7 MB raw to 1.08 MB on the wire** (~27× less than the new raw payload,
  and ~45× less than the pre-6.4 48.7 MB response).
- **Built-forecast cache.** The serialised response is cached in memory, keyed
  by the calendar day plus the mtime/size of `mushrooms.json`, `zones.json`,
  `zones_enriched.json` and `weather_cache.json`, for 300 s. A repeat request
  takes **~2 ms instead of ~3 s**, and a failed rebuild serves the last good
  payload (`X-Forecast-Cache: hit | miss | stale`), matching the weather cache's
  stale-on-error behaviour.
- **No GeoJSON/PMTiles.** Zones are curated point stands with optional access
  notes, not polygons; there is no polygon data to serve. Adding vector tiles
  would mean sourcing new geometry, not making the current map faster, so it was
  deliberately not done.
- **Accessibility and keyboard.** A visible `:focus-visible` ring, focus moving
  into the detail panel when it opens and back to the card (or search) when it
  closes, `Escape` closing the panel and the explanation dialog, `role="dialog"`
  + `aria-modal` + focus restoration on the explainer, `aria-selected` on the
  mobile map/list tabs, 44 px mobile touch targets, `prefers-reduced-motion`
  handling, and darker score-pill green/amber for WCAG AA contrast. The zone
  detail's confidence badge no longer renders `NaN%` (the Phase 4.4 confidence
  object had replaced the curated numeric value).
- **Measured on 2026-11-11** with the weather cache warm: `build_forecast()`
  2.38 s, serialise 0.35 s, gzip 0.20 s; first HTTP request 3.07 s, cached hit
  1.77 ms, browser transfer 1.08 MB in 168 ms, 46 stations / 135 zones / 0
  errors. Scores were verified identical against an un-deduplicated build in the
  same process (byte-equal after rehydration).

---

## Coverage expansion (Phase 6.2)

The map grew from 6 station groups / 22 stations / 66 zones to **22 groups /
46 stations / 135 zones**. All 13 priority comarques now have at least one
verified forest stand, plus three adjacent comarques (Gironès, Vallès Oriental,
Alt Penedès) whose stations fall just outside the nominal boundary.

| Comarca | New stations | New zones |
|---|---|---|
| Alt Urgell | 3 | 9 |
| Solsonès | 2 | 5 |
| Osona | 2 | 6 |
| La Selva | 1 | 3 |
| Alta Ribagorça | 2 | 6 |
| Val d'Aran | 2 | 6 |
| Noguera | 2 | 6 |
| Priorat | 1 | 3 |
| Terra Alta | 2 | 5 |
| Montsià | 1 | 3 |
| Baix Empordà | 1 | 3 |
| Maresme | 1 | 3 |
| Garraf | 1 | 2 |
| Gironès (adjacent) | 1 | 3 |
| Vallès Oriental (adjacent) | 1 | 3 |
| Alt Penedès (adjacent) | 1 | 3 |

**Method (same rules as Phase 2):**

1. Each massís/forest starts from a **published coordinate** — a Catalan
   Wikipedia article or an OpenStreetMap/Nominatim place record — never a
   guessed point.
2. A 5 × 5 grid (1 km spacing, widened to 7 × 7 / 750 m when needed) around that
   anchor is queried against **CORINE CLC 2018**; only forest cells (311, 312,
   313, 324) are kept.
3. **ICGC 5 m DEM** gives each candidate's altitude, aspect and slope.
4. Up to three cells per massís are kept (north/obaga, south/solana, then the
   highest remaining stand, at least 500 m apart).
5. **IGME MAGNA 50 (1:50k)**, falling back to **IGME 1:1M**, supplies
   lithology (calcareous/mixed/siliceous) and **SoilGrids v2** supplies pH
   when the service answers; otherwise pH stays
   `null` and the source list omits SoilGrids. `access`, `water_m`,
   `drive_min` and `difficulty` stay `null` until a source is verified (Phase
   7.2 fills `drive_min`/`difficulty`; canopy is the LiDAR `enrichment.canopy`).

**Verification:** every one of the 69 surviving new zone centroids was re-queried
live against CORINE after curation — **69/69 return a forest class matching the
stored `forest.type`**. Two candidate cells failed that final re-check (one in
Serra de Cavalls, one in Montgròs) and were deleted rather than kept. Zone IDs
are unique across the whole file (135/135).

**Honest limits:** zone altitude is the selected forest cell's DEM altitude, not
the massís summit (a low massís such as Montgrí legitimately contributes stands
at ~110 m). CORINE is a 100 m mapping unit, so `forest.dominant` names
the CORINE group (`frondós`, `conífera`, `mixt`) rather than a tree species;
lithology is IGME MAGNA 50 (1:50k) where it answers, else 1:1M; 52 of the 69 new
zones have no pH because SoilGrids timed out, and that field is left empty
instead of invented. Their confidence is derived from that evidence by Phase 7.3
(no pH and no parking mean a lower value, not a fabricated one).

### Forest-offset integrity gate (Phase 7.1)

`repair_forest_offsets.py` is the standing check that every station point is
real forest. It queries CORINE CLC 2018 for each of the 46 station coordinates,
accepts only the forest classes **311/312/313/324**, and re-gates every zone
centroid with `--check-zones`. Results are written to
`forest_offset_report.json` (station, comarca, old coordinates, gate code,
zone count, candidate, status).

- `python3 repair_forest_offsets.py` — read-only gate; prints one line per
  station and writes the report.
- `python3 repair_forest_offsets.py --check-zones` — also gate all 135 zones.
- `python3 repair_forest_offsets.py --apply` — write a moved point **only** when
  its candidate passes the forest gate. The previous coordinates, date, reason
  and source are stored in the station's `forest_offset_history`; altitude is
  never rewritten silently (the candidate DEM altitude is recorded for review).
- `python3 repair_forest_offsets.py --self-test` — offline fixtures for the
  pass/candidate/needs-review/apply/history paths.

**Live result (2026-11-12):** 46/46 stations pass the forest gate, 135/135 zone
centroids pass and match their curated forest class, 0 candidates, 0 moves. So
the old "Ribes de Freser / Puigcerdà land on non-forest" note was stale — those
towns are no longer station points, and the current 46 are all forest-sourced.
Two station points are forest but in a different class from their zones'
majority — Serra del Montsià (mixed vs broadleaf zones) and Pallars – Sort
(broadleaf vs conifer zones). Both are valid stands within a mixed massís and
are reported as review flags rather than moved.

### Zone facts completion (Phase 7.2)

`complete_zone_facts.py` fills the curated fields that used to be null even
though a citable source existed. It writes back into `zones.json` (and
`enrich_zones.py` then regenerates `zones_enriched.json`, keeping the two files
in agreement — checked by `python3 complete_zone_facts.py --check-schema`):

- **`access.drive_min`** — OSRM driving time in whole minutes from the
  **comarca capital** (the documented reference point; Wikipedia / OSM Nominatim)
  to the zone's parking point, or to the zone centroid when no parking is mapped.
  The origin/destination are recorded in `access.drive_min_source`, and the trip
  card labels the time with that origin (`25 min · des de Ripoll`).
- **`access.difficulty`** — a written rule from slope + walk distance. Walk
  distance is the straight-line parking → centroid, or the station's documented
  forest point → centroid when no parking is mapped; slope alone is used only
  when neither origin exists. Rule: `fàcil` = walk ≤ 1500 m and slope < 20°
  (slope < 15° without a walk origin); `moderada` = walk ≤ 4000 m and slope
  < 30° (slope < 25°); otherwise `exigent`. Recorded in
  `access.difficulty_source`.
- **`water_m`** — distance to the nearest OSM `waterway` / `natural=water` /
  `water` feature, computed from Overpass geometry and cached in
  `water_cache.json`. When Overpass answers but no feature is mapped, `water_m`
  is null and `water_source` says "no mapped feature (unknown, not 'no water')";
  when Overpass is unavailable the fields are left untouched, never faked.
- **`access.parking_lat`/`parking_lon`** — for the 69 zones added in 6.2 whose
  parking was null, the nearest OSM `amenity=parking` within 2.5 km (same
  Overpass query). 53 of the 69 got a mapped point; 16 stay null because OSM has
  no parking feature within the radius (unknown, not "no parking").
- **`forest.canopy_pct` / `forest.undergrowth` removed** — these null placeholders
  duplicated the LiDAR `enrichment.canopy` block; the enrichment is now the only
  source (the UI reads `enrichment.canopy` directly).

External results are cached in `water_cache.json` and `route_cache.json` (both
gitignored), so re-runs never re-query. The Overpass endpoint order is the
French world mirror first (`overpass.openstreetmap.fr`), then
`overpass-api.de`, then `kumi.systems`: on the 2026-11-16 retry the primary was
flapping between HTTP 502 "at capacity" and multi-second queues while the French
mirror answered a Catalan station bbox in ~2 s with full coverage.

> **Status (2026-11-16): complete.** `drive_min` 135/135, `difficulty` 135/135,
> `water_m` **135/135**, parking **119/135** (53 of the 69 6.2 zones got a
> mapped point; 16 have none within 2.5 km and stay null). All 46 stations
> answered Overpass in one run; `--check-schema` passes. Re-deriving confidence
> (7.3) now gives **110 `alta` / 25 `medium`** (water and parking are evidence
> bonuses), up from 82/53. Three zones were
> re-checked against independent `around:` queries — a waterway exists just
> outside `water_m` and none inside, so the distances are real geometry. Drive
> times changed on 44 zones and difficulty on 14 because the walk origin is now
> the mapped parking instead of the zone centroid/station point (the documented
> method). Water and access are display-only: the score is unchanged.

### Confidence that discriminates (Phase 7.3)

`zones.json` used to carry `confidence: 0.6` (`medium`) on all 135 zones, so the
`C` factor could not rank one stand above another. `derive_zone_confidence.py`
now derives each zone's curated confidence from evidence that already exists —
no new data and no hand-written value:

```text
confidence = clamp(0.30, 0.45 + Σ evidence bonuses, 0.80)
```

| evidence | bonus | source |
|---|---|---|
| 4 source labels / 5+ | +0.02 / +0.04 | the zone's own `sources` list |
| SoilGrids pH answered | +0.05 | `enrichment.soil.ph` (or `soil.ph_approx`) |
| real 1:25k soil / MAGNA 50 (1:50k) | +0.10 / +0.07 | `enrichment.soil.resolution` (7.4/7.6 active: 7 × 1:25k, 49 × 1:50k) |
| soil class known (calcareous/siliceous) | +0.05 | `enrichment.soil.type`; `mixed` earns 0 |
| CHC50 1:25k habitat | +0.10 | `enrichment.habitat.resolution` (step 7.6; absent today) |
| ICGC 5 m LiDAR / Copernicus DEM | +0.04 / +0.02 | `enrichment.terrain.dem_source` |
| LiDAR canopy coverage ≥ 0.90 / ≥ 0.75 | +0.03 / +0.015 | `enrichment.canopy.sample_coverage` |
| CORINE forest gate passed | +0.04 | `forest_offset_report.json` `zone_gate` (step 7.1) |
| drive time + difficulty present | +0.04 | `access.drive_min` + `access.difficulty` |
| parking coordinates + trailhead present | +0.03 | `access` (absence is **not** a failure) |
| `water_m` known | +0.03 | `water_m`; null means **unknown**, no bonus, never a penalty |

Labels: `alta ≥ 0.75 > medium ≥ 0.55 > baixa`. “Alta” means every available
evidence layer answered — not that the dominant tree was verified in the field.
The value is **reporting-only**: it feeds the 4.4 `confidence` block and the
explainer's `C` factor, never a score (the 7.3 shadow diff is byte-identical
apart from `confidence`/`C`).

Each zone also stores `confidence_evidence`: the per-component bonus, value and
human-readable detail, so a reviewer can see why it scored what it did.
`confidence_report.json` records the old-vs-new distribution and every zone's
evidence.

- `python3 derive_zone_confidence.py` — shadow diff only (no write).
- `python3 derive_zone_confidence.py --apply` — write `zones.json` + report.
- `python3 enrich_zones.py` — **required after `--apply`**: `zones_enriched.json`
  duplicates the curated fields, and `complete_zone_facts.py --check-schema`
  fails if it is stale.
- `python3 derive_zone_confidence.py --check` — verify the file matches the
  derivation.
- `python3 derive_zone_confidence.py --self-test` — offline evidence/anchors.

**Live result (2026-11-12):** 135/135 zones changed from `0.6` to a range of
**0.62–0.77**; labels **44 alta / 91 medium**; the 4.4 prediction-confidence
score now spans 0.631–0.678 (was 0.577–0.624), and completeness stays 100 %.
`water_m`/parking nulls are treated as unknown, so the 7.2 Overpass blocker does
not lower any zone's confidence.

**After step 7.4 (2026-11-15):** re-derived with the MAGNA 50 anchor active,
`--check` passes and the range is **0.62–0.80** with **63 alta / 72 medium**
(56 zones gained the 1:50k bonus and/or a known soil class; the 2 held zones
stay `alta` but drop from `0.80` to `0.77`). Confidence remains reporting-only.

**After step 7.6 (2026-11-15):** the 1:25k soil/habitat anchors are active, so
the current derivation is **0.62–0.80** with **82 alta / 53 medium**; see the
7.6 section for the coverage and the 2026-11-15 audit correction.

### IGME MAGNA 50 soil (Phase 7.4)

Soil lithology now queries **IGME MAGNA 50** ("Litologías color") at each zone
centroid and promotes a class only when the legend is unambiguous:

- **calcareous** — pure carbonate/evaporite terms (caliza, dolomía, marga, yeso,
  calcarenita…);
- **siliceous** — igneous/metamorphic or siliceous sedimentary terms (granito,
  gneis, pizarra, cuarcita, lidita…), with no carbonate term;
- **mixed → fall back to 1:1M** — detrital-only descriptions (sandstone,
  conglomerate, lutite, clay), carbonate + detrital transitions, and surficial
  deposits (glacial, colluvium, dunes, landslides).

Each promoted zone stores `resolution: "1:50k"`, the raw `litho_text`, the
`magna_hoja` sheet number, and `fallback_reason: null`; a fallback stores
`resolution: "1:1M"` plus the reason (no sheet coverage, ambiguous legend, or a
review hold). A held zone also keeps the suppressed proposal in
`soil.magna_review` (class, legend, sheet, `status: "held"`). The score
(`app.py::_apply_magna50_soil`) and the confidence anchors (`_conf_quality`) both
read `enrichment.soil`, so a 1:50k zone's `H` factor uses the finer class and its
confidence gets `Q_SOIL_MAGNA50`.

**Audited result (2026-11-15):** 56 zones at 1:50k across 17 sheets, 79 at 1:1M
(12 no coverage, 65 ambiguous legend, 2 held); **0 fallback zones changed
class**; 41 promotions kept the old class (resolution/confidence only) and
**15 changed** (8 mixed→siliceous, 7 mixed→calcareous). All 58 MAGNA-answering
points were re-queried live and match exactly (`0` mismatches). The two
calcareous→siliceous flips (Coll de Pal — cresta alta, Bagà — obaga pi) sit on
the broad *Liditas y alternancia de areniscas y lutitas* unit, reproduced at
±300 m around each point, but their class change inverts the soil multiplier,
so they are **held at 1:1M pending a field check** (see `MAGNA_REVIEW_HOLDS`).
`enrich_zones.py --self-test`, `py_compile`, the 135-zone regeneration and the
live API all pass; see `PHASES.md` step 7.4 for the full per-zone audit. The zone
detail card now shows the same 1:50k class (with `· 1:50k`) that the score uses,
so the explanation cannot contradict the ranking. Step 7.6 later re-sampled 7 of
these zones at 1:25k and moved the counts on (see the 7.6 section).

### Backtest and weight validation (Phase 7.5)

The hand weather weights (rain 35 / temperature 25 / wind 20 / altitude 10 /
humidity 10) and the `H`/`M`/`P` multipliers are modelling choices, not
field-verified numbers. `calibrate.py` now validates them against GBIF +
iNaturalist occurrence data and writes the result into
`calibration_report.json` (version 2) under `backtest_7_5`:

- **Pseudo-absences** are target-group background — background points sampled
  from the pooled occurrence set of all species (excluding the focal species),
  so they reflect where recorders actually look.
- **Recorder-effort weighting** down-weights spatially clustered records:
  `w = 1 / (1 + neighbours within 5 km)`, applied to every presence and
  background point via a weighted Mann–Whitney U.
- **Factor sensitivity** permutes each stored factor (`W`, `H`, `M`, `P`) and
  reports the drop in weighted AUC; **model fit** refits the five weather weights
  on a held-out split and reports a bootstrap 95 % CI on the gain.
- **Temporal split** (train on older occurrences, test on newer) applies only to
  the time-invariant habitat signal (`H` × `M` × altitude) — weather `W` and
  phenology `P` are scored with today's conditions and cannot be split by year.
  The two eras are scored separately; the older-era 95th-percentile background
  threshold is also carried to the newer era as a strict transfer check.

**Live result (2026-11-15):** 3216 pooled rows, baseline weighted AUC 0.6037.
`H` is the dominant discriminator (permutation drop 0.0822 vs `W` 0.0082,
`M` 0.0039, `P` −0.0003). The weight refit is **not promoted**: held-out AUC
0.631 (current) vs 0.6299 (refit), gain −0.001 with bootstrap 95 % CI
[−0.008, +0.0043] — so the hand weights stay and `app.py` scoring is unchanged.
On the temporal split (year 2025: 759 older / 431 newer presences, 1232 / 778
background), habitat-only AUC is 0.5334 older and 0.5929 newer (pooled 0.5551):
the rank transfers across eras, but only 3.5 % of newer presences clear the
older-era 95th-percentile threshold, so the absolute score level does not.
Run `python3 calibrate.py` (and `--self-test` for the offline checks). The
presence-only caveats still apply: this validates rank discrimination, not a
calibrated probability; only field reports can do that.

### Real 1:25k soil and habitat (Phase 7.6)

`enrich_zones.py` now retries the two intended 1:25k layers at every zone
centroid and records `resolution: "1:25k"` where they answer, ahead of the
MAGNA 50 / CORINE fallbacks:

- **Soil — ICGC MSC25M.** The *Mapa de sòls de Catalunya 1:25.000* is queried
  through its WFS (`geoserveis.icgc.cat/…/edafologia/wfs`, layer
  `icgc_sols:sols-25000`). Each polygon's parent material (`descripcio`, e.g.
  "S'han format sobre calcàries") is classified calcareous/siliceous with the
  same conservative keyword rule as MAGNA 50; a detrital/transported parent
  stays "mixed" (keeps the fallback). Coverage is published sheet by sheet, so
  the mountain sheets are not there yet: it answers for **7/135 zones** (Puig de la
  Mola, Montgrí, Montgròs), all calcareous and matching the MAGNA/1:1M class, so
  **no soil class changed** — the score is byte-identical and only
  `resolution`/`source` move (the soil unit, Soil-Taxonomy class and parent
  material are recorded in `enrichment.soil.soil_1_25k`). The WFS BBOX filter
  returns every polygon *intersecting* the box, so the provider keeps only the
  polygon that contains the centroid (ray casting); a point with no containing
  polygon stays on the fallback. The 128 uncovered zones keep their MAGNA 50 /
  1:1M value with the reason recorded.
- **Habitat — CHC50 is still down; CHC3 (1:25k) answers for Barcelona.** The UB
  "geoveg" CHC50 WMS is still unreachable (no response; `geoveg.creaf.cat`
  does not resolve), so the *version-3* cartography (**CHC3, 1:25k, 2019-2022**)
  is used instead, served for the Barcelona counties by the Diputació de
  Barcelona SITMUN WMS (`SITXELL`, layer `SITXELL_MN340`). It answers for
  **50/135 zones** with a full CORINE-list code/name (e.g. `42.5921+` "Boscos de
  pi roig (Pinus sylvestris), calcícoles i xeròfils, dels Pirineus"), which
  resolves stand-level tree species — the exact distinction CORINE CLC (100 m)
  cannot make. The finer habitat is recorded in `enrichment.habitat.chc3` as a
  **shadow block**; the score keeps the CORINE forest group (step 7.6's "keep
  the old value" rule), and the 85 zones outside the Barcelona province stay on
  CORINE CLC 2018.

The zone-detail soil badge now shows the resolution (`· 1:25k` / `· 1:50k`), and
the confidence reasons label the finer layers (`sòl ICGC MSC25M (1:25k)`,
`hàbitat CHC3 (1:25k, ombra)`). Re-deriving confidence (7.3) with the new layers
moves the 135 zones from 63 `alta` / 72 `medium` to **82 `alta` / 53 `medium`** —
a reporting change only; the score is unchanged because the 1:25k soil class
equals the MAGNA/1:1M class and the CHC3 habitat is shadow-only. Only zones with
an explicit 1:25k resolution earn the habitat anchor; the provider's chain
description is not parsed (an earlier pass credited all 135 zones, which the
2026-11-15 audit corrected).

### GeoVeg and manual field observations (Phase 7.7)

The YouTube tool's key vegetation source — the UB/CREAF interactive map
("GeoVeg" / SIVIM) that returns free-text vegetation polygons with the
stand-level tree species and soil reaction — has been down for the whole
project. Step 7.7 adds a **dormant** provider for it and a **manual
field-observation path** so a trusted person can fill the same gaps by hand.

- **Dormant GeoVeg provider (`enrich_zones.py`).** `_geoveg(lat, lon)` mirrors
  the `_corine` interface and currently returns `(None, "unavailable")` — the
  host is down and its query shape cannot be verified, so nothing is fabricated.
  `_parse_geoveg(text)` is the reviewed keyword parser: it reads the stand's
  `calcícola`/`acidòfil` ecology words into `soil_reaction`
  (calcareous/siliceous), the tree keywords into a `tree_species` list (ambiguous
  "roures" → `Quercus spp.`, never a single invented species) and derives a
  `forest_group` (conifer/broadleaf/mixed). `_geoveg_shadow(parsed, corine_code)`
  diff-computes the parsed result against the CORINE group the score uses and
  reports a `matches_corine` flag (or `null` when either side has no clear tree
  group). It is **not wired into the score** — activating it is a one-line change
  once the host returns, so the score stays byte-identical. The parser and shadow
  diff are exercised by `python3 enrich_zones.py --self-test`.
- **Manual field observations (`field_observations.json`).** A trusted person can
  record stand-level facts for a zone by hand — `tree_species`, `undergrowth`,
  `soil_reaction`, `water_m` — each entry carrying a `source`, `verified_at` date,
  `observer` and the observer's own `confidence` (`alta`/`medium`/`baixa`). The
  loader (`app.py::get_field_observations`) **validates** each entry: it is
  dropped unless it records a source, a date, an observer and at least one
  observed fact, so a manual note is never silently trusted and **never overwrites
  a sourced enrichment or curated value**. A zone with an entry gets a
  **"✓ Verificat per una persona"** badge in the zone detail, its observed facts
  listed, and a `field_observation` line in the data-confidence reasons. The file
  is committed empty (`observations: {}`) with the schema documented in `_meta`;
  add an entry keyed by the zone `id` and restart to surface it. Every forecast
  payload carries `field_observation` (the entry or `null`) and
  `verified_by_person` (a boolean) per zone, and the built-forecast cache
  invalidates on file edits.

### Radar rain (Phase 7.8) — blocked

Step 7.8 set out to replace the ~11 km rain grid with radar. The 2026-11-16
investigation found that the original premise ("Meteocat exposes no XRAD
product") has **evolved**, but the step still cannot reach its evidence bar, so
it is recorded as `blocked` with no code change.

- **A free, geo-referenced source now exists.** EUMETNET publishes OPERA
  pan-European radar composites through the **MeteoGate Open Radar Data (ORD)
  API** (`https://api.meteogate.eu/eu-eumetnet-weather-radar/`, CC BY 4.0,
  anonymous since 2026-05-20). `ACRR` is a **1-hour accumulation in mm** on a
  2 km grid, delivered as open-access, uncompressed, tiled float32 GeoTIFF
  (~2.7 MB) on an S3 store; `RATE` and `DBZH` are ODIM HDF5. The grid is LAEA
  (`+proj=laea +lat_0=55 +lon_0=10 +x_0=1950000 +y_0=-2100000`, 1900×2200 at
  2000 m).
- **Why it is still blocked.** The ORD EDR `/position` and `/locations` queries
  do not sample composites at a point (HTTP 204 / metadata-centre series only),
  so a consumer must download tiles, decode them and project lat/lon → LAEA
  itself. This app is deliberately **stdlib-only** (no `numpy`, `rasterio`,
  `pyproj`, `tifffile` or HDF5 reader), the ORD object store holds a **24-hour
  rolling cache only** (so `mm_72h`/`mm_7d` need an archive that is not
  confirmed), and the step's required radar-vs-gauge validation on a storm day
  could not run in the then-current dry 24 h window. Hand-rolling a TIFF tile
  reader plus LAEA and gauge adjustment without a storm-day validation risks
  injecting wrong rainfall into the score, which the "no invented values" rule
  forbids.
- **Unblock path.** Decide the dependency question (add a raster decoder or
  hand-roll the uncompressed tiled-TIFF reader + LAEA and unit-test it against a
  known pixel), confirm archive access for 72 h/7 d, validate ACRR 1 h/24 h mm
  against the existing XEMA gauge IDW (`_xema_daily_idw`) over a rainy period,
  then wire a `_radar_rain` provider plus a labelled `radar` blend into
  `blend_water_precip` / `compute_water_block` and re-run the no-key
  byte-identical regression. The gauge side already exists: XEMA variable 35 is
  measured 30-minute precipitation, used by the Phase 4.3 blend.

Full probe notes live in `PHASES.md` (step 7.8 result) because the raw artifacts
were written to a temporary directory.

---

## Files

```
bolets/
├── app.py           — single-file Python web app (stdlib only, no pip); also
│                      serves the PWA manifest, service worker and icons (Phase 6.1)
├── forecast.py      — original CLI-only scorer (kept for reference/debugging)
├── mushrooms.json   — species database + station definitions + scoring weights
├── zones.json       — curated micro-zone definitions, keyed by station name
├── enrich_zones.py  — terrain/canopy enrichment (Phase 3), writes zones_enriched.json
├── zones_enriched.json — generated: zones.json + per-zone enrichment block
├── terrain_cache.json  — generated: enrichment samples by rounded lat/lon (source + timestamp)
├── geo_cache.json   — auto-generated, IGME + CORINE cache per lat/lon
├── parking_cache.json — precomputed nearby parking per station (warm_parking.py)
├── reports.db        — auto-generated: SQLite field reports (Phase 5.1), gitignored
├── calibrate.py      — calibration + published metrics pipeline (Phase 5.6)
├── calibration_report.json — generated: AUC/Brier/calibration results (Phase 5.6)
├── warm_parking.py  — one-off script to fill parking_cache.json from Overpass
├── complete_zone_facts.py — derive water_m/drive_min/difficulty + canopy de-dup (Phase 7.2)
├── water_cache.json  — generated: OSM water + parking per station (Phase 7.2), gitignored
├── route_cache.json  — generated: OSRM drive times (Phase 7.2), gitignored
├── repair_forest_offsets.py — CORINE forest gate for stations + zones (Phase 7.1)
├── forest_offset_report.json — generated: last gate result, per-station diff (Phase 7.1)
├── derive_zone_confidence.py — evidence-based per-zone confidence (Phase 7.3)
├── confidence_report.json — generated: old-vs-new confidence + evidence (Phase 7.3)
├── field_observations.json — curated manual field observations per zone (Phase 7.7)
├── PROPOSAL.md      — audit of BoletRadar + phased roadmap to surpass it
├── PHASES.md        — execution ledger: status, substeps and acceptance criteria
├── .opencode/commands/phase.md        — `/phase <step>` fresh-session runner
├── .opencode/commands/steps.md        — `/steps` phase map and goals
├── .opencode/commands/phase-status.md — `/phase-status` read-only report
├── appIdea.md       — original project spec
└── youtubetranscript.md  — transcript of the YouTube video that defines the rules
```

---

## Known limitations

### 1. CORINE resolution (100m)
CORINE land cover is mapped at 100m resolution from satellite imagery. It distinguishes conifer from broadleaf well at the comarca scale, but cannot tell Scots pine from black pine, or a young reforestation from an old-growth forest. The YouTuber's key insight — "Scots pine reforestation without undergrowth" — cannot be detected from CORINE alone.

### 2. IGME lithology resolution (1:1M, MAGNA 50 where available)
The 1:1M geology map is good for distinguishing the Pyrenean calcareous massifs from the siliceous granitic zones, but misses local variation: a hillside can switch from calcareous to siliceous over a few hundred metres. Phase 7.4 now queries the finer IGME MAGNA 50 (1:50,000) first and uses it when the sheet covers the point and the legend is unambiguous — **56 of 135 zones are 1:50k**, 79 keep the 1:1M value. Coverage is still patchy: 12 zones have no MAGNA sheet at the point, 65 have a verbose/transitional legend (sandstone–shale alternations, conglomerates, surficial deposits) that the conservative mapping refuses to guess, and 2 high-impact calcareous→siliceous flips are held for field review, so all three groups fall back to 1:1M and record the reason in `enrichment.soil.fallback_reason`.

For the 79 zones still on 1:1M there is a separate, pre-7.4 quirk: the score uses
the app's cached geo sample, which may resolve an ambiguous lithology to a
definite class from SoilGrids pH (`fetch_geo`: pH < 6.3 → siliceous, > 7.0 →
calcareous). The detail card now shows that same class and marks it
"pH-inferred" (11 zones), instead of showing the curated `mixed` type. Three
zones have a curated class but no cached geo sample: the card shows the curated
class while the score treats the soil as unknown (a conservative 0.9 multiplier).
Unifying those sources belongs to step 7.6.

### 3. Station coordinates are forest points
The legacy separate `forest_lat/forest_lon` offsets no longer exist. Every one of
the 46 stations in `mushrooms.json` is itself a curated forest point (Phases
2.2–2.5 re-sourced the original 22; Phase 6.2 sourced the new ones), and the
coordinate drives the station's IGME/CORINE sample, its weather request and its
altitude. The Phase 7.1 gate re-checked all 46 against CORINE CLC 2018 on
2026-11-12: **46/46 are forest** (311/312/313/324) and all 135 zone centroids
also pass (135/135). A station still shares one weather series across its zones
(zone weather is fetched separately in Phase 4.1), so within a massís the
microclimate difference comes from the DEM, not from moving the station point.

### 4. GeoVeg / SIVIM is down
The YouTube video's key tool — the UB/CREAF interactive vegetation map (geoveg.creaf.cat and ub.edu/geoveg) — is currently broken. Both return DB errors or timeout. This was the best source for distinguishing tree species at the individual stand level, and for the "acidòfil/calcícola" soil classification at 1:25,000. When it comes back online, it would replace CORINE as the vegetation source and improve accuracy significantly.

### 5. Aspect / canopy resolution (resolved by Phase 3)
The YouTuber emphasises north-facing slopes (obaga) and open undergrowth for most species. Phase 3 now computes slope aspect, solar radiation, cold-air pooling and canopy openness per zone from the ICGC 5 m DEM and LiDAR, and scores them as the **M** (microclimate) and part of the **H** (habitat) factor. What remains limited is **resolution**, not absence: the DEM neighbourhood is sampled at ~100 m and the LiDAR canopy at ~25 m, so a single zone is a stand-level estimate, not a tree-level one. See "Terrain and canopy enrichment (Phase 3)" below.

### 6. SoilGrids is a global ML model
SoilGrids pH values are derived from a global machine-learning model at 250m resolution. They are systematically slightly high for the Pyrenees (calcareous geology dominates), which means siliceous pockets can be masked. It is used only as a fallback for ambiguous IGME results, not as the primary signal.

### 7. Meteocat XEMA is opt-in; radar is not integrated
Since Phase 4.2 the app can read Meteocat's XEMA station network (real local
observations, interpolated per zone with distance/data-age recorded), but only
when a free `METEOCAT_API_KEY` is configured — without it, Open-Meteo only,
with no change in behaviour or scores. Meteocat's API has no radar (XRAD)
product, so rain accumulation comes from XEMA rain gauges; radar remains a
pending upgrade (see the Phase 4.2 section). Since Phase 4.3, observed XEMA
daily rain also blends into the water-balance series (documented; only when
the key is configured).

### 8. The soil water balance is a model, not a measurement
The Phase 4.3 recharge/drought index is a deterministic function of the
Open-Meteo P − ET0 series, with a documented storage cap (100 mm), ±50 mm
state thresholds and a per-species rain-term modifier that are modelling
choices, not field-verified. ET0 history currently spans ~59 days, so the
60/90-day windows are partially covered, and ET0 is not lapse-corrected.
Field calibration belongs to Phase 5.

---

## Improvements roadmap

### Just shipped (Phases 1–6)
- **Search, filters and sorting** across places, forests, municipalities and species.
- **Free best-zones leaderboard**, route links and nearby parking — nothing hidden behind a paywall.
- **Map ↔ list sync**, marker clustering, always-on legend, geolocation and URL state.
- **Data-quality indicator** per zone (meteo + soil + forest completeness) and a 7-day score strip.
- **Micro-zones** — 135 independently scored zones across 46 stations (massís → obaga/solana/carena stands), with a zone comparison strip and zone detail.
- **Terrain and canopy science** — per-zone aspect, slope, solar radiation, cold-air pooling and canopy openness from ICGC 5 m DEM + LiDAR, integrated into the score as an explainable H·M·W·P·C breakdown.
- **21 species with seasons and lookalikes** — spring/summer/winter species are filtered to their season, and every edible carries a safety-critical "Perill de confusió" lookalike warning in the species row and explainer.
- **Installable PWA** with an offline shell and a user-requested "save zone for the day" snapshot.
- **Field-grade performance** — deduplicated species catalogue, gzip (1.08 MB on the wire) and a built-forecast cache (~2 ms repeat requests), plus a keyboard/contrast/mobile accessibility pass.
- **Forest-offset integrity gate (Phase 7.1)** — all 46 station points and 135 zone centroids re-gated against CORINE: 46/46 and 135/135 are real forest; no coordinate needed moving.
- See `PROPOSAL.md` for the remaining plan (Phase 7 model/data depth).

### Short term
- **Meteocat API key (optional)** — set `METEOCAT_API_KEY` (register at apidocs.meteocat.gencat.cat) to activate the XEMA integration shipped in Phase 4.2. Live-verified with a real key on 2026-11-08 (see `PHASES.md` step 4.2); three real-data fixes (state filtering, blank-state readings, daily-stats shape) landed during that verification.
- **Re-gate new station points** — before adding a station, run `python3 repair_forest_offsets.py --check-zones` and confirm its point (and every zone) returns a CORINE forest class. The 2026-11-12 run passes 46/46 stations and 135/135 zones; see `forest_offset_report.json`.
- **Add more stations** — Meteocat XEMA has stations at Vallcebre, Bagà forest, La Molina, etc. Adding 5–6 more points per comarca would increase granularity.

### Medium term
- **1:25k soil and habitat (step 7.6)** — MSC25M soil now answers for 7/135 zones and CHC3 habitat for 50/135 (shadow); the remaining sheets/provinces and the CHC50 source are still unavailable.
- **GeoVeg when it returns** — if geoveg.creaf.cat or ub.edu/geoveg comes back online, add a third geo layer: query the vegetation polygon text and parse `acidòfil`/`calcícola` + tree species keywords. This would replace or complement CORINE.
- **Season selector** — a manual UI toggle to force a season (the app now filters spring/summer/winter species automatically by month; a toggle would let users preview the next season).

### Long term
- **Historical validation** — compare forecast scores against known sighting reports from iNaturalist or GBIF for past seasons. Calibrate weights.
- **Precipitation accumulation map** — fetch Open-Meteo for a grid of points across the covered comarques and render a heatmap of recent rainfall, as Meteocat shows on their monthly summary page.
- **Push notifications / weekly digest** — run the scorer as a cron job, send a Telegram or email alert when any station hits "Molt bona" for Rovelló or Cep after sufficient rain.

---

## Adding a new species

Edit `mushrooms.json` and add an entry to the `species` array following the existing schema. The required fields are:

```json
{
  "id": "unique-id",
  "common_name": "Nom català",
  "scientific_name": "Genus species",
  "trees": ["Scientific tree names"],
  "tree_keywords": ["pi roig", "faig", ...],
  "prefers_scots_pine": false,
  "soil": { "type": "calcareous|siliceous|both", "ph": "basic|acid|neutral_to_acid" },
  "altitude_m": { "min": 400, "ideal_min": 800, "ideal_max": 1400, "max": 1800 },
  "slope_aspect": ["north"],
  "temperature_c": { "min": 5, "ideal_min": 10, "ideal_max": 20, "max": 25 },
  "rain_trigger_mm": 20,
  "rain_window_days": 7,
  "dry_spell_before_days": 5,
  "wind_sensitivity": "high|medium|low",
  "season": "autumn|spring|summer|winter",
  "notes": "Plain text description for the UI.",
  "lookalikes": [
    {
      "name": "Confusable species · Latin name",
      "danger": "mortal|toxic|inedible|none",
      "differences": "Key field differences to tell them apart."
    }
  ]
}
```

Restart the server after editing. No code changes needed.

- `season` is optional. Omit it (or set `"autumn"`) for the default
  year-round behaviour; `spring` / `summer` / `winter` species are filtered out
  of the forecast outside their months (Mar–May / Jun–Aug / Dec–Feb).
- `lookalikes` is a safety-critical field for every edible species. `danger` is
  one of `mortal`, `toxic`, `inedible` or `none` (no serious lookalike).

---

## Adding a new station

Edit the `target_stations` section in `mushrooms.json`:

```json
"Berguedà": [
  {
    "name": "Vallcebre",
    "lat": 42.10,
    "lon": 1.90,
    "alt_m": 1150,
    "notes": "Famous rovelló reforestation area from the YouTube video"
  }
]
```

- `lat/lon` — the station's **forest point**. Use a DEM-verified point inside a
  CORINE forest polygon (311/312/313/324), not the town centre or a pasture.
  It feeds the IGME/CORINE sample, weather request and altitude score.
- `alt_m` — elevation in metres from the same DEM, used in the altitude score
- `notes` — documented local knowledge, with the forest class and lithology

The geo data for the new station is fetched and cached automatically on first load.
After editing, run `python3 repair_forest_offsets.py --check-zones`; it gates the
station and every zone against CORINE and writes `forest_offset_report.json`.
A failed point is never moved silently: `--apply` only writes a candidate that
passes the gate, and keeps the previous coordinates in the station's
`forest_offset_history`.

---

## Adding a micro-zone

`zones.json` splits a station into smaller, independently scored zones (a stand,
a slope sector, a reforestation patch). It is keyed by the **station name exactly
as written in `mushrooms.json`**.

> The JSON below is a **schema example with placeholder values**, not a real
> zone. Do not copy its coordinates, altitude, aspect, soil or confidence.
> Replace every field with a value you can cite in `sources`.

```json
{
  "version": 1,
  "zones": {
    "Station name from mushrooms.json": [
      {
        "id": "example-zone",
        "name": "Example — north slope",
        "lat": 0.0,
        "lon": 0.0,
        "alt_m": 0,
        "alt_range_m": [0, 0],
        "aspect_deg": 0,
        "aspect": "north",
        "slope_deg": 0,
        "forest": {
          "type": "conifer",
          "dominant": "Pinus sylvestris"
        },
        "soil": { "type": "calcareous", "ph_approx": 6.5, "source": "IGME 1:1M + SoilGrids v2 (pH)" },
        "water_m": 380,
        "water_source": "OSM waterway/waterbody via Overpass (distància al segment més proper)",
        "access": {
          "parking_lat": 42.1078,
          "parking_lon": 1.8851,
          "trailhead": "named trailhead",
          "drive_min": 38,
          "drive_min_source": "OSRM driving · capital de comarca → l'aparcament",
          "difficulty": "moderada",
          "difficulty_source": "regla escrita: pendent + distància a peu",
          "parking_source": "OSM"
        },
        "confidence": 0.74,
        "confidence_label": "alta",
        "sources": [
          "source 1 for coordinate/altitude",
          "source 2 for aspect/forest",
          "source 3 for confidence"
        ],
        "notes": "One field note with a date and observer."
      }
    ]
  }
}
```

**Required for every zone:** `id`, `name`, `lat`, `lon`, `alt_m`, `sources`, and
`confidence` (plus `confidence_label`). Omit a field when there is no real source
for it. Never invent a coordinate, altitude, aspect, soil value or confidence to
fill the schema — a zone with fewer fields and an honest `sources` list is better
than a complete-looking invented one.

**Fields that are nullable:** `water_m`, `access.parking_lat`/`parking_lon`,
`access.drive_min` and `access.difficulty` are `null` when no source was found
(and `water_m` is left null — never "0" — when no water is mapped nearby or
Overpass is unreachable); the UI hides them rather than showing a made-up
number. `forest.canopy_pct` / `forest.undergrowth` no longer exist in
`zones.json`: canopy cover and undergrowth are the LiDAR-derived
`enrichment.canopy` block in `zones_enriched.json` (Phase 3.3), which is the
single source of truth. `confidence_label` is one of `baixa` / `medium` / `alta`.

**The 135 shipped zones** (46 stations, 2–3 each) were curated against **CORINE
CLC 2018** (forest class per centroid), **Copernicus DEM / ICGC 5m LiDAR**
(altitude, aspect, slope), **IGME MAGNA 50 / 1:1M** (lithology →
calcareous/siliceous) and **SoilGrids v2** (pH when available). Per-zone
confidence is **derived from evidence** (Phase 7.3): source count, pH present,
soil/habitat/DEM resolution, canopy sample coverage, the forest gate and access
facts. On 2026-11-15, after step 7.4 activated the MAGNA 50 anchor on 56 zones,
the 135 zones span `0.62–0.80` with 63 `alta` / 72 `medium` (before 7.4:
`0.62–0.77`, 44/91); the value is still capped because CORINE is 100 m, most
zones remain on 1:1M, and the dominant tree comes from the CORINE class or
station notes (local knowledge, not verified tree-by-tree). The Phase 6.2
additions use the CORINE group as `dominant` and leave the pH `null` when
SoilGrids does not answer. Phase 3 replaces the coarse samples with LiDAR canopy
and the best available soil/habitat layers. See “Confidence that discriminates
(Phase 7.3)” and “IGME MAGNA 50 soil (Phase 7.4)”.

**How zones are scored**

- The zone uses its own `alt_m` and its own IGME/CORINE sample fetched at
  `lat`/`lon` (cached in `geo_cache.json` like stations).
- Weather comes from the parent station, so all zones in a massís share the same
  forecast; only altitude and the geo sample change the result.
- The formula is the same `score_station` used for stations, so zone scores are
  directly comparable with the legacy station score.
- In Phase 3.5 the coarse curated sample is overridden by the richer enrichment
  factors: `H` (soil × forest × canopy-openness) and `M` (aspect × potential sun
  × cold-air drainage) are applied per zone, so the obaga and solana stands in a
  massís score differently. See "Scoring integration (step 3.5)" below.
- A station with no entry, or an empty `zones` object, keeps the legacy
  one-station-one-score behaviour.

**API shape.** Each station in `/api/forecast` now includes `zones: []` (empty
when none are curated). Each zone carries the legacy `species`, `days`, `dates`,
`geo` and `quality` fields plus a compact summary:

```json
"zone_score": {
  "species_id": "rovelló",
  "species": "Rovelló",
  "scientific": "Lactarius sanguifluus",
  "score": 78,
  "label": "Molt bona",
  "day_offset": 2,
  "date": "2026-11-09"
}
```

(The score and date above are illustrative; the API fills them from the live
forecast.)

Set `ZONES_FILE=/path/to/zones.json` to load a different zone file (used by the
verification fixture).

---

## Terrain and canopy enrichment (Phase 3)

`enrich_zones.py` is the pipeline that turns the curated `zones.json` into a
scientifically richer model. It reads every zone, runs it through four
enrichment providers, and writes `zones_enriched.json` (a superset of
`zones.json` with an `enrichment` block per zone):

- **`terrain`** — altitude, slope and aspect (curated in Phase 2), plus the
  **step 3.2 DEM metrics**: curvature, topographic position index (TPI),
  cold-air pooling and solar radiation (annual/seasonal), each with units and
  the DEM source.
- **`canopy`** — canopy cover %, canopy height, undergrowth proxy and edge
  density from the ICGC LiDAR — filled by step 3.3.
- **`soil`** — 1:25k soil type, texture and pH — filled by step 3.4.
- **`habitat`** — dominant tree group from ICGC habitats 1:25k — filled by 3.4.

Every provider samples at the zone centroid and caches the result in
`terrain_cache.json` **by rounded lat/lon** (4 decimals ≈ 11 m), recording the
`source` and a UTC `timestamp` per sample, so repeated runs — and repeated phase
steps — never re-query an external service for the same cell.

```bash
python3 enrich_zones.py               # enrich all zones → zones_enriched.json
python3 enrich_zones.py --self-test   # offline cache/enrich round-trip (no network)
```

### DEM metrics (step 3.2)

The `dem` provider queries the **ICGC 5 m LiDAR DEM** (`model-elevacions-terreny-
catalunya-lidar-5m-2021-2023` via the `elevacions-territorial` WMS) at a 9-point
neighbourhood around each zone centroid — four cardinal points at 100 m and four
diagonals at 250 m — and derives, per zone:

| Field | Meaning | Unit |
|---|---|---|
| `dem_alt_m` | Ground elevation at the centroid | m |
| `dem_slope_deg` | Slope from the 100 m cross | degrees |
| `dem_aspect_deg` | Aspect (downslope direction, clockwise from north) | degrees |
| `curvature` | Laplacian of elevation over the 100 m cross (negative = convex crest, positive = concave hollow) | 1/m |
| `tpi` | Topographic Position Index: centre minus the 250 m ring mean (negative = valley, positive = ridge) | m |
| `cold_air_pooling` | Centre minus the 250 m ring minimum (~0 = sits in the cold-air depression, large = drains) | m |
| `solar_radiation` | Potential clear-sky insolation on the slope as a ratio of a horizontal surface (`annual`, `seasonal` = Mar–Aug) | dimensionless |

The DEM metrics are stored under `enrichment.terrain` next to the curated Phase 2
`alt_m`/`slope_deg`/`aspect_deg` (which are preserved unchanged). Because the
DEM is sampled at ~100 m, its `dem_aspect_deg`/`dem_slope_deg` can differ from
the curated values; both are kept so the discrepancy is visible rather than
silently overridden. These metrics are stored and cached now but are **not yet
scored** — wiring them into the score and the explainer is step 3.5.

Until step 3.4 lands, the remaining providers (1:25k soil and habitat) are
stubs and their factors are written as `null` / `"pending"` — no value is
invented. Steps 3.2–3.3 change the enrichment data only; they do **not** change
the scoring formula or the UI.

### Canopy metrics (step 3.3)

The `lidar` provider queries the **ICGC LiDAR vegetation-height raster**
(`model-alcaries-vegetacio-catalunya-lidar-1m-2021-2023`, the canopy height
model CHM = surface − ground) at a 5×5 grid (25 cells at 25 m spacing ≈ 100 m
stand box) and derives, per zone:

| Field | Meaning | Unit |
|---|---|---|
| `canopy_pct` | Fraction of sampled cells with vegetation ≥ 5 m (tree cover) | 0–1 |
| `canopy_height_m` | 90th percentile of sampled vegetation heights (dominant canopy top) | m |
| `undergrowth` | Fraction of sampled cells with 0.5–5 m vegetation — a shrub/understory *proxy* (only visible where the canopy is open; sub-canopy undergrowth is not resolvable by top-down LiDAR) | 0–1 |
| `edge_density` | Fraction of adjacent sampled cells with a ≥ 3 m height jump (canopy edges / gaps) | 0–1 |
| `sample_coverage` | Fraction of the 25 cells that returned a value (1.0 = complete) | 0–1 |

**Bare ground vs. coverage gap:** the vegetation-height raster encodes *no
vegetation* (bare ground, rock, water) as the `-9999` nodata sentinel. The
pipeline maps that to 0 m — so bare cells correctly reduce `canopy_pct` — while a
network error or malformed response stays a genuine gap and is reported via
`sample_coverage` rather than fabricated as zero. This is why high-crest zones
(e.g. `tossa-carena-alta`, ~0.32 cover) and clearings (`camprodon-solana-sud`,
~0.12 cover) show low cover instead of being dropped.

### Soil and habitat (step 3.4)

The `soil_1_25k` and `habitat` providers record substrate and vegetation at each
zone. The intended ICGC 1:25k soil map and ICGC/CREAF habitat map (CHC50 v3) are
currently unavailable (the habitat host has been down; the soil/geology WMS
returned empty/error responses), so soil uses IGME **MAGNA 50 first (step 7.4)**
and falls back to IGME 1:1M + SoilGrids; habitat falls back to CORINE. The
1:25k texture/habitat upgrade is flagged `pending` rather than invented:

| Field | Source | Meaning |
|---|---|---|
| `soil.type` | IGME MAGNA 50 (1:50k) when unambiguous, else IGME 1:1M | `calcareous` / `siliceous` / `mixed` |
| `soil.ph` | SoilGrids v2 (0–5 cm) | mean pH |
| `soil.litho_text` | the source that supplied `type` | raw lithology string |
| `soil.resolution` | derived | `1:50k` (MAGNA answered) or `1:1M` (fallback) |
| `soil.magna_hoja` | MAGNA 50 | sheet number when promoted |
| `soil.fallback_reason` | derived | why 1:1M was kept (`null` on a 1:50k zone) |
| `soil.texture` | — | `null` (1:25k texture map unavailable) |
| `habitat.dominant` | CORINE CLC 2018 | dominant tree group (conifer / broadleaf / mixed) |
| `habitat.corine_code` | CORINE CLC 2018 | 311/312/313/324 |

These cross-check cleanly: the CORINE-derived `habitat.dominant` agrees with the
curated `forest.type` for all 135 zones. After step 7.4 the soil distribution is
**calcareous 83 / siliceous 30 / mixed 22** (MAGNA 50: 56 zones; 1:1M fallback:
79, including the 2 held), versus 76 / 22 / 37 under the old 1:1M sample — the 15
zones that left `mixed` are the siliceous pockets and limestone units the coarse
map could not separate.

### Scoring integration (step 3.5)

The enrichment factors are now wired into the zone score and the "why this
score" explainer. Each species result carries a five-factor breakdown:

| Factor | Meaning | Source |
|---|---|---|
| **H** · hàbitat | soil × forest × canopy-openness match | IGME/CORINE + LiDAR canopy |
| **M** · microclima | aspect × potential sun × cold-air drainage | ICGC 5m DEM (slope/aspect/solar/TPI) |
| **W** · meteorologia | the existing weather score (rain, temp, wind, altitude, humidity) | Open-Meteo |
| **P** · fenologia | GDD (suma tèrmica) × season gate; zones only | real temperature series; full phenology in 4.5 |
| **C** · confiança | the zone's curated confidence label | `zones.json` |

The zone score is `W × H × M`, capped at 99. **Station scores are unchanged** —
`H` reduces to the legacy soil×forest multiplier and `M` is neutral (1.0) when a
zone has no enrichment block, so a missing `zones_enriched.json` (or a station
with no zones) preserves the exact Phase-2 behaviour. Within a massís the new
`M` factor is what makes the obaga and solana stands score differently: a
north-facing stand now scores higher for cep/rossinyol and lower for rovelló, and
the explainer shows the aspect, potential insolation, cold-air and canopy values
behind that difference.

The factors are computed from species preferences already in `mushrooms.json`
(`slope_aspect`, `soil.ph`, `tree_keywords`) and the sampled enrichment values —
**no preference is invented**. Factors are neutral (×1.0) when the relevant data
is absent, and the explainer says explicitly that the score is a *relative
favourability index, not a probability*.

**Phase 3 is complete.** Every zone carries a sourced `enrichment` block
(terrain, canopy, soil, habitat), and those factors feed the score and the
explainer. Two upgrades are carried forward, not silently faked: the ICGC 1:25k
soil-texture map and the ICGC/CREAF CHC50 habitat map were unavailable, so soil
uses IGME MAGNA 50 where it answers (step 7.4), falling back to IGME 1:1M +
SoilGrids, and habitat to CORINE CLC 2018 (the 1:25k layers flagged `pending` in
the data). Next is Phase 4 — weather quality.

---

## Weather and elevation correction (Phase 4.1)

Each zone now gets **its own local weather** instead of inheriting the parent
station's town forecast, and the temperature is **elevation-corrected** to the
zone's verified altitude:

- **Batch fetch.** Open-Meteo is queried once per forecast for every station *and*
  zone centroid in a single multi-coordinate request (46 stations + 135 zones).
  The response is parsed correctly as one object per location (each carrying its
  own `daily` and `elevation`), and each result is cached to
  `weather_cache.json` **keyed by coordinate + calendar date** so a forecast is
  never served on the wrong day.
- **Lapse-rate correction.** Open-Meteo reports the model/grid `elevation` it
  used for each coordinate. Because that grid altitude can differ from the
  zone's curated `alt_m` (ICGC 5 m LiDAR / Copernicus DEM), the daily
  `temperature_2m_max` / `temperature_2m_min` are shifted by the standard
  environmental lapse rate — **6.5 °C per 1000 m** (ICAO Standard Atmosphere).
  A higher zone is colder, a lower one warmer. Precipitation, wind and humidity
  are **not** altered (they have no simple lapse relationship, and inventing one
  would fabricate data).
- **Transparency.** Each zone object in `/api/forecast` now carries a `weather`
  block — `grid_alt_m` (the model altitude), `zone_alt_m` (the curated altitude)
  and `lapse_correction_c` (the applied °C shift) — so the correction is visible,
  not hidden. In practice most zone centroids already sit within a few metres of
  Open-Meteo's grid altitude, so the correction is usually < 0.05 °C; for the
  ~32 zones where the two disagree by more than ~8 m it is a real, documented
  adjustment (largest observed: −2.24 °C on a ridge where Open-Meteo's grid was
  ~344 m above the LiDAR altitude).

The correction changes only the *temperature* the zone score sees; station
scoring is unchanged. Surface of the correction in the UI (and the separate
confidence / data-age treatment) belongs to later Phase 4 steps.

> Verified in [Phase 4 verification (4.6)](#phase-4-verification-46): the
> formula holds for all 66 zones on live data, including the −2.24 °C Ogassa
> case; station-day temperature deltas are quantified there.

---

## Meteocat XEMA and radar (Phase 4.2)

When a `METEOCAT_API_KEY` is configured, each zone's payload also carries an
`xema` block of **observed** conditions from Meteocat's XEMA network of ~190
automatic stations — real readings, interpolated to the zone — next to the
Open-Meteo forecast. **Without the key, the app makes zero Meteocat calls and
behaves byte-for-byte as before** (Open-Meteo only).

### What is fetched

| Meteocat endpoint (API v1, header `X-Api-Key`) | Data | Cache |
|---|---|---|
| `/xema/v1/estacions/metadades?codiEstacio=TOTES` | station list: code, name, lat/lon, altitude, state history — filtered client-side to operative stations (latest `estats` entry with `dataFi: null` has `codi` 2; verified live 2026-11-08: 182/188 state-2 stations report, 0/57 state-1 do) | 24 h |
| `/xema/v1/variables/mesurades/32/ultimes` | variable 32 = **Temperatura** (°C), last reading of the last 4 h per station | 15 min |
| `/xema/v1/variables/mesurades/35/ultimes` | variable 35 = **Precipitació** (mm per 30-min period) | 15 min |
| `/xema/v1/variables/estadistics/diaris/1300?any=…&mes=…` | variable 1300 = **Precipitació acumulada diària** (mm) for the current month | 1 h |

Variable codes come from Meteocat's official variable table (32 = Temperatura,
35 = Precipitació, 1300 = Precipitació acumulada diària).

### The `xema` block per zone

```json
"xema": {
  "source": "Meteocat XEMA (estacions automàtiques)",
  "fetched_at": "2026-11-08T10:33:12Z",
  "temp_c": 9.2,               // IDW of lapse-corrected station temps
  "precip_last_mm": 0.2,       // IDW of latest 30-min-period readings
  "precip_today_mm": 12.2,     // IDW of variable 1300 for today
  "precip_7d_mm": 15.4,        // 7-day gauge accumulation (radar substitute)
  "precip_7d_days": 3,         // days with data in that sum
  "nearest_distance_km": 3.5,  // nearest XEMA station used
  "data_age_min": 12,          // minutes since the newest reading used
  "stations": [ { "codi": "X1", "nom": "…", "distance_km": 3.5,
                  "alt_m": 1240, "age_min": 12 } ]
}
```

### Interpolation and data-quality rules

- **IDW** (inverse-distance squared) over the nearest ≤ 4 operative stations
  within 40 km, using the official station lat/lon/altitude. The nearest
  station dominates.
- **Temperature** is lapse-corrected (6.5 °C/km, the same constant as Phase
  4.1) from each station's altitude to the zone's curated `alt_m` *before*
  interpolation. **Precipitation is not** altitude-corrected — no simple lapse
  relationship exists, and inventing one would fabricate data.
- XEMA state codes: only `N` (invalid) readings are dropped. `V` (valid) and
  `T` (pending validation) are used, and **blank-labelled readings are
  accepted too**: live `ultimes` data carries `estat: " "` on ~100 % of the
  semi-hourly provisional readings, so dropping blanks would silently disable
  the feature in production (fixed during the 2026-11-08 live verification).
  Daily statistics with a data-coverage `percentatge` below 70 % are
  non-representative per Meteocat's open-data rules and are dropped.
- `data_age_min` is minutes since the newest *measurement label* among the
  stations used. Labels are UTC and forward-labelled (an 11:00Z reading covers
  11:00–11:30Z), so true age can be up to ~30 min greater.
- Zones with no station within 40 km (or no usable reading) get no `xema`
  block — the Open-Meteo payload stays untouched.

### Blend policy (explicit)

XEMA **annotates, it does not replace**: the `xema` block rides alongside the
Open-Meteo `weather` block; Open-Meteo remains the fallback and the source of
the 7-day forecast and of every score. The one place observed XEMA values now
enter the scoring is the Phase 4.3 water balance (documented above): observed
daily precipitation substitutes modelled P for the published days, which can
change the recharge index and its rain-term modifier — visible in `water.
blend_dates`, never silent. The `xema` block itself never changes a score, and
station scores are byte-identical with or without the key.

### Radar (XRAD): deferred — honest gap

The API's operation catalogue is **XEMA, XDDE, Predicció, Referència, Quotes**.
There is **no XRAD product** — radar data (4 C-band Doppler radars, 6-min
updates) is only served as web images/widgets or paid personalised deliveries,
with no point/GIS query. Per the roadmap rule ("never fabricate; record the
gap"), this step implements rain accumulation from **XEMA rain gauges**
(`precip_7d_mm`) instead of a raster pipeline, and marks radar `pending` for a
future step if the SMC exposes a numeric product.

### Key setup

1. Register a free "Accés ciutadà i administració" plan at
   https://apidocs.meteocat.gencat.cat/ (tick **Dades de la XEMA**). You
   receive the key by email.
2. Run the app with `METEOCAT_API_KEY=<your-key> python3 app.py`.
3. `/api/forecast` then includes a top-level `xema.status` (`ok` /
   `error` + reason) and the per-zone `xema` blocks. On any Meteocat failure
   the app logs the reason and keeps serving Open-Meteo only.

> Verified in [Phase 4 verification (4.6)](#phase-4-verification-46): live
> 2026-11-09 run with 188 operative stations, 66/66 `xema` blocks and
> `source`/`fetched_at`/`data_age_min` on every block.

---

## Soil water balance and drought index (Phase 4.3)

A wet 7-day window after a dry summer does not mean moist soil — dry soil
absorbs the first rains before fruiting responds, and a long wet season keeps
fruiting alive through short dry spells. Phase 4.3 replaces "rain mm only"
with a per-zone **soil water balance**: precipitation minus reference
evapotranspiration, tracked over the season, plus a bounded
**recharge/drought index** that scales each species' rain score term.

### Data

- Open-Meteo serves `et0_fao_evapotranspiration` (FAO-56 reference
  evapotranspiration, mm/day — FAO Irrigation and Drainage Paper 56, Allen
  et al. 1998) as a daily variable with `past_days` up to 92 (verified live
  2026-11-08). One extra batched call per forecast fetches
  `precipitation_sum` + ET0 for all stations and zones (92 past + 7 forecast
  days).
- The series is cached in `weather_cache.json` under the same coordinate +
  calendar-day key as the forecast (fields `w_daily` / `w_date` / `w_t`).
  **Stale-balance rule:** a series is only reused while `w_date == today`; a
  balance stamped with an earlier calendar day is never served.
- ET0 is **not** altitude-corrected (no documented lapse relationship for
  reference ET — inventing one would fabricate data; recorded as an honest
  gap). Precipitation is the same grid value the weather score uses.

### The balance windows

For each zone, ending today (the last observed day):

```text
balance_Nd_mm = Σ (P − ET0)   over the last N calendar days (N = 14, 30, 60, 90)
```

Only days where both P and ET0 exist are summed, and each window records
`days` (how many were actually used). The 60/90-day windows can be partially
covered: the forecast API's ET0 history currently starts ~59 days back, so
their `days` reflects that (the Archive API has older ET0 but no batch mode —
a possible later backfill). A window with no ET0 at all yields **no `water`
block** — nothing is fabricated, and the score is byte-identical to the
previous phase.

### The recharge index (FAO-56 bucket concept, documented modelling choice)

The FAO-56 water-balance method treats the root zone as a **bounded
reservoir**: water beyond the soil's storage capacity percolates away, ET0
draws the store down. Phase 4.3 normalises the window balance by an explicit
storage cap:

```text
recharge_index R = clamp(B / S_cap, −1, +1)
drought_index  D = clamp(−B / S_cap, 0, 1)
state          = drought if B ≤ −50 mm, recharge if B ≥ +50 mm, else neutral
```

- `B` = the longest usable window balance (60 d if ≥ 45 days covered, else
  30 d if ≥ 20, else 14 d if ≥ 7; recorded as `recharge_window`).
- `S_cap = 100 mm` is a **modelling choice, not field-verified**: FAO-56
  Table 19 gives typical total available water (TAW) ranges of ~40–60 mm for
  shallow and >140 mm for deep soils; 100 mm is the chosen representative
  forest-soil storage, so a ±100 mm net imbalance saturates the index.

### XEMA observed-rain blend (documented, never silent)

When `METEOCAT_API_KEY` is configured, the balance substitutes **observed**
for modelled precipitation where Meteocat publishes it: for each calendar
day with an observed daily accumulation (variable 1300, ≥70 % data coverage —
the same quality gate as the `xema` block), the IDW-interpolated observed mm
(same ≤4 nearest stations within 40 km and p=2 weights as `interpolate_xema`)
replaces the modelled `precipitation_sum` for that day. Only **past** days
can be substituted (Meteocat publishes a day's statistic the following day,
and the context covers the current month). The block records `blend_days`,
`blend_dates` and `blend_source`. Without a key: zero Meteocat calls, no
blending.

> This supersedes the Phase 4.2 "scores identical with or without the key"
> guarantee **only for the water block and its modifier**: with a key, the
> blend can change a zone's balance/index (observed rain ≠ modelled rain),
> which can change the zone score — visibly and documented, never silently.
> The `xema` block itself still annotates only, and **station scores are
> byte-identical in every mode**.

### Per-species drought/recharge modifier on the rain term

Zone scores only. The zone's rain score term is scaled by a deterministic
function of the recharge index and the species' documented water fields
(`mushrooms.json`):

```text
m(R) = clamp(1 + k·R, 0.75, 1.25)      k = 0.15 × rain_trigger_mm / 20
r_sc' = min(1.0, r_sc × m)
```

- **Drought** (R < 0) damps the rain term — dry soils absorb the first rains.
- **Recharge** (R > 0) boosts it slightly.
- A species with a higher `rain_trigger_mm` (needs more rain) is more
  sensitive to a deficit — that is the entire per-species calibration, from
  the documented fields only; no new species thresholds are invented.
- Bounded to ±25 % of the rain term (~±9 % of the weather score). The raw
  rain percentage stays visible in `breakdown.pluja`; the modifier appears as
  `breakdown.sequera` (100 = neutral) on zone species only. Station payloads
  carry neither (byte-identical to Phase 4.2).

**This relationship is a modelling choice, not field-verified** — it encodes
the documented "dry soils absorb rain" mechanism with a conservative
magnitude. Field calibration belongs to Phase 5.

### The `water` block per zone

```json
"water": {
  "source": "Open-Meteo: Σ(P − ET0) acumulat per dia; P = precipitation_sum, ET0 = et0_fao_evapotranspiration",
  "computed_at": "2026-11-08",
  "windows": { "14d": {"mm": 38.0, "days": 14}, "30d": {"mm": 70.0, "days": 30},
               "60d": {"mm": 55.0, "days": 60}, "90d": {"mm": 40.0, "days": 90} },
  "recharge_window": "60d",
  "recharge_index": 0.55,       // −1 (drought) … +1 (recharge)
  "drought_index": 0.0,         // 0 … 1 (1 = severe drought)
  "state": "recharge",          // drought | neutral | recharge
  "storage_cap_mm": 100.0,
  "blend_days": 2, "blend_dates": ["2026-11-06", "2026-11-07"],
  "blend_source": "Meteocat XEMA variable 1300 (IDW, mm)"   // null without a key
}
```

(The numbers are illustrative.) The block is backend data for later Phase-4
steps to surface; this step changes no UI and no station scoring.

### Limitations

- ET0 history from the forecast API currently spans ~59 days (verified
  2026-11-08), so the 60/90-day windows are partially covered (`days`
  recorded) until more history accumulates or the Archive API is wired in.
- The storage cap, the ±50 mm state thresholds and the modifier k are
  documented modelling choices, not field-verified per zone.
- ET0 is not lapse-corrected and precipitation is the Open-Meteo grid value
  (or the documented XEMA blend); orographic corrections stay out of scope.

> Verified in [Phase 4 verification (4.6)](#phase-4-verification-46):
> 66/66 live `water` blocks, source/computed_at/window day counts audited, and
> the ET0-history limitation recorded.

---

## Per-zone data confidence (Phase 4.4)

Phase 4.4 separates two concepts that previous phases conflated: **data
completeness** (are the inputs the score uses actually present?) and
**prediction confidence** (how trustworthy is the prediction, given the
resolution and freshness of those inputs?). Both are *reported* — shown in
the zone detail panel and per species — and are **never multiplied into any
score**. The `C` factor in the explainer remains the curated zone confidence
(Phase 7.3 derives it per zone from evidence, now `0.62–0.80` after the 7.4
MAGNA anchor; `alta`/`medium`);
the new block is independent of it.

### Two concepts, one block

Every zone in `/api/forecast` now carries a `confidence` block, and every
zone species result carries a per-species `confidence` field. Station
payloads are unchanged.

```json
"confidence": {
  "computed_at": "2026-11-08",
  "completeness_pct": 86,
  "completeness": { "weather": true, "terrain": true, "canopy": true,
                    "soil": true, "habitat": true, "curated": true,
                    "xema": true, "water": false },
  "level": "mitjana",          // alta | mitjana | baixa
  "score": 0.62,               // 0–1 deterministic prediction confidence
  "field_reports": 0,          // honest zero — Phase 5 supplies real counts
  "reasons": [
    { "code": "om_grid",  "km": 11, "impact": "−", "label": "Open-Meteo · graella ~11 km" },
    { "code": "xema_dist", "km": 8.2, "impact": "+", "label": "XEMA · estació més propera 8.2 km" },
    { "code": "xema_age",  "min": 45, "impact": "+", "label": "XEMA · observacions de fa 45 min" },
    { "code": "terrain",   "src": "lidar", "impact": "+", "label": "DEM LiDAR ICGC 5 m" },
    { "code": "canopy",    "cov_pct": 92, "impact": "+", "label": "LiDAR · mostra de capçada 92%" },
    { "code": "soil",      "ph": true, "impact": "·", "label": "sòl IGME 1:1M + SoilGrids (250 m)" },
    { "code": "habitat",   "impact": "·", "label": "hàbitat CORINE Land Cover (100 m)" },
    { "code": "curation",  "pct": 60, "label_key": "medium", "impact": "·", "label": "curació · 60%" },
    { "code": "field_reports", "count": 0, "impact": "−", "label": "cap informe de camp encara" }
  ]
}
```

Per-species: `"confidence": {"score": 0.58, "label": "mitjana",
"inputs": ["weather", "terrain", "soil", "forest", "curation", "reports"],
"field_reports": 0}` — the same deterministic formula, restricted to the
inputs the species' *active* scoring factors depend on (below).

### Completeness (fraction of inputs present)

```text
completeness_pct = 100 × present / total
```

Every input counts once: `weather` (a zone is only scored when weather
exists), `terrain`, `canopy`, `soil`, `habitat`, `curated` — plus `xema` only
when `METEOCAT_API_KEY` is configured (its pipeline is active) and `water`
only when the water-balance series was actually fetched. **Graceful
degradation, never zero:** without a key, completeness is scored over the
six core inputs (a fully enriched zone shows 100 %, not 87.5 %); a key
configured but a zone without a nearby XEMA station shows 6/7; a zone with
weather but no enrichment shows 33 %, never 0. A zone with no weather at all
carries `completeness_pct: 0` and a "sense predicció" reason (honest — there
is no prediction).

### Prediction confidence (deterministic formula)

```text
score = Σ wᵢ·qᵢ / Σ wᵢ          level: alta ≥ 0.70 > mitjana ≥ 0.50 > baixa
```

Weights (documented modelling choice — they encode how much each input's
quality matters, not a calibrated probability):

| input | weight | quality q (0–1) from sourced data |
|---|---|---|
| weather | 20 | constant 0.55 — Open-Meteo ~11 km grid model + ICAO lapse correction |
| xema | 15 | 0.6·d_q + 0.4·a_q; d_q = clamp(1 − dist/40 km, 0, 1) from `nearest_distance_km`; a_q = clamp(1 − age/360 min, 0, 1) from `data_age_min`. Absent block → the weight redistributes over the other inputs (never scored) |
| terrain | 15 | 0.95 ICGC 5 m LiDAR DEM (2021-2023) · 0.70 Copernicus DEM (~90 m) · 0.30 missing (factor neutral) |
| canopy | 10 | the LiDAR `sample_coverage` fraction itself (25-cell 1 m vegetation-height sample) · 0.30 missing |
| soil | 15 | 0.90 real 1:25k (7.6) · 0.75 IGME MAGNA 50 (7.4) · 0.60 IGME 1:1M lithology + SoilGrids v2 (~250 m) pH · 0.50 lithology only · 0.30 missing |
| forest | 15 | 0.85 CHC50 1:25k habitat (7.6) · 0.60 CORINE CLC 2018 (100 m mapping unit) · 0.30 missing |
| curation | 10 | the curated zone `confidence` from `zones.json` (evidence-derived by Phase 7.3: 0.62–0.80 after 7.4) |
| reports | 10 | 0 today — there are **no field reports yet** (Phase 5). Shown as "cap informe de camp encara", never a made-up number |

Impact signs are deterministic from q: `+` at q ≥ 0.70, `·` above 0.45,
`−` below (for XEMA distance/age the thresholds are 10/25 km and 90/180 min).
Every q is either a documented constant tied to a source resolution or a
direct function of real fetched data (station distance, data age, sample
coverage, curated confidence). All weight and anchor choices are **modelling
choices, not field-verified**; calibration belongs to Phase 5.

### Per-species confidence

The same formula over only the inputs the species' active scoring factors
use, derived from the documented preferences in `mushrooms.json` (no new
species data):

- `soil` — the species documents a soil-pH preference
  (`soil_multiplier` applies);
- `forest` — the species documents tree associations
  (`forest_multiplier` applies);
- `canopy` — the species notes mention open / no-undergrowth habitat *and*
  LiDAR canopy data is present (`canopy_openness_factor` applies);
- `terrain` — the species has an aspect preference, or is frost-sensitive
  (temperature min > 2 °C, the documented cold-air gating);
- `xema` — only when the zone's water balance blended observed XEMA rain
  (that is the only place observed data enters the score);
- `weather`, `curation`, `reports` — always.

The same q values and weights apply, normalised over the active inputs, so
per-zone and per-species numbers are directly comparable.

### Limitations

- Field reports: 0 (Phase 5). The reports weight (10) is therefore 0 today —
  the prediction score stays around 0.63–0.68 even after Phase 7.3 raised the
  curated confidence. This is honest, not pessimistic: the model is
  uncalibrated.
- The weights, quality anchors and level thresholds are documented modelling
  choices, not field-verified.
- Confidence is reporting-only: it never enters `zone_score` or any species
  score, and stations carry none of it (byte-identical to Phase 4.3).
- The water balance is not a confidence input (it is a derived model, see
  4.3); only its *presence* counts in completeness.

> Verified in [Phase 4 verification (4.6)](#phase-4-verification-46):
> 66/66 live `confidence` blocks (reporting-only, no score regression) and the
> sources/timestamps audit, including the missing single source string.

---

## Phenology and altitude lag (Phase 4.5)

Each zone species now carries a **growing-degree-day (GDD) phenology state**
and the zone score's `P` factor is computed from it — this is the "rovelló
wave": the fruiting window opens first at low altitude and climbs as the
season advances, so every altitude band has its own open/opening/closed
state computed from the real temperature series.

### GDD definition

```
GDD_14d = Σ max(0, T_mean − T_base)   over the last 14 days
```

- **T_base per species = its documented hard minimum `temperature_c.min`**
  from `mushrooms.json` — the only defensible per-species base available
  (below it the species cannot grow, so heat above it is what accumulates).
  Rovelló 5 °C, fredolic 2 °C, rossinyol 12 °C, ou de reig 15 °C, etc.
- **T_mean** = (max + min) / 2 from the real Open-Meteo daily series
  (`past_days=14` + 7 forecast days), **lapse-corrected** from the Open-Meteo
  grid altitude to the zone's curated `alt_m` with the documented 6.5 °C/km
  constant — exactly the Phase 4.1 correction, now applied to the heat sum.
  That correction is what makes the wave climb: a higher zone is colder, so
  it accumulates fewer degree-days and its window opens later.
- **Why a 14-day rolling sum?** Two reasons, both documented: (1) it is the
  length of the temperature series the app already stores — the 92-day
  water-balance series carries precipitation and ET0 only, and adding a
  second temperature fetch was declined (no redundant network calls; a
  longer seasonal accumulation is a future improvement); (2) a rolling sum
  can *close* as well as open, so the crest of the wave passes each altitude
  band — a since-September total could only open.

### Window open/close (documented arithmetic on the species file)

```
gdd_open  = 14 × (ideal_min − base)      e.g. rovelló: 14 × (10 − 5) = 70 °C·d
gdd_close = 14 × (ideal_max − base)      e.g. rovelló: 14 × (20 − 5) = 210 °C·d
state = closed   if GDD < 0.5 × gdd_open
        opening  if 0.5 × gdd_open ≤ GDD < gdd_open
        open     if gdd_open ≤ GDD ≤ gdd_close
        closing  if GDD > gdd_close        (heat above the documented band)
```

`gdd_open`/`gdd_close` use only documented fields; the 0.5 "half-way to
open" boundary and the "14 days at the documented band" interpretation are
modelling choices in the spirit of standard mushroom-phenology thermal-time
models (e.g. degree-day models for *Boletus edulis* / *Morchella*
fructification), **not field-verified per species**. A window with fewer
than 7 valid days of temperatures yields explicit nulls — nothing is
fabricated.

### The P factor (zone scoring only)

```
P_gdd  = 0.5 + 0.5 × GDD / gdd_open        (ramp up,  closed → opening)
       = 1.0                                (open)
       = max(0.5, 1.0 − 0.5 × (GDD − gdd_close) / gdd_close)   (closing)
P      = P_gdd × month gate
```

The month gate is the pre-4.5 calendar gate (1.0 Sep–Nov, 0.85 Aug/Dec, 0.5
otherwise; spring species 1.0 Mar–May). The 0.5 floor/ramps are documented
modelling choices. **Stations never use any of this** — their payloads and
scores are byte-identical to Phase 4.4 (no phenology context, the old month
gate). Zone scores change only via `P`: in early November real data, low
Garrotxa rovelló zones (GDD ≈ 100) stay at P=1.0 while a 1,360 m carena
(GDD ≈ 35) drops to P≈0.75 and a 1,800 m obaga (GDD ≈ 25) to P≈0.68 — the
same zone that scored 72 for rovelló in Phase 4.4 now scores 63, visibly
damped by the season.

### Payload

- **Per zone** (`/api/forecast` → `comarques.*.zones[].phenology`): a summary
  block — `computed_at`, `window_days`, `alt_m`, a note naming the lapse
  correction, and `species` → the per-species block for today.
- **Per zone species** (each result in `days[]`/`species`): `gdd_base_c`,
  `gdd_now`, `gdd_open`, `gdd_close`, `state` (closed/opening/open/closing),
  `p_factor`, `days_to_open`/`days_to_close` (from the 7-day forecast, null
  beyond the horizon), `window_days`, `days_used`, `gdd_forecast` (7 values
  for the wave strip) and `altitude_lag_days`.
- **`altitude_lag_days`** = ΔGDD between this zone and the warmest zone of
  the same species (the wave front), divided by this zone's own heat rate
  (gdd_now / 14 °C·d per day). Null when the zone has no real heat
  (gdd_now < 2.8 °C·d) or the lag exceeds 30 days — "the wave will not
  reach/pass this altitude this season" — never a fabricated number.
- Degraded paths: no weather → no `phenology` key at all (zones already
  carry the honest "no prediction" state); missing temperature arrays →
  explicit nulls. Stations carry no phenology keys.

### UI

- **Species rows** in the zone detail show a state badge ("finestra:
  oberta", "s'obrint", "tancada") with the GDD number, days-to-open/close
  and the altitude lag.
- The **explainer** adds a "Fenologia · suma tèrmica" section with two
  compact strips: the **altitude wave** (every zone of the species, one cell
  each, sorted by altitude — open green, opening amber, closed grey, the
  current zone outlined) and the **next-7-days strip** for this zone from
  the forecast series. Both are labelled *estimació* and are keyboard-/
  screen-reader-accessible (`role="img"` + full aria-labels).

### Limitations

- The 14-day window means "season" is only visible as its recent thermal
  signature; a since-September accumulation needs a longer stored series
  (declined to avoid redundant fetches — future work).
- Thresholds (0.5 × open boundary, P ramps, lag caps) are documented
  modelling choices; calibration against field reports is Phase 5.
- The GDD uses *air* temperature lapse-corrected, not soil temperature;
  soil-temperature series are not available from Open-Meteo.

> **Verification:** the Phase 4 checks for this section (station-day GDD
> inputs, lapse correction, cache stamps) are recorded in
> [Phase 4 verification (4.6)](#phase-4-verification-46).

---

## Phase 4 verification (4.6)

Step 4.6 checks the whole weather pipeline against real observations and
documents where it is approximate. Everything below comes from live API
responses and the live cache; none of the numbers are model output invented
for this report. Raw responses are kept under `/tmp/opencode`
(`openmeteo_station_verify.json`, `xema_daily_1000/1001/1002_2026_11.json`,
`xema_daily_1300_2026_11_46.json`, `live_46_forecast.json`).

### Known-station-day check (temperature)

Four real XEMA stations near curated zones, two published days
(2026-11-07/08). "Grid" is the raw Open-Meteo daily mean at the station
coordinate, `(max+min)/2`; "corrected" applies the app's 6.5 °C/km lapse
correction from the model grid altitude to the station's real altitude.
XEMA observed mean is variable 1000 (daily mean temperature).

| Station (real alt / model grid alt) | Day | Grid mean | Corrected mean | XEMA mean | Δ raw | Δ corrected |
|---|---|---:|---:|---:|---:|---:|
| Viladrau — WS (956 m / 954 m) | 2026-11-07 | 8.8 °C | 8.8 °C | 7.8 °C | +1.0 | +1.0 |
| Viladrau — WS | 2026-11-08 | 11.1 °C | 11.1 °C | 10.5 °C | +0.6 | +0.6 |
| la Quar — CR (872 m / 863 m) | 2026-11-07 | 7.3 °C | 7.2 °C | 7.8 °C | −0.5 | −0.6 |
| la Quar — CR | 2026-11-08 | 8.4 °C | 8.3 °C | 9.7 °C | −1.3 | −1.4 |
| Sant Pau de Segúries — CI (853 m / 850 m) | 2026-11-07 | 9.0 °C | 9.0 °C | 6.6 °C | +2.4 | +2.4 |
| Sant Pau de Segúries — CI | 2026-11-08 | 10.2 °C | 10.2 °C | 8.9 °C | +1.3 | +1.3 |
| Núria — DG (1,971 m / 1,980 m) | 2026-11-07 | 3.2 °C | 3.2 °C | 1.3 °C | +1.9 | +1.9 |
| Núria — DG | 2026-11-08 | 5.6 °C | 5.7 °C | 5.0 °C | +0.6 | +0.7 |

Honest reading:

- **The mean-temperature error is +0.6 to +2.4 °C at three stations and
  −0.5 to −1.4 °C at la Quar** — the expected order of magnitude for a
  ~11 km global model, not a calibration.
- **The station-level lapse correction is almost nil** because Open-Meteo's
  grid altitude already matches the real station altitude within 24 m at all
  18 nearest XEMA stations. The correction only becomes material where a
  curated *zone* altitude differs from the grid cell.
- **Daily max/min errors are larger than the mean error**: min temperature
  is too warm by up to +4.4 °C at the valley stations (Sant Pau de Segúries)
  and +3.3 °C at Núria, while max temperature is too cool by up to −2.5 °C.
  Cold-air pooling at night is exactly what a coarse model misses; this is
  reported as a limitation, not corrected by an invented offset.
- **Precipitation** on the same days was trace: Open-Meteo 0.0 mm at all four
  points, XEMA 0.0 mm except Viladrau 0.1 mm (11-07) and Sant Pau de Segúries
  0.1 mm (11-08). No meaningful rain signal to compare.
- Two days at four stations is a spot check, **not** a validation dataset.
  Phase 5 calibration will publish proper metrics.

### End-to-end lapse correction for a zone

`score_zone` stores `weather.grid_alt_m` (model), `weather.zone_alt_m`
(curated LiDAR altitude) and `weather.lapse_correction_c`, and must satisfy
`(zone_alt_m − grid_alt_m) × 0.0065` within rounding. The live 2026-11-09
run passes this for **66/66 zones** (0 mismatches). Example:
`ogassa-carena-oest` — grid 1,393 m, zone 1,049 m, correction −2.24 °C
(expected −2.236 → −2.24). Across the 66 zones only one correction exceeds
1 °C (Ogassa, −2.24 °C); most grid cells already sit close to the curated
zone altitude.

### Day rollover and cache stamps (2026-11-08 → 2026-11-09)

`weather_cache.json` is keyed by rounded coordinate and stores the calendar
day (`date` for the 21-day forecast series, `w_date` for the 92-day water
series). Before starting the 2026-11-09 run, **all 72 cached entries were
stamped 2026-11-08** (`date` and `w_date`). A fresh server start on
2026-11-09 refetched and restamped **all 72 entries to 2026-11-09**
(`t = 2026-11-09 09:34:26` local, 08:34:26Z); no 11-08-stamped entry remained.
The live `/api/forecast` reported `date: 2026-11-09` and
`xema.fetched_at: 2026-11-09T08:34:31Z`, so a previous day's series is never
served for today. This is enforced by the `date == today` / `w_date == today`
checks in `fetch_weather_batch` / `fetch_water_batch`; the 3 h `WEATHER_TTL`
only applies inside the same day.

### Sources and timestamps audit (66 zones, live run)

| Block | Present | Provenance carried | Exception |
|---|---:|---|---|
| `weather` | 66/66 | `grid_alt_m`, `zone_alt_m`, `lapse_correction_c` | **No `source` or `fetched_at` field** — provenance is the cache entry (`date` + `t`) and this README. Recorded as an audit exception, not fabricated. |
| `xema` | 66/66 | `source`, `fetched_at`, `data_age_min`, `nearest_distance_km`, station rows | none |
| `water` | 66/66 | `source`, `computed_at`, `blend_source`, window day counts | none |
| `confidence` | 66/66 | `computed_at`, input completeness/reasons | no single `source` string (it names each input in `reasons`) |
| `phenology` | 66/66 | `computed_at`, `note` naming GDD + lapse source | none |

Top-level `xema.status: "ok"`, 188 operative stations, all 66 zones got an
`xema` block with the key. Without `METEOCAT_API_KEY` the fixture path makes
**0 Meteocat calls** and all other blocks still cover 66/66 zones.

### Regression evidence (2026-11-09)

- `python3 -m py_compile app.py forecast.py warm_parking.py enrich_zones.py`
  → OK.
- Real `build_forecast()` fixture with network fetchers monkeypatched:
  22 stations, 66 zones, 0 errors; `weather`/`water`/`confidence`/`phenology`
  66/66; with key `xema` 66/66; no-key path **byte-identical** to the 4.5
  baseline (`after45b.json`) and **0 Meteocat calls**.
- Live server (port 8899, real key): `/` 200 (140,828 B), `/api/stations`
  200 (4,708 B), `/api/forecast` 200 (15,706,019 B, 6.09 s), 0 station/zone
  errors.
- The embedded `<script>` is **byte-identical to the 4.5 extraction**
  (`app_script_45.js`); `node --check` OK. No UI behaviour changed in 4.6.

### Phase 4 limitations (carried forward)

- **Model error range**: spot-checked mean deltas +0.6…+2.4 °C and
  −0.5…−1.4 °C; daily minima can be several °C too warm in valleys. The
  7-day forecast is planning guidance, not a guarantee.
- **ET0 history length**: Open-Meteo's ET0 series starts ~59 days back, so the
  60/90-day water windows are partially covered; each window records the days
  actually used and nothing is extrapolated.
- **XEMA coverage gaps**: the key activates 188 operative stations; coverage
  and data age vary by zone, and readings are provisional (`estat` blank or
  `T`). Without a key the app stays fully functional on Open-Meteo.
- **Radar deferred**: Meteocat exposes no XRAD product; rain accumulation uses
  the XEMA gauges (variable 1300).
- **Field calibration**: thresholds, the soil storage cap, the drought
  modifier and the GDD ramps are documented modelling choices, not
  field-verified. Phase 5 calibrates them against reports/GBIF.

---

## Field reports (Phase 5.1)

Phase 5 closes the loop: a hunter records what they actually found (or did not
find) in the field, and that data calibrates the model. Step 5.1 ships the
**report model, storage and API** — no UI yet (the 30-second report form is the
optional step 5.2, deferred). Calibration and published metrics are step 5.6.

### Privacy by design

- The client posts a `lat`/`lon`, but only the **1 km-rounded cell** is stored
  and returned (`round_to_km` → 0.01° ≈ 1.1 km). The exact coordinate is never
  written to disk or exposed.
- Neither the raw device id nor the client IP is stored. Each is kept only as a
  **salted SHA-256 hash** (a random per-deployment salt is generated once and
  stored in the DB `meta` table), so abuse limits work without collecting
  identity.
- `GET /api/reports` returns **aggregated counts**, never individual rows,
  device hashes or exact positions.
- `DELETE /api/reports` gives a **right-to-erasure** path: a device (identified
  by the same salted hash used on POST) can delete its own reports — all of
  them, or one by `id` — without the server ever returning raw identity.

### Storage

A SQLite database (`reports.db`, in `DATA_DIR`, so on Fly it lives on the
mounted `/app/data` volume; gitignored locally). Table `reports`:

| Column | Meaning |
|---|---|
| `cell_lat` / `cell_lon` / `cell_key` | the 1 km-rounded cell (e.g. `42.11,1.89`) |
| `comarca` | free text, required, ≤ 64 chars |
| `species_id` | id from `mushrooms.json`, or `NULL` |
| `found` | 1 = found, 0 = not found |
| `quantity` | specimens (nullable, 0–10000) |
| `duration_min` | time spent (nullable, 0–1440) |
| `trip_date` | YYYY-MM-DD the trip happened (defaults to today) |
| `trip_time` | HH:MM (nullable) |
| `score_at_time` | the model score shown to the user at report time (nullable, 0–99) — client-supplied, used later for calibration |
| `device_hash` / `client_ip_hash` | salted hashes |
| `created_at` | UTC ISO-8601 submission time |

### API

**`POST /api/reports`** — submit a trip report.

```json
{
  "lat": 42.1091, "lon": 1.8873,
  "comarca": "Berguedà",
  "species": "rovelló",       // optional, must be a known id
  "found": true,              // required boolean
  "quantity": 8,              // optional
  "duration_min": 75,         // optional
  "date": "2026-11-09",       // optional, YYYY-MM-DD
  "time": "08:15",            // optional, HH:MM
  "score": 78                 // optional, 0–99
}
```

The device is identified by the `X-Device-Id` header or a `device_id` body
field; if absent, the client IP + `User-Agent` are hashed instead. Success
returns `201` with the stored (rounded) cell:

```json
{ "status": "ok", "id": 7, "cell": { "lat": 42.11, "lon": 1.89 } }
```

Invalid input returns `400` with a message; over the abuse limits returns `429`.

**`GET /api/reports?bbox=&days=`** — privacy-safe aggregates.

- `bbox` = `south,west,north,east` (lat,lon,lat,lon), optional.
- `days` = lookback window, default 30, hard cap 365.

```json
{
  "reports": [
    {
      "lat": 42.11, "lon": 1.89, "comarca": "Berguedà",
      "found": 2, "not_found": 1,
      "species": { "rovelló": {"found": 2, "not_found": 1} }
    }
  ],
  "total": 3,
  "window_days": 7
}
```

**`DELETE /api/reports`** — erase this device's reports (privacy / right to
erasure). The device is resolved the same way as on POST (`X-Device-Id` header
or a `device_id` body field, else the IP + `User-Agent` hash), so a report can
only be deleted by the identity that created it.

- `DELETE /api/reports` — deletes **all** of this device's reports.
- `DELETE /api/reports?id=<id>` — deletes that single report, only if it belongs
  to this device. Returns `200 {"status":"ok","deleted":1}` on success,
  `404 {"status":"not_found"}` for an unknown id, `403 {"status":"forbidden"}`
  when the id belongs to another device, and `400` for a malformed id.

No exact coordinate, device hash or IP is ever returned by any of these
endpoints.

### Moderation and abuse limits

Rolling windows over `created_at` (documented ops choices, single-process app):

| Limit | Value |
|---|---|
| per device hash, 1 h | 10 |
| per device hash, 24 h | 50 |
| per client IP, 1 h | 60 |

Exceeding any limit returns `429 { "error": "rate_limited", "reason": "…" }`.
All input is validated (`found` must be boolean, `species` must be a known id,
numbers bounded, `date`/`time` well-formed); malformed JSON is rejected `400`.

### What is deliberately not in this step

- **No UI** — the report form is the optional step 5.2 (deferred).
- **No scoring/confidence change** — `FIELD_REPORTS_COUNT` is still `0` in the
  confidence block; wiring the live count (`field_report_count()`) in is a
  remaining follow-up (the confidence block reports the honest zero until it is
  wired). See step 5.7.
- **No calibration** — reports are collected now; AUC/Brier and retraining are
  step 5.6.

---

## Calibration and published metrics (Phase 5.6)

`calibrate.py` (stdlib-only) computes and publishes the model's accuracy. Two
surfaces, because only one of them has true binary labels:

- **Field reports** (`reports.db`, step 5.1) are the only labels with a real
  match between "what the model said" (`score_at_time`) and "what happened"
  (`found`/`not_found`). They yield **AUC**, **Brier score** and a binned
  **calibration curve**, evaluated on a deterministic held-out split.
- **GBIF + iNaturalist occurrences** (presence-only, deduplicated) yield a
  per-species **AUC** of the model's *current* score at known occurrence sites
  versus random Catalonia background points — standard rank-discrimination for
  presence-only data (no true absences).

```bash
python3 calibrate.py              # full pipeline → calibration_report.json
python3 calibrate.py --self-test  # offline metric-math checks (no network)
```

### Published results (2026-11-10)

**Field reports:** `n = 0` — the report store shipped in 5.1 is empty, so
**AUC / Brier / calibration curve are not computable yet and no recalibration
is applied**. This is deliberate: with no held-out binary data, retraining the
score would overfit. The pipeline is in place and will publish real numbers as
reports accumulate.

**Occurrence AUC** (model's current score at occurrence sites vs 200 random
background points, each scored by its nearest zone ≤ 20 km):

| Species | AUC | n (in coverage) |
|---|---:|---:|
| Trompeta de la Mort | **0.745** | 46 |
| Cep | **0.668** | 55 |
| Ou de Reig | **0.664** | 58 |
| Rovelló | **0.653** | 55 |
| Orella de Llebre | **0.653** | 29 |
| Picornell | 0.623 | 104 |
| Rossinyol | 0.599 | 20 |
| Llenegra Negra | 0.577 | 18 |
| Fredolic | 0.533 | 56 |
| Llenegra Blanca | 0.514 | 36 |
| Bolet de Tinta | 0.421 | 70 |
| Camagroc | 0.321 | 47 |
| Murgola | — (n/a) | 0 |

> AUC = 1.0 perfect separation, 0.5 chance, < 0.5 worse than random.

### Honest reading

- **The model discriminates the classic forest species it was built for**
  (trompeta, cep, ou de reig, rovelló, orella de llebre all ≥ 0.65) — those
  occurrence sites score above random background.
- **Weak or negative discrimination is itself a finding.** Bolet de Tinta
  (0.42) grows in meadows and roadsides, not forest — the app only scores forest
  zones, so it cannot place it. Camagroc (0.32) is a high-altitude
  late-autumn *pine* species whose occurrence sites are under-weighted by the
  current seasonal score. These flag where the model is not yet predictive,
  not a bug to hide.
- **Murgola has no autumn score** (it is filtered out in autumn), so its
  spring-only occurrences cannot be validated by the current forecast — n/a,
  not zero.
- **These are presence-only, current-weather numbers.** They measure
  *spatial/seasonal discrimination*, not a calibrated probability. The true
  calibration (score → probability of finding) can only come from field
  reports, which start at zero and accumulate through the 5.1 store.

### Method notes and limits

- Occurrences are real GBIF + iNaturalist records (deduplicated, filtered to
  Catalonia). Each is scored by its nearest curated zone, so the metric is at
  the model's zone resolution.
- Background points are uniform random Catalonia coordinates within 20 km of a
  zone (the model's coverage), scored the same way.
- No recalibration was applied to the score. The published numbers are
  descriptive validation — published honestly, including the negative results.

---

## Disclaimer

This app is a planning tool, not an identification guide.

**Never eat a mushroom unless you are 100% certain of its identification.** Many edible species have toxic lookalikes. When in doubt, consult a mycologist or a trusted field guide.

Mushroom collection in Catalunya is free for personal use up to 6 kg per person per day. Respect private property and local regulations. Do not step on moss — it takes years to regenerate.
