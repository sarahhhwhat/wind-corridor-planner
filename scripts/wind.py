import requests, numpy as np, pandas as pd

url = "https://archive-api.open-meteo.com/v1/archive"
p = {"latitude": 19.076, "longitude": 72.8777,
     "start_date": "2025-01-01", "end_date": "2025-12-31",
     "hourly": "wind_speed_10m,wind_direction_10m", "timezone": "Asia/Kolkata"}
h = requests.get(url, params=p).json()["hourly"]
df = pd.DataFrame(h)
df["month"] = pd.to_datetime(df["time"]).dt.month

def prevailing(g):
    rad = np.radians(g["wind_direction_10m"])
    u = (g["wind_speed_10m"] * np.sin(rad)).mean()
    v = (g["wind_speed_10m"] * np.cos(rad)).mean()
    return round((np.degrees(np.arctan2(u, v)) + 360) % 360)

print("Yearly:", prevailing(df))
print(df.groupby("month").apply(prevailing))