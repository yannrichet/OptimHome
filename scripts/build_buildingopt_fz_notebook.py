"""One-off script that generates BuildingOpt_fz.ipynb from scratch via nbformat.

Not part of the app/test suite: run manually whenever BuildingOpt_fz.ipynb
needs to be regenerated (e.g. after editing this script), then delete or
re-run — it always overwrites the target file.
"""
import nbformat as nbf

nb = nbf.v4.new_notebook()
nb.metadata = {
    "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
    "language_info": {
        "codemirror_mode": {"name": "ipython", "version": 3},
        "file_extension": ".py", "mimetype": "text/x-python", "name": "python",
        "nbconvert_exporter": "python", "pygments_lexer": "ipython3", "version": "3.12.10",
    },
}

cells = []


def md(src):
    cells.append(nbf.v4.new_markdown_cell(src))


def code(src):
    cells.append(nbf.v4.new_code_cell(src))


# ---------------------------------------------------------------------------
md(r"""# Optimisation multi-objectif (NSGA-II via `fz`) — Équilibre thermique d'habitation

Variante de [`BuildingOpt.ipynb`](BuildingOpt.ipynb) qui utilise
[`fz`](https://github.com/Funz/fz) **autant que possible** au lieu de
`pymoo` : le plan d'expérience/optimisation multi-objectif (NSGA-II) est
piloté par `fz.fzd()`, avec le modèle physique appelé directement comme une
fonction Python (aucun fichier d'entrée/sortie, aucun calculateur externe
pour le solveur pur Python) — et le solveur OpenModelica optionnel appelle
lui aussi le binaire compilé via `fz.fzr()` plutôt qu'un `subprocess` brut.

**Nécessite la branche `main` de `fz` sur GitHub, pas la version publiée sur
PyPI** : le mode « modèle = fonction Python » et les objectifs
multi-scalaires (vecteur d'expressions de sortie, requis pour NSGA-II) sont
des fonctionnalités récentes, pas encore publiées sur PyPI au moment de
l'écriture de ce notebook. La cellule d'installation ci-dessous installe
`fz` directement depuis GitHub (`pip install git+...@main`).

Le reste du notebook :

- optimise les **mêmes 5 variables de conception** que les curseurs mis en avant dans l'app
  (Chauffage, Climatisation, Photovolt., Isolation ext., Isolation int.) ;
- calcule les **mêmes 3 indicateurs de sortie** que l'app (degrés-heures de manque de
  chauffage, degrés-heures d'excès de chaleur, coût €) ;
- lance **NSGA-II** — non pas `pymoo`, mais l'algorithme d'exemple
  [`nsga2.py`](https://github.com/Funz/fz/blob/main/examples/algorithms/nsga2.py)
  fourni par `fz` lui-même (pure stdlib, aucune dépendance numpy), branché
  sur `fz.fzd()` via son support natif d'objectifs vectoriels ;
- **regroupe** (k-means, `scikit-learn` — `fz` n'a pas d'algorithme de
  clustering, ce post-traitement reste inchangé) le front de Pareto obtenu
  en **N scénarios représentatifs** (5 par défaut) et affiche pour chacun le
  même graphique temporel que l'app.

Voir le [dépôt GitHub](https://github.com/yannrichet/OptimHome) et le
[README](https://github.com/yannrichet/OptimHome#readme) pour le contexte complet
(modèle physique, app Streamlit, solveur de secours).""")

# ---------------------------------------------------------------------------
md(r"""## 0. Installation (Google Colab) et récupération du modèle

Sur Colab, cette cellule installe les dépendances Python qui manquent —
dont `fz` depuis la branche `main` de GitHub, pas PyPI (voir ci-dessus) — et
télécharge `BuildingTherm.py`, `indicators.py` ainsi que l'algorithme
NSGA-II de `fz` (le notebook reste autonome : pas besoin de cloner ni
`OptimHome` ni `fz`). En local, si ces fichiers sont déjà présents et que
`fz` est déjà installé (par ex. en editable depuis un clone de `fz` sur
`main`), tout est simplement ignoré.""")

# ---------------------------------------------------------------------------
code(r'''import sys, subprocess, importlib.util, urllib.request

IN_COLAB = "google.colab" in sys.modules

if IN_COLAB:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "git+https://github.com/Funz/fz.git@main",
         "scikit-learn", "plotly", "pandas", "numpy", "scipy", "requests"],
        check=True,
    )

if importlib.util.find_spec("BuildingTherm") is None:
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/yannrichet/OptimHome/main/BuildingTherm.py",
        "BuildingTherm.py",
    )
if importlib.util.find_spec("indicators") is None:
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/yannrichet/OptimHome/main/indicators.py",
        "indicators.py",
    )

print("BuildingTherm.py + indicators.py téléchargés (importés plus loin).")
''')

