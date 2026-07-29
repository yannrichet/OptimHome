"""Pure-Python reimplementation of BuildingTherm.mo (no OpenModelica needed).

Same RC-network building model (6-node tricouche wall, adaptive natural/night
ventilation ramps, PV self-consumption) as BuildingTherm.mo, integrated with
scipy's BDF solver instead of Modelica/DASSL.

Why BDF and not a simple fixed-step integrator: with the default e_iti = 0 m
(no interior insulation), the corresponding wall node collapses to a near-zero
resistance AND near-zero capacitance, giving that node a sub-second thermal
time constant while the rest of the building responds over hours — a stiff
ODE system. An explicit fixed-step integrator (Euler, RK4) diverges on it;
BDF is an implicit, adaptive-step method built for exactly this case, and
matches what Modelica's default DASSL solver does under the hood. BDF is
given the analytic Jacobian of the RHS (`_jac`, below) instead of estimating
it by finite differences, which is both faster (~20% off a full-year run)
and removes the numerical Jacobian estimator's transient extreme-step-size
probing that used to require silencing scipy's RuntimeWarnings.
"""
import math

import numpy as np
from scipy.integrate import solve_ivp

DEFAULT_PARAMS = {
    # ---- Variables de conception ----
    "Pheat": 8000.0, "Pcool": 2000.0, "ach_day": 1.5, "ach_night": 2.0,
    "e_ite": 0.16, "e_iti": 0.0,
    # ---- Parametres physiques nominaux ----
    "lam_iso": 0.036, "ach": 0.6, "Qint": 400.0, "dTout": 1.0,
    "fsol": 0.5, "seer": 3.5,
    # ---- Geometrie ----
    "Sfloor": 40.0, "Htot": 7.5, "Awin": 20.0,
    "UAother_ref": 58.0, "Sfloor_ref": 40.0,
    # ---- Mur tricouche ----
    "e_blk": 0.20, "lam_blk": 0.95,
    "rhoc_blk": 1300 * 1000.0, "rhoc_iso": 30 * 1030.0,
    "hi": 7.7, "he": 25.0,
    # ---- Regulations ----
    "Tset_h": 292.15, "Tset_c": 299.15, "Kp": 4000.0, "Kc": 4000.0,
    "fanWhm3": 0.15, "Ppv_kWc": 3.0, "PR_pv": 0.90,
}

(I_TAIR, I_T1, I_T2, I_T3, I_T4, I_T5, I_T6,
 I_EHEAT, I_ECOOL, I_EGRID, I_ESELF, I_EEXPORT) = range(12)
