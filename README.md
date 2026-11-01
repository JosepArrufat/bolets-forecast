# Bolets Forecast

**Live demo:** https://bolets-forecast.fly.dev

A mushroom hunting forecast tool for Catalunya — specifically the comarques of **Berguedà**, **Ripollès**, and **Cerdanya**. It combines real-time weather data with geological and vegetation data to score how likely each of the top 13 edible Catalan mushrooms is to appear at a set of key forest stations, today.

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

## What it does

### The UI

- **Left sidebar** — all stations grouped by comarca. Each card shows altitude, last 7 days of rain, average temperature, max wind, and the top 4 species by score.
- **Map** — Leaflet map with a numbered marker per station, colored green/amber/red by best species score. Click any marker to open the detail panel.
- **Right panel** — opens on station click. Shows soil type badge (calcareous/siliceous/mixed), forest type badge (from CORINE), the raw lithology text from IGME, a 3-stat weather summary, and the full ranked species list. Click any species row to expand its score breakdown and notes.
- **Topo ICGC toggle** — top-right map button overlays the official ICGC topographic tiles for terrain context.

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

---

## Data sources

| Source | What it provides | Key needed | Speed |
|---|---|---|---|
| [Open-Meteo](https://open-meteo.com) | Past 14 days + 7-day forecast: precipitation, temp min/max, wind gusts, humidity | None | ~0.3s |
| [IGME Litologías 1M](https://mapas.igme.es/gis/rest/services/Cartografia_Geologica/IGME_Litologias_1M/MapServer) | Spanish geological survey. Lithology text per point: "Dolomías, calizas…" vs "Cuarcitas, pizarras…" → calcareous or siliceous | None | ~0.1s |
| [CORINE Land Cover 2018](https://image.discomap.eea.europa.eu/arcgis/services/Corine/CLC2018_WM/MapServer/WMSServer) | EU land cover map. Codes: 311=broadleaf, 312=conifer, 313=mixed, 324=transitional shrub | None | ~0.5s |
| [SoilGrids v2 (ISRIC)](https://rest.isric.org/soilgrids/v2.0/properties/query) | Global soil pH at 250m resolution. Used as fallback only when IGME lithology is ambiguous | None | ~8s |
| [Meteocat API](https://api.meteo.cat) | Official Catalan Met Service. Higher-resolution local station data than Open-Meteo | Free key (apply at meteo.cat) | fast |

IGME and CORINE results are cached to `geo_cache.json` on first fetch and never re-fetched (geology does not change). Weather is always re-fetched live.

---

## The species

13 edible Catalan autumn mushrooms, each defined in `mushrooms.json` with:

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

Full conditions (temperature ranges, rain triggers, altitude bands, dry spell requirements, wind sensitivity) are in `mushrooms.json` and can be edited without touching the code.

---

## Files

```
bolets/
├── app.py           — single-file Python web app (stdlib only, no pip)
├── forecast.py      — original CLI-only scorer (kept for reference/debugging)
├── mushrooms.json   — species database + station definitions + scoring weights
├── geo_cache.json   — auto-generated, IGME + CORINE cache per lat/lon
├── appIdea.md       — original project spec
└── youtubetranscript.md  — transcript of the YouTube video that defines the rules
```

---

## Known limitations

### 1. CORINE resolution (100m)
CORINE land cover is mapped at 100m resolution from satellite imagery. It distinguishes conifer from broadleaf well at the comarca scale, but cannot tell Scots pine from black pine, or a young reforestation from an old-growth forest. The YouTuber's key insight — "Scots pine reforestation without undergrowth" — cannot be detected from CORINE alone.

### 2. IGME lithology resolution (1:1M scale)
The 1:1M geology map is good for distinguishing the Pyrenean calcareous massifs from the siliceous granitic zones, but misses local variation. A hillside can switch from calcareous to siliceous over a few hundred metres. The finer IGME MAGNA 50 (1:50,000) has better detail but patchy coverage — some sheets are missing for the Pyrenees.

### 3. Station coords vs forest coords
Weather is measured at the station (typically in the town valley). The geo query (IGME + CORINE) is offset to a `forest_lat/forest_lon` nearby. These offsets were chosen manually and are approximate — they point roughly at the forested hillsides above each town. Some still land on pasture (Ribes de Freser) or agricultural land (Puigcerdà).

### 4. GeoVeg / SIVIM is down
The YouTube video's key tool — the UB/CREAF interactive vegetation map (geoveg.creaf.cat and ub.edu/geoveg) — is currently broken. Both return DB errors or timeout. This was the best source for distinguishing tree species at the individual stand level, and for the "acidòfil/calcícola" soil classification at 1:25,000. When it comes back online, it would replace CORINE as the vegetation source and improve accuracy significantly.

### 5. No aspect (obaga/solana) detection
The YouTuber emphasises north-facing slopes (obaga) for most species. The app scores altitude and temperature but does not currently compute slope aspect. Adding this would require querying a DEM (Digital Elevation Model) and computing the aspect angle for each forest point.

### 6. SoilGrids is a global ML model
SoilGrids pH values are derived from a global machine-learning model at 250m resolution. They are systematically slightly high for the Pyrenees (calcareous geology dominates), which means siliceous pockets can be masked. It is used only as a fallback for ambiguous IGME results, not as the primary signal.

### 7. No Meteocat integration yet
Open-Meteo is good but uses ERA5 reanalysis + forecast models. Meteocat's XEMA network has actual physical stations at many of these exact locations (Rasos de Peguera, Ulldeter, Tossa d'Alp). Their API is free with registration. Swapping Open-Meteo for Meteocat for precipitation especially would improve short-term accuracy.

---

## Improvements roadmap

### Short term
- **Meteocat API key** — register at meteo.cat, add `METEOCAT_API_KEY` env var, swap weather fetch for local station data. The `forecast.py` has the URL pattern ready.
- **Fine-tune forest offsets** — Ribes de Freser and Puigcerdà still land on non-forest. Adjust `forest_lat/forest_lon` in `mushrooms.json` to confirmed pine forest GPS points.
- **Add more stations** — Meteocat XEMA has stations at Vallcebre, Bagà forest, La Molina, etc. Adding 5–6 more points per comarca would increase granularity.

### Medium term
- **IGME MAGNA 50 fallback** — try MAGNA 50 first (1:50k, more detail), fall back to 1:1M when no result. Would catch local siliceous pockets within calcareous zones.
- **Slope aspect from DEM** — query ICGC's 5m DEM (available as WMTS) to compute north/south aspect for each forest point. Apply obaga/solana multiplier per species.
- **GeoVeg when it returns** — if geoveg.creaf.cat or ub.edu/geoveg comes back online, add a third geo layer: query the vegetation polygon text and parse `acidòfil`/`calcícola` + tree species keywords. This would replace or complement CORINE.
- **Season selector** — UI toggle for spring (murgola season, March–May) vs autumn. Currently murgola is filtered out in autumn months.

### Long term
- **Historical validation** — compare forecast scores against known sighting reports from iNaturalist or GBIF for past seasons. Calibrate weights.
- **Precipitation accumulation map** — fetch Open-Meteo for a grid of points across the three comarques and render a heatmap of recent rainfall, as Meteocat shows on their monthly summary page.
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
  "notes": "Plain text description for the UI."
}
```

Restart the server after editing. No code changes needed.

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
    "forest_lat": 42.09,
    "forest_lon": 1.91,
    "notes": "Famous rovelló reforestation area from the YouTube video"
  }
]
```

- `lat/lon` — used for weather queries (put this at the nearest Meteocat station or town)
- `forest_lat/forest_lon` — used for IGME + CORINE queries (put this in the actual forest, not the town centre)
- `alt_m` — elevation in metres, used in the altitude score

The geo data for the new station is fetched and cached automatically on first load.

---

## Disclaimer

This app is a planning tool, not an identification guide.

**Never eat a mushroom unless you are 100% certain of its identification.** Many edible species have toxic lookalikes. When in doubt, consult a mycologist or a trusted field guide.

Mushroom collection in Catalunya is free for personal use up to 6 kg per person per day. Respect private property and local regulations. Do not step on moss — it takes years to regenerate.
