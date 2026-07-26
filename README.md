# Confort thermique de bâtiment

Application web interactive pour explorer le confort thermique et la
consommation énergétique d'un bâtiment, à partir d'un modèle Modelica
(`BuildingOpt.mo`) : mur tricouche ITE/ISOLANT/ITE, chauffage/froid,
photovoltaïque en autoconsommation, et météo réelle dynamique par
position/dates.

## Aperçu

- **Modèle physique** ([`BuildingOpt.mo`](BuildingOpt.mo)) : réseau RC 6 nœuds
  pour un mur tricouche (isolant intérieur / paroi structurelle / isolant
  extérieur), chauffage proportionnel plafonné, PAC de rafraîchissement,
  aération naturelle diurne + surventilation nocturne, PV en
  autoconsommation directe (couvre chauffage **et** froid).
- **Géométrie paramétrable** : parallélépipède rectangle, emprise au sol
  carrée, surface et hauteur totale réglables.
- **Météo réelle dynamique** : température + irradiance horaires
  téléchargées depuis [Open-Meteo](https://open-meteo.com/) (réanalyse ERA5,
  sans clé API), pour n'importe quelle position (carte cliquable ou
  géolocalisation navigateur) et n'importe quelle plage de dates réelle
  (1950 → aujourd'hui, aucune prévision).
- **Simulation** : le binaire OpenModelica compilé est exécuté via
  [`fz`/`fzr`](https://pypi.org/project/fz/) plutôt qu'en appel direct, voir
  [Architecture](#architecture).
- **Sorties** : indicateurs de confort et de coût sur la période choisie
  (température min/max, conso nette après PV, autoconsommation, coût en €),
  et un graphique Plotly (températures intérieure/extérieure min-max
  journalières + puissances importées/autoconsommées).

## Installation

Nécessite [OpenModelica](https://openmodelica.org/) (`omc`) installé et dans
le `PATH`, en plus de Python 3.10+.

```bash
pip install -r requirements.txt
```

Compiler le modèle (à refaire après toute modification de `BuildingOpt.mo`) :

```bash
omc build.mos
```

## Lancer l'app

```bash
streamlit run app.py
```

Ouvre ensuite `http://localhost:8501`.

## Architecture

```
BuildingOpt.mo         modèle Modelica (source)
build.mos              script de compilation omc -> binaire BuildingOpt
app.py                 app Streamlit (UI, météo, simulation, graphique)
app_fzr/
  params.txt           template fz minimal (une seule variable : case_id)
  run.sh               calculateur sh:// invoqué par fzr
```

La simulation ne modifie pas `BuildingOpt.mo` par run : elle réutilise le
binaire déjà compilé et lui passe les paramètres de conception via
`-override=...`, ainsi que la plage temporelle via `-startTime`/`-stopTime`.

**Pourquoi `fz.fzr` plutôt qu'un appel direct au binaire ?** Pour rester
cohérent avec le notebook d'optimisation multi-objectif qui utilise le même
framework (`fzd`/`fzr`) pour piloter OpenModelica. Deux contraintes en
découlent, gérées dans `app.py`/`app_fzr/run.sh` :

- `fzr` nomme chaque dossier de résultat par la concaténation de toutes les
  variables passées : avec ~20 paramètres (ou un chemin météo contenant des
  `/`), ce nom dépasse la limite de 255 caractères par composant de chemin.
  On ne passe donc à `fzr` qu'un identifiant court (`case_id`, hash MD5) ; les
  vraies valeurs (`-override=...`, météo, durée) transitent par un petit
  fichier d'environnement (`/tmp/buildingopt_case_<id>.sh`) que `run.sh` va
  lire.
- `fzr` exécute chaque cas dans son propre dossier temporaire : `run.sh` copie
  `BuildingOpt_init.xml`/`BuildingOpt_JacA.bin` avant de lancer le binaire.
- `fz.fzr()` installe un handler `SIGINT` via `signal.signal()`, valide
  uniquement dans le thread principal — or Streamlit exécute le script dans
  un thread de travail. `app.py` neutralise temporairement `signal.signal()`
  autour de l'appel (`_fzr_outside_main_thread`).

**Nettoyage de la sortie OpenModelica.** Le modèle génère des événements
(rampes de ventilation) qui produisent plusieurs lignes quasi simultanées
dans le CSV de sortie autour de chaque événement. `run_simulation()` regroupe
par heure entière et garde la dernière valeur (état stabilisé après
l'événement) avant de reconstruire la série temporelle — sans quoi une
indexation horaire naïve désynchronise progressivement toute la série.

## Limites connues

- Météo réelle uniquement : pas de prévision, dates bornées à aujourd'hui.
- Le chauffage est supposé électrique résistif (COP = 1) pour l'autoconso PV.
- Couverture ERA5 : la précision dépend de la résolution de la réanalyse
  (~9 km), moins fine qu'une station météo locale.