# ---------------------------------------------------------------------------
md(r"""## 0bis. Choix du solveur

Deux options, comme dans l'app Streamlit :

- `"python"` (par défaut) — [`BuildingTherm.py`](BuildingTherm.py), pur Python
  (`scipy.integrate.solve_ivp`, méthode `BDF`). Aucune installation, portable
  partout (Colab compris), ~3 s par simulation annuelle. Fidélité validée à
  ~0.02 % près par rapport à OpenModelica (voir le
  [README](https://github.com/yannrichet/OptimHome#solveur-de-secours-python-buildingthermpy)).
  Appelé directement comme fonction Python par `fz.fzd()` (aucun calculateur
  externe nécessaire pour ce chemin).
- `"openmodelica"` — compile et exécute le vrai modèle
  [`BuildingTherm.mo`](BuildingTherm.mo) via `omc`, puis exécute le binaire
  compilé via `fz.fzr()` (même calculateur `sh://app_fzr/run.sh` que
  `app.py`) plutôt qu'un `subprocess` direct. Solveur DAE de référence
  (DASSL), généralement plus rapide *par simulation* une fois compilé, mais
  **installation d'OpenModelica sur Colab lente (~2-4 min)** et non garantie
  selon l'image Colab du moment.

Change simplement la valeur ci-dessous ; le reste du notebook s'adapte
automatiquement.""")

# ---------------------------------------------------------------------------
code('SOLVER = "python"   # "python" ou "openmodelica"\n')

# ---------------------------------------------------------------------------
md(r"""### Installation d'OpenModelica (uniquement si `SOLVER = "openmodelica"`)

Cellule sans effet si `SOLVER = "python"`. Sur Colab (Ubuntu), installe `omc`
depuis le dépôt APT officiel d'OpenModelica, compile `BuildingTherm.mo`
(téléchargé depuis GitHub si absent) en un binaire — exactement comme
`build.mos` le fait dans le dépôt — et récupère `app_fzr/run.sh` +
`app_fzr/params.txt` (le calculateur `fz` que ce notebook réutilise tel
quel depuis `app.py`).""")

# ---------------------------------------------------------------------------
code(r'''import os
import shutil

if SOLVER == "openmodelica":
    if shutil.which("omc") is None:
        print("Installation d'OpenModelica (peut prendre 2-4 min)...")
        codename = subprocess.run(["lsb_release", "-cs"], capture_output=True, text=True).stdout.strip()
        subprocess.run(
            f"echo 'deb http://build.openmodelica.org/apt {codename} release' "
            "| sudo tee /etc/apt/sources.list.d/openmodelica.list",
            shell=True, check=True,
        )
        subprocess.run(
            "curl -fsSL http://build.openmodelica.org/apt/openmodelica.asc | sudo apt-key add -",
            shell=True, check=True,
        )
        subprocess.run("sudo apt-get update -qq", shell=True, check=True)
        subprocess.run("sudo apt-get install -y -qq --no-install-recommends omc", shell=True, check=True)
        print("OpenModelica installé.")
    else:
        print(f"omc déjà disponible : {shutil.which('omc')}")

    if not os.path.exists("BuildingTherm.mo"):
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/yannrichet/OptimHome/main/BuildingTherm.mo",
            "BuildingTherm.mo",
        )
    with open("build_nb.mos", "w") as f:
        f.write('loadModel(Modelica); getErrorString();\n')
        f.write('loadFile("BuildingTherm.mo"); getErrorString();\n')
        f.write(
            'buildModel(BuildingTherm, outputFormat="csv", '
            'variableFilter="time|Eheat|Ecool|Egrid_total|Eself_cool|Eexport|Tair|Tout|Qheat|Pelec|Ppv|Pself_cool|Pgrid_cool"); '
            'getErrorString();\n'
        )
    subprocess.run(["omc", "build_nb.mos"], check=True)
    print("Binaire BuildingTherm compilé.")

    if not os.path.exists("app_fzr/run.sh"):
        os.makedirs("app_fzr", exist_ok=True)
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/yannrichet/OptimHome/main/app_fzr/run.sh",
            "app_fzr/run.sh",
        )
        os.chmod("app_fzr/run.sh", 0o755)
        urllib.request.urlretrieve(
            "https://raw.githubusercontent.com/yannrichet/OptimHome/main/app_fzr/params.txt",
            "app_fzr/params.txt",
        )
        print("app_fzr/ (calculateur fz) récupéré.")
else:
    print("SOLVER='python' : aucune installation supplémentaire nécessaire.")
''')

# ---------------------------------------------------------------------------
md(r"""## 1. Météo réelle (Open-Meteo)

Même source et même API que l'app (`archive-api.open-meteo.com`, réanalyse ERA5,
sans clé). Position et période par défaut ci-dessous — à changer librement.
Le fichier `weather_nb.txt` n'est écrit que pour le solveur OpenModelica
(`CombiTimeTable` lit un fichier ; le solveur Python prend les tableaux
directement en mémoire).""")

