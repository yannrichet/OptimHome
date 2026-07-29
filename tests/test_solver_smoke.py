"""Fast sanity checks on BuildingTherm.py, independent of the OpenModelica
reference (see test_python_solver_matches_openmodelica.py for that). These
catch NaNs/exceptions/regressions quickly without needing omc anywhere."""
import math
import os

import BuildingTherm as bt

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
WEATHER_PATH = os.path.join(FIXTURES, "weather_reference.txt")


def test_default_params_simulate_without_nan_over_short_horizon():
    weather = bt.load_weather_table(WEATHER_PATH)
    rows = bt.simulate(bt.DEFAULT_PARAMS, weather, stop_time=5 * 86400)
    assert len(rows) > 0
    for row in rows:
        for key, value in row.items():
            assert math.isfinite(value), f"non-finite {key}={value} at t={row['time']}"


def test_interior_temperature_stays_in_a_physically_plausible_range():
    weather = bt.load_weather_table(WEATHER_PATH)
    rows = bt.simulate(bt.DEFAULT_PARAMS, weather, stop_time=20 * 86400)
    tair_c = [row["Tair"] - 273.15 for row in rows]
    assert min(tair_c) > 0.0
    assert max(tair_c) < 40.0


def test_run_simulation_matches_simulate(tmp_path):
    """run_simulation() (the entry point app.py calls) must be a thin wrapper
    around load_weather_table() + simulate()."""
    weather = bt.load_weather_table(WEATHER_PATH)
    direct = bt.simulate(bt.DEFAULT_PARAMS, weather, stop_time=3 * 86400)
    via_wrapper = bt.run_simulation(bt.DEFAULT_PARAMS, WEATHER_PATH, stop_time=3 * 86400)
    assert direct == via_wrapper
