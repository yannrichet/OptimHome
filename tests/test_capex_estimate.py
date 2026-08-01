"""capex_estimate() (indicators.py) — CAPEX estimate for the 5 design
variables, each included or excluded via a 0/1 flag (e.g. an already-financed
heating system shouldn't be re-counted as a new investment)."""
import pytest

from indicators import CAPEX_UNIT_COSTS, DEFAULT_CAPEX_FLAGS, capex_estimate


def test_default_flags_match_the_documented_defaults():
    # chauffage=0 (deja finance), clim=1, pv=0 (deja finance), ite=1, iti=1
    assert DEFAULT_CAPEX_FLAGS == {"Pheat": 0, "Pcool": 1, "Ppv_kWc": 0, "e_ite_cm": 1, "e_iti_cm": 1}


def test_default_flags_exclude_pheat_and_ppv():
    with_pheat = capex_estimate(Pheat=8000, Pcool=0, Ppv_kWc=0, e_ite_cm=0, e_iti_cm=0, Awall=100)
    with_ppv = capex_estimate(Pheat=0, Pcool=0, Ppv_kWc=5.0, e_ite_cm=0, e_iti_cm=0, Awall=100)
    assert with_pheat == pytest.approx(0.0)
    assert with_ppv == pytest.approx(0.0)


def test_default_flags_include_pcool_ite_iti():
    capex = capex_estimate(Pheat=0, Pcool=2000, Ppv_kWc=0, e_ite_cm=16.0, e_iti_cm=0, Awall=100)
    expected = CAPEX_UNIT_COSTS["Pcool"] * 2000 + CAPEX_UNIT_COSTS["e_ite_cm"] * 100 * 16.0
    assert capex == pytest.approx(expected)


def test_insulation_costs_scale_with_wall_area():
    small_wall = capex_estimate(Pheat=0, Pcool=0, Ppv_kWc=0, e_ite_cm=10.0, e_iti_cm=0, Awall=50)
    big_wall = capex_estimate(Pheat=0, Pcool=0, Ppv_kWc=0, e_ite_cm=10.0, e_iti_cm=0, Awall=100)
    assert big_wall == pytest.approx(2 * small_wall)


def test_flags_override_defaults():
    # force-include Pheat, force-exclude Pcool
    capex = capex_estimate(
        Pheat=8000, Pcool=2000, Ppv_kWc=0, e_ite_cm=0, e_iti_cm=0, Awall=100,
        flags={"Pheat": 1, "Pcool": 0},
    )
    assert capex == pytest.approx(CAPEX_UNIT_COSTS["Pheat"] * 8000)


def test_zero_values_contribute_nothing_regardless_of_flags():
    capex = capex_estimate(
        Pheat=0, Pcool=0, Ppv_kWc=0, e_ite_cm=0, e_iti_cm=0, Awall=100,
        flags={"Pheat": 1, "Pcool": 1, "Ppv_kWc": 1, "e_ite_cm": 1, "e_iti_cm": 1},
    )
    assert capex == pytest.approx(0.0)


def test_all_flags_off_gives_zero_capex():
    capex = capex_estimate(
        Pheat=8000, Pcool=2000, Ppv_kWc=3.0, e_ite_cm=16.0, e_iti_cm=5.0, Awall=100,
        flags={"Pheat": 0, "Pcool": 0, "Ppv_kWc": 0, "e_ite_cm": 0, "e_iti_cm": 0},
    )
    assert capex == pytest.approx(0.0)