# ---------------------------------------------------------------------------
code(r'''import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import date, timedelta

import BuildingTherm as bt
from indicators import capex_estimate, comfort_indicators

LAT, LON = 48.8566, 2.3522          # Paris par défaut ; change librement
END_DATE = date.today() - timedelta(days=1)  # Open-Meteo n'a pas encore les donnees d'aujourd'hui (decalage d'archivage)
START_DATE = END_DATE - timedelta(days=364)
WARMUP_DAYS = 14                     # mise en régime, comme dans l'app


def fetch_weather(lat, lon, start_date, end_date, warmup_days=WARMUP_DAYS):
    """(times, Tout_K, Gh) horaires, même format que BuildingTherm.load_weather_table."""
    fetch_start = start_date - timedelta(days=warmup_days)
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={"latitude": lat, "longitude": lon,
                "start_date": fetch_start.isoformat(), "end_date": end_date.isoformat(),
                "hourly": "temperature_2m,shortwave_radiation", "timezone": "UTC"},
        timeout=60,
    )
    r.raise_for_status()
    h = r.json()["hourly"]
    Tout_K = np.array(h["temperature_2m"]) + 273.15
    Gh = np.maximum(np.array(h["shortwave_radiation"]), 0.0)
    times = np.arange(len(Tout_K)) * 3600.0
    return times, Tout_K, Gh


def write_weather_file(weather, path):
    """Meme format texte que celui ecrit par app.py (table CombiTimeTable)."""
    times, Tout_K, Gh = weather
    with open(path, "w") as f:
        f.write("#1\n")
        f.write(f"double tmy({len(times)},3)\n")
        for t, tk, g in zip(times, Tout_K, Gh):
            f.write(f"{t:.0f} {tk:.2f} {max(g, 0.0):.1f}\n")


weather = fetch_weather(LAT, LON, START_DATE, END_DATE)
stop_time = (len(weather[0]) - 1) * 3600.0
print(f"{len(weather[0])} points horaires ({stop_time/86400:.1f} j, dont {WARMUP_DAYS} j de mise en régime)")

WEATHER_PATH = os.path.abspath("weather_nb.txt")
if SOLVER == "openmodelica":
    write_weather_file(weather, WEATHER_PATH)
    print(f"Météo écrite dans {WEATHER_PATH}")
''')

# ---------------------------------------------------------------------------
md(r"""## 2. `fz` : installation vérifiée, modèle et algorithme récupérés

Vérifie que la version de `fz` installée est bien la branche `main`
(support du mode « modèle = fonction Python » et des objectifs vectoriels
requis pour NSGA-II — absents de la version publiée sur PyPI au moment de
l'écriture), puis télécharge l'algorithme NSGA-II d'exemple de `fz`
lui-même (aucune réimplémentation dans ce dépôt : c'est le code de
[Funz/fz](https://github.com/Funz/fz/blob/main/examples/algorithms/nsga2.py)
tel quel).""")

# ---------------------------------------------------------------------------
code(r'''import fz

_supports_function_model = hasattr(fz.core, "_normalize_function_model_result")
if not _supports_function_model:
    raise RuntimeError(
        f"fz {fz.__version__} ne supporte pas le mode 'model=fonction Python' ni les "
        "objectifs vectoriels requis par ce notebook (fonctionnalités de la branche "
        "main de fz, pas encore publiées sur PyPI). Réinstalle depuis GitHub main :\n"
        "  pip install -q --force-reinstall --no-deps git+https://github.com/Funz/fz.git@main"
    )

if not os.path.exists("nsga2.py"):
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/Funz/fz/main/examples/algorithms/nsga2.py",
        "nsga2.py",
    )

print(f"fz {fz.__version__} (branche main) — modèle=fonction Python + objectifs vectoriels OK.")
print("Algorithme NSGA-II (examples/algorithms/nsga2.py de fz) prêt.")
''')

