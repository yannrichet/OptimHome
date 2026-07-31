"""Regression test: BuildingTherm.py must stay numerically equivalent to
BuildingTherm.mo.

The repo carries two independent implementations of the same physics (see
README.md, "Solveur de secours Python"). Nothing enforced that they stayed in
sync: a change to one could silently drift from the other. This test replays
a fixed, committed weather series through the pure-Python solver and compares
it to a reference trace produced once by the compiled OpenModelica binary,
so any future edit to either implementation that breaks the equivalence
fails CI instead of surfacing as a silent divergence in production.

Regenerating the reference (only needed after an intentional change to the
model equations in BuildingTherm.mo/.py) is done with
`python scripts/regenerate_reference_fixture.py`, which requires a local
OpenModelica install (omc) — not part of the CI environment.
"""
import os

import pandas as pd
import pytest

import BuildingTherm as bt

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
WEATHER_PATH = os.path.join(FIXTURES, "weather_reference.txt")
REFERENCE_CSV = os.path.join(FIXTURES, "reference_openmodelica.csv")

# From README.md's own validated claim ("écart max sur la température
# intérieure 0.015 K ... < 0.02 %"), with headroom: this fixture is a shorter
# synthetic weather series than the full-year comparison in the README, but
# the tolerance stays representative of the two solvers' true agreement.
TAIR_ATOL_K = 0.02
ENERGY_RTOL = 5e-4


@pytest.fixture(scope="module")
def reference():
    return pd.read_csv(REFERENCE_CSV)


@pytest.fixture(scope="module")
def python_result(reference):
    weather = bt.load_weather_table(WEATHER_PATH)
    stop_time = int(reference["time"].iloc[-1])
    rows = bt.simulate(bt.DEFAULT_PARAMS, weather, stop_time)
    return pd.DataFrame(rows)


def test_reference_fixture_is_hourly_and_matches_python_grid(reference, python_result):
    assert list(reference["time"]) == list(python_result["time"])


def test_interior_air_temperature_matches_openmodelica(reference, python_result):
    diff = (python_result["Tair"] - reference["Tair"]).abs()
    assert diff.max() <= TAIR_ATOL_K, (
        f"max |Tair_python - Tair_openmodelica| = {diff.max():.4f} K "
        f"exceeds {TAIR_ATOL_K} K at t={reference['time'][diff.idxmax()]}"
    )


@pytest.mark.parametrize("column", ["Eheat", "Ecool", "Egrid_total", "Eself_cool", "Eexport"])
def test_cumulative_energy_indicators_match_openmodelica(reference, python_result, column):
    py_end = python_result[column].iloc[-1]
    om_end = reference[column].iloc[-1]
    assert py_end == pytest.approx(om_end, rel=ENERGY_RTOL, abs=1e-6), (
        f"{column}: python={py_end:.4f} kWh vs openmodelica={om_end:.4f} kWh"
    )
