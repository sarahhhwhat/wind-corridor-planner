"""Seasonal ventilation analysis for Mumbai wards.

For each season (winter / summer / monsoon) the prevailing FROM-direction from
wind_seasons.json is combined with per-ward NDBI (built-up density) to give:

1. A ventilation score per ward (0..100, higher = better ventilation potential):
     score = 100 * (1 - built_up_norm) * (0.5 + 0.5 * exposure_norm)
   where built_up_norm ranks the ward's NDBI relative to all wards, and
   exposure measures how close the ward is to the upwind coast/edge along the
   seasonal wind bearing, i.e. how much unobstructed fetch it gets. Farther
   inland = lower exposure (turbulent wake of the city first).

2. Corridor lines: candidate ventilation corridors running ALONG the wind
   (from its upwind origin inland). We distribute transects across the city
   width perpendicular to the wind, extend each along the bearing from the
   upwind edge to the downwind edge, and sample the NDBI-aware openness along
   each (a weighted mean NDBI of intersected wards: --more open-- NDBI low =
   more open). We rank them and keep the top three (most open) plus flag the
   wards they cross as "protect recommended"; the worst-scoring wards get
   "create new corridor / green space" recommendations.

3. Heat + priority per ward (from scripts/lst.py, data/lst_by_ward.csv):
     lst_c, heat_score   summer median land surface temperature (Landsat 8/9,
                         Mar-May 2021-2025) and its 0..1 min-max normalisation
                         (0 = coolest ward, 1 = hottest ward);
     priority_score = 0.5 * heat_score + 0.5 * (1 - ventilation_score)
     with ventilation_score = summer score / 100 (already 0..100), so priority
     is 0..1 and rank 1 = highest priority = hot + poorly ventilated. The
     SUMMER ventilation score is used because it matches the LST window.

Outputs:
  web/public/data/wards.geojson    full ward dataset + LST/priority +
                                   per-season score/rank
  web/public/data/corridors_{winter,summer,monsoon}.geojson

Geometry is processed in EPSG:32643 (UTM 43N) and converted back to EPSG:4326.
"""
import csv
import json
import os

import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, mapping
from shapely.ops import substring

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "web", "public", "data")
WARDS_BASE = os.path.join(OUT_DIR, "wards_base.geojson")
NDBI_JSON = os.path.join(OUT_DIR, "ndbi.json")
WIND_JSON = os.path.join(OUT_DIR, "wind_seasons.json")
LST_CSV = os.path.join(ROOT, "data", "lst_by_ward.csv")  # scripts/lst.py

SEASONS = ["winter", "summer", "monsoon"]


def load():
    wards = gpd.read_file(WARDS_BASE)      # EPSG:4326
    wards_utm = wards.to_crs(32643)
    ndbi = json.load(open(NDBI_JSON))["ndbi"]
    wind = json.load(open(WIND_JSON))
    return wards, wards_utm, ndbi, wind


def load_lst():
    """Ward summer LST from scripts/lst.py -> {ward: {lst_c, heat_score, ...}}."""
    if not os.path.exists(LST_CSV):
        raise SystemExit(f"{LST_CSV} missing - run scripts/lst.py first")
    with open(LST_CSV) as f:
        return {r["ward"]: r for r in csv.DictReader(f)}


def norm(v):
    arr = np.asarray(v, dtype="float64")
    lo, hi = np.nanmin(arr), np.nanmax(arr)
    if hi - lo < 1e-12:
        return np.full_like(arr, 0.5)
    return (arr - lo) / (hi - lo)


def ward_centroids(wards_utm):
    return np.array([(c.x, c.y) for c in wards_utm.geometry.centroid])


def exposure_from(direction_from_deg, centroids, city_bounds):
    """How unobstructed the wind is at a ward: distance to the UPWIND city
    boundary along the wind bearing, normalised 1 (very upwind/open fetch)
    to 0 (deep inland). Model simply: project centroids onto the wind unit
    vector; the smaller the projection (i.e. nearest the upwind edge), the
    better the fetch."""
    rad = np.radians(direction_from_deg)
    # unit vector pointing INTO the wind (towards its source)
    ux, uy = -np.sin(rad), np.cos(rad)  # FROM north: -sin = west, cos = north
    cx, cy = centroids[:, 0], centroids[:, 1]
    proj = cx * ux + cy * uy            # larger = more upwind
    lo, hi = proj.min(), proj.max()
    fetch = (proj - lo) / max(hi - lo, 1.0)  # 1 at very upwind, 0 downwind end
    fetch = 1.0 - fetch
    fetch = 1 - fetch  # keep explicit: fetch==1 at upwind edge, 0 at downwind
    return fetch


