"""Equilibre thermique d'habitation — simulation Modelica interactive.

Fait tourner le modele Modelica compile (binaire BuildingOpt) avec les
parametres de conception choisis par l'utilisateur (chauffage, froid, PV,
cout en euro, materiau de mur, geometrie parametrable et localisation/dates
dynamiques) et affiche le plot temporel correspondant (temperatures +
puissances journalieres), en Plotly interactif.

La meteo horaire reelle (temperature + irradiance globale horizontale)
est telechargee depuis l'API Open-Meteo (ERA5, archive-api.open-meteo.com)
pour la position et la plage de dates choisies, a chaque changement de
l'un de ces deux selecteurs. Cette API ne demande pas de cle et couvre les
donnees reelles (aucune prevision) de 1950 jusqu'a la date du jour.

Lancer avec : streamlit run app.py
"""
import hashlib
import os
import signal
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta

import fz
import folium
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_folium import st_folium
from streamlit_geolocation import streamlit_geolocation

WORK = os.path.dirname(os.path.abspath(__file__))
FZR_DIR = os.path.join(WORK, "app_fzr")
FZR_PARAMS = os.path.join(FZR_DIR, "params.txt")
FZR_CALCULATOR = f"sh://{os.path.join(FZR_DIR, 'run.sh')}"
FZ_MODEL = {
    "varprefix": "$", "formulaprefix": "@", "delim": "{}", "commentline": "#",
    "output": {
        "time": "python://csv_file('res.csv', column='time')",
        "Tair": "python://csv_file('res.csv', column='Tair')",
        "Tout": "python://csv_file('res.csv', column='Tout')",
        "Qheat": "python://csv_file('res.csv', column='Qheat')",
        "Pgrid_cool": "python://csv_file('res.csv', column='Pgrid_cool')",
        "Pself_cool": "python://csv_file('res.csv', column='Pself_cool')",
        "Egrid_cool_last": "python://csv_file('res.csv', column='Egrid_cool')[-1]",
        "Eself_cool_last": "python://csv_file('res.csv', column='Eself_cool')[-1]",
        "Eexport_last": "python://csv_file('res.csv', column='Eexport')[-1]",
    },
}
WARMUP_DAYS = 14
WARMUP_HOURS = WARMUP_DAYS * 24


@contextmanager
def _fzr_outside_main_thread():
    """fz.fzr() installe un handler SIGINT via signal.signal(), qui n'est
    valide que dans le thread principal de l'interpreteur principal. Streamlit
    execute le script dans un thread de travail (ScriptRunner), pas le thread
    principal : on neutralise temporairement signal.signal() pour eviter le
    ValueError "signal only works in main thread of the main interpreter"."""
    original_signal = signal.signal
    signal.signal = lambda *a, **k: None
    try:
        yield
    finally:
        signal.signal = original_signal

DEFAULT_LAT, DEFAULT_LON = 48.8566, 2.3522
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
DATE_UI_MIN = date(1950, 1, 15)
DATE_UI_MAX = date.today()  # aucune prevision : donnees reelles uniquement, jusqu'a aujourd'hui
DEFAULT_END = DATE_UI_MAX
DEFAULT_START = DEFAULT_END - timedelta(days=364)

# lam [W/m.K], rhoc [J/m3.K], epaisseur par defaut [m] — valeurs indicatives
MATERIAUX = {
    "Parpaing (bloc béton creux)": dict(lam=0.95, rhoc=1300 * 1000, e=0.20),
    "Brique pleine (ancienne)": dict(lam=0.84, rhoc=1700 * 840, e=0.22),
    "Brique creuse (moderne, perforée)": dict(lam=0.45, rhoc=900 * 840, e=0.20),
    "Meulière (pierre, Île-de-France)": dict(lam=1.70, rhoc=2200 * 1000, e=0.45),
    "Moellon (pierre calcaire appareillée)": dict(lam=1.40, rhoc=2000 * 1000, e=0.40),
}


@st.cache_data(show_spinner=False)
def fetch_open_meteo_range(lat: float, lon: float, start_date: date, end_date: date) -> pd.DataFrame:
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


