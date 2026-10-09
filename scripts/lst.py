"""Summer land surface temperature (LST) for Mumbai wards from Landsat 8/9.

Input : data/mumbai_wards.geojson (24 BMC wards, property `name` = ward code,
        CRS EPSG:4326) -- reprojected to EPSG:32643 (UTM 43N) for all maths.

Method:
  * Fixed 30 m grid over the ward bounds + 300 m pad (EPSG:32643).
  * Microsoft Planetary Computer STAC, collection "landsat-c2-l2",
    Landsat 8 and 9 only, eo:cloud_cover < 10 %, March-May of every year
    2021..2025; scenes sorted by cloud cover, best MAX_SCENES kept.
  * Per scene: windowed read of assets "lwir11" (band 10) and "qa_pixel"
    through a rasterio WarpedVRT onto the fixed grid (nearest, nodata=0) --
    only the study-area window is fetched, never the full scene.
  * Celsius = DN * 0.00341802 + 149.0 - 273.15, then masked where
    DN == 0 (fill), (qa_pixel & 0b10011111) != 0 (fill, dilated cloud,
    cirrus, cloud, cloud shadow, water) and outside 15..65 C.
  * Per-pixel nanmedian across scenes -> cached to
    data/raw/lst_summer_median.npy (data/raw is gitignored; re-runs reuse it).
  * Wards rasterized onto the grid; ward mean LST -> heat_score
    (min-max normalised across wards, 0 = coolest, 1 = hottest).

Note: this is land SURFACE temperature (satellite thermal infrared), not air
temperature.

Output: data/lst_by_ward.csv  (ward_index, ward, lst_c, pixels, heat_score)
"""
import csv
import json
import os
import time
import warnings

import geopandas as gpd
import numpy as np
import planetary_computer as pc
import rasterio
from pystac_client import Client
from rasterio import features
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WARDS_SRC = os.path.join(ROOT, "data", "mumbai_wards.geojson")
RAW = os.path.join(ROOT, "data", "raw")
CACHE = os.path.join(RAW, "cache")
MEDIAN_NPY = os.path.join(RAW, "lst_summer_median.npy")
OUT_CSV = os.path.join(ROOT, "data", "lst_by_ward.csv")

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "landsat-c2-l2"
PLATFORMS = {"landsat-8", "landsat-9"}          # Landsat 8 and 9 only
SPACECRAFT = {"LANDSAT_8", "LANDSAT_9"}
YEARS = range(2021, 2026)                        # 2021..2025
MONTH_WINDOW = (3, 5)                            # March to May, per year
CLOUD_MAX = 10                                   # eo:cloud_cover < 10 %
MAX_SCENES = 8                                   # best (clearest) scenes used

RES = 30          # grid resolution, metres
PAD = 300         # grid pad around ward bounds, metres

SCALE, OFFSET = 0.00341802, 149.0                # Landsat C2 L2 ST -> kelvin
QA_MASK = 0b10011111                              # fill, dilated, cirrus,
                                                  # cloud, shadow, water
LST_MIN, LST_MAX = 15.0, 65.0                     # plausible surface temp, C

os.makedirs(CACHE, exist_ok=True)
os.makedirs(RAW, exist_ok=True)


def ref_grid(gdf_utm):
    """Fixed 30 m UTM 43N grid over ward bounds + 300 m pad."""
    minx, miny, maxx, maxy = gdf_utm.total_bounds
    minx, miny, maxx, maxy = minx - PAD, miny - PAD, maxx + PAD, maxy + PAD
    w = int(np.ceil((maxx - minx) / RES))
    h = int(np.ceil((maxy - miny) / RES))
    return from_origin(minx, maxy, RES, RES), h, w


def search_scenes(bbox4326):
    """Best MAX_SCENES Landsat 8/9 summer scenes (Mar-May, cloud < 10 %)."""
    cat = Client.open(STAC, modifier=pc.sign_inplace)
    found = []
    for year in YEARS:
        lo, hi = MONTH_WINDOW
        s = cat.search(
            collections=[COLLECTION],
            bbox=list(bbox4326),
            datetime=f"{year}-{lo:02d}-01/{year}-{hi:02d}-31",
            query={"eo:cloud_cover": {"lt": CLOUD_MAX}},
        )
        items = list(s.items())
        print(f"  {year} Mar-May cloud<{CLOUD_MAX}%: {len(items)} items", flush=True)
        found.extend(items)

    keep = []
    seen = set()
    for it in found:
        if it.id in seen:
            continue
        platform = (it.properties.get("platform") or "").lower()
        craft = (it.properties.get("spacecraft_id") or "").upper()
        if platform not in PLATFORMS and craft not in SPACECRAFT:
            continue  # Landsat 7 / 5 / others
        if "lwir11" not in it.assets or "qa_pixel" not in it.assets:
            continue
        seen.add(it.id)
        keep.append(it)

    keep.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100))
    print(f"  {len(keep)} usable Landsat 8/9 scenes, keeping best {MAX_SCENES}", flush=True)
    return keep[:MAX_SCENES]