def corridor_candidates(wards_utm, direction_from_deg, n=10, length=28000):
    """Generate n transect lines across the city along the wind bearing,
    laterally distributed perpendicular to it."""
    minx, miny, maxx, maxy = wards_utm.total_bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    rad = np.radians(direction_from_deg)
    # wind 'towards' unit vector
    tx, ty = -np.sin(rad), np.cos(rad)  # blows toward = FROM + 180
    # perpendicular (across wind)
    px, py = -ty, tx
    # lateral size of the city
    lat_size = max(maxx - minx, maxy - miny)
    lines = []
    for i in range(n):
        f = (i / (n - 1)) - 0.5       # -0.5..0.5
        ox = cx + px * lat_size * f * 1.1
        oy = cy + py * lat_size * f * 1.1
        p0 = (ox - tx * length / 2, oy - ty * length / 2)
        p1 = (ox + tx * length / 2, oy + ty * length / 2)
        lines.append(LineString([p0, p1]))
    return lines


def openness_along(line, wards_utm, ndbi_map):
    """Mean NDBI of wards crossed by the line, weighted by intersection
    length  -- a proxy for how free the corridor path is."""
    total_w = 0.0
    total = 0.0
    for _, row in wards_utm.iterrows():
        inter = row.geometry.intersection(line)
        if inter.is_empty:
            continue
        w = inter.length
        v = ndbi_map.get(row["id"], -0.05)
        total += w * v
        total_w += w
    return total / total_w if total_w > 0 else None


def clip_corridor(line, wards_union_utm):
    """Trim the transect to the part that lies within the city's convex hull
    (so lines crossing the sea / beyond Mumbai look sensible on the map)."""
    return line.intersection(wards_union_utm.buffer(1000))


def season_output(wards_utm, ndbi, wind_season, season):
    from_deg = wind_season["from_deg"]
    centroids = ward_centroids(wards_utm)
    ids = list(wards_utm["id"])
    ndbi_vals = np.array([ndbi.get(i, np.nanmean(list(ndbi.values()))) for i in ids])

    built = norm(-ndbi_vals)         # higher NDBI -> lower score component
    exposure = exposure_from(from_deg, centroids, None)
    score = 100 * (0.65 * built + 0.35 * exposure)
    score = score.round(1)

    order = np.argsort(-score)       # best first
    rank = np.empty(len(ids), dtype=int)
    rank[order] = np.arange(1, len(ids) + 1)

    quint = np.percentile(score, [20, 40, 60, 80])
    def rec(s):
        if s >= quint[3]:
            return "Well ventilated. Protect existing open space and wind passages; no new obstruction in or upwind of this ward."
        if s >= quint[2]:
            return "Good ventilation. Maintain open space; watch for upwind blocking from high-rise growth."
        if s >= quint[1]:
            return "Moderate. Encourage street-level permeability; avoid closing key links upwind."
        if s >= quint[0]:
            return "Poor. Create or widen green/open-space corridors aligned with the prevailing wind; restrictive on tall, wide built mass upwind."
        return "Critical. Prioritise new ventilation corridors and protect remaining open/green land; strong upwind obstruction control."
    recs = [rec(s) for s in score]

    # corridor lines
    union = wards_utm.union_all()
    cands = corridor_candidates(wards_utm, from_deg, n=10)
    scored = []
    for ln in cands:
        op = openness_along(ln, wards_utm, ndbi)
        if op is None:
            continue
        clipped = clip_corridor(ln, union)
        if clipped.is_empty:
            continue
        scored.append((op, clipped))
    scored.sort(key=lambda t: t[0])   # most open (lowest NDBI) first
    n_keep = min(3, len(scored))
    corridors = []
    for i, (op, geom) in enumerate(scored[:n_keep]):
        crossings = [row["id"] for _, row in wards_utm.iterrows()
                     if row.geometry.intersects(geom)]
        corridors.append({
            "rank": i + 1,
            "openness": round(float(op), 3),
            "crosses": crossings,
            "from_deg": from_deg,
            "toward_deg": (from_deg + 180) % 360,
        })
    return ids, score, rank, recs, corridors


