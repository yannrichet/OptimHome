#title: GPareto + rlibKriging surrogate-based multi-objective optimization (EGO)
#author: OptimHome (yannrichet)
#type: optimization
#options: n_init=0;iterations=30;q=1;crit=SMS;optim_method=pso;maxit=100;covtype=matern5_2;seed=42

"""
Multi-objective Efficient Global Optimization (EGO) as a native fzd algorithm,
using the R packages `GPareto` (infill criteria: SMS-EGO, EHI, EMI, SUR) and
`rlibkriging` (fast C++ kriging, `KM()` objects that are drop-in replacements
for DiceKriging's `km` objects — GPareto's criteria dispatch on them exactly
as on a `km`).

Alternative to examples/algorithms/nsga2.py (from the `fz` repo itself) for
the same vector-objective fzd() pipeline::

    fz.fzd("input.txt", {"x": "[0;1]", "y": "[0;1]"}, model,
           ["19 - min(Tser)", "max(Tser) - 26"],       # objectives, all MINIMIZED
           "gpareto_rlibkriging.py",
           algorithm_options={"n_init": 30, "iterations": 40, "q": 3})

Requires R plus the `rpy2`, `GPareto` and `rlibkriging` packages (see the
notebook's installation cell) — this module talks to R only through rpy2,
no reimplementation of the kriging/infill-criterion maths in Python.

Batches: fzd evaluates each generation in parallel across the available
calculators, exactly as nsga2.py does. Each generation here is one EGO
iteration proposing `q` points. For q > 1 the batch is built with the
"constant liar" heuristic (Ginsbourger et al., 2010): points are proposed
one at a time, each one is temporarily added to the training data with a
liar response (the current model's mean prediction) so the next proposal
in the same batch does not collapse onto the same optimum; the liars are
discarded once fzd returns the real simulator outputs.

Initial design: a scrambled Latin Hypercube (scipy.stats.qmc), not an
R/GPareto helper — plain space-filling design, no kriging involved yet.

get_analysis() writes the non-dominated set to gpareto_pareto.csv, mirroring
nsga2.py's get_analysis() (same "pareto_X"/"pareto_F" keys in the returned
"data" dict, so downstream notebook cells — clustering, plotting — are
identical for both algorithms).
"""

import csv
import os

import numpy as np
from scipy.stats import qmc


def _r_environment():
    """Import rpy2 + the R packages lazily, with an actionable error message
    if R/rpy2/GPareto/rlibkriging are missing (all installed by the notebook's
    setup cell, not a hard dependency of the rest of this repo)."""
    try:
        import rpy2.robjects as ro
        from rpy2.robjects.packages import importr
    except ImportError as e:
        raise ImportError(
            "gpareto_rlibkriging.py requires rpy2 (pip install rpy2) and a working "
            "R installation with the GPareto and rlibkriging packages."
        ) from e
    try:
        gpareto = importr("GPareto")
        rlibkriging = importr("rlibkriging")
    except Exception as e:
        raise ImportError(
            "R packages 'GPareto' and 'rlibkriging' are required "
            '(R: install.packages(c("GPareto", "rlibkriging"))).'
        ) from e
    return ro, gpareto, rlibkriging


