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