def main():
    wards, wards_utm, ndbi, wind = load()
    lst = load_lst()
    props = {}
    corridor_features = {}
    for season in SEASONS:
        ids, score, rank, recs, corridors = season_output(
            wards_utm, ndbi, wind["seasons"][season], season)
        for i, wid in enumerate(ids):
            props.setdefault(wid, {})
            props[wid][season] = {
                "score": float(score[i]),
                "rank": int(rank[i]),
                "rec": recs[i],
            }
        # Per-season corridors: rank candidates by openness, keep the 3 most
        # open, clip to the city footprint, convert to EPSG:4326 for the map.
        from_deg = wind["seasons"][season]["from_deg"]
        union = wards_utm.union_all()
        cands = corridor_candidates(wards_utm, from_deg, n=10)
        scored = []
        for ln in cands:
            op = openness_along(ln, wards_utm, ndbi)
            if op is None:
                continue
            scored.append((op, ln))
        scored.sort(key=lambda t: t[0])   # lowest NDBI = most open first
        feats = []
        for i, (op, ln) in enumerate(scored[:3]):
            clipped = clip_corridor(ln, union)
            g4326 = gpd.GeoSeries([clipped], crs=32643).to_crs(4326).iloc[0]
            crossings = [row["id"] for _, row in wards_utm.iterrows()
                         if row.geometry.intersects(clipped)]
            feats.append({
                "type": "Feature",
                "properties": {
                    "rank": i + 1,
                    "openness": round(float(op), 3),
                    "crosses": crossings,
                    "from_deg": from_deg,
                    "toward_deg": (from_deg + 180) % 360,
                    "wind": wind["seasons"][season]["from_compass"],
                },
                "geometry": mapping(g4326),
            })
        corridor_features[season] = feats

    # Heat + priority: 0.5 * heat_score + 0.5 * (1 - ventilation_score),
    # ventilation_score = SUMMER score / 100 (same Mar-May window as the LST
    # composite). Both 0..1; rank 1 = highest priority (hot + poorly
    # ventilated).
    ids = list(wards_utm["id"])
    heat = np.array([float(lst[i]["heat_score"]) for i in ids])
    vent = np.array([props[i]["summer"]["score"] for i in ids]) / 100.0
    priority = 0.5 * heat + 0.5 * (1.0 - vent)
    order = np.argsort(-priority)
    prank = np.empty(len(ids), dtype=int)
    prank[order] = np.arange(1, len(ids) + 1)
    prio = {wid: (round(float(priority[k]), 3), int(prank[k]))
            for k, wid in enumerate(ids)}

    print("priority (0.5*heat + 0.5*(1-vent), summer ventilation):")
    for wid in sorted(ids, key=lambda w: prio[w][1]):
        print(f"  #{prio[wid][1]:>2} {wid:<4} priority={prio[wid][0]:.3f} "
              f"lst={lst[wid]['lst_c']}C heat={lst[wid]['heat_score']} "
              f"vent={props[wid]['summer']['score']}")

    out_features = []
    for _, row in wards.iterrows():
        wid = row["id"]
        p = {
            "id": wid,
            "display_name": row["display_name"],
            "area_km2": float(row["area_km2"]),
            "ndbi": ndbi.get(wid),
            "lst_c": float(lst[wid]["lst_c"]),
            "heat_score": float(lst[wid]["heat_score"]),
            "priority_score": prio[wid][0],
            "priority_rank": prio[wid][1],
            "seasons": props.get(wid, {}),
        }
        out_features.append({
            "type": "Feature", "id": wid,
            "properties": p,
            "geometry": mapping(row.geometry),
        })
    wards_fc = {"type": "FeatureCollection", "features": out_features}
    wards_path = os.path.join(OUT_DIR, "wards.geojson")
    with open(wards_path, "w") as f:
        json.dump(wards_fc, f)
    print("wrote", wards_path, f"{os.path.getsize(wards_path)/1024:.0f} KiB")

    for season in SEASONS:
        fc = {"type": "FeatureCollection",
              "features": corridor_features[season],
              "meta": {"season": season,
                       "wind": wind["seasons"][season]}}
        path = os.path.join(OUT_DIR, f"corridors_{season}.geojson")
        with open(path, "w") as f:
            json.dump(fc, f)
        print("wrote", path, f"({len(fc['features'])} corridors)")


if __name__ == "__main__":
    main()