# ---------------------------------------------------------------------------
md(r"""## 3. Variables de conception, objectifs, fonction de simulation

**Variables de conception** (5, mêmes bornes que les sliders de l'app) :
`Pheat` (Chauffage), `Pcool` (Climatisation), `Ppv_kWc` (Photovolt.),
`e_ite_cm` (Isolation ext.), `e_iti_cm` (Isolation int.).

**Objectifs** (4, mêmes indicateurs que l'app, tous à **minimiser**) — des degrés-heures
d'inconfort plutôt qu'un simple Tmin/Tmax : plus lisses pour NSGA-II (Tmin/Tmax sont des
statistiques d'ordre à gradient quasi partout nul ; une somme varie avec chaque variable de
conception), et plus représentatifs du vécu réel (un pic bref pèse moins qu'un dépassement
prolongé). Une tolérance de `DEFAULT_TOLERANCE_C` = 1 °C (`indicators.comfort_indicators()`,
défaut) élargit la bande de confort avant de compter un écart : un régulateur proportionnel
(pas PI, cf. `Kp`/`Kc` dans `BuildingTherm`) a toujours un léger écart de régime permanent,
qui croît avec les pertes thermiques du bâtiment — sans cette marge, un bâtiment mal isolé
compterait à tort des mois entiers comme "hors confort" pour un écart chronique de quelques
dixièmes de degré :
- **Froid·Heure** [K·h] : `Σ max(0, T_confort_min − tolérance − Tair_h)` sur toutes les
  heures de la période (après mise en régime) — degrés-heures sous la limite basse (≈ DJU
  horaires).
- **Chaleur·Heure** [K·h] : `Σ max(0, Tair_h − T_confort_max − tolérance)` — degrés-heures
  au-dessus de la limite haute.
- **Coût net** [€] : `Egrid_total·prix_elec − Eexport·prix_rachat_pv`, sur la période choisie
  (OPEX — cout d'exploitation, tous les postes comptent, finances ou non).
- **CAPEX** [€] : `indicators.capex_estimate()`, investissement estime pour les seuls postes
  marques comme a financer dans `CAPEX_FLAGS` (defaut : chauffage=0 et PV=0, deja en place ;
  climatisation=1, isolation ext.=1, isolation int.=1) — sans ce 4e objectif, le front de
  Pareto pousserait mecaniquement vers le sur-equipement, puisque OPEX seul ne penalise
  jamais un investissement plus gros.

`simulate_scenario()` appelle le solveur Python (directement) ou le binaire
OpenModelica (via `fz.fzr()`) selon `SOLVER`, mais renvoie dans les deux cas
un DataFrame avec les mêmes colonnes — tout le reste du notebook (objectifs,
graphiques) est indépendant du solveur choisi.

**`building_model()`** est la fonction passée telle quelle à `fz.fzd()`
comme modèle (section 4) : `fzd`, en mode « modèle = fonction Python »,
l'appelle directement avec les variables de conception en argument nommé
(`Pheat=...`, `Pcool=...`, etc. — les clés de `input_variables`) et attend
en retour un `dict {nom_objectif: valeur}` ; aucun fichier d'entrée/sortie,
aucun calculateur externe, pour ce chemin.

Tous les autres paramètres du modèle restent aux valeurs par défaut de l'app
(matériau parpaing, géométrie 40 m²/7,5 m, ventilation, etc.).""")