def read_band(item, band, transform, h, w):
    """WarpedVRT read of one asset onto the fixed grid (windowed, COG only).

    Caches the small grid-sized array to data/raw/cache/ so a re-run never
    re-fetches; full scenes are never downloaded.
    """
    stamp = f"{item.id}_{band}"
    npy = os.path.join(CACHE, stamp + ".npy")
    if os.path.exists(npy):
        return np.load(npy), True

    with rasterio.Env(GDAL_HTTP_MAX_RETRY=5, GDAL_HTTP_RETRY_DELAY=2):
        href = pc.sign(item.assets[band].href)
        with rasterio.open(href) as src:
            with WarpedVRT(src, crs="EPSG:32643", transform=transform,
                           width=w, height=h,
                           resampling=Resampling.nearest,
                           src_nodata=0, nodata=0) as vrt:
                arr = vrt.read(1)
    np.save(npy, arr)
    return arr, False


def scene_lst(item, transform, h, w):
    """Masked Celsius LST of one scene on the fixed grid (NaN = invalid)."""
    lwir, c1 = read_band(item, "lwir11", transform, h, w)
    qa, c2 = read_band(item, "qa_pixel", transform, h, w)

    dn = lwir.astype("float32")
    c = dn * SCALE + OFFSET - 273.15
    invalid = (
        (lwir == 0)                                  # fill / nodata
        | ((qa.astype("uint16") & QA_MASK) != 0)     # cloud / shadow / water
        | (c < LST_MIN) | (c > LST_MAX)              # out of range
        | ~np.isfinite(c)
    )
    c[invalid] = np.nan
    return c, (c1 and c2)


def build_median(bbox4326, transform, h, w):
    if os.path.exists(MEDIAN_NPY):
        arr = np.load(MEDIAN_NPY)
        print(f"reusing cache {MEDIAN_NPY} {arr.shape}", flush=True)
        return arr

    print("searching Planetary Computer STAC ...", flush=True)
    items = search_scenes(bbox4326)
    if not items:
        raise SystemExit("No Landsat 8/9 scenes found (cloud < 10 %, Mar-May).")

    stack, used = [], []
    for i, it in enumerate(items, 1):
        cloud = it.properties.get("eo:cloud_cover")
        t0 = time.time()
        arr, cached = scene_lst(it, transform, h, w)
        n_valid = int(np.isfinite(arr).sum())
        print(f"  [{i}/{len(items)}] {it.id} cloud={cloud:.1f}% "
              f"{'cached' if cached else 'fetched'} valid={n_valid:,} "
              f"in {time.time()-t0:.1f}s", flush=True)
        if n_valid:
            stack.append(arr)
            used.append(it)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices
        median = np.nanmedian(np.stack(stack), axis=0).astype("float32")
    np.save(MEDIAN_NPY, median)
    cover = float(np.mean(np.isfinite(median)))
    print(f"median of {len(used)} scenes -> {MEDIAN_NPY} "
          f"(valid coverage {cover:.1%})", flush=True)
    return median


def ward_means(gdf_utm, median, transform):
    """Rasterize wards on the grid, mean LST per ward + min-max heat_score."""
    h, w = median.shape
    labels = features.rasterize(
        [(geom, i + 1) for i, geom in enumerate(gdf_utm.geometry)],
        out_shape=(h, w), transform=transform, fill=0,
        all_touched=True, dtype="int32")

    rows = []
    for i, (_, row) in enumerate(gdf_utm.iterrows()):
        vals = median[labels == (i + 1)]
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            raise SystemExit(f"no valid LST pixels for ward {row['name']}")
        rows.append({
            "ward_index": i,                 # 0-based feature order in the source
            "ward": row["name"],             # ward code, e.g. "A", "F/S"
            "lst_c": round(float(vals.mean()), 2),
            "pixels": int(vals.size),
        })

    lst = np.array([r["lst_c"] for r in rows])
    lo, hi = lst.min(), lst.max()
    for r, v in zip(rows, lst):
        r["heat_score"] = round(float((v - lo) / (hi - lo)) if hi - lo > 1e-12 else 0.5, 3)
    return rows


def main():
    gdf = gpd.read_file(WARDS_SRC)
    assert gdf.crs.to_epsg() == 4326, f"expected EPSG:4326, got {gdf.crs}"
    bbox4326 = gdf.total_bounds  # (minx, miny, maxx, maxy) lon/lat
    gdf_utm = gdf.to_crs(32643)

    transform, h, w = ref_grid(gdf_utm)
    print(f"grid {w}x{h} @ {RES} m (pad {PAD} m), {len(gdf_utm)} wards")

    median = build_median(bbox4326, transform, h, w)
    rows = ward_means(gdf_utm, median, transform)

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    cols = ["ward_index", "ward", "lst_c", "pixels", "heat_score"]
    with open(OUT_CSV, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)
    print("wrote", OUT_CSV)

    print("\nWard land surface temperature (summer median, sorted by lst_c):")
    print(f"{'ward_index':>10}  {'ward':<6} {'lst_c':>7} {'pixels':>8} {'heat_score':>10}")
    for r in sorted(rows, key=lambda r: -r["lst_c"]):
        print(f"{r['ward_index']:>10}  {r['ward']:<6} {r['lst_c']:>7.2f} "
              f"{r['pixels']:>8,} {r['heat_score']:>10.3f}")


if __name__ == "__main__":
    main()
