"""Pure post-processing indicators shared by app.py and BuildingOpt.ipynb.

No Streamlit/network dependency by design, so it can be unit-tested (and
imported by the notebook) without pulling in the whole app."""


DEFAULT_TOLERANCE_C = 1.0


def comfort_indicators(Tint_period_C, T_confort_min, T_confort_max, tolerance=DEFAULT_TOLERANCE_C):
    """Heures hors bande de confort (comptage) + degres-heures d'inconfort
    (integrale du depassement, en K.h — ~DJU horaires), sur une serie
    horaire de temperature interieure [°C]. Plus lisses/representatifs que
    Tmin/Tmax seuls, qui ne captent qu'un unique pic ponctuel sans
    distinguer un exces bref d'un exces prolonge.

    tolerance [°C] : marge appliquee de part et d'autre de [T_confort_min,
    T_confort_max] avant de compter une heure/un degre comme hors confort
    (bande effective [T_confort_min - tolerance, T_confort_max + tolerance]).
    Un regulateur proportionnel (pas PI) a toujours un ecart de regime
    permanent qui croit avec les pertes thermiques du batiment (cf. Kp/Kc
    dans BuildingTherm) ; sans marge, un ecart chronique de quelques
    dixiemes de degre sous la consigne suffit a compter des mois entiers
    comme "hors confort" alors que l'ecart reste mineur. 1°C par defaut.

    Lecture litterale des noms (pas la convention DJU chauffage/froid du
    batiment) : DH_froid = degres-heures ou il fait froid (sous la limite
    basse), DH_chaleur = degres-heures ou il fait chaud (au-dessus de la
    limite haute).

    Returns (heures_inconfort: int, DH_froid: float, DH_chaleur: float)."""
    lo = T_confort_min - tolerance
    hi = T_confort_max + tolerance
    heures_inconfort = int(((Tint_period_C < lo) | (Tint_period_C > hi)).sum())
    DH_froid = (lo - Tint_period_C).clip(lower=0).sum()
    DH_chaleur = (Tint_period_C - hi).clip(lower=0).sum()
    return heures_inconfort, DH_froid, DH_chaleur


# Estimation grossiere, marche FR (a ajuster) — que le poste soit finance ou
# non depend des drapeaux 0/1 passes a capex_estimate(), pas de ces couts
# unitaires eux-memes.
CAPEX_UNIT_COSTS = {
    "Pheat": 0.10,       # chauffage electrique resistif, convecteurs poses [euros/W]
    "Pcool": 1.20,       # PAC reversible / clim split, posee [euros/W]
    "Ppv_kWc": 2000.0,   # photovoltaique pose, onduleur inclus [euros/kWc]
    "e_ite_cm": 7.0,     # isolation thermique exterieure, pose+enduit [euros/m2/cm]
    "e_iti_cm": 5.0,     # isolation thermique interieure, pose+finition [euros/m2/cm]
}

DEFAULT_CAPEX_FLAGS = {
    # 1 = ce poste est un investissement a financer (compte dans le CAPEX) ;
    # 0 = deja en place/deja finance, exclu du CAPEX (mais son cout
    # d'exploitation reste bien compte dans les degres-heures/cout net).
    "Pheat": 0, "Pcool": 1, "Ppv_kWc": 0, "e_ite_cm": 1, "e_iti_cm": 1,
}


def capex_estimate(Pheat, Pcool, Ppv_kWc, e_ite_cm, e_iti_cm, Awall, flags=None):
    """CAPEX total [euros] pour les 5 variables de conception, chacune
    incluse ou non selon `flags` (dict {nom: 0/1}, defaut DEFAULT_CAPEX_FLAGS) :
    ex. l'installation de chauffage deja en place n'a pas a etre refinancee,
    seule une nouvelle climatisation ou de l'isolation supplementaire compte.

    CAPEX = Σ flag[v] * cout_unitaire[v] * valeur[v], les deux postes
    d'isolation etant proportionnels a la surface de mur (Awall, cf.
    BuildingTherm.derive_constants()) en plus de l'epaisseur."""
    f = dict(DEFAULT_CAPEX_FLAGS, **(flags or {}))
    return (
        f["Pheat"] * CAPEX_UNIT_COSTS["Pheat"] * Pheat
        + f["Pcool"] * CAPEX_UNIT_COSTS["Pcool"] * Pcool
        + f["Ppv_kWc"] * CAPEX_UNIT_COSTS["Ppv_kWc"] * Ppv_kWc
        + f["e_ite_cm"] * CAPEX_UNIT_COSTS["e_ite_cm"] * Awall * e_ite_cm
        + f["e_iti_cm"] * CAPEX_UNIT_COSTS["e_iti_cm"] * Awall * e_iti_cm
    )
