"""Regenerate tests/fixtures/reference_openmodelica.csv from the compiled
OpenModelica binary.

Run this after any intentional change to the model equations in
BuildingTherm.mo (and the matching change in BuildingTherm.py) so the
regression test in tests/test_python_solver_matches_openmodelica.py compares
against fresh ground truth instead of a stale reference.

Requires OpenModelica (`omc build.mos`) to have produced the `BuildingTherm`
binary in the repo root first. Not run in CI: CI only replays the committed
CSV through the pure-Python solver.
"""
import os
import subprocess
import sys
import tempfile

import pandas as pd

import BuildingTherm as bt

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINARY = os.path.join(REPO_ROOT, "BuildingTherm")
WEATHER_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "weather_reference.txt")
OUTPUT_CSV = os.path.join(REPO_ROOT, "tests", "fixtures", "reference_openmodelica.csv")

COLUMNS = ["time", "Tair", "Tout", "Qheat", "Pgrid_cool", "Pself_cool",
           "Egrid_total", "Eself_cool", "Eexport", "Eheat", "Ecool"]


def main():
    if not os.path.isfile(BINARY):
        sys.exit(f"{BINARY} not found — run `omc build.mos` first.")

    weather = bt.load_weather_table(WEATHER_PATH)
    stop_time = int(weather[0][-1])

    override = f"tmy.fileName={WEATHER_PATH}," + ",".join(
        f"{k}={v}" for k, v in bt.DEFAULT_PARAMS.items()
    )

    with tempfile.TemporaryDirectory() as run_dir:
        for name in ("BuildingTherm_init.xml", "BuildingTherm_JacA.bin"):
            src = os.path.join(REPO_ROOT, name)
            if os.path.isfile(src):
                subprocess.run(["cp", src, run_dir], check=True)

        result_csv = os.path.join(run_dir, "res.csv")
        subprocess.run(
            [BINARY, f"-override={override}", "-startTime=0",
             f"-stopTime={stop_time}", "-stepSize=3600", f"-r={result_csv}"],
            cwd=run_dir, check=True, capture_output=True, text=True,
        )

        raw = pd.read_csv(result_csv)
        raw.columns = [c.strip('"') for c in raw.columns]

    # Same de-duplication as app.py's OpenModelica path: OM emits several
    # near-simultaneous rows around each ventilation-ramp event; keep the
    # last (settled) value per integer hour.
    raw["hour"] = (raw["time"] / 3600).round().astype(int)
    sim = raw.groupby("hour", as_index=False).last()
    sim["time"] = sim["hour"] * 3600
    sim = sim[[c for c in COLUMNS if c in sim.columns]]
    sim.to_csv(OUTPUT_CSV, index=False)
    print(f"wrote {len(sim)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