@st.cache_data(show_spinner="Téléchargement météo Open-Meteo…")
def prepare_weather(lat: float, lon: float, start_date: date, end_date: date):
    """Fenetre meteo horaire reelle (mise en regime + periode choisie), ecrite
    au format CombiTimeTable dans un fichier stable (cache disque par site+dates)."""
    fetch_start = start_date - timedelta(days=WARMUP_DAYS)
    win = fetch_open_meteo_range(round(lat, 3), round(lon, 3), fetch_start, end_date)
    if win.empty:
        raise RuntimeError("Aucune donnée météo Open-Meteo pour cette position/période.")

    key = f"{lat:.3f}_{lon:.3f}_{start_date}_{end_date}"
    h = hashlib.md5(key.encode()).hexdigest()[:16]
    weather_path = os.path.join(tempfile.gettempdir(), f"buildingopt_weather_{h}.txt")
    with open(weather_path, "w") as f:
        f.write("#1\n")
        f.write(f"double tmy({len(win)},3)\n")
        for i, row in enumerate(win.itertuples()):
            f.write(f"{i * 3600} {row.Tout_C + 273.15:.2f} {max(row.Gh, 0.0):.1f}\n")

    stop_time = (len(win) - 1) * 3600
    return weather_path, stop_time


st.set_page_config(page_title="Equilibre thermique d'habitation", layout="wide")

st.title("Equilibre thermique d'habitation")
st.caption(
    "Modele Modelica `BuildingOpt.mo` (mur tricouche ITE/ITI, PV en "
    "autoconsommation). Paramètres de conception, PV, coût €, matériau de mur, "
    "géométrie et météo réelle (Open-Meteo) dynamique."
)

if "lat" not in st.session_state:
    st.session_state["lat"] = DEFAULT_LAT
    st.session_state["lon"] = DEFAULT_LON

page_col_left, page_col_right = st.columns([1, 2])