# ---------------------------------------------------------------------------
code(r'''import hashlib
import tempfile

FIXED_PARAMS = dict(
    ach_day=1.5, ach_night=2.0,
    lam_iso=0.036, ach=0.6, Qint=400.0, dTout=1.0, fsol=0.5, seer=3.5,
    Sfloor=40.0, Htot=7.5, Awin=20.0, UAother_ref=58.0, Sfloor_ref=40.0,
    e_blk=0.20, lam_blk=0.95, rhoc_blk=1300 * 1000.0, rhoc_iso=30 * 1030.0,
    hi=7.7, he=25.0,
    Tset_h=292.15, Tset_c=299.15, Kp=4000.0, Kc=4000.0,
    fanWhm3=0.15, PR_pv=0.90,
)
PRIX_ELEC, PRIX_RACHAT_PV = 0.2516, 0.04     # €/kWh, mêmes valeurs par défaut que l'app
T_CONFORT_MIN, T_CONFORT_MAX = 19.0, 26.0    # °C, bande de confort par defaut de l'app
WARMUP_HOURS = WARMUP_DAYS * 24

VAR_NAMES = ["Pheat", "Pcool", "Ppv_kWc", "e_ite_cm", "e_iti_cm"]
VAR_LABELS = ["Chauffage [W]", "Climatisation [W]", "Photovolt. [kWc]",
              "Isolation ext. [cm]", "Isolation int. [cm]"]
XL = np.array([1000.0, 0.0, 0.0, 0.0, 0.0])       # mêmes bornes que les sliders de l'app
XU = np.array([12000.0, 6000.0, 9.0, 30.0, 20.0])

OBJ_NAMES = ["DH_froid_Kh", "DH_chaleur_Kh", "Cout_net_eur", "Capex_eur"]   # tous a minimiser directement
OBJ_LABELS = ["Froid·Heure [K·h]", "Chaleur·Heure [K·h]", "Coût net [€]", "CAPEX [€]"]

# Postes finances (1) vs deja en place/deja finances (0) -- memes valeurs par
# defaut que les cases a cocher de l'app (voir indicators.DEFAULT_CAPEX_FLAGS) ;
# ce notebook n'a pas d'UI, donc fixe ici plutot qu'ajustable au clic.
CAPEX_FLAGS = {"Pheat": 0, "Pcool": 1, "Ppv_kWc": 0, "e_ite_cm": 1, "e_iti_cm": 1}

OUTPUT_COLS = ["time", "Tair", "Tout", "Qheat", "Pgrid_cool", "Pself_cool",
               "Egrid_total", "Eself_cool", "Eexport"]

# Calculateur fz pour le chemin OpenModelica — meme FZ_MODEL/params.txt/run.sh
# que app.py (voir README, "Pourquoi fz.fzr plutot qu'un appel direct au binaire").
FZR_DIR = os.path.abspath("app_fzr")
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
        "Egrid_total_last": "python://csv_file('res.csv', column='Egrid_total')[-1]",
        "Eself_cool_last": "python://csv_file('res.csv', column='Eself_cool')[-1]",
        "Eexport_last": "python://csv_file('res.csv', column='Eexport')[-1]",
    },
}


def _scenario_params(x):
    Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm = x
    return dict(FIXED_PARAMS, Pheat=Pheat, Pcool=Pcool, Ppv_kWc=Ppv_kWc,
                e_ite=e_ite_cm / 100.0, e_iti=e_iti_cm / 100.0)


def _simulate_python(x):
    rows = bt.simulate(_scenario_params(x), weather, stop_time)
    return pd.DataFrame(rows)[OUTPUT_COLS]


def _simulate_openmodelica(x):
    """Execute le binaire OpenModelica compile via fz.fzr() — meme calculateur
    sh://app_fzr/run.sh que app.py, genuine usage de fz plutot qu'un
    subprocess brut. Contrairement a app.py, pas besoin ici du contournement
    _fzr_outside_main_thread : un notebook Jupyter tourne dans le thread
    principal, fz.fzr() peut donc installer son gestionnaire SIGINT normalement
    (et meme si ce n'etait pas le cas, fz main l'ignore silencieusement hors
    thread principal au lieu de lever une exception, cf. fz/core.py)."""
    override = f"tmy.fileName={WEATHER_PATH}," + ",".join(f"{k}={v}" for k, v in _scenario_params(x).items())
    case_id = hashlib.md5(f"{override}|{stop_time}".encode()).hexdigest()[:16]
    env_path = os.path.join(tempfile.gettempdir(), f"buildingopt_fz_case_{case_id}.sh")
    with open(env_path, "w") as f:
        f.write(f'OV="{override}"\nSTARTT="0"\nSTOPT="{stop_time}"\n')

    with tempfile.TemporaryDirectory() as results_dir:
        result = fz.fzr(FZR_PARAMS, {"case_id": case_id}, FZ_MODEL,
                         results_dir=results_dir, calculators=[FZR_CALCULATOR])
    row = result.iloc[0]
    if row.get("status") != "done":
        raise RuntimeError(f"Simulation fzr échouée:\n{row.get('error')}\n{row.get('stderr')}")

    raw = pd.DataFrame({
        "time": row["time"], "Tair": row["Tair"], "Tout": row["Tout"], "Qheat": row["Qheat"],
        "Pgrid_cool": row["Pgrid_cool"], "Pself_cool": row["Pself_cool"],
    })
    raw["hour"] = (raw["time"] / 3600).round().astype(int)
    sim = raw.groupby("hour", as_index=False).last()
    sim["time"] = sim["hour"] * 3600
    sim = sim.drop(columns="hour")
    sim["Egrid_total"] = row["Egrid_total_last"]
    sim["Eself_cool"] = row["Eself_cool_last"]
    sim["Eexport"] = row["Eexport_last"]
    return sim[OUTPUT_COLS]


def simulate_scenario(x):
    """x = [Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm] -> DataFrame (colonnes = app)."""
    if SOLVER == "openmodelica":
        return _simulate_openmodelica(x)
    return _simulate_python(x)


def building_model(Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm):
    """Modele fz.fzd() (mode 'model=fonction Python', voir section 4) : recoit
    les 5 variables de conception en argument nomme, renvoie un dict
    {nom_objectif: valeur} — DH_froid/DH_chaleur/cout/capex sur la periode,
    apres mise en regime, les 4 a minimiser.

    DH_froid/DH_chaleur = degres-heures d'inconfort (Sum des depassements
    horaires de la bande de confort, en K.h — meme fonction que l'app,
    indicators.comfort_indicators) plutot que Tmin/Tmax : une somme,
    contrairement a un min/max, varie avec chaque variable de conception
    (meilleur signal pour NSGA-II) et pese la duree du depassement, pas
    seulement son pic.

    Capex_eur (indicators.capex_estimate, CAPEX_FLAGS ci-dessus) : sans lui,
    le front de Pareto pousse mecaniquement vers le sur-equipement (chaque
    variable n'a qu'un cout d'exploitation, jamais d'investissement) ; les
    postes deja en place/deja finances (flag 0) restent comptes dans les
    degres-heures/cout net (leur cout d'exploitation est reel), mais pas
    dans ce 4e objectif.
    """
    x = [Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm]
    sim = simulate_scenario(x)
    sim_p = sim.iloc[WARMUP_HOURS:] if len(sim) > WARMUP_HOURS else sim
    Tint = sim_p["Tair"] - 273.15
    _, DH_froid, DH_chaleur = comfort_indicators(Tint, T_CONFORT_MIN, T_CONFORT_MAX)
    egrid_total = sim["Egrid_total"].iloc[-1]
    eexport = sim["Eexport"].iloc[-1]
    cout = egrid_total * PRIX_ELEC - eexport * PRIX_RACHAT_PV
    Awall = bt.derive_constants(_scenario_params(x))["Awall"]
    capex = capex_estimate(Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm, Awall, flags=CAPEX_FLAGS)
    return {"DH_froid_Kh": DH_froid, "DH_chaleur_Kh": DH_chaleur, "Cout_net_eur": cout, "Capex_eur": capex}


# sanity check sur un scenario "par defaut" (memes valeurs que l'app au chargement)
print(f"solveur = {SOLVER!r}")
print("objectifs (defaut app) :", building_model(8000, 2000, 3.0, 16.0, 0.0))
''')

