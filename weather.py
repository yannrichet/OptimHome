"""Open-Meteo weather fetch + CombiTimeTable writer, shared by app.py and api.py.

No Streamlit dependency: app.py wraps these with @st.cache_data for the UI;
api.py calls them directly."""
import hashlib
import os
import tempfile
from datetime import timedelta

import pandas as pd
import requests

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_open_meteo_range(lat, lon, start_date, end_date):
    """Serie horaire reelle T2m [°C] + rayonnement global horizontal [W/m2]
    (ERA5 reanalysis) via l'API Open-Meteo, sans cle, de 1940 a aujourd'hui."""
    r = requests.get(
        OPEN_METEO_URL,
        params={"latitude": lat, "longitude": lon,
                "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                "hourly": "temperature_2m,shortwave_radiation", "timezone": "UTC"},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if "hourly" not in payload:
        raise RuntimeError(payload.get("reason", "réponse Open-Meteo invalide"))
    h = payload["hourly"]
    df = pd.DataFrame({
        "dt": pd.to_datetime(h["time"]),
        "Tout_C": h["temperature_2m"],
        "Gh": h["shortwave_radiation"],
    })
    return df.dropna(subset=["Tout_C", "Gh"]).reset_index(drop=True)


def prepare_weather(lat, lon, start_date, end_date, warmup_days=14):
    """Fenetre meteo horaire reelle (mise en regime + periode choisie), ecrite
    au format CombiTimeTable dans un fichier stable (cache disque par site+dates).

    Returns (weather_path, stop_time)."""
    fetch_start = start_date - timedelta(days=warmup_days)
    win = fetch_open_meteo_range(round(lat, 3), round(lon, 3), fetch_start, end_date)
    if win.empty:
        raise RuntimeError("Aucune donnée météo Open-Meteo pour cette position/période.")

    key = f"{lat:.3f}_{lon:.3f}_{start_date}_{end_date}_{warmup_days}"
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    weather_path = os.path.join(tempfile.gettempdir(), f"buildingopt_weather_{h}.txt")
    with open(weather_path, "w") as f:
        f.write("#1\n")
        f.write(f"double tmy({len(win)},3)\n")
        for i, row in enumerate(win.itertuples()):
            f.write(f"{i * 3600} {row.Tout_C + 273.15:.2f} {max(row.Gh, 0.0):.1f}\n")

    stop_time = (len(win) - 1) * 3600
    return weather_path, stop_time
