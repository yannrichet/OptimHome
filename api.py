"""API JSON pour le modele BuildingTherm — simulation a la demande.

Un seul endpoint, GET ou POST, sur /simulate :

- GET  : parametres passes en query string (?Pheat=6000&e_ite=0.20&...).
- POST : parametres passes en JSON dans le corps de la requete ; la query
  string (si presente) est appliquee par-dessus en surcharge.

Tous les parametres sont optionnels : tout parametre du modele physique
absent de la requete garde sa valeur par defaut (BuildingTherm.DEFAULT_PARAMS,
la meme que celle utilisee par l'app Streamlit). C'est le contrat de
`BuildingTherm.simulate()` (merge sur DEFAULT_PARAMS) qui garantit ce
comportement, pas une logique dupliquee ici.

Utilise uniquement le solveur pur Python (BuildingTherm.py, cf. README) : pas
d'appel au binaire OpenModelica compile depuis cette API — eviter d'exposer
un subprocess construit a partir d'entrees reseau, et le solveur Python est
deja valide a moins de 0.02 K de l'OpenModelica de reference (voir
tests/test_python_solver_matches_openmodelica.py).

Lancer en dev : python api.py  (sert sur :8000)
En prod : gunicorn -w 2 -b 0.0.0.0:8000 api:app
"""
import os
from datetime import date, timedelta

import pandas as pd
from flask import Flask, jsonify, request

import BuildingTherm as bt
from indicators import comfort_indicators
from weather import prepare_weather

app = Flask(__name__)

DEFAULT_LAT, DEFAULT_LON = 48.8566, 2.3522
WARMUP_DAYS = 14

# Parametres hors modele physique (meteo/periode, bande de confort, cout) —
# memes valeurs par defaut que les sliders de app.py.
META_PARAM_NAMES = {
    "lat", "lon", "start_date", "end_date",
    "t_confort_min", "t_confort_max", "tolerance", "prix_elec", "prix_rachat_pv", "series",
}


def _merged_request_params():
    """JSON poste (POST) fusionne avec la query string (GET, ou surcharge sur POST)."""
    merged = {}
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            merged.update(body)
    merged.update(request.args.to_dict())
    return merged


def _parse_float(raw, name):
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"paramètre '{name}' invalide (attendu un nombre) : {raw!r}")


def _parse_date(raw, name, fallback):
    if raw in (None, ""):
        return fallback
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise ValueError(f"paramètre '{name}' invalide (attendu AAAA-MM-JJ) : {raw!r}")


def _parse_bool(raw, default=False):
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@app.route("/", methods=["GET"])
def index():
    return jsonify(
        description="API de simulation d'équilibre thermique d'habitation (BuildingTherm).",
        endpoint="/simulate",
        methods=["GET", "POST"],
        parametres_modele=dict(sorted(bt.DEFAULT_PARAMS.items())),
        parametres_meteo={"lat": DEFAULT_LAT, "lon": DEFAULT_LON,
                           "start_date": "AAAA-MM-JJ (defaut: aujourd'hui - 364 j)",
                           "end_date": "AAAA-MM-JJ (defaut: aujourd'hui)"},
        parametres_confort_cout={"t_confort_min": 19.0, "t_confort_max": 26.0, "tolerance": 1.0,
                                  "prix_elec": 0.2516, "prix_rachat_pv": 0.04},
        options={"series": "false — inclure la série horaire complète dans la réponse"},
    )


@app.route("/simulate", methods=["GET", "POST"])
def simulate():
    try:
        raw = _merged_request_params()

        params = {}
        for key in bt.DEFAULT_PARAMS:
            if key in raw:
                params[key] = _parse_float(raw[key], key)

        unknown = set(raw) - set(bt.DEFAULT_PARAMS) - META_PARAM_NAMES
        if unknown:
            raise ValueError(f"paramètre(s) inconnu(s) : {', '.join(sorted(unknown))}")

        lat = _parse_float(raw.get("lat", DEFAULT_LAT), "lat")
        lon = _parse_float(raw.get("lon", DEFAULT_LON), "lon")
        end_date = _parse_date(raw.get("end_date"), "end_date", date.today())
        start_date = _parse_date(raw.get("start_date"), "start_date", end_date - timedelta(days=364))
        if end_date < start_date:
            start_date, end_date = end_date, start_date

        t_confort_min = _parse_float(raw.get("t_confort_min", 19.0), "t_confort_min")
        t_confort_max = _parse_float(raw.get("t_confort_max", 26.0), "t_confort_max")
        tolerance = _parse_float(raw.get("tolerance", 1.0), "tolerance")
        prix_elec = _parse_float(raw.get("prix_elec", 0.2516), "prix_elec")
        prix_rachat_pv = _parse_float(raw.get("prix_rachat_pv", 0.04), "prix_rachat_pv")
        include_series = _parse_bool(raw.get("series"))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    try:
        weather_path, stop_time = prepare_weather(lat, lon, start_date, end_date, warmup_days=WARMUP_DAYS)
        rows = bt.run_simulation(params, weather_path, stop_time)
    except Exception as e:
        return jsonify(error=f"échec de la simulation : {e}"), 502

    sim = pd.DataFrame(rows)
    warmup_hours = WARMUP_DAYS * 24
    sim_p = sim.iloc[warmup_hours:] if len(sim) > warmup_hours else sim
    Tint_period = sim_p["Tair"] - 273.15
    heures_hors_confort, dh_froid, dh_chaleur = comfort_indicators(
        Tint_period, t_confort_min, t_confort_max, tolerance=tolerance)

    egrid_total = float(sim["Egrid_total"].iloc[-1])
    eself_cool = float(sim["Eself_cool"].iloc[-1])
    eexport = float(sim["Eexport"].iloc[-1])
    cout_net_eur = egrid_total * prix_elec - eexport * prix_rachat_pv

    response = {
        "params": dict(bt.DEFAULT_PARAMS, **params),
        "meteo": {"lat": lat, "lon": lon,
                  "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
                  "warmup_days": WARMUP_DAYS},
        "confort_cout": {"t_confort_min": t_confort_min, "t_confort_max": t_confort_max, "tolerance": tolerance,
                          "prix_elec": prix_elec, "prix_rachat_pv": prix_rachat_pv},
        "resultats": {
            "temp_min_C": round(float(Tint_period.min()), 2),
            "temp_max_C": round(float(Tint_period.max()), 2),
            "heures_hors_confort": heures_hors_confort,
            "degres_heures_froid_Kh": round(float(dh_froid), 2),
            "degres_heures_chaleur_Kh": round(float(dh_chaleur), 2),
            "conso_nette_kWh": round(egrid_total, 2),
            "autoconso_pv_kWh": round(eself_cool, 2),
            "export_pv_kWh": round(eexport, 2),
            "cout_net_eur": round(cout_net_eur, 2),
        },
    }
    if include_series:
        response["serie_horaire"] = sim.to_dict(orient="list")

    return jsonify(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