# ---------------------------------------------------------------------------
md(r"""## 4. Optimisation multi-objectif (NSGA-II via `fz.fzd()`)

`POP_SIZE` × `N_GEN` simulations annuelles complètes seront exécutées. Chaque
évaluation prend ~4 s en pur Python (BuildingTherm.simulate() seul), mais
`fz.fzd()` ajoute un surcoût mesuré d'environ 20 % par appel (évaluation de
`output_expression`, écriture du CSV/manifest par itération, construction du
DataFrame `XY`...), soit ~5 s/évaluation au total : avec les valeurs par
défaut ci-dessous (pop=40, 20 générations, soit ~800 simulations), compter
environ 55-70 minutes en pur Python — sensiblement plus que les 35-45 minutes
de la version `pymoo` pour les mêmes réglages. Ce coût est le prix du passage
par `fz` pour l'orchestration ; augmenter `POP_SIZE`/`N_GEN` donne un front
de Pareto plus fin, au prix du temps de calcul (linéaire).

`fz.fzd()` reçoit `building_model` directement comme `model` (mode « modèle
= fonction Python », pas de fichier d'entrée), `output_expression` comme
**liste** de 4 noms (un par clé du dict que `building_model` renvoie —
c'est ce qui déclenche le mode multi-objectif de `fzd`), et
`algorithm="nsga2.py"` (téléchargé section 2, code natif de `fz`, pas une
réimplémentation locale). Chaque évaluation de modèle se fait séquentiellement
dans le thread appelant (pas de pool de threads, cf. docstring de `fzd`).""")

# ---------------------------------------------------------------------------
code(r'''POP_SIZE = 40   # reduire (ex. 16) pour un run plus rapide, augmenter pour un front plus fin
N_GEN = 20        # reduire (ex. 6) pour un run plus rapide, augmenter pour une meilleure convergence

fzd_result = fz.fzd(
    input_path=None,                       # modele = fonction Python : pas de fichier d'entree
    input_variables={name: f"[{lo};{hi}]" for name, lo, hi in zip(VAR_NAMES, XL, XU)},
    model=building_model,
    output_expression=OBJ_NAMES,           # liste de 4 noms -> mode multi-objectif de fzd
    algorithm="nsga2.py",
    calculators=1,                         # ignore pour un modele fonction (toujours sequentiel)
    algorithm_options={"pop_size": POP_SIZE, "generations": N_GEN, "seed": 1},
    analysis_dir="fzd_analysis",
)

print(fzd_result["summary"])
print(fzd_result["analysis"]["text"])
''')

# ---------------------------------------------------------------------------
md(r"""## 5. Regroupement du front de Pareto en N scénarios représentatifs

K-means (dans l'espace des 4 objectifs, standardisé) découpe le front en
`N_SCENARIOS` groupes ; pour chacun, on retient la solution la plus proche du
centroïde comme scénario représentatif. Le front de Pareto final vient de
`fzd_result["analysis"]["data"]` (calculé par `nsga2.py`, cf. sa méthode
`get_analysis()`) — `fz` n'a pas d'algorithme de clustering, ce
post-traitement reste donc `scikit-learn`, inchangé par rapport à la
version `pymoo`.""")

