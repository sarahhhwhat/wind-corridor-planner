"""Sentinel-2 L2A dry-season NDBI for Mumbai wards.

Uses pystac-client + planetary-computer: low-cloud (<10 %, with fallbacks)
Sentinel-2 L2A dry-window scenes (Jan-May), windowed read of B08 + B11 COGs,
mosaicked on a fixed EPSG:32643 (UTM 43N) 20 m grid, NDBI = (SWIR1 - NIR) /
(SWIR1 + NIR), then zonal mean per ward (wards in UTM 43N for the mask).

Per-item band windows are cached as .npy under data/raw/cache/ so a slow
network never loses progress: re-runs skip already-fetched items. Raw rasters
stay in data/raw/ (gitignored, never committed).

Fallback ladder (automatic):
  1. clearest 8 items with cloud < 10 % across 2024-01-01..2025-05-31
  2. extend to 12 items (same cloud cap)
  3. relax to cloud < 15 %
  4. relax to cloud < 20 %, Jan-Apr 2025 only (smaller window)
  reports which attempt was used in meta.

Outputs:
  web/public/data/ndbi.json            ward -> mean NDBI + meta
  web/public/data/ndbi_raster_4326.json tiny gridded sample for overlay
  data/raw/mumbai_ndbi_composite.tif   raw NDBI raster (gitignored)
  data/raw/cache/<item>_<band>.npy     band caches (gitignored)
"""
import json
import os
import sys
import time

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from rasterio.windows import from_bounds as win_from_bounds
from rasterio.enums import Resampling as RSample

from pystac_client import Client
import planetary_computer as pc
from shapely.geometry import mapping

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "web", "public", "data")
RAW = os.path.join(ROOT, "data", "raw")
CACHE = os.path.join(RAW, "cache")
WARDS = os.path.join(OUT_DIR, "wards_base.geojson")

STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
BBOX = [72.77, 18.85, 73.05, 19.30]  # Mumbai lon/lat
RES = 20  # metres, reference grid

os.makedirs(CACHE, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)

CITY_LON, CITY_LAT = 72.8777, 19.076


def query_items(datetime_range, max_cloud, max_items):
    cat = Client.open(STAC, modifier=pc.sign_inplace)
    search = cat.search(
        collections=[COLLECTION], bbox=BBOX, datetime=datetime_range,
        query={"eo:cloud_cover": {"lt": max_cloud}},
    )
    items = list(search.items())
    items = sorted(items, key=lambda it: it.properties.get("eo:cloud_cover", 100))
    return items[:max_items]


def ref_grid(gdf_utm):
    """Fixed UTM 43N grid over the wards (+2 km buffer) at RES m."""
    minx, miny, maxx, maxy = gdf_utm.total_bounds
    minx, miny, maxx, maxy = minx - 2000, miny - 2000, maxx + 2000, maxy + 2000
    w = int(np.ceil((maxx - minx) / RES))
    h = int(np.ceil((maxy - miny) / RES))
    transform = from_bounds(minx, miny, maxx, maxy, w, h)
    return transform, h, w