with page_col_left:
    with st.container(height=850):
        st.subheader("Localisation et période météo")
        st.caption(
            "Position du site (clic sur la carte, ou géolocalisation navigateur) "
            "et plage de dates : la météo réelle horaire (Open-Meteo) est retéléchargée "
            "dès que l'une des deux change."
        )
        m = folium.Map(location=[st.session_state["lat"], st.session_state["lon"]], zoom_start=11)
        folium.Marker([st.session_state["lat"], st.session_state["lon"]], tooltip="Bâtiment").add_to(m)
        map_data = st_folium(m, height=280, use_container_width=True, key="site_map")
        if map_data and map_data.get("last_clicked"):
            new_lat, new_lon = map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]
            if (new_lat, new_lon) != (st.session_state["lat"], st.session_state["lon"]):
                st.session_state["lat"] = new_lat
                st.session_state["lon"] = new_lon
                st.rerun()

        geoloc = streamlit_geolocation()
        if geoloc and geoloc.get("latitude"):
            st.session_state["lat"] = geoloc["latitude"]
            st.session_state["lon"] = geoloc["longitude"]
        st.write(f"**Latitude** : {st.session_state['lat']:.4f} — **Longitude** : {st.session_state['lon']:.4f}")

        date_col1, date_col2 = st.columns(2)
        date_start = date_col1.date_input(
            "Date de début", value=DEFAULT_START,
            min_value=DATE_UI_MIN, max_value=DATE_UI_MAX,
        )
        date_end = date_col2.date_input(
            "Date de fin", value=DEFAULT_END,
            min_value=DATE_UI_MIN, max_value=DATE_UI_MAX,
        )
        if date_end < date_start:
            date_start, date_end = date_end, date_start
        st.caption(
            f"Météo réelle Open-Meteo (ERA5), aucune prévision : dates limitées à "
            f"aujourd'hui ({DATE_UI_MAX:%d/%m/%Y}). 14 j supplémentaires sont téléchargés "
            f"avant la date de début pour la mise en régime."
        )

        st.divider()
        st.header("Variables de conception")
        ach_day = st.slider("ach_day — aération naturelle diurne [vol/h]", 0.5, 4.0, 1.5, step=0.1)
        ach_night = st.slider("ach_night — surventilation nocturne électrique [vol/h]", 0.0, 6.0, 2.0, step=0.1)

        st.divider()
        st.header("Géométrie (parallélépipède, emprise ≈ carré)")
        Sfloor = st.slider("Sfloor — surface au sol (emprise) [m²]", 15, 200, 40, step=1)
        Htot = st.slider("Htot — hauteur totale du bâtiment [m]", 2.5, 15.0, 7.5, step=0.5)

        st.divider()
        st.header("Matériau du mur (couche structurelle)")
        materiau = st.selectbox("Matériau", list(MATERIAUX.keys()))
        mat = MATERIAUX[materiau]
        e_blk_cm = st.slider("Épaisseur du mur structurel [cm]", 10.0, 60.0, mat["e"] * 100, step=1.0)
        st.dataframe(
            pd.DataFrame(
                {"λ [W/m.K]": {k: v["lam"] for k, v in MATERIAUX.items()}}
            ).style.apply(
                lambda col: ["font-weight: bold" if idx == materiau else "" for idx in col.index]
            ),
            use_container_width=True,
        )

        st.divider()
        st.header("Bande de confort")
        T_confort_min = st.slider("Température confort min (consigne chauffage) [°C]", 15.0, 22.0, 19.0, step=0.5)
        T_confort_max = st.slider("Température confort max (consigne froid) [°C]", 23.0, 30.0, 26.0, step=0.5)

        st.divider()
        st.header("Coût de l'énergie")
        prix_elec = st.slider("Prix électricité importée [€/kWh]", 0.05, 0.40, 0.2516, step=0.001)
        prix_rachat_pv = st.slider("Tarif de rachat du surplus PV [€/kWh]", 0.00, 0.20, 0.04, step=0.005)

        st.divider()
        st.header("Paramètres physiques (nominaux)")
        lam_iso = st.slider("lam_iso — conductivité isolant [W/m.K]", 0.030, 0.045, 0.036, step=0.001)
        ach = st.slider("ach — renouvellement d'air hygiénique [vol/h]", 0.3, 1.0, 0.6, step=0.05)
        Qint = st.slider("Qint — apports internes moyens [W]", 100, 700, 400, step=10)
        dTout = st.slider("dTout — décalage climatique [K]", -2.0, 3.0, 1.0, step=0.1)
        fsol = st.slider("fsol — facteur solaire vitrage x occultations [-]", 0.1, 0.7, 0.5, step=0.01)
        seer = st.slider("seer — SEER de la PAC [-]", 2.5, 5.0, 3.5, step=0.1)


    @st.cache_data(show_spinner="Simulation Modelica en cours (fzr)…")
    def run_simulation(params: dict, weather_path: str, stop_time: int) -> pd.DataFrame:
        """Execute le modele via fz.fzr (calculateur sh://app_fzr/run.sh), qui
        invoque le binaire BuildingOpt compile avec les parametres/meteo/duree
        du cas courant. Le cas est identifie par un hash court (case_id) : les
        vraies valeurs (potentiellement longues, avec des '/') transitent par
        un fichier d'environnement plutot que par les variables fz elles-memes,
        pour eviter que fzr ne les injecte telles quelles dans le nom du
        dossier de resultats (limite de 255 caracteres par composant de chemin)."""
        override = f"tmy.fileName={weather_path}," + ",".join(f"{k}={v}" for k, v in params.items())
        case_id = hashlib.md5(f"{override}|{stop_time}".encode()).hexdigest()[:16]
        env_path = os.path.join(tempfile.gettempdir(), f"buildingopt_case_{case_id}.sh")
        with open(env_path, "w") as f:
            f.write(f'OV="{override}"\nSTARTT="0"\nSTOPT="{stop_time}"\n')

        with tempfile.TemporaryDirectory() as results_dir, _fzr_outside_main_thread():
            result = fz.fzr(FZR_PARAMS, {"case_id": case_id}, FZ_MODEL,
                             results_dir=results_dir, calculators=[FZR_CALCULATOR])
        row = result.iloc[0]
        if row.get("status") != "done":
            raise RuntimeError(f"Simulation fzr échouée:\n{row.get('error')}\n{row.get('stderr')}")

        # OpenModelica ecrit plusieurs lignes quasi simultanees autour des
        # evenements (rampes de ventilation) : meme heure nominale, valeurs
        # avant/apres evenement. On reduit a une ligne par heure (derniere
        # valeur = etat stabilise apres evenement), sans quoi l'indexation
        # horaire naive desynchronise tout le reste de la serie.
        raw = pd.DataFrame({
            "time": row["time"], "Tair": row["Tair"], "Tout": row["Tout"], "Qheat": row["Qheat"],
            "Pgrid_cool": row["Pgrid_cool"], "Pself_cool": row["Pself_cool"],
        })
        raw["hour"] = (raw["time"] / 3600).round().astype(int)
        sim = raw.groupby("hour", as_index=False).last()
        sim["time"] = sim["hour"] * 3600
        sim = sim.drop(columns="hour")
        sim["Egrid_cool"] = row["Egrid_cool_last"]
        sim["Eself_cool"] = row["Eself_cool_last"]
        sim["Eexport"] = row["Eexport_last"]
        return sim