# ---------------------------------------------------------------------------
code(r'''from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

N_SCENARIOS = 5   # nombre de scenarios a extraire du front de Pareto

# F : (n_sol, 4) [DH_froid_Kh, DH_chaleur_Kh, cout_net_eur, capex_eur] ; X : (n_sol, 5) variables
F = np.array(fzd_result["analysis"]["data"]["pareto_F"])
X = np.array(fzd_result["analysis"]["data"]["pareto_X"])

scaler = StandardScaler()
F_scaled = scaler.fit_transform(F)

k = min(N_SCENARIOS, len(F))
kmeans = KMeans(n_clusters=k, n_init=10, random_state=0).fit(F_scaled)

selected_idx = []
for c in range(k):
    members = np.where(kmeans.labels_ == c)[0]
    center = kmeans.cluster_centers_[c]
    dists = np.linalg.norm(F_scaled[members] - center, axis=1)
    selected_idx.append(members[np.argmin(dists)])
selected_idx = sorted(selected_idx, key=lambda i: F[i, 2])  # tri par cout croissant

scenarios_df = pd.DataFrame(X[selected_idx], columns=VAR_NAMES)
scenarios_df["DH_froid_Kh"] = F[selected_idx, 0]
scenarios_df["DH_chaleur_Kh"] = F[selected_idx, 1]
scenarios_df["Cout_net_eur"] = F[selected_idx, 2]
scenarios_df["Capex_eur"] = F[selected_idx, 3]
scenarios_df.index = [f"Scénario {i + 1}" for i in range(len(selected_idx))]
scenarios_df.round(1)
''')

# ---------------------------------------------------------------------------
md(r"""## 6. Front de Pareto (3D) : degrés-heures froid / chaleur / coût

Projection sur 3 des 4 objectifs (le CAPEX n'a pas d'axe ici — voir la vue
en coordonnées parallèles, section 7, pour les 4 à la fois). En plus du
front de Pareto final et des scénarios retenus, ce graphique
affiche aussi (en fond, points pâles) **toutes** les évaluations de toutes
les générations — disponibles directement via `fzd_result["XY"]`, un
DataFrame que `fz` construit automatiquement (variables + sorties de chaque
cas). La version `pymoo` n'avait accès qu'au front final (`res.F`) : cette
vue d'ensemble est un a-côté gratuit de l'usage de `fz`.""")

# ---------------------------------------------------------------------------
code(r'''XY = fzd_result["XY"]

fig = go.Figure()
fig.add_trace(go.Scatter3d(
    x=XY["DH_froid_Kh"], y=XY["DH_chaleur_Kh"], z=XY["Cout_net_eur"],
    mode="markers", name=f"Toutes les évaluations ({len(XY)})",
    marker=dict(color="rgba(120,120,120,0.25)", size=2),
))
fig.add_trace(go.Scatter3d(
    x=F[:, 0], y=F[:, 1], z=F[:, 2], mode="markers", name="Front de Pareto",
    marker=dict(color="rgba(31,119,180,0.6)", size=4),
))
fig.add_trace(go.Scatter3d(
    x=F[selected_idx, 0], y=F[selected_idx, 1], z=F[selected_idx, 2],
    mode="markers+text", name="Scénarios retenus",
    marker=dict(color="rgba(214,39,40,0.9)", size=7, symbol="diamond"),
    text=[f"S{i + 1}" for i in range(len(selected_idx))],
))
fig.update_layout(
    scene=dict(xaxis_title="Froid·Heure [K·h]", yaxis_title="Chaleur·Heure [K·h]", zaxis_title="Coût net [€]"),
    title="Front de Pareto (3 des 4 objectifs, fz.fzd + nsga2.py) — scénarios représentatifs en évidence",
    height=550, margin=dict(l=0, r=0, t=50, b=0),
)
fig.show()
''')

# ---------------------------------------------------------------------------
md(r"""## 7. Vue d'ensemble : coordonnées parallèles

Chaque ligne est une simulation ; les 9 axes sont les 5 variables de
conception (`Pheat`, `Pcool`, `Ppv_kWc`, `e_ite_cm`, `e_iti_cm`) suivies des
4 objectifs (`Froid·Heure`, `Chaleur·Heure`, `Coût net`, `CAPEX`). Toutes les
évaluations de `fzd_result["XY"]` sont tracées en gris clair, les 5
scénarios retenus (centroïdes k-means, section 5) en rouge — un coup d'œil
pour repérer les compromis (ex. `Ppv_kWc` élevé et `Cout_net_eur` faible
vont-ils dans le même sens, ou s'opposent-ils ?).""")

# ---------------------------------------------------------------------------
code(r'''centroid_df = pd.DataFrame(X[selected_idx], columns=VAR_NAMES)
for j, name in enumerate(OBJ_NAMES):
    centroid_df[name] = F[selected_idx, j]
centroid_df["est_centroide"] = 1

all_df = XY[VAR_NAMES + OBJ_NAMES].copy()
all_df["est_centroide"] = 0

combined = pd.concat([all_df, centroid_df], ignore_index=True)

fig = go.Figure(data=go.Parcoords(
    line=dict(
        color=combined["est_centroide"],
        colorscale=[[0, "rgba(120,120,120,0.35)"], [1, "rgba(214,39,40,0.9)"]],
        showscale=False,
    ),
    dimensions=[
        dict(label=label, values=combined[name])
        for name, label in zip(VAR_NAMES + OBJ_NAMES, VAR_LABELS + OBJ_LABELS)
    ],
))
fig.update_layout(
    title=f"Coordonnées parallèles — {len(XY)} évaluations (gris) + {len(selected_idx)} scénarios retenus (rouge)",
    height=550, margin=dict(l=80, r=80, t=100, b=20),
)
fig.show()
''')

