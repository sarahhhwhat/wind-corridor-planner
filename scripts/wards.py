"""Prepare Mumbai ward geometry.

Input : data/mumbai_wards.geojson  (24 BMC wards, property `name` = ward code,
        e.g. "A", "F/S", "K/W"; CRS EPSG:4326).
Steps : reproject to EPSG:32643 (UTM 43N) -- ALL area/distance/buffer maths
        happen there -- recompute area/length in m / m2 (the original
        shape_leng / shape_area properties are ignored: they came from another
        CRS and unit), add display names, simplify geometry for the web, then
        reproject back to EPSG:4326 for output.
Output: web/public/data/wards_base.geojson  (geometry + id/display/area only;
        analysis properties are added later by corridors.py)
"""
import json
import os

import geopandas as gpd
from shapely.geometry import mapping

SRC = os.path.join(os.path.dirname(__file__), "..", "data", "mumbai_wards.geojson")
OUT = os.path.join(os.path.dirname(__file__), "..", "web", "public", "data", "wards_base.geojson")

# Ward code -> display name ("F/S" -> "F/South Ward").
# Letters stand for ward areas; /N /S /E /W are north/south/east/west sub-wards.
SUFFIX = {"N": "North", "S": "South", "E": "East", "W": "West"}


def display_name(code: str) -> str:
    if "/" in code:
        base, _, sub = code.partition("/")
        return f"{base}/{SUFFIX.get(sub, sub)} Ward"
    return f"{code} Ward"


def main():
    g = gpd.read_file(SRC)
    assert g.crs.to_epsg() == 4326, f"expected EPSG:4326, got {g.crs}"
    g = g.to_crs(32643)  # UTM 43N -- metres

    # Recomputed measurements (original shape_leng/shape_area ignored).
    g["area_km2"] = (g.geometry.area / 1e6).round(2)
    g["perim_m"] = g.geometry.length.round(0)

    # Simplify for the web (metres at UTM 43N): ~30 m tolerance.
    g["geometry"] = g.geometry.simplify(30, preserve_topology=True)

    g = g.to_crs(4326)

    keep = g[["name", "geometry"]].copy()
    keep["id"] = keep["name"]
    keep["display_name"] = keep["name"].map(display_name)
    keep["area_km2"] = g["area_km2"].values
    keep["perim_m"] = g["perim_m"].values

    fc = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": [
            {
                "type": "Feature",
                "id": row["id"],
                "properties": {k: row[k] for k in ("id", "display_name", "area_km2", "perim_m")},
                "geometry": mapping(row.geometry),
            }
            for _, row in keep.iterrows()
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(fc, f)
    size = os.path.getsize(OUT) / 1024
    print(f"wrote {OUT} ({size:.0f} KiB), {len(keep)} wards")
    print(keep[["id", "display_name", "area_km2"]].to_string(index=False))


if __name__ == "__main__":
    main()