class GParetoRlibkriging:
    """Multi-objective EGO for fzd: GPareto infill criteria over rlibkriging
    KM models, generational (one EGO iteration = one batch of q points)."""

    def __init__(self, **options):
        self._ro, self._gpareto, self._rlibkriging = _r_environment()
        self._predict_mean = self._ro.r(
            'function(m, x) predict(m, x, checkNames=FALSE)$mean'
        )

        self.n_init = int(float(options.get('n_init', 0)))  # 0 -> resolved to 6*dim below
        self.iterations = int(float(options.get('iterations', 30)))
        self.q = max(1, int(float(options.get('q', 1))))
        self.crit = str(options.get('crit', 'SMS'))
        self.optim_method = str(options.get('optim_method', 'pso'))
        self.maxit = int(float(options.get('maxit', 100)))
        self.covtype = str(options.get('covtype', 'matern5_2'))
        self.seed = int(float(options.get('seed', 42)))

        self.names, self.lo, self.hi = [], [], []
        self.X, self.Y = [], []       # all real evaluations so far (python lists)
        self.consumed = 0
        self.iter = 0

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _as_vector(out):
        if out is None:
            return None
        if isinstance(out, (list, tuple)):
            if any(v is None for v in out):
                return None
            return [float(v) for v in out]
        return [float(out)]

    @staticmethod
    def _dominates(a, b):
        return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))

    def _pareto_front_idx(self, Y):
        """Indices of the non-dominated points of Y (list of lists)."""
        n = len(Y)
        return [i for i in range(n)
                if not any(j != i and self._dominates(Y[j], Y[i]) for j in range(n))]

    def _todict(self, x):
        return {n: float(v) for n, v in zip(self.names, x)}

    # ----------------------------------------------------------------- R glue
    def _r_matrix(self, X):
        """Plain FloatVector + r.matrix(), column-major flatten — deliberately
        NOT rpy2's numpy2ri converter, which turns r.matrix()'s return value
        straight back into a numpy array instead of an R matrix object."""
        ro = self._ro
        X = np.asarray(X, dtype=float)
        flat = ro.FloatVector(X.flatten(order='F').tolist())
        return ro.r.matrix(flat, nrow=X.shape[0], ncol=X.shape[1])

    def _fit_models(self, X, Y):
        """One rlibkriging KM model per objective, fitted on (X, Y)."""
        ro = self._rlibkriging
        r_X = self._r_matrix(X)
        n_obj = len(Y[0])
        models = []
        for k in range(n_obj):
            yk = self._ro.FloatVector([y[k] for y in Y])
            models.append(ro.KM(design=r_X, response=yk, covtype=self.covtype))
        return self._ro.r['list'](*models)

    def _propose_one(self, X, Y):
        """Fit models on (X, Y) and return the next point maximizing the
        infill criterion (no objective-function call: only the models'
        predictions/uncertainty are used, cf. crit_optimizer's docstring)."""
        gpareto = self._gpareto
        models = self._fit_models(X, Y)
        front_idx = self._pareto_front_idx(Y)
        pareto_front = self._r_matrix([Y[i] for i in front_idx])
        res = gpareto.crit_optimizer(
            crit=self.crit, model=models,
            lower=self._ro.FloatVector(self.lo), upper=self._ro.FloatVector(self.hi),
            paretoFront=pareto_front,
            optimcontrol=self._ro.r['list'](method=self.optim_method, maxit=self.maxit, trace=0),
        )
        x_new = np.asarray(res.rx2('par')).flatten().tolist()
        # liar response = current models' mean prediction at x_new (constant-liar batching)
        newdata = self._r_matrix([x_new])
        y_liar = [float(np.asarray(self._predict_mean(m, newdata)).flatten()[0]) for m in models]
        return x_new, y_liar

    # ------------------------------------------------------------ fzd interface
    def get_initial_design(self, input_vars, output_vars):
        self.names = list(input_vars.keys())
        for n in self.names:
            lo, hi = input_vars[n]
            self.lo.append(float(lo))
            self.hi.append(float(hi))
        d = len(self.names)
        if self.n_init <= 0:
            self.n_init = max(6 * d, 8)

        sampler = qmc.LatinHypercube(d=d, seed=self.seed)
        unit = sampler.random(self.n_init)
        design = qmc.scale(unit, self.lo, self.hi)
        self._pending = [list(row) for row in design]
        return [self._todict(x) for x in self._pending]

    def get_next_design(self, all_inputs, all_outputs):
        for inp, out in zip(all_inputs[self.consumed:], all_outputs[self.consumed:]):
            y = self._as_vector(out)
            if y is None:
                continue    # failed simulation: drop, can't feed a GP a missing response
            self.X.append([float(inp[n]) for n in self.names])
            self.Y.append(y)
        self.consumed = len(all_outputs)

        self.iter += 1
        if self.iter > self.iterations or len(self.X) < 2:
            return []

        batch_X = list(self.X)
        batch_Y = [list(y) for y in self.Y]
        proposals = []
        for _ in range(self.q):
            x_new, y_liar = self._propose_one(batch_X, batch_Y)
            proposals.append(x_new)
            batch_X.append(x_new)
            batch_Y.append(y_liar)

        self._pending = proposals
        return [self._todict(x) for x in proposals]

    def get_analysis(self, all_inputs, all_outputs):
        front_idx = self._pareto_front_idx(self.Y) if self.Y else []
        n_obj = len(self.Y[0]) if self.Y else 0
        path = os.path.abspath("gpareto_pareto.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(self.names + [f"objective_{k + 1}" for k in range(n_obj)])
            for i in front_idx:
                w.writerow(self.X[i] + self.Y[i])
        lines = [f"GPareto/rlibkriging EGO ({self.crit}): {self.iter} iterations, "
                 f"{len(self.X)} evaluations, Pareto front: {len(front_idx)} points -> {path}"]
        for i in front_idx[:10]:
            objs = ", ".join(f"{v:.4g}" for v in self.Y[i])
            lines.append("  " + self._todict(self.X[i]).__repr__() + f" -> [{objs}]")
        return {"text": "\n".join(lines),
                "data": {"pareto_X": [self.X[i] for i in front_idx],
                         "pareto_F": [self.Y[i] for i in front_idx]}}
