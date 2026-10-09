"""Compute seasonal prevailing wind for Mumbai (2020-2025) from Open-Meteo archive.

Speed-weighted vector mean per season. wind_direction_10m is the direction the
wind blows FROM, in degrees clockwise from north (meteorological convention).

Seasons (meteorological, for Mumbai):
  winter   Dec+Jan+Feb  -- taking Nov out of winter and Oct out of monsoon
  summer   Mar+Apr+May
  monsoon  Jun+Jul+Aug+Sep
October is a weak transition month (prevailing ~143 deg on its own, between the
monsoon SW and the winter NE recurvature); it is folded into NOTHING and simply
excluded, since including it would bias whichever season it joins.
November is a winter onset month in Mumbai (NE'ly winds set in) so it is kept
in winter.

Output: web/public/data/wind_seasons.json
"""
import json
import os

import numpy as np
import pandas as pd
import requests

URL = "https://archive-api.open-meteo.com/v1/archive"
LAT, LON = 19.076, 72.8777  # central Mumbai
YEARS = range(2020, 2026)  # API: one request per year
OUT = os.path.join(os.path.dirname(__file__), "..", "web", "public", "data", "wind_seasons.json")

SEASONS = {
    "winter": [11, 12, 1, 2],   # Nov, Dec, Jan, Feb
    "summer": [3, 4, 5],        # Mar, Apr, May
    "monsoon": [6, 7, 8, 9],    # Jun..Sep
}
# October (month 10) deliberately absent above.

ROSE_BINS = np.arange(0, 360 + 22.5, 22.5)  # 16 sectors centred on 0,22.5,...
ROSE_LABELS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
               "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def fetch_year(year):
    p = {
        "latitude": LAT, "longitude": LON,
        "start_date": f"{year}-01-01", "end_date": f"{year}-12-31",
        "hourly": "wind_speed_10m,wind_direction_10m",
        "timezone": "Asia/Kolkata",
        "wind_speed_unit": "ms",
    }
    r = requests.get(URL, params=p, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    df = pd.DataFrame(h)
    df["time"] = pd.to_datetime(df["time"])
    df["month"] = df["time"].dt.month
    df["year"] = year
    # API can return nulls (fill values) -- drop them
    df = df.dropna(subset=["wind_speed_10m", "wind_direction_10m"])
    return df[["year", "month", "wind_speed_10m", "wind_direction_10m"]]


def speed_weighted_mean_dir(g):
    """Vector mean, weighted by speed, of FROM-direction (deg from N, cw)."""
    rad = np.radians(g["wind_direction_10m"])
    u = (g["wind_speed_10m"] * np.sin(rad)).mean()
    v = (g["wind_speed_10m"] * np.cos(rad)).mean()
    return (np.degrees(np.arctan2(u, v)) + 360) % 360


def rose_table(dirs, speeds):
    """Speed-weighted 16-point rose: fraction of total speed per FROM-sector."""
    which = np.digitize(dirs, ROSE_BINS[1:-1])  # 0..15
    sums = np.bincount(which, weights=speeds, minlength=16)
    frac = (sums / sums.sum() * 100).round(1)
    return dict(zip(ROSE_LABELS, frac.tolist()))


def main():
    parts = [fetch_year(y) for y in YEARS]
    df = pd.concat(parts, ignore_index=True)
    print(f"fetched {len(df)} hourly records, {df['year'].min()}-{df['year'].max()}")

    out = {"meta": {
        "city": "Mumbai", "lat": LAT, "lon": LON,
        "period": f"{YEARS[0]}-01-01/{YEARS[-1]}-12-31",
        "source": "Open-Meteo ERA5 archive API (hourly, 10 m)",
        "method": "speed-weighted vector mean of wind FROM-direction",
        "note": "October excluded as a weak transition month",
        "direction_convention": "degrees clockwise from north; FROM direction",
    }, "seasons": {}}

    for season, months in SEASONS.items():
        g = df[df["month"].isin(months)]
        deg = speed_weighted_mean_dir(g)
        label = ROSE_LABELS[int((deg + 11.25) // 22.5) % 16]  # nearest of 16
        # The direction the wind blows TOWARD (for map arrows)
        toward = (deg + 180) % 360
        out["seasons"][season] = {
            "from_deg": round(deg),
            "toward_deg": round(toward),
            "from_compass": label,
            "mean_speed_ms": round(g["wind_speed_10m"].mean(), 2),
            "n_hours": int(len(g)),
            "rose": rose_table(g["wind_direction_10m"].to_numpy(),
                               g["wind_speed_10m"].to_numpy()),
        }
        print(season, out["seasons"][season]["from_deg"], label,
              out["seasons"][season]["mean_speed_ms"])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