with page_col_right:

    slider_col1, slider_col2, slider_col3, slider_col4, slider_col5 = st.columns(5)
    Pheat = slider_col1.slider("Pheat — chauffage [W]", 1000, 12000, 8000, step=100)
    Pcool = slider_col2.slider("Pcool — froid PAC [W]", 0, 6000, 2000, step=50)
    Ppv_kWc = slider_col3.slider("PV crête [kWc]", 0.0, 9.0, 3.0, step=0.1)
    e_ite_cm = slider_col4.slider("e_ite — ITE [cm]", 0.0, 30.0, 16.0, step=0.5)
    e_iti_cm = slider_col5.slider("e_iti — ITI [cm]", 0.0, 20.0, 0.0, step=0.5)

    params = {
        "Pheat": Pheat, "Pcool": Pcool, "ach_day": ach_day, "ach_night": ach_night,
        "e_ite": e_ite_cm / 100.0, "e_iti": e_iti_cm / 100.0,
        "Ppv_kWc": Ppv_kWc,
        "Sfloor": Sfloor, "Htot": Htot,
        "lam_blk": mat["lam"], "rhoc_blk": mat["rhoc"], "e_blk": e_blk_cm / 100.0,
        "lam_iso": lam_iso, "ach": ach, "Qint": Qint, "dTout": dTout,
        "fsol": fsol, "seer": seer,
        "Tset_h": T_confort_min + 273.15, "Tset_c": T_confort_max + 273.15,
    }

    try:
        weather_path, stop_time = prepare_weather(
            st.session_state["lat"], st.session_state["lon"], date_start, date_end
        )
        sim = run_simulation(params, weather_path, stop_time)
    except Exception as e:
        st.error(str(e))
        st.stop()

    sim_p = sim.iloc[WARMUP_HOURS:].reset_index(drop=True)
    jours = (sim_p["time"] - sim_p["time"].iloc[0]) / 86400
    jour_idx = jours.astype(int)

    daily = pd.DataFrame({
        "jour": jour_idx,
        "Tint_min": sim_p["Tair"] - 273.15,
        "Tint_max": sim_p["Tair"] - 273.15,
        "Text_min": sim_p["Tout"] - 273.15,
        "Text_max": sim_p["Tout"] - 273.15,
    }).groupby("jour").agg({
        "Tint_min": "min", "Tint_max": "max", "Text_min": "min", "Text_max": "max",
    })
    kW_grid = (sim_p["Pgrid_cool"] / 1000).groupby(jour_idx).mean()
    kW_pv_self = (sim_p["Pself_cool"] / 1000).groupby(jour_idx).mean()
    dates_x = [date_start + timedelta(days=int(d)) for d in daily.index]

    # ---------------------------------------------------------------------------
    # Indicateurs sur la periode choisie + coût en euros
    # ---------------------------------------------------------------------------
    n_days = (date_end - date_start).days + 1
    periode_label = "kWh/an" if 360 <= n_days <= 370 else f"kWh/{n_days}j"

    Tmin_hiver = sim_p["Tair"].min() - 273.15
    Tmax_ete = sim_p["Tair"].max() - 273.15
    Egrid_cool = sim["Egrid_cool"].iloc[-1]  # import reseau NET, chauffage+froid, apres autoconso PV
    Eself_cool = sim["Eself_cool"].iloc[-1]  # autoconsommation PV directe, chauffage+froid
    Eexport = sim["Eexport"].iloc[-1]
    Conso_nette = Egrid_cool  # deja net de l'autoconso PV (chauffage compris)
    Cout_net_eur = Conso_nette * prix_elec - Eexport * prix_rachat_pv

    Text_min_period = sim_p["Tout"].min() - 273.15
    Text_max_period = sim_p["Tout"].max() - 273.15

    # ---------------------------------------------------------------------------
    # Plot temporel Plotly (bande de confort + bandes min-max de temperature +
    # puissances empilees)
    # ---------------------------------------------------------------------------
    fig = go.Figure()

    # bande de confort, en fond
    fig.add_hrect(y0=T_confort_min, y1=T_confort_max, fillcolor="rgba(46,160,67,0.12)", line_width=0,
                  annotation_text=f"confort {T_confort_min:.0f}–{T_confort_max:.0f} °C", annotation_position="top left")

    # temperatures min/max journalieres, en lignes visibles (interieur/exterieur)
    fig.add_trace(go.Scatter(
        x=dates_x, y=daily["Text_max"], mode="lines",
        line=dict(width=1.2, color="rgba(120,120,120,0.9)"),
        name="T extérieure max/j",
    ))
    fig.add_trace(go.Scatter(
        x=dates_x, y=daily["Text_min"], mode="lines",
        line=dict(width=1.2, color="rgba(120,120,120,0.9)", dash="dot"),
        fill="tonexty", fillcolor="rgba(120,120,120,0.25)",
        name="T extérieure min/j",
    ))
    fig.add_trace(go.Scatter(
        x=dates_x, y=daily["Tint_max"], mode="lines",
        line=dict(width=1.2, color="rgba(31,119,180,0.9)"),
        name="T intérieure max/j",
    ))
    fig.add_trace(go.Scatter(
        x=dates_x, y=daily["Tint_min"], mode="lines",
        line=dict(width=1.2, color="rgba(31,119,180,0.9)", dash="dot"),
        fill="tonexty", fillcolor="rgba(31,119,180,0.3)",
        name="T intérieure min/j",
    ))

    fig.add_trace(go.Scatter(
        x=dates_x, y=kW_grid.values, mode="lines", name="Import réseau — conso (chauf.+froid) [kW]",
        stackgroup="power", yaxis="y2", line=dict(color="rgba(214,39,40,0.9)", width=0.5),
        fillcolor="rgba(214,39,40,0.35)",
    ))
    fig.add_trace(go.Scatter(
        x=dates_x, y=kW_pv_self.values, mode="lines", name="Autoconso PV (chauf.+froid) [kW]",
        stackgroup="power", yaxis="y2", line=dict(color="rgba(255,127,14,0.9)", width=0.5),
        fillcolor="rgba(255,127,14,0.35)",
    ))

    fig.update_layout(
        xaxis=dict(title=f"Date — météo réelle Open-Meteo ({st.session_state['lat']:.2f}, {st.session_state['lon']:.2f})"),
        yaxis=dict(title="Température [°C]"),
        yaxis2=dict(title="Puissance moyenne/j [kW]", overlaying="y", side="right", rangemode="tozero"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=550,
        margin=dict(l=60, r=60, t=40, b=50),
        hovermode="x unified",
    )

    st.plotly_chart(fig, use_container_width=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("T min période", f"{Tmin_hiver:.1f} °C")
    c2.metric("T max période", f"{Tmax_ete:.1f} °C")
    c3.metric("Conso nette (chauf.+froid après PV)", f"{Conso_nette:.0f} {periode_label}")
    c4.metric("Autoconso PV (chauf.+froid)", f"{Eself_cool:.0f} {periode_label}")
    c5.metric("Coût net (période)", f"{Cout_net_eur:.0f} €")

    if Tmin_hiver < T_confort_min or Tmax_ete > T_confort_max:
        st.warning(
            f"Hors bande de confort [{T_confort_min:.0f}–{T_confort_max:.0f} °C] : "
            f"Tmin={Tmin_hiver:.1f} °C, Tmax={Tmax_ete:.1f} °C."
        )
