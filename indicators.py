"""Pure post-processing indicators shared by app.py and BuildingOpt.ipynb.

No Streamlit/network dependency by design, so it can be unit-tested (and
imported by the notebook) without pulling in the whole app."""


def comfort_indicators(Tint_period_C, T_confort_min, T_confort_max):
    """Heures hors bande de confort (comptage) + degres-heures d'inconfort
    (integrale du depassement, en K.h — ~DJU horaires), sur une serie
    horaire de temperature interieure [°C]. Plus lisses/representatifs que
    Tmin/Tmax seuls, qui ne captent qu'un unique pic ponctuel sans
    distinguer un exces bref d'un exces prolonge.

    Lecture litterale des noms (pas la convention DJU chauffage/froid du
    batiment) : DH_froid = degres-heures ou il fait froid (sous la limite
    basse), DH_chaleur = degres-heures ou il fait chaud (au-dessus de la
    limite haute).

    Returns (heures_inconfort: int, DH_froid: float, DH_chaleur: float)."""
    heures_inconfort = int(((Tint_period_C < T_confort_min) | (Tint_period_C > T_confort_max)).sum())
    DH_froid = (T_confort_min - Tint_period_C).clip(lower=0).sum()
    DH_chaleur = (Tint_period_C - T_confort_max).clip(lower=0).sum()
    return heures_inconfort, DH_froid, DH_chaleur
