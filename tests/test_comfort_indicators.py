"""comfort_indicators() (indicators.py, used by both app.py and the
notebook) computes the two comfort metrics shown in the app's metric row:
hours outside the comfort band, and cold/heat discomfort degree-hours (see
README's "Sorties" section). Literal naming: DH_froid = degree-hours below
the comfort floor (it's cold), DH_chaleur = degree-hours above the comfort
ceiling (it's hot) — not the building-industry DJU chauffage/froid
convention (which names by the HVAC system needed, the opposite mapping)."""
import pandas as pd
import pytest

from indicators import comfort_indicators


def test_all_hours_within_band_gives_zero_everywhere():
    Tint = pd.Series([20.0, 21.0, 22.0, 25.0])
    hours, dh_froid, dh_chaleur = comfort_indicators(Tint, T_confort_min=19.0, T_confort_max=26.0)
    assert hours == 0
    assert dh_froid == pytest.approx(0.0)
    assert dh_chaleur == pytest.approx(0.0)


def test_undershoot_counts_as_cold_degree_hours():
    Tint = pd.Series([15.0, 17.0, 20.0])  # 4 K + 2 K under a 19 C floor, 1 in-band
    hours, dh_froid, dh_chaleur = comfort_indicators(Tint, T_confort_min=19.0, T_confort_max=26.0)
    assert hours == 2
    assert dh_froid == pytest.approx(4.0 + 2.0)
    assert dh_chaleur == pytest.approx(0.0)


def test_overshoot_counts_as_heat_degree_hours():
    Tint = pd.Series([27.0, 30.0, 20.0])  # 1 K + 4 K over a 26 C ceiling, 1 in-band
    hours, dh_froid, dh_chaleur = comfort_indicators(Tint, T_confort_min=19.0, T_confort_max=26.0)
    assert hours == 2
    assert dh_froid == pytest.approx(0.0)
    assert dh_chaleur == pytest.approx(1.0 + 4.0)


def test_a_brief_spike_counts_less_than_a_sustained_excursion():
    """The whole point of degree-hours over a plain Tmax: a short spike must
    weigh less than the same peak sustained over many hours."""
    brief_spike = pd.Series([26.0, 30.0, 26.0, 26.0, 26.0])
    sustained = pd.Series([28.0, 28.0, 28.0, 28.0, 28.0])
    _, _, dh_brief = comfort_indicators(brief_spike, T_confort_min=19.0, T_confort_max=26.0)
    _, _, dh_sustained = comfort_indicators(sustained, T_confort_min=19.0, T_confort_max=26.0)
    assert dh_brief < dh_sustained
