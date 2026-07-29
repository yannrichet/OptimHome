"""_jac() is a hand-derived analytic Jacobian of _rhs(), kept only for
performance (see BuildingTherm.py:_jac docstring). Nothing else ties it to
_rhs() — a future edit to the RHS equations (or the clip breakpoints they use)
that isn't mirrored in _jac() would silently make solve_ivp's Newton
iterations converge on a wrong linearization while still integrating a
correct (if slower to converge) system, which is easy to miss. This test
catches that by comparing _jac() to a finite-difference Jacobian of _rhs() at
many random states."""
import os

import numpy as np
import pytest

import BuildingTherm as bt

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
WEATHER_PATH = os.path.join(FIXTURES, "weather_reference.txt")
FD_EPS = 1e-6


def _finite_difference_jacobian(t, y, c, weather):
    f0 = np.array(bt._rhs(t, y, c, weather))
    J = np.zeros((bt.N_STATES, bt.N_STATES))
    for j in range(bt.N_STATES):
        yp = np.array(y, dtype=float)
        h = FD_EPS * max(1.0, abs(y[j]))
        yp[j] += h
        f1 = np.array(bt._rhs(t, yp, c, weather))
        J[:, j] = (f1 - f0) / h
    return J


@pytest.mark.parametrize("seed", range(10))
def test_analytic_jacobian_matches_finite_differences(seed):
    weather = bt.load_weather_table(WEATHER_PATH)
    c = bt.derive_constants(bt.DEFAULT_PARAMS)
    rng = np.random.default_rng(seed)

    t = rng.uniform(0, 74 * 86400)
    y = np.array(bt.Y0) + rng.normal(scale=3.0, size=bt.N_STATES)

    analytic = bt._jac(t, y, c, weather)
    numeric = _finite_difference_jacobian(t, y, c, weather)

    assert analytic == pytest.approx(numeric, abs=1e-6, rel=1e-4)