# ---------------------------------------------------------------------------
md(r"""## 8. Détail temporel des scénarios sélectionnés

Même visualisation que l'app Streamlit (bande de confort, températures
intérieure/extérieure min-max journalières, puissances importées/autoconsommées).""")

# ---------------------------------------------------------------------------
code(r'''def plot_scenario(x, title):
    sim = simulate_scenario(x)
    sim_p = sim.iloc[WARMUP_HOURS:].reset_index(drop=True)
    jours = ((sim_p["time"] - sim_p["time"].iloc[0]) / 86400).astype(int)

    daily = pd.DataFrame({
        "jour": jours,
        "Tint_min": sim_p["Tair"] - 273.15, "Tint_max": sim_p["Tair"] - 273.15,
        "Text_min": sim_p["Tout"] - 273.15, "Text_max": sim_p["Tout"] - 273.15,
    }).groupby("jour").agg({"Tint_min": "min", "Tint_max": "max", "Text_min": "min", "Text_max": "max"})
    kW_grid = (sim_p["Pgrid_cool"] / 1000).groupby(jours).mean()
    kW_pv_self = (sim_p["Pself_cool"] / 1000).groupby(jours).mean()

    fig = go.Figure()
    fig.add_hrect(y0=T_CONFORT_MIN, y1=T_CONFORT_MAX, fillcolor="rgba(46,160,67,0.12)", line_width=0,
                  annotation_text=f"confort {T_CONFORT_MIN:.0f}-{T_CONFORT_MAX:.0f} °C", annotation_position="top left")
    fig.add_trace(go.Scatter(x=daily.index, y=daily["Text_max"], mode="lines",
                              line=dict(width=1.2, color="rgba(120,120,120,0.9)"), name="T extérieure max/j"))
    fig.add_trace(go.Scatter(x=daily.index, y=daily["Text_min"], mode="lines",
                              line=dict(width=1.2, color="rgba(120,120,120,0.9)", dash="dot"),
                              fill="tonexty", fillcolor="rgba(120,120,120,0.25)", name="T extérieure min/j"))
    fig.add_trace(go.Scatter(x=daily.index, y=daily["Tint_max"], mode="lines",
                              line=dict(width=1.2, color="rgba(31,119,180,0.9)"), name="T intérieure max/j"))
    fig.add_trace(go.Scatter(x=daily.index, y=daily["Tint_min"], mode="lines",
                              line=dict(width=1.2, color="rgba(31,119,180,0.9)", dash="dot"),
                              fill="tonexty", fillcolor="rgba(31,119,180,0.3)", name="T intérieure min/j"))
    fig.add_trace(go.Scatter(x=kW_grid.index, y=kW_grid.values, mode="lines", name="Import réseau [kW]",
                              stackgroup="power", yaxis="y2", line=dict(color="rgba(214,39,40,0.9)", width=0.5),
                              fillcolor="rgba(214,39,40,0.35)"))
    fig.add_trace(go.Scatter(x=kW_pv_self.index, y=kW_pv_self.values, mode="lines", name="Autoconso PV [kW]",
                              stackgroup="power", yaxis="y2", line=dict(color="rgba(255,127,14,0.9)", width=0.5),
                              fillcolor="rgba(255,127,14,0.35)"))
    fig.update_layout(
        title=title, xaxis_title="Jour", yaxis=dict(title="Température [°C]"),
        yaxis2=dict(title="Puissance moyenne/j [kW]", overlaying="y", side="right", rangemode="tozero"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=380, margin=dict(l=60, r=60, t=60, b=40), hovermode="x unified",
    )
    return fig
''')

# ---------------------------------------------------------------------------
# 5 separate cells (one per scenario) rather than a single loop, so each plot
# can be scrolled/collapsed to independently in Jupyter's outline.
for i in range(5):
    code(f'''if len(selected_idx) > {i}:
    idx = selected_idx[{i}]
    x = X[idx]
    params_txt = ", ".join(f"{{n}}={{v:.1f}}" for n, v in zip(VAR_NAMES, x))
    title = (f"Scénario {i + 1}/{{len(selected_idx)}} — {{params_txt}}<br>"
             f"Froid·Heure {{F[idx, 0]:.0f}} K·h · Chaleur·Heure {{F[idx, 1]:.0f}} K·h · "
             f"Coût net {{F[idx, 2]:.0f}} € · CAPEX {{F[idx, 3]:.0f}} €")
    plot_scenario(x, title).show()
''')

nb["cells"] = cells
nbf.write(nb, "BuildingOpt_fz.ipynb")
print(f"wrote BuildingOpt_fz.ipynb with {len(cells)} cells")
