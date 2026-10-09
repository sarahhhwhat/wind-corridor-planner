# wind-corridor-planner

Ward-level map of Mumbai’s urban ventilation and heat. Combines prevailing wind, built-up
density and land surface temperature from satellite data to find where airflow is blocked
and where corridors or open space help most.

## Data pipeline

Run in this order (Python deps: `geopandas`, `rasterio`, `pystac-client`,
`planetary-computer`, `pandas`, `requests`):

| script | output |
| --- | --- |
| `scripts/wards.py` | `web/public/data/wards_base.geojson` — ward geometry, maths in EPSG:32643 |
| `scripts/wind.py` | `web/public/data/wind_seasons.json` — seasonal prevailing wind (Open-Meteo ERA5) |
| `scripts/ndbi.py` | `web/public/data/ndbi.json`, `ndbi_raster_4326.json` — Sentinel-2 built-up density |
| `scripts/lst.py` | `data/lst_by_ward.csv` — summer land surface temperature per ward (Landsat 8/9) |
| `scripts/corridors.py` | `web/public/data/wards.geojson` + `corridors_{season}.geojson` — scores, priority, corridors |

Raw rasters and caches live in `data/raw/` (gitignored).

## Land surface temperature (LST) methodology

- **Source**: Landsat 8 and 9 **Collection 2 Level-2** (`landsat-c2-l2`) through the
  [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/) STAC API
  (`scripts/lst.py`).
- **Scenes**: `eo:cloud_cover` < 10 %, **March to May of each year 2021–2025**,
  Landsat 8/9 only, sorted by cloud cover, best `MAX_SCENES = 8` scenes used.
- **Grid**: fixed 30 m grid in EPSG:32643 (UTM 43N) covering the ward bounds + 300 m pad.
  Per scene, assets `lwir11` (thermal band 10) and `qa_pixel` are read window-wise through
  a rasterio `WarpedVRT` (nearest resampling, nodata = 0) — full scenes are never
  downloaded, so the script runs on a small laptop.
- **Conversion**: °C = DN × 0.00341802 + 149.0 − 273.15.
- **QA masking**: pixels are dropped where DN = 0 (fill), where
  `(qa_pixel & 0b10011111) != 0` — fill, dilated cloud, cirrus, cloud, cloud shadow and
  **water** (open water is excluded) — and where the value falls outside 15–65 °C.
- **Composite**: per-pixel **median** across the scenes (cached to
  `data/raw/lst_summer_median.npy`, reused on re-runs), then the **mean of the pixels
  inside each ward** (wards rasterized onto the grid) → `data/lst_by_ward.csv`
  (`ward_index, ward, lst_c, pixels, heat_score`).
- **heat_score**: min–max normalisation of `lst_c` across the 24 wards — 0 = coolest ward,
  1 = hottest ward.

> **This is land SURFACE temperature, not air temperature.** It is what the satellite
> thermal sensor sees (roof, road and soil skin temperature), which on a hot afternoon runs
> well above shaded air temperature. The values are for relative ward-to-ward comparison,
> not as weather-station readings.

## Priority score

```
priority_score = 0.5 * heat_score + 0.5 * (1 - ventilation_score)
```

- `heat_score` — 0..1 min–max normalised ward-mean summer LST (0 = coolest, 1 = hottest).
- `ventilation_score` — the existing per-ward ventilation score divided by 100 (already
  0–100 where higher = better ventilated); the **summer** score is used so it matches the
  March–May LST window.

Higher = worse: **rank 1 = the hottest and most poorly ventilated ward**. The fields
`lst_c`, `heat_score`, `priority_score` and `priority_rank` are written into
`web/public/data/wards.geojson` by `scripts/corridors.py`.

## Web app

```bash
cd web && npm ci && npm run dev    # or npm run build
```

React + Vite + Leaflet, OpenStreetMap basemap. Ward layer switcher (Priority — default,
Ventilation score, Heat (LST)), seasonal wind tabs, corridor lines, ward popup with
locality names, and top-5 tables (priority / best / worst ventilated); layout is
responsive down to phone widths.