N_STATES = 12
Y0 = (285.15, 284.9, 284.6, 284.0, 283.2, 282.5, 282.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def load_weather_table(path):
    """Parse a CombiTimeTable text file: '#1', 'double tmy(N,3)', then N rows
    of 'time Tout_K Gh'. Returns (times, Tout_K, Gh) as numpy arrays."""
    times, Tout_K, Gh = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("double"):
                continue
            t, tk, g = line.split()
            times.append(float(t))
            Tout_K.append(float(tk))
            Gh.append(float(g))
    return np.array(times), np.array(Tout_K), np.array(Gh)


def _interp_periodic(t, times, values):
    """Linear interpolation over (times, values); periodic extrapolation
    beyond the table's span, matching Modelica.Blocks.Types.Extrapolation.Periodic."""
    t0, t1 = times[0], times[-1]
    span = t1 - t0
    if span > 0:
        t = t0 + (t - t0) % span
    return np.interp(t, times, values)


def derive_constants(params):
    """Compute every derived (parameter-only) quantity from the base params,
    mirroring the `parameter Real ... = ...` chain in BuildingTherm.mo."""
    p = dict(DEFAULT_PARAMS)
    p.update(params)

    V = p["Sfloor"] * p["Htot"]
    perimetre = 4 * math.sqrt(p["Sfloor"])
    Awall = max(perimetre * p["Htot"] - p["Awin"], 1.0)
    UAother = p["UAother_ref"] * p["Sfloor"] / p["Sfloor_ref"]
    Cair = 1.2 * 1006 * V * 6

    ei = max(p["e_iti"], 1e-4)
    ee = max(p["e_ite"], 1e-4)
    Riti = ei / (p["lam_iso"] * Awall)
    Rblk = p["e_blk"] / (p["lam_blk"] * Awall)
    Rite = ee / (p["lam_iso"] * Awall)
    Rsi = 1 / (p["hi"] * Awall) + Riti / 4
    R12 = Riti / 2
    R23 = Riti / 4 + Rblk / 4
    R34 = Rblk / 2
    R45 = Rblk / 4 + Rite / 4
    R56 = Rite / 2
    R6e = Rite / 4 + 1 / (p["he"] * Awall)
    C1 = p["rhoc_iso"] * ei / 2 * Awall
    C2 = C1
    C3 = p["rhoc_blk"] * p["e_blk"] / 2 * Awall
    C4 = C3
    C5 = p["rhoc_iso"] * ee / 2 * Awall
    C6 = C5

    return dict(
        p, V=V, perimetre=perimetre, Awall=Awall, UAother=UAother, Cair=Cair,
        Riti=Riti, Rblk=Rblk, Rite=Rite, Rsi=Rsi, R12=R12, R23=R23, R34=R34,
        R45=R45, R56=R56, R6e=R6e, C1=C1, C2=C2, C3=C3, C4=C4, C5=C5, C6=C6,
    )


def _algebraics(t, y, c, weather):
    """All algebraic (non-derivative) quantities at time t, state y."""
    times, Tout_K, Gh = weather
    Tair = y[I_TAIR]

    Tout = _interp_periodic(t, times, Tout_K) + c["dTout"]
    Gh_t = _interp_periodic(t, times, Gh)
    Qsol = c["fsol"] * 0.5 * c["Awin"] * Gh_t

    hour = (t / 3600) % 24
    night = 1.0 if (hour > 22 or hour < 7) else 0.0
    needCool = max(0.0, min(1.0, (Tair - 297.15) / 2))
    vfrac = max(0.0, min(1.0, (Tair - Tout - 0.5) / 1.5))
    vopen = max(0.0, min(1.0, (Tair - 299.15) / 1.5)) * vfrac * c["ach_day"]
    boostN = night * needCool * vfrac * c["ach_night"]
    UAv = (c["ach"] + boostN + vopen) * c["V"] * 0.34

    Qheat = min(c["Pheat"], max(0.0, c["Kp"] * (c["Tset_h"] - Tair)))
    Qcool = min(c["Pcool"], max(0.0, c["Kc"] * (Tair - c["Tset_c"])))
    Pelec = Qheat + Qcool / c["seer"] + boostN * c["V"] * c["fanWhm3"]
    Ppv = c["Ppv_kWc"] * 1000 * (Gh_t / 1000) * c["PR_pv"]
    Pgrid_cool = max(Pelec - Ppv, 0.0)
    Pself_cool = min(Pelec, Ppv)
    Pexport = max(Ppv - Pelec, 0.0)

    meas = 1.0 if t > 14 * 86400 else 0.0

    return dict(
        Tout=Tout, Qsol=Qsol, UAv=UAv, Qheat=Qheat, Qcool=Qcool, Pelec=Pelec,
        Ppv=Ppv, Pgrid_cool=Pgrid_cool, Pself_cool=Pself_cool, Pexport=Pexport,
        meas=meas,
    )


def _rhs(t, y, c, weather):
    a = _algebraics(t, y, c, weather)
    Tair, T1, T2, T3, T4, T5, T6 = y[I_TAIR:I_T6 + 1]

    dTair = ((T1 - Tair) / c["Rsi"] + (a["UAv"] + c["UAother"]) * (a["Tout"] - Tair)
             + a["Qheat"] - a["Qcool"] + c["Qint"] + a["Qsol"]) / c["Cair"]
    dT1 = ((Tair - T1) / c["Rsi"] + (T2 - T1) / c["R12"]) / c["C1"]
    dT2 = ((T1 - T2) / c["R12"] + (T3 - T2) / c["R23"]) / c["C2"]
    dT3 = ((T2 - T3) / c["R23"] + (T4 - T3) / c["R34"]) / c["C3"]
    dT4 = ((T3 - T4) / c["R34"] + (T5 - T4) / c["R45"]) / c["C4"]
    dT5 = ((T4 - T5) / c["R45"] + (T6 - T5) / c["R56"]) / c["C5"]
    dT6 = ((T5 - T6) / c["R56"] + (a["Tout"] - T6) / c["R6e"]) / c["C6"]

    dEheat = a["meas"] * a["Qheat"] / 3.6e6
    dEcool = a["meas"] * a["Pelec"] / 3.6e6
    dEgrid = a["meas"] * a["Pgrid_cool"] / 3.6e6
    dEself = a["meas"] * a["Pself_cool"] / 3.6e6
    dEexport = a["meas"] * a["Pexport"] / 3.6e6

    return [dTair, dT1, dT2, dT3, dT4, dT5, dT6,
            dEheat, dEcool, dEgrid, dEself, dEexport]


def _jac(t, y, c, weather):
    """Analytic d(rhs)/dy, matching _rhs/_algebraics term for term.

    Every algebraic quantity here (UAv, Qheat, Qcool, Pelec, Pgrid_cool,
    Pself_cool, Pexport) is a function of (t, Tair) only, built out of clips
    (max/min): each clip's derivative is its "active" slope where the clip
    is unsaturated, 0 where it's pinned at a bound. Supplying this exact
    Jacobian instead of letting BDF estimate it by finite differences drops
    ~30% of the total right-hand-side evaluations (the perturbation calls
    BDF would otherwise make every time it re-forms the Jacobian).
    """
    times, Tout_K, Gh = weather
    Tair = y[I_TAIR]

    Tout = _interp_periodic(t, times, Tout_K) + c["dTout"]
    Gh_t = _interp_periodic(t, times, Gh)

    hour = (t / 3600) % 24
    night = 1.0 if (hour > 22 or hour < 7) else 0.0

    raw_needCool = (Tair - 297.15) / 2
    needCool = max(0.0, min(1.0, raw_needCool))
    dneedCool = 0.5 if 0.0 < raw_needCool < 1.0 else 0.0

    raw_vfrac = (Tair - Tout - 0.5) / 1.5
    vfrac = max(0.0, min(1.0, raw_vfrac))
    dvfrac = (1 / 1.5) if 0.0 < raw_vfrac < 1.0 else 0.0

    raw_A = (Tair - 299.15) / 1.5
    A = max(0.0, min(1.0, raw_A))
    dA = (1 / 1.5) if 0.0 < raw_A < 1.0 else 0.0

    vopen = A * vfrac * c["ach_day"]
    dvopen = (dA * vfrac + A * dvfrac) * c["ach_day"]

    boostN = night * needCool * vfrac * c["ach_night"]
    dboostN = night * c["ach_night"] * (dneedCool * vfrac + needCool * dvfrac)

    UAv = (c["ach"] + boostN + vopen) * c["V"] * 0.34
    dUAv = (dboostN + dvopen) * c["V"] * 0.34

    raw_Qheat = c["Kp"] * (c["Tset_h"] - Tair)
    Qheat = min(c["Pheat"], max(0.0, raw_Qheat))
    dQheat = -c["Kp"] if 0.0 < Qheat < c["Pheat"] else 0.0

    raw_Qcool = c["Kc"] * (Tair - c["Tset_c"])
    Qcool = min(c["Pcool"], max(0.0, raw_Qcool))
    dQcool = c["Kc"] if 0.0 < Qcool < c["Pcool"] else 0.0

    Pelec = Qheat + Qcool / c["seer"] + boostN * c["V"] * c["fanWhm3"]
    dPelec = dQheat + dQcool / c["seer"] + dboostN * c["V"] * c["fanWhm3"]

    Ppv = c["Ppv_kWc"] * 1000 * (Gh_t / 1000) * c["PR_pv"]
    dPgrid = dPelec if Pelec > Ppv else 0.0
    dPself = dPelec if Pelec < Ppv else 0.0
    dPexport = -dPelec if Ppv > Pelec else 0.0

    meas = 1.0 if t > 14 * 86400 else 0.0

    J = np.zeros((N_STATES, N_STATES))
    J[I_TAIR, I_TAIR] = (-1 / c["Rsi"] + dUAv * (Tout - Tair)
                          - (UAv + c["UAother"]) + dQheat - dQcool) / c["Cair"]
    J[I_TAIR, I_T1] = (1 / c["Rsi"]) / c["Cair"]

    for lo, mid, hi, Rlo, Rhi, C in (
        (I_TAIR, I_T1, I_T2, c["Rsi"], c["R12"], c["C1"]),
        (I_T1, I_T2, I_T3, c["R12"], c["R23"], c["C2"]),
        (I_T2, I_T3, I_T4, c["R23"], c["R34"], c["C3"]),
        (I_T3, I_T4, I_T5, c["R34"], c["R45"], c["C4"]),
        (I_T4, I_T5, I_T6, c["R45"], c["R56"], c["C5"]),
    ):
        J[mid, lo] = (1 / Rlo) / C
        J[mid, mid] = (-1 / Rlo - 1 / Rhi) / C
        J[mid, hi] = (1 / Rhi) / C

    J[I_T6, I_T5] = (1 / c["R56"]) / c["C6"]
    J[I_T6, I_T6] = (-1 / c["R56"] - 1 / c["R6e"]) / c["C6"]

    J[I_EHEAT, I_TAIR] = meas * dQheat / 3.6e6
    J[I_ECOOL, I_TAIR] = meas * dPelec / 3.6e6
    J[I_EGRID, I_TAIR] = meas * dPgrid / 3.6e6
    J[I_ESELF, I_TAIR] = meas * dPself / 3.6e6
    J[I_EEXPORT, I_TAIR] = meas * dPexport / 3.6e6
    return J


def simulate(params, weather, stop_time, output_interval=3600.0):
    """Integrate the model from t=0 to stop_time with an implicit stiff solver.

    weather: (times, Tout_K, Gh) as returned by load_weather_table().
    Returns a list of row-dicts sampled every `output_interval` seconds,
    with the same fields as the OpenModelica CSV output used by app.py.
    """
    c = derive_constants(params)
    t_eval = np.arange(0.0, stop_time + output_interval / 2, output_interval)
    t_eval = t_eval[t_eval <= stop_time + 1e-6]

    sol = solve_ivp(
        _rhs, (0.0, stop_time), Y0, method="BDF", t_eval=t_eval,
        args=(c, weather), rtol=1e-6, atol=1e-6, jac=_jac,
    )
    if not sol.success:
        raise RuntimeError(f"Integration failed: {sol.message}")

    rows = []
    for i, t in enumerate(sol.t):
        y = sol.y[:, i]
        a = _algebraics(t, y, c, weather)
        rows.append({
            "time": t, "Tair": y[I_TAIR], "Tout": a["Tout"], "Qheat": a["Qheat"],
            "Qcool": a["Qcool"], "Pelec": a["Pelec"], "Ppv": a["Ppv"],
            "Pgrid_cool": a["Pgrid_cool"], "Pself_cool": a["Pself_cool"],
            "Eheat": y[I_EHEAT], "Ecool": y[I_ECOOL],
            "Egrid_cool": y[I_EGRID], "Eself_cool": y[I_ESELF],
            "Eexport": y[I_EEXPORT],
        })
    return rows


def run_simulation(params, weather_path, stop_time):
    """Drop-in equivalent of app.py's OpenModelica-backed run_simulation():
    same params dict, same weather.txt file, returns the same columns."""
    weather = load_weather_table(weather_path)
    rows = simulate(params, weather, stop_time)
    return rows
