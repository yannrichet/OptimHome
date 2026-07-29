"""Regenerate tests/fixtures/weather_reference.txt: a fully deterministic,
synthetic 74-day weather series (14 d warm-up + 60 d test window) in the
CombiTimeTable format BuildingTherm.{mo,py} expect.

Synthetic rather than a real Open-Meteo download so the test suite has no
network dependency and is byte-for-byte reproducible. Only needs re-running
if the desired test horizon/shape changes — the model equations don't affect
this file.
"""
import os

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "weather_reference.txt")

N_DAYS = 74


def main():
    hours = np.arange(N_DAYS * 24)
    t = hours * 3600.0
    day = hours / 24.0

    # Slow seasonal warming (2C -> 10C) + diurnal swing + a slow synoptic
    # wobble so the series isn't perfectly periodic.
    Tout_C = (
        2.0 + 8.0 * (day / N_DAYS)
        - 6.0 * np.cos(2 * np.pi * (hours % 24) / 24 - np.pi / 3)
        + 1.5 * np.sin(2 * np.pi * day / 9.7)
    )
    Tout_K = Tout_C + 273.15

    hour_of_day = hours % 24
    daylight = np.clip(np.sin(np.pi * (hour_of_day - 6) / 12), 0.0, None)
    Gh = np.round(750.0 * daylight * (0.6 + 0.4 * np.sin(2 * np.pi * day / 13)), 1)

    with open(OUTPUT_PATH, "w") as f:
        f.write("#1\n")
        f.write(f"double tmy({len(hours)},3)\n")
        for ti, tk, g in zip(t, Tout_K, Gh):
            f.write(f"{ti:.0f} {tk:.2f} {g:.1f}\n")

    print(f"wrote {len(hours)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
