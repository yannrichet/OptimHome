"""One-off script that generates BuildingOpt_fz_gpareto.ipynb from scratch via
nbformat.

Not part of the app/test suite: run manually whenever
BuildingOpt_fz_gpareto.ipynb needs to be regenerated (e.g. after editing this
script), then delete or re-run — it always overwrites the target file.
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
md(r"""# Optimisation multi-objectif (GPareto + rlibKriging via `fz`) — Équilibre thermique d'habitation

Variante de [`BuildingOpt_fz.ipynb`](BuildingOpt_fz.ipynb) qui remplace
NSGA-II par un algorithme d'**optimisation bayésienne multi-objectif** (EGO —
Efficient Global Optimization) : à chaque itération, un modèle de krigeage
[`rlibkriging`](https://github.com/libKriging/rlibKriging) (`KM()`, un objet
compatible avec la classe `km` de `DiceKriging`) est ajusté par objectif sur
les points déjà évalués, puis le critère d'enrichissement SMS-EGO du package
R [`GPareto`](https://github.com/mbinois/GPareto) (`crit_optimizer()`)
propose le·s point·s suivant·s — sans jamais rappeler le simulateur pendant
cette étape, seule l'incertitude du modèle guide le choix.

Tout le reste est identique à `BuildingOpt_fz.ipynb` : mêmes 5 variables de
conception, mêmes 3 objectifs, même pipeline `fz.fzd()`, même
post-traitement (k-means + graphiques). Seul l'algorithme change —
[`gpareto_rlibkriging.py`](gpareto_rlibkriging.py) (ce dépôt) au lieu de
[`nsga2.py`](https://github.com/Funz/fz/blob/main/examples/algorithms/nsga2.py)
(le dépôt `fz`) — implémentant la même interface `get_initial_design` /
`get_next_design` / `get_analysis` que `fzd()` attend d'un algorithme.

**Pourquoi EGO plutôt que NSGA-II ici ?** La simulation thermique annuelle
coûte plusieurs secondes ; NSGA-II a besoin de centaines de générations x
population pour converger (`POP_SIZE x N_GEN` ≈ 800 évaluations dans
`BuildingOpt_fz.ipynb`). Un modèle de krigeage exploite l'information de
*chaque* évaluation pour ne proposer que des points prometteurs (compromis
exploration/exploitation), au prix d'un côut de calcul du critère
d'enrichissement qui croît avec le nombre de points — adapté à un budget de
simulation beaucoup plus faible (quelques dizaines à ~150 évaluations dans ce
notebook). Attendez-vous à un front de Pareto moins dense que la version
NSGA-II à budget de calcul (temps) équivalent, mais obtenu avec 5 à 10 fois
moins de simulations.

**Nécessite R** (packages `GPareto` + `rlibkriging`) en plus de Python, via
`rpy2` — voir la cellule d'installation ci-dessous — et, comme
`BuildingOpt_fz.ipynb`, la branche `main` de `fz` sur GitHub (mode « modèle =
fonction Python » et objectifs vectoriels).

Voir le [dépôt GitHub](https://github.com/yannrichet/OptimHome) et le
[README](https://github.com/yannrichet/OptimHome#readme) pour le contexte complet
(modèle physique, app Streamlit, solveur de secours).""")

# ---------------------------------------------------------------------------
md(r"""## 0. Installation (Google Colab) et récupération du modèle

Sur Colab, cette cellule installe les dépendances Python — dont `fz` depuis
la branche `main` de GitHub, pas PyPI — et télécharge `BuildingTherm.py`,
`indicators.py` ainsi que l'algorithme `gpareto_rlibkriging.py` (le notebook
reste autonome : pas besoin de cloner `OptimHome` ni `fz`). En local, si ces
fichiers sont déjà présents, tout est simplement ignoré.""")

# ---------------------------------------------------------------------------
code(r'''import os, sys, subprocess, importlib.util, urllib.request

IN_COLAB = "google.colab" in sys.modules

if IN_COLAB:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q",
         "git+https://github.com/Funz/fz.git@main",
         "scikit-learn", "plotly", "pandas", "numpy", "scipy", "requests", "rpy2"],
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
if not os.path.exists("gpareto_rlibkriging.py"):
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/yannrichet/OptimHome/main/gpareto_rlibkriging.py",
        "gpareto_rlibkriging.py",
    )

print("BuildingTherm.py + indicators.py + gpareto_rlibkriging.py téléchargés (importés plus loin).")
''')

# ---------------------------------------------------------------------------
md(r"""### Installation de R, GPareto et rlibkriging

Sur Colab (Ubuntu), R est déjà présent ; cette cellule installe seulement les
deux packages R manquants depuis CRAN. **`rlibkriging` compile une extension
C++ depuis les sources — compter 3 à 6 minutes la première fois** (pas de
binaire précompilé disponible pour toutes les images Colab). En local, si R
et les deux packages sont déjà installés, la cellule ne fait rien.""")

# ---------------------------------------------------------------------------
code(r'''import shutil

if shutil.which("R") is None:
    print("Installation de R (r-base)...")
    subprocess.run("sudo apt-get update -qq", shell=True, check=True)
    subprocess.run("sudo apt-get install -y -qq --no-install-recommends r-base", shell=True, check=True)

check_pkgs = subprocess.run(
    ["Rscript", "-e",
     'cat(requireNamespace("GPareto", quietly=TRUE) && requireNamespace("rlibkriging", quietly=TRUE))'],
    capture_output=True, text=True,
)
if check_pkgs.stdout.strip() != "TRUE":
    print("Installation de GPareto + rlibkriging (peut prendre plusieurs minutes)...")
    subprocess.run(
        ["Rscript", "-e",
         'install.packages(c("GPareto", "rlibkriging"), repos="https://cloud.r-project.org")'],
        check=True,
    )
    print("GPareto + rlibkriging installés.")
else:
    print("GPareto + rlibkriging déjà disponibles.")
''')

# ---------------------------------------------------------------------------
md(r"""## 1. Météo réelle (Open-Meteo)

Même source et même API que l'app (`archive-api.open-meteo.com`, réanalyse ERA5,
sans clé). Position et période par défaut ci-dessous — à changer librement.
Le fichier `weather_nb.txt` n'est écrit que pour le solveur OpenModelica
(`CombiTimeTable` lit un fichier ; le solveur Python prend les tableaux
directement en mémoire).""")

# ---------------------------------------------------------------------------
code(r'''import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import date, timedelta

import BuildingTherm as bt
from indicators import comfort_indicators

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


SOLVER = "python"   # "python" ou "openmodelica" (voir BuildingOpt_fz.ipynb pour l'installation d'OpenModelica)

weather = fetch_weather(LAT, LON, START_DATE, END_DATE)
stop_time = (len(weather[0]) - 1) * 3600.0
print(f"{len(weather[0])} points horaires ({stop_time/86400:.1f} j, dont {WARMUP_DAYS} j de mise en régime)")

WEATHER_PATH = os.path.abspath("weather_nb.txt")
''')

# ---------------------------------------------------------------------------
md(r"""## 2. `fz` : installation vérifiée, algorithme GPareto/rlibkriging récupéré

Vérifie que la version de `fz` installée est bien la branche `main` (support
du mode « modèle = fonction Python » et des objectifs vectoriels), puis
télécharge [`gpareto_rlibkriging.py`](gpareto_rlibkriging.py) — ce dépôt,
pas `fz` : contrairement à `nsga2.py`, cet algorithme est spécifique à
`OptimHome` (il fait le pont vers R via `rpy2`, `fz` lui-même n'a pas de
dépendance R).""")

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

if not os.path.exists("gpareto_rlibkriging.py"):
    urllib.request.urlretrieve(
        "https://raw.githubusercontent.com/yannrichet/OptimHome/main/gpareto_rlibkriging.py",
        "gpareto_rlibkriging.py",
    )

print(f"fz {fz.__version__} (branche main) — modèle=fonction Python + objectifs vectoriels OK.")
print("Algorithme GPareto/rlibkriging (gpareto_rlibkriging.py) prêt.")
''')

# ---------------------------------------------------------------------------
md(r"""## 3. Variables de conception, objectifs, fonction de simulation

Identique à `BuildingOpt_fz.ipynb` : **5 variables de conception** (`Pheat`,
`Pcool`, `Ppv_kWc`, `e_ite_cm`, `e_iti_cm`), **3 objectifs** à minimiser
(Froid·Heure, Chaleur·Heure, Coût net) calculés par `building_model()`, la
fonction passée telle quelle à `fz.fzd()` comme modèle.""")

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

OBJ_NAMES = ["DH_froid_Kh", "DH_chaleur_Kh", "Cout_net_eur"]   # tous a minimiser directement
OBJ_LABELS = ["Froid·Heure [K·h]", "Chaleur·Heure [K·h]", "Coût net [€]"]

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
    sh://app_fzr/run.sh que app.py. Voir BuildingOpt_fz.ipynb pour la cellule
    d'installation d'OpenModelica (non répétée ici, SOLVER='python' par défaut)."""
    override = f"tmy.fileName={WEATHER_PATH}," + ",".join(f"{k}={v}" for k, v in _scenario_params(x).items())
    case_id = hashlib.md5(f"{override}|{stop_time}".encode()).hexdigest()[:16]
    env_path = os.path.join(tempfile.gettempdir(), f"buildingopt_fz_gpareto_case_{case_id}.sh")
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
    {nom_objectif: valeur} — DH_froid/DH_chaleur/cout sur la periode, apres
    mise en regime, les 3 a minimiser (meme fonction que BuildingOpt_fz.ipynb)."""
    x = [Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm]
    sim = simulate_scenario(x)
    sim_p = sim.iloc[WARMUP_HOURS:] if len(sim) > WARMUP_HOURS else sim
    Tint = sim_p["Tair"] - 273.15
    _, DH_froid, DH_chaleur = comfort_indicators(Tint, T_CONFORT_MIN, T_CONFORT_MAX)
    egrid_total = sim["Egrid_total"].iloc[-1]
    eexport = sim["Eexport"].iloc[-1]
    cout = egrid_total * PRIX_ELEC - eexport * PRIX_RACHAT_PV
    return {"DH_froid_Kh": DH_froid, "DH_chaleur_Kh": DH_chaleur, "Cout_net_eur": cout}


# sanity check sur un scenario "par defaut" (memes valeurs que l'app au chargement)
print(f"solveur = {SOLVER!r}")
print("objectifs (defaut app) :", building_model(8000, 2000, 3.0, 16.0, 0.0))
''')

# ---------------------------------------------------------------------------
md(r"""## 4. Optimisation multi-objectif (GPareto + rlibkriging via `fz.fzd()`)

`fz.fzd()` reçoit `building_model` directement comme `model`,
`output_expression` comme liste de 3 noms (mode multi-objectif), et
`algorithm="gpareto_rlibkriging.py"` (téléchargé section 2). Options
(`algorithm_options`) :

- `n_init` : taille du plan d'expérience initial (hypercube latin), 0 = résolu
  automatiquement à `6 x nb_variables` (30 ici) ;
- `iterations` : nombre d'itérations EGO après le plan initial ;
- `q` : nombre de points proposés par itération (batch, via l'heuristique du
  "menteur constant" — chaque point du batch est ajouté temporairement au
  modèle avec sa moyenne prédite comme fausse réponse, le temps de proposer
  le point suivant du même batch) ;
- `crit` : critère d'enrichissement GPareto (`"SMS"` par défaut — SMS-EGO,
  cf. `crit_SMS`/`crit_EHI`/`crit_EMI`/`crit_SUR`) ;
- `optim_method` : optimiseur interne du critère (`"pso"` par défaut,
  alternatives `"genoud"`/`"random"`).

Avec les valeurs par défaut ci-dessous (30 + 10x3 = 60 simulations), compter
environ 5 minutes en pur Python (~5 s/évaluation) — contre 55-70 minutes pour
les ~800 simulations de la version NSGA-II à réglages comparables : c'est
tout l'intérêt de l'approche EGO pour un simulateur coûteux, au prix d'un
front de Pareto moins dense.""")

# ---------------------------------------------------------------------------
code(r'''N_INIT = 30       # 0 = auto (6 x nb variables) ; taille du plan d'experience initial
ITERATIONS = 10   # nombre d'iterations EGO apres le plan initial
Q = 3             # points proposes par iteration (batch, "menteur constant")

fzd_result = fz.fzd(
    input_path=None,                       # modele = fonction Python : pas de fichier d'entree
    input_variables={name: f"[{lo};{hi}]" for name, lo, hi in zip(VAR_NAMES, XL, XU)},
    model=building_model,
    output_expression=OBJ_NAMES,           # liste de 3 noms -> mode multi-objectif de fzd
    algorithm="gpareto_rlibkriging.py",
    calculators=1,                         # ignore pour un modele fonction (toujours sequentiel)
    algorithm_options={"n_init": N_INIT, "iterations": ITERATIONS, "q": Q, "seed": 1},
    analysis_dir="fzd_analysis",
)

print(fzd_result["summary"])
print(fzd_result["analysis"]["text"])
''')

# ---------------------------------------------------------------------------
md(r"""## 5. Regroupement du front de Pareto en N scénarios représentatifs

Identique à `BuildingOpt_fz.ipynb` : k-means (dans l'espace des 3 objectifs,
standardisé) découpe le front de Pareto (`fzd_result["analysis"]["data"]`,
calculé par `gpareto_rlibkriging.py`, même schéma `pareto_X`/`pareto_F` que
`nsga2.py`) en `N_SCENARIOS` groupes, et retient pour chacun la solution la
plus proche du centroïde.""")

# ---------------------------------------------------------------------------
code(r'''from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

N_SCENARIOS = 5   # nombre de scenarios a extraire du front de Pareto

# F : (n_sol, 3) [DH_froid_Kh, DH_chaleur_Kh, cout_net_eur] ; X : (n_sol, 5) variables
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
scenarios_df.index = [f"Scénario {i + 1}" for i in range(len(selected_idx))]
scenarios_df.round(1)
''')

# ---------------------------------------------------------------------------
md(r"""## 6. Front de Pareto (3D) : degrés-heures froid / chaleur / coût

Comme dans `BuildingOpt_fz.ipynb`, `fzd_result["XY"]` donne accès à
**toutes** les évaluations (plan initial + points EGO), affichées en fond.""")

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
    title="Front de Pareto à 3 objectifs (fz.fzd + GPareto/rlibkriging) — scénarios représentatifs en évidence",
    height=550, margin=dict(l=0, r=0, t=50, b=0),
)
fig.show()
''')

# ---------------------------------------------------------------------------
md(r"""## 7. Vue d'ensemble : coordonnées parallèles

Chaque ligne est une simulation ; les 8 axes sont les 5 variables de
conception (`Pheat`, `Pcool`, `Ppv_kWc`, `e_ite_cm`, `e_iti_cm`) suivies des
3 objectifs (`Froid·Heure`, `Chaleur·Heure`, `Coût net`). Toutes les
évaluations de `fzd_result["XY"]` (plan initial + points EGO) sont tracées
en gris clair, les 5 scénarios retenus (centroïdes k-means, section 5) en
rouge — un coup d'œil pour repérer les compromis (ex. `Ppv_kWc` élevé et
`Cout_net_eur` faible vont-ils dans le même sens, ou s'opposent-ils ?).""")

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
             f"Froid·Heure {{F[idx, 0]:.0f}} K·h · Chaleur·Heure {{F[idx, 1]:.0f}} K·h · Coût net {{F[idx, 2]:.0f}} €")
    plot_scenario(x, title).show()
''')

nb["cells"] = cells
nbf.write(nb, "BuildingOpt_fz_gpareto.ipynb")
print(f"wrote BuildingOpt_fz_gpareto.ipynb with {len(cells)} cells")
