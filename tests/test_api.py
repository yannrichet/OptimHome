"""api.py — /simulate over GET (query string) and POST (JSON body), all
BuildingTherm params optional. prepare_weather() is monkeypatched to the
local weather fixture so these tests never hit the Open-Meteo network."""
import os

import pytest

import api
import BuildingTherm as bt

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
WEATHER_PATH = os.path.join(FIXTURES, "weather_reference.txt")
STOP_TIME = 74 * 86400  # matches the fixture's span


@pytest.fixture(autouse=True)
def _no_network_weather(monkeypatch):
    monkeypatch.setattr(api, "prepare_weather", lambda *a, **k: (WEATHER_PATH, STOP_TIME))


@pytest.fixture
def client():
    api.app.config["TESTING"] = True
    return api.app.test_client()


def test_index_lists_all_model_params(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(body["parametres_modele"]) == set(bt.DEFAULT_PARAMS)


def test_simulate_with_no_params_uses_defaults(client):
    resp = client.get("/simulate")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["params"] == bt.DEFAULT_PARAMS
    for key in ("temp_min_C", "temp_max_C", "heures_hors_confort",
                "degres_heures_froid_Kh", "degres_heures_chaleur_Kh",
                "conso_nette_kWh", "autoconso_pv_kWh", "export_pv_kWh", "cout_net_eur"):
        assert key in body["resultats"]
    assert "serie_horaire" not in body


def test_get_query_param_overrides_default(client):
    resp = client.get("/simulate?Pheat=1000&e_iti=0.05")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["params"]["Pheat"] == 1000.0
    assert body["params"]["e_iti"] == 0.05
    # every other param keeps its BuildingTherm default
    assert body["params"]["Pcool"] == bt.DEFAULT_PARAMS["Pcool"]


def test_post_json_body_sets_params(client):
    resp = client.post("/simulate", json={"Ppv_kWc": 0.0, "Pcool": 0.0})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["params"]["Ppv_kWc"] == 0.0
    assert body["params"]["Pcool"] == 0.0


def test_query_string_overrides_posted_json(client):
    resp = client.post("/simulate?Pheat=500", json={"Pheat": 9999.0})
    assert resp.status_code == 200
    assert resp.get_json()["params"]["Pheat"] == 500.0


def test_all_model_params_are_individually_accepted(client):
    """Every key in BuildingTherm.DEFAULT_PARAMS must be settable, not just
    the 5 sliders the app exposes."""
    for key, default in bt.DEFAULT_PARAMS.items():
        value = default + 1.0 if default else 1.0
        resp = client.get(f"/simulate?{key}={value}")
        assert resp.status_code == 200, f"{key} rejected: {resp.get_json()}"
        assert resp.get_json()["params"][key] == pytest.approx(value)


def test_unknown_param_is_rejected(client):
    resp = client.get("/simulate?not_a_real_param=1")
    assert resp.status_code == 400
    assert "not_a_real_param" in resp.get_json()["error"]


def test_non_numeric_param_is_rejected(client):
    resp = client.get("/simulate?Pheat=not_a_number")
    assert resp.status_code == 400
    assert "Pheat" in resp.get_json()["error"]


def test_invalid_date_is_rejected(client):
    resp = client.get("/simulate?start_date=not-a-date")
    assert resp.status_code == 400
    assert "start_date" in resp.get_json()["error"]


def test_series_flag_includes_hourly_timeseries(client):
    resp = client.get("/simulate?series=true")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "serie_horaire" in body
    assert "Tair" in body["serie_horaire"]
    assert len(body["serie_horaire"]["Tair"]) > 0


def test_comfort_and_cost_params_affect_results(client):
    narrow = client.get("/simulate?t_confort_min=21&t_confort_max=22").get_json()
    wide = client.get("/simulate?t_confort_min=10&t_confort_max=35").get_json()
    assert narrow["resultats"]["heures_hors_confort"] >= wide["resultats"]["heures_hors_confort"]