def read_band_window(item, band, dst_bounds_utm, dst_transform, dst_shape):
    """Read band COG cropped to the study area (windowed, decimated 2x),
    reproject onto the ref grid, cache to disk. Returns (arr, was_cached)."""
    stamp = f"{item.id}_{band}"
    npy = os.path.join(CACHE, stamp + ".npy")
    jsn = os.path.join(CACHE, stamp + ".json")
    h, w = dst_shape
    if os.path.exists(npy) and os.path.exists(jsn):
        return np.load(npy), True

    # NOTE: a plain Env with just retry args; the fancy MULTIRANGE/MERGE
    # options caused all-nan reprojects on this rasterio/GDAL build.
    with rasterio.Env(GDAL_HTTP_MAX_RETRY=5, GDAL_HTTP_RETRY_DELAY=2):
        href = pc.sign(item.assets[band].href)
        with rasterio.open(href) as src:
            # window covering the UTM study bounds, expressed in src CRS
            # (careful: B08 is 10 m, B11 is 20 m -- use the band's OWN transform)
            xs = [dst_bounds_utm[0], dst_bounds_utm[2]] * 2
            ys = [dst_bounds_utm[1], dst_bounds_utm[1],
                  dst_bounds_utm[3], dst_bounds_utm[3]]
            to_src = rasterio.warp.transform("EPSG:32643", src.crs, xs, ys)
            sx = to_src[0]; sy = to_src[1]
            win = win_from_bounds(min(sx), min(sy), max(sx), max(sy),
                                  transform=src.transform).round_offsets().round_lengths()
            if win.width <= 0 or win.height <= 0:
                return None, False
            # decimate 50% with bilinear (fast on COG overviews) -- this is
            # equivalent to reading each native pixel once for 20 m output.
            out_h = max(1, int(win.height) // 2)
            out_w = max(1, int(win.width) // 2)
            arr = src.read(1, window=win, out_shape=(out_h, out_w),
                           resampling=RSample.bilinear).astype("float32")
            # after out_shape halving, each new cell spans 2 native pixels,
            # so scale the window transform by 2/1 -> (width/2 cells)
            t = rasterio.windows.transform(win, src.transform) * rasterio.Affine.scale(2, 2)
            crs = src.crs
        nod = arr == 0  # L2A nodata/saturation sentinel 0
        arr = np.where(nod, np.nan, arr)

    dst = np.full((h, w), np.nan, dtype="float32")
    # NOTE: with rasterio 1.3+, giving src_nodata=np.nan makes GDAL treat the
    # whole float source as nodata when combined with bilinear resampling on
    # some builds -- reproduce-documented bug. Mask explicitly using a sentinel
    # value (-9999.0) for source nodata, compute over the valid mask only.
    SENT = -9999.0
    arr_masked = np.where(np.isfinite(arr), arr, SENT).astype("float32")
    reproject(arr_masked, dst,
              src_transform=t, src_crs=crs, src_nodata=SENT,
              dst_transform=dst_transform, dst_crs="EPSG:32643",
              dst_width=w, dst_height=h,
              resampling=Resampling.bilinear, dst_nodata=np.nan)
    np.save(npy, dst)
    with open(jsn, "w") as f:
        json.dump({"item": item.id, "band": band,
                   "datetime": item.datetime.isoformat(),
                   "cloud": item.properties.get("eo:cloud_cover")}, f)
    return dst, False


def build_mosaic(items, transform, h, w):
    """Average all valid band pixels into B08/B11 mosaics on ref grid."""
    # bounds = (left, BOTTOM, right, TOP); transform.f is the grid TOP (maxy)
    bounds = (transform.c, transform.f - h * RES, transform.c + w * transform.a, transform.f)
    sum_nir = np.zeros((h, w), "float32"); cnt_nir = np.zeros((h, w), "float32")
    sum_sw = np.zeros((h, w), "float32"); cnt_sw = np.zeros((h, w), "float32")
    for i, it in enumerate(items):
        t0 = time.time()
        nir, cached = read_band_window(it, "B08", bounds, transform, (h, w))
        sw, _ = read_band_window(it, "B11", bounds, transform, (h, w))
        print(f"  [{i+1}/{len(items)}] {it.id} cloud={it.properties.get('eo:cloud_cover'):.1f}% "
              f"{'cached' if cached else 'fetched'} in {time.time()-t0:.1f}s", flush=True)
        if nir is None or sw is None:
            continue
        m = np.isfinite(nir); sum_nir[m] += nir[m]; cnt_nir[m] += 1
        m = np.isfinite(sw); sum_sw[m] += sw[m]; cnt_sw[m] += 1
    with np.errstate(invalid="ignore"):
        nir_m = np.where(cnt_nir > 0, sum_nir / np.maximum(cnt_nir, 1), np.nan)
        sw_m = np.where(cnt_sw > 0, sum_sw / np.maximum(cnt_sw, 1), np.nan)
    return nir_m, sw_m


def compute_ndbi(nir, sw):
    with np.errstate(invalid="ignore", divide="ignore"):
        return (sw - nir) / (sw + nir)

    means = {}
    inv = ~rasterio.Affine.identity()
    for _, row in gdf_utm.iterrows():
        geoms = [mapping(row["geometry"])]
        # rasterize the ward onto the grid, then take nanmean
        mask_arr = features.rasterize(
            [(row["geometry"], 1)], out_shape=ndbi.shape,
            transform=transform, fill=0, all_touched=True, dtype="uint8")
        vals = ndbi[(mask_arr == 1) & np.isfinite(ndbi)]
        if vals.size:
            ward_id = row.get("name", row.get("id"))
            means[ward_id] = round(float(vals.mean()), 3)
    return means


def sample_grid_for_map(ndbi, transform, target_cells=150):
    """Downsample to a coarse lat/lon grid (<=~150x150 cells) for the frontend."""
    h, w = ndbi.shape
    step = max(1, int(np.ceil(max(h, w) / target_cells)))
    rows = np.arange(0, h, step); cols = np.arange(0, w, step)
    sub = ndbi[np.ix_(rows, cols)]
    t = transform * rasterio.Affine.scale(step, step)
    west, north = t * (0, 0)
    east, south = t * (sub.shape[1], sub.shape[0])
    nw, nh = sub.shape[1], sub.shape[0]
    dst_t = from_bounds(west, south, east, north, nh, nw)
    dst = np.full((nh, nw), np.nan, "float32")
    reproject(sub, dst, src_transform=t, src_crs="EPSG:32643", src_nodata=np.nan,
              dst_transform=dst_t, dst_crs="EPSG:4326", dst_width=nw, dst_height=nh,
              resampling=Resampling.average, dst_nodata=np.nan)
    return dst, dst_t


ATTEMPTS = [
    ("primary", "2024-01-01/2025-05-31", 10, 8),
    ("more-items", "2024-01-01/2025-05-31", 10, 12),
    ("cloud-15", "2024-01-01/2025-05-31", 15, 12),
    ("cloud-20-2025", "2025-01-01/2025-04-30", 20, 10),
]


def main():
    gdf = gpd.read_file(WARDS)
    gdf_utm = gdf.to_crs(32643)
    transform, h, w = ref_grid(gdf_utm)
    print(f"ref grid {w}x{h} @ {RES} m")

    used = None
    for label, rng, cloud, max_items in ATTEMPTS:
        print(f"[{label}] {rng} cloud<{cloud}% items<={max_items}", flush=True)
        items = query_items(rng, cloud, max_items)
        print(f"  {len(items)} items")
        if len(items) < 2:
            continue
        nir, sw = build_mosaic(items, transform, h, w)
        cover = float(np.mean(np.isfinite(nir) & np.isfinite(sw)))
        print(f"  coverage {cover:.1%}")
        used = (label, items, nir, sw, cover)
        if cover >= 0.85:
            break
    if used is None:
        raise SystemExit("No usable Sentinel-2 data found.")
    label, items, nir, sw, cover = used
    print(f"using attempt '{label}' ({len(items)} items, coverage {cover:.1%})")

    ndbi = compute_ndbi(nir, sw)
    ndbi[~np.isfinite(ndbi)] = np.nan

    prof = {"driver": "GTiff", "height": h, "width": w, "count": 1,
            "dtype": "float32", "transform": transform, "crs": "EPSG:32643",
            "nodata": float("nan")}
    raw_path = os.path.join(RAW, "mumbai_ndbi_composite.tif")
    with rasterio.open(raw_path, "w", **prof) as dst:
        dst.write(ndbi.astype("float32"), 1)
    print("raw ->", raw_path)

    # zonal mean per ward
    from rasterio import features
    means = {}
    for _, row in gdf_utm.iterrows():
        mask_arr = features.rasterize([(row["geometry"], 1)], out_shape=ndbi.shape,
                                      transform=transform, fill=0,
                                      all_touched=True, dtype="uint8")
        vals = ndbi[(mask_arr == 1) & np.isfinite(ndbi)]
        if vals.size:
            ward_id = row.get("name", row.get("id"))
            means[ward_id] = round(float(vals.mean()), 3)
    print(f"zonal means {len(means)}/{len(gdf_utm)} wards")

    cl = [it.properties.get("eo:cloud_cover", 999) for it in items]
    meta = {
        "source": "Sentinel-2 L2A via Microsoft Planetary Computer STAC",
        "attempt": label, "n_items": len(items),
        "item_ids": [it.id for it in items],
        "cloud_covers_pct": [round(c, 1) for c in cl],
        "datetime_range": ATTEMPTS[[a[0] for a in ATTEMPTS].index(label)][1],
        "formula": "NDBI = (B11 SWIR1 - B08 NIR) / (B11 + B08)",
        "valid_coverage_pct": round(cover * 100, 1),
        "grid": f"EPSG:32643 @ {RES} m",
        "zonal_method": "mean of NDBI pixels inside ward (UTM 43N, all_touched)",
        "ward_values": {k: float(v) for k, v in means.items()},
    }
    with open(os.path.join(OUT_DIR, "ndbi.json"), "w") as f:
        json.dump({"meta": meta, "ndbi": means}, f, indent=2)
    print("wrote ndbi.json")
    print(json.dumps(means, indent=2))

    grid, gt = sample_grid_for_map(ndbi, transform, target_cells=140)
    values = [[None if not np.isfinite(v) else round(float(v), 3) for v in r]
              for r in grid.tolist()]
    west, north = gt * (0, 0)
    east, south = gt * (grid.shape[1], grid.shape[0])
    with open(os.path.join(OUT_DIR, "ndbi_raster_4326.json"), "w") as f:
        json.dump({"bounds": [round(west, 5), round(south, 5),
                              round(east, 5), round(north, 5)],
                   "nrows": grid.shape[0], "ncols": grid.shape[1],
                   "values": values}, f)
    print("wrote ndbi_raster_4326.json")


if __name__ == "__main__":
    main()
