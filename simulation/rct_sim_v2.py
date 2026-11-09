"""
rct_sim_v2.py -- Design analysis (ADEMP simulation study) for the planned
three-arm cluster-randomised trial of course AI-use policies (version 2).

Arms (cluster = tutorial group, mean size 25):
  A = AI prohibited (reference)    B = Socratic AI tutor    C = unrestricted AI with disclosure
  (a common verification viva is planned in all arms).
Confirmatory contrasts B-A and C-A (two-sided, Holm, FWER 0.05); B-C exploratory.

Design (exactly as planned)
  J = 28: one offering of 28 groups, 4 strata of 7 groups.
  J = 56: two offerings x 28 groups, 4 strata of 7 WITHIN each offering
          (8 strata nested in offering).
  Equal allocation 10:9:9 per offering: each stratum of 7 gets 2-2-2 plus one extra;
  the four extras of an offering are the multiset {A, A, B, C}, assigned to the four
  strata in random order. Control-heavy 12:8:8 per offering = 3:2:2 in every stratum.
  Per-replicate randomisation: every simulated trial draws a fresh allocation (an
  independent random permutation of the extras over the strata of each offering, and a
  random permutation of the arm labels over the groups of each stratum) from a layout
  stream that is separate from the data stream. Mode 'legacy' instead uses the fixed
  layout of rct_sim.py v1 (J = 28 only) to reproduce v1 results exactly.
  General J (sample-size search): J/2 groups per offering, each offering split into
  4 near-equal strata; per stratum floor(size/3) per arm; the remaining extras of an
  offering are the cyclic multiset A,B,C,A,... assigned at random (no stratum receives
  two extras of the same arm).

Analysis model (all estimators share the fixed-effect design)
  X = [1, B, C, stratum dummies (G-1, nested strata; offering is absorbed), pre-test]
  c = number of cluster-level fixed-effect parameters = 3 + (G - 1)
    = 6 at J = 28 (G = 4) and 10 at J = 56 (G = 8).
Estimators (code -> label)
  OLS_HC1     'OLS-HC1 ignoring clustering'          individual OLS, HC1, t(N - p)
  LMM_z       'LMM Wald z'                           REML random-intercept LMM, z
  LMM_tJc     'LMM t(J-c) (planned)'                 same fit, t on J_obs - c df
  CR2_tJc     'CR2 with t(J-c)'                      OLS + CR2 SEs, t on J_obs - c df
  CR2_BM      'CR2 with Bell-McCaffrey df'           OLS + CR2 SEs, Bell-McCaffrey df
  TwoStage_CL 'Two-stage cluster-level analysis'     stage 1: OLS of y on [1, strata, x]
              (no arm); stage 2: unweighted OLS of covariate-adjusted cluster-mean
              residuals on [1, B, C, strata]; t on J_obs - c df.
  J_obs = number of clusters with >= 1 analysed student (= J unless clusters are lost).

Usage
  python rct_sim_v2.py --shard k --nshards K [--families base,sens,...]  -> shards/res_k.csv
  python rct_sim_v2.py --merge                                           -> results/
  python rct_sim_v2.py --manifest                                        -> results/scenario_manifest.csv
"""
import argparse, json, os, sys, time, zlib
import numpy as np
import pandas as pd
from scipy import stats, optimize

BASE_SEED = 20261104
ALPHA = 0.05
NBAR = 25
CONTRASTS = ["BvsA", "CvsA", "BvsC"]
ESTIMATORS = ["OLS_HC1", "LMM_z", "LMM_tJc", "CR2_tJc", "CR2_BM", "TwoStage_CL"]
LABELS = {"OLS_HC1": "OLS-HC1 ignoring clustering",
          "LMM_z": "LMM Wald z",
          "LMM_tJc": "LMM t(J-c) (planned)",
          "CR2_tJc": "CR2 with t(J-c)",
          "CR2_BM": "CR2 with Bell-McCaffrey df",
          "TwoStage_CL": "Two-stage cluster-level analysis"}
HERE = os.path.dirname(os.path.abspath(__file__))


# =================================================================== design ===
def structure(J, n_off=None):
    """Fixed trial structure: offering, stratum (global index), position, tutor."""
    if n_off is None:
        n_off = 1 if J <= 28 else 2
    sizes_off = [len(a) for a in np.array_split(np.arange(J), n_off)]
    offering, stratum, pos = [], [], []
    g = 0
    for o, mo in enumerate(sizes_off):
        for s_sz in [len(a) for a in np.array_split(np.arange(mo), 4)]:
            offering += [o] * s_sz; stratum += [g] * s_sz; pos += list(range(s_sz))
            g += 1
    offering, stratum, pos = map(np.array, (offering, stratum, pos))
    G = g
    tutor = None
    if J == 56 and n_off == 2 and all(np.bincount(stratum) == 7):
        s_in_off = stratum % 4
        tutor = pos + 7 * (s_in_off // 2)          # 14 tutors x 4 groups, 2 per offering
        assert np.all(np.bincount(tutor) == 4)
    return dict(J=J, n_off=n_off, offering=offering, stratum=stratum, pos=pos, G=G,
                c=3 + G - 1, tutor=tutor)


def _stratum_plan(struct, alloc):
    """Per offering: list of (indices, base counts per arm, n_extras) and extras multiset."""
    plan = []
    for o in range(struct["n_off"]):
        strata = [g for g in np.unique(struct["stratum"][struct["offering"] == o])]
        items = []
        for g in strata:
            idx = np.where(struct["stratum"] == g)[0]
            s = len(idx)
            if alloc == "equal":
                base = np.array([s // 3] * 3); r = s % 3
            elif alloc == "control_heavy":
                if s != 7:
                    raise ValueError("control-heavy 3:2:2 requires strata of 7")
                base = np.array([3, 2, 2]); r = 0
            else:
                raise ValueError(alloc)
            items.append((idx, base, r))
        E = sum(it[2] for it in items)
        extras = np.sort(np.array([k % 3 for k in range(E)], int))   # A,A,B,C for E = 4
        plan.append((items, extras))
    return plan


def draw_arms(struct, alloc, rng, R):
    """Per-replicate stratified allocation, shape (R, J)."""
    plan = _stratum_plan(struct, alloc)
    arms = np.empty((R, struct["J"]), int)
    for r in range(R):
        for items, extras in plan:
            while True:
                perm = rng.permutation(extras) if len(extras) else extras
                cuts = np.cumsum([0] + [it[2] for it in items])
                ok = all(len(set(perm[cuts[k]:cuts[k + 1]])) == cuts[k + 1] - cuts[k]
                         for k in range(len(items)))
                if ok:
                    break
            for k, (idx, base, nr) in enumerate(items):
                lab = np.concatenate([np.repeat([0, 1, 2], base), perm[cuts[k]:cuts[k + 1]]])
                arms[r, idx] = rng.permutation(lab)
    return arms


def legacy_arms(struct, alloc):
    """Fixed v1 layout for J = 28 (extras A, A, B, C in strata 1..4, arms sorted)."""
    plan = _stratum_plan(struct, alloc)
    arms = np.empty(struct["J"], int)
    for items, extras in plan:
        cuts = np.cumsum([0] + [it[2] for it in items])
        for k, (idx, base, nr) in enumerate(items):
            f = base.copy()
            for e in extras[cuts[k]:cuts[k + 1]]:
                f[e] += 1
            arms[idx] = np.repeat([0, 1, 2], f)
    return arms


def design_Z(struct, arms):
    """Cluster-level design (R, J, c): 1, B, C, stratum dummies 2..G."""
    R, J = arms.shape
    c = struct["c"]
    Z = np.zeros((R, J, c))
    Z[..., 0] = 1
    Z[..., 1] = arms == 1
    Z[..., 2] = arms == 2
    for g in range(1, struct["G"]):
        Z[..., 2 + g] = (struct["stratum"] == g)[None, :]
    return Z


def arm_totals(J, alloc, n_off=None):
    st = structure(J, n_off)
    return np.bincount(legacy_arms(st, alloc), minlength=3)


# ======================================================== data generation ===
DEFAULTS = dict(J=56, alloc="equal", icc=0.05, R2=0.3, R2b=None, cv=0.3, attr=0.1,
                dB=0.3, dC=0.3, off_shift=0.0, het=None, sdC=1.0, miss="mcar",
                miss_arm=None, consent=None, lose=0, tutor_share=0.0,
                ncA=0.0, ncA_delta=0.0, leakB=0.0, bounded=False, layout="random",
                n_off=None)
BOUND = dict(scale=15.0, step=5.0, q=0.90)
BOUND["mu"] = 100.0 - BOUND["scale"] * stats.norm.ppf(BOUND["q"])


def logit_intercept(target, slope, mu=0.0):
    """a0 with E[expit(a0 + slope*Z)] = target, Z ~ N(mu, 1) (Gauss-Hermite)."""
    gx, gw = np.polynomial.hermite_e.hermegauss(80)
    gw = gw / gw.sum()
    f = lambda a0: (gw / (1 + np.exp(-(a0 + slope * (gx + mu))))).sum() - target
    return optimize.brentq(f, -30, 30)


MISS_SLOPE = -1.0        # log-odds of missingness per SD (lower x / y -> more missing)
CONSENT_SLOPE = 0.5      # log-odds of consent per SD of pre-test
CONSENT_ARM = (0.65, 0.80, 0.80)
CONSENT_BETA = (0.75, 0.10)


def tau_matrix(p, struct, arms):
    """Arm effect for each replicate x cluster (R, J)."""
    R, J = arms.shape
    if p["het"] is None:
        t = np.array([0.0, p["dB"], p["dC"]])
        return t[arms]
    tau = np.zeros((R, J))
    for o, dd in enumerate(p["het"]):          # het = ((dB_o1, dC_o1), (dB_o2, dC_o2))
        t = np.array([0.0, dd[0], dd[1]])
        sel = struct["offering"] == o
        tau[:, sel] = t[arms[:, sel]]
    return tau


def gen(rng, p, struct, arms):
    """Simulate one batch. arms (R, J). Returns x, y, w (R, J, nmax).
    The base branch consumes the RNG exactly as rct_sim.py v1."""
    R, J = arms.shape
    icc, R2, cv = p["icc"], p["R2"], p["cv"]
    if cv == 0:
        m = np.full((R, J), NBAR)
    else:
        k = 1 / cv ** 2
        m = np.clip(np.rint(rng.gamma(k, NBAR / k, (R, J))), 12, 75).astype(int)
    nmax = int(m.max())
    a = rng.standard_normal((R, J))
    u = rng.standard_normal((R, J))
    b = rng.standard_normal((R, J, nmax))
    e = rng.standard_normal((R, J, nmax))
    x = np.sqrt(icc) * a[..., None] + np.sqrt(1 - icc) * b
    tau = tau_matrix(p, struct, arms)[..., None]
    isA, isB, isC = [(arms == k)[..., None] for k in range(3)]
    R2b = R2 if p["R2b"] is None else p["R2b"]
    sdC = p["sdC"]
    if R2b == R2 and sdC == 1.0:
        y = (tau + np.sqrt(R2) * x
             + np.sqrt(icc * (1 - R2)) * u[..., None]
             + np.sqrt((1 - icc) * (1 - R2)) * e)
    else:          # pre-test explains R2b of between- and R2 of within-cluster variance
        resid = np.sqrt(icc * (1 - R2b)) * u[..., None] + np.sqrt((1 - icc) * (1 - R2)) * e
        resid = resid * np.where(isC, sdC, 1.0)
        y = (tau + np.sqrt(icc * R2b) * a[..., None] + np.sqrt((1 - icc) * R2) * b + resid)
    if p["ncA"] > 0:                 # covert AI use in arm A, effect delta vs compliant A
        nc = rng.random((R, J, nmax)) < p["ncA"]
        y = y + p["ncA_delta"] * nc * isA
    w = (np.arange(nmax)[None, None, :] < m[..., None])
    # ---- missingness of the outcome
    if p["miss"] == "mcar":
        if p["attr"] > 0:
            w &= rng.random((R, J, nmax)) >= p["attr"]
    elif p["miss"] == "diff_arm":
        rate = np.array(p["miss_arm"])[arms][..., None]
        w &= rng.random((R, J, nmax)) >= rate
    elif p["miss"] == "mar_x":
        a0 = logit_intercept(p["attr"], MISS_SLOPE)
        w &= rng.random((R, J, nmax)) >= 1 / (1 + np.exp(-(a0 + MISS_SLOPE * x)))
    elif p["miss"] == "mnar_y":
        a0 = logit_intercept(p["attr"], MISS_SLOPE)       # calibrated to 10 % in arm A at null
        w &= rng.random((R, J, nmax)) >= 1 / (1 + np.exp(-(a0 + MISS_SLOPE * y)))
    else:
        raise ValueError(p["miss"])
    # ---- extra components (drawn after the v1 sequence)
    if p["leakB"] > 0:               # share of arm B using unrestricted AI -> arm C effect
        lk = rng.random((R, J, nmax)) < p["leakB"]
        y = y + (p["dC"] - p["dB"]) * lk * isB
    if p["tutor_share"] > 0:
        s = p["tutor_share"]
        v = rng.standard_normal((R, int(struct["tutor"].max()) + 1))
        y = tau + np.sqrt(1 - s) * (y - tau) + np.sqrt(s) * v[:, struct["tutor"]][..., None]
    if p["off_shift"] != 0:
        y = y + p["off_shift"] * (struct["offering"] == 1)[None, :, None]
    if p["consent"] == "cluster_beta":
        mu_, sd_ = CONSENT_BETA
        kk = mu_ * (1 - mu_) / sd_ ** 2 - 1
        pj = rng.beta(mu_ * kk, (1 - mu_) * kk, (R, J))
        w &= rng.random((R, J, nmax)) < pj[..., None]
    elif p["consent"] == "arm_diff_x":
        b0 = np.array([logit_intercept(q, CONSENT_SLOPE) for q in CONSENT_ARM])[arms][..., None]
        w &= rng.random((R, J, nmax)) < 1 / (1 + np.exp(-(b0 + CONSENT_SLOPE * x)))
    if p["lose"] > 0:
        lost = np.argsort(rng.random((R, J)), axis=1)[:, :p["lose"]]
        keep = np.ones((R, J), bool)
        np.put_along_axis(keep, lost, False, axis=1)
        w &= keep[..., None]
    if p["bounded"]:
        raw = BOUND["mu"] + BOUND["scale"] * y
        y = np.clip(BOUND["step"] * np.round(raw / BOUND["step"]), 0, 100)
    return x, y, w.astype(float)


def bounded_mean(tau):
    """E[min(100, max(0, step*round((mu + scale*Y)/step)))], Y ~ N(tau, 1)."""
    st, sc, mu = BOUND["step"], BOUND["scale"], BOUND["mu"]
    vals = np.arange(0, 100 + st, st)
    edges = np.concatenate([[-np.inf], vals[:-1] + st / 2, [np.inf]])
    z = (edges - mu) / sc - tau
    pr = np.diff(stats.norm.cdf(z))
    return float((pr * vals).sum())


def truths(p):
    """ITT truths (B-A, C-A, B-C) on the analysis scale."""
    if p["het"] is not None:
        tB = np.mean([h[0] for h in p["het"]]); tC = np.mean([h[1] for h in p["het"]])
    else:
        tB, tC = p["dB"], p["dC"]
    tB = tB + p["leakB"] * (p["dC"] - p["dB"])
    tA = p["ncA"] * p["ncA_delta"]
    if p["bounded"]:
        mA, mB, mC = (bounded_mean(t) for t in (tA, tB, tC))
        return np.array([mB - mA, mC - mA, mB - mC])
    return np.array([tB - tA, tC - tA, tB - tC])


# =============================================================== estimators ===
def sym_fn(Mat, fn):
    ev, V = np.linalg.eigh(Mat)
    return np.einsum("...ik,...k,...jk->...ij", V, fn(ev), V)


def assemble(Z, n, Sx, Sxx, Sy, Sxy):
    R, J, c = Z.shape
    P = c + 1
    XtX = np.empty((R, P, P))
    XtX[:, :c, :c] = (Z * n[..., None]).swapaxes(1, 2) @ Z
    zx = np.einsum("rj,rja->ra", Sx, Z)
    XtX[:, :c, c] = zx; XtX[:, c, :c] = zx
    XtX[:, c, c] = Sxx.sum(1)
    Xty = np.empty((R, P))
    Xty[:, :c] = np.einsum("rj,rja->ra", Sy, Z)
    Xty[:, c] = Sxy.sum(1)
    return XtX, Xty


def reml_fit(Z, n, Sx, Sy, Syy, XtX, Xty, grid_n=31, rho_max=0.6, iters=22):
    """Exact REML for the random-intercept LMM from cluster sufficient statistics.
    Profiles sigma_e^2; maximises over rho_r = s_u^2/(s_u^2+s_e^2) in [0, rho_max]."""
    R, J, c = Z.shape
    P = c + 1
    s = np.concatenate([n[..., None] * Z, Sx[..., None]], axis=2)      # (R,J,P) = X_j'1
    SS = (s[..., :, None] * s[..., None, :]).reshape(R, J, P * P)
    Sy_s = s * Sy[..., None]
    yy = Syy.sum(1)
    N = n.sum(1)

    def evalf(rho):
        lam = rho / (1 - rho)
        wgt = lam[..., None] / (1 + n[:, None, :] * lam[..., None])
        M = XtX[:, None] - (wgt @ SS).reshape(R, -1, P, P)
        v = Xty[:, None] - wgt @ Sy_s
        cc = yy[:, None] - np.einsum("rgj,rj->rg", wgt, Sy ** 2)
        beta = np.linalg.solve(M, v[..., None])[..., 0]
        rss = cc - np.einsum("rgp,rgp->rg", v, beta)
        _, ld = np.linalg.slogdet(M)
        ldH = np.log1p(n[:, None, :] * lam[..., None]).sum(-1)
        ll = -0.5 * ((N[:, None] - P) * np.log(rss / (N[:, None] - P)) + ldH + ld)
        return ll, beta, rss, M

    grid = np.linspace(0, rho_max, grid_n)
    llg = evalf(np.broadcast_to(grid, (R, grid_n)).copy())[0]
    k = llg.argmax(1)
    lo = grid[np.clip(k - 1, 0, grid_n - 1)]
    hi = grid[np.clip(k + 1, 0, grid_n - 1)]
    gr = (np.sqrt(5) - 1) / 2
    x1 = hi - gr * (hi - lo); x2 = lo + gr * (hi - lo)
    f1 = evalf(x1[:, None])[0][:, 0]; f2 = evalf(x2[:, None])[0][:, 0]
    for _ in range(iters):
        left = f1 > f2
        lo2 = np.where(left, lo, x1); hi2 = np.where(left, x2, hi)
        x1n = np.where(left, hi2 - gr * (hi2 - lo2), x2)
        x2n = np.where(left, x1, lo2 + gr * (hi2 - lo2))
        fnew = evalf(np.where(left, x1n, x2n)[:, None])[0][:, 0]
        f1, f2 = np.where(left, fnew, f2), np.where(left, f1, fnew)
        lo, hi, x1, x2 = lo2, hi2, x1n, x2n
    xb = np.where(f1 > f2, x1, x2); fb = np.maximum(f1, f2)
    gbest = grid[k]; gval = llg[np.arange(R), k]
    rho_hat = np.where(gval > fb, gbest, xb)
    ll, beta, rss, M = evalf(rho_hat[:, None])
    beta = beta[:, 0]; M = M[:, 0]
    sig2 = rss[:, 0] / (N - P)
    V = sig2[:, None, None] * np.linalg.inv(M)
    s2u = rho_hat / (1 - rho_hat) * sig2
    return beta, V, rho_hat, ll[:, 0], sig2, s2u


def contrast_matrix(c):
    P = c + 1
    Cm = np.zeros((3, P))
    Cm[0, 1] = 1; Cm[1, 2] = 1; Cm[2, 1] = 1; Cm[2, 2] = -1
    return Cm


def analyse(Z, x, y, w, return_fits=False):
    """dict estimator -> (est[R,3], se[R,3], df[R,3]); extras."""
    R, J, c = Z.shape
    P = c + 1
    n = w.sum(-1)
    wx, wy = w * x, w * y
    Sx, Sy = wx.sum(-1), wy.sum(-1)
    Sxx, Sxy, Syy = (wx * x).sum(-1), (wx * y).sum(-1), (wy * y).sum(-1)
    N = n.sum(1)
    nonempty = (n > 0).astype(float)
    Jobs = nonempty.sum(1)
    XtX, Xty = assemble(Z, n, Sx, Sxx, Sy, Sxy)
    Mo = np.linalg.inv(XtX)
    beta = np.einsum("rab,rb->ra", Mo, Xty)
    Cm = contrast_matrix(c)
    out = {}
    con = lambda V: np.sqrt(np.einsum("ka,rab,kb->rk", Cm, V, Cm))
    dfJc = np.repeat((Jobs - c)[:, None], 3, 1)

    est_ols = beta @ Cm.T
    fit_c = np.einsum("ra,rja->rj", beta[:, :c], Z)
    res = w * (y - fit_c[..., None] - beta[:, c, None, None] * x)
    se2 = (res * res).sum(-1); se2x = (res * res * x).sum(-1); se2xx = (res * res * x * x).sum(-1)
    meat = np.empty((R, P, P))
    meat[:, :c, :c] = (Z * se2[..., None]).swapaxes(1, 2) @ Z
    meat[:, :c, c] = np.einsum("rj,rja->ra", se2x, Z); meat[:, c, :c] = meat[:, :c, c]
    meat[:, c, c] = se2xx.sum(1)
    V_hc1 = (N / (N - P))[:, None, None] * Mo @ meat @ Mo
    out["OLS_HC1"] = (est_ols, con(V_hc1), np.repeat((N - P)[:, None], 3, 1))

    # ---- CR2 via 2x2 per-cluster algebra (X_j = U_j C_j, U_j = [1, x_j])
    Ue = np.stack([res.sum(-1), (res * x).sum(-1)], -1)
    W = np.empty((R, J, 2, 2))
    W[..., 0, 0] = n; W[..., 0, 1] = W[..., 1, 0] = Sx; W[..., 1, 1] = Sxx
    Cj = np.zeros((R, J, 2, P)); Cj[:, :, 0, :c] = Z; Cj[:, :, 1, c] = 1
    CjT = Cj.swapaxes(-1, -2)
    G = Cj @ Mo[:, None] @ CjT
    tol = 1e-10
    Rs = sym_fn(W, lambda ev: np.sqrt(np.clip(ev, 0, None)))
    Ri = sym_fn(W, lambda ev: np.where(ev > tol, 1 / np.sqrt(np.clip(ev, tol, None)), 0.0))
    K = Rs @ G @ Rs
    E1 = sym_fn(K, lambda ev: 1 / np.sqrt(1 - ev))
    E2 = sym_fn(K, lambda ev: 1 / (1 - ev))
    UAe = np.einsum("rjab,rjb->rja", Rs @ E1 @ Ri, Ue)
    XAe = (CjT @ UAe[..., None])[..., 0]
    V_cr2 = Mo @ (XAe.swapaxes(1, 2) @ XAe) @ Mo
    se_cr2 = con(V_cr2)
    UAU = Rs @ E1 @ Rs; UA2U = Rs @ E2 @ Rs
    df_bm = np.empty((R, 3))
    for k, cvec in enumerate(Cm):
        Mc = Mo @ cvec
        t = (Cj @ Mc[:, None, :, None])[..., 0]
        gg = (t[..., None, :] @ UA2U @ t[..., None])[..., 0, 0] * nonempty
        q = (CjT @ (UAU @ t[..., None]))[..., 0] * nonempty[..., None]
        B = -((q @ Mo) @ q.swapaxes(1, 2))
        B[:, np.arange(J), np.arange(J)] += gg
        trB = np.einsum("rjj->r", B)
        df_bm[:, k] = trB ** 2 / (B * B).sum((1, 2))
    out["CR2_BM"] = (est_ols, se_cr2, df_bm)
    out["CR2_tJc"] = (est_ols, se_cr2, dfJc)

    # ---- LMM (REML)
    bl, Vl, rho_hat, ll, sig2, s2u = reml_fit(Z, n, Sx, Sy, Syy, XtX, Xty)
    est_l = bl @ Cm.T; se_l = con(Vl)
    out["LMM_z"] = (est_l, se_l, np.full((R, 3), np.inf))
    out["LMM_tJc"] = (est_l, se_l, dfJc)

    # ---- two-stage cluster-level analysis
    keep = [0] + list(range(3, c)) + [c]
    b1 = np.linalg.solve(XtX[:, keep][:, :, keep], Xty[:, keep][..., None])[..., 0]
    Z1 = Z[..., [0] + list(range(3, c))]
    rsum = Sy - n * np.einsum("ra,rja->rj", b1[:, :-1], Z1) - b1[:, -1, None] * Sx
    rbar = np.where(n > 0, rsum / np.maximum(n, 1), 0.0)
    ZtWZ = (Z * nonempty[..., None]).swapaxes(1, 2) @ Z
    ZtWr = np.einsum("rj,rja,rj->ra", nonempty, Z, rbar)
    Mi = np.linalg.inv(ZtWZ)
    th = np.einsum("rab,rb->ra", Mi, ZtWr)
    r2 = nonempty * (rbar - np.einsum("ra,rja->rj", th, Z)) ** 2
    dfc = Jobs - c
    Vc = (r2.sum(1) / dfc)[:, None, None] * Mi
    Cmc = Cm[:, :c]
    out["TwoStage_CL"] = (th @ Cmc.T, np.sqrt(np.einsum("ka,rab,kb->rk", Cmc, Vc, Cmc)),
                          np.repeat(dfc[:, None], 3, 1))
    extras = {"lmm_boundary": rho_hat < 1e-6, "lmm_rho": rho_hat, "N": N, "Jobs": Jobs}
    if return_fits:
        extras.update(beta_ols=beta, V_hc1=V_hc1, V_cr2=V_cr2, beta_lmm=bl, V_lmm=Vl,
                      sig2=sig2, s2u=s2u, reml_ll=ll, th2=th, V2=Vc)
    return out, extras


# ============================================================== performance ===
def pvals(est, se, df):
    t = est / se
    dff = np.where(np.isinf(df), 1e6, df)
    p = np.where(np.isinf(df), 2 * stats.norm.sf(np.abs(t)), 2 * stats.t.sf(np.abs(t), dff))
    crit = np.where(np.isinf(df), stats.norm.ppf(0.975), stats.t.ppf(0.975, dff))
    return p, crit


def binom_se(v):
    m = v.mean(); return m, np.sqrt(m * (1 - m) / len(v))


def holm(pb, pc, alpha=ALPHA):
    pmin, pmax = np.minimum(pb, pc), np.maximum(pb, pc)
    step1 = pmin <= alpha / 2
    both = step1 & (pmax <= alpha)
    rejB = np.where(pb <= pc, step1, both)
    rejC = np.where(pc < pb, step1, both)
    return step1, both, rejB, rejC


def perf(outs, truth, null_flags):
    rows = {}
    for e in ESTIMATORS:
        est = np.concatenate([o[e][0] for o in outs]); se = np.concatenate([o[e][1] for o in outs])
        df = np.concatenate([o[e][2] for o in outs])
        R = est.shape[0]
        p, crit = pvals(est, se, df)
        r = {"n_rep": R}
        for k, cn in enumerate(CONTRASTS):
            rej = p[:, k] < ALPHA
            cov = np.abs(est[:, k] - truth[k]) <= crit[:, k] * se[:, k]
            r[f"{cn}_rej"], r[f"{cn}_rej_mcse"] = binom_se(rej)
            r[f"{cn}_cov"], r[f"{cn}_cov_mcse"] = binom_se(cov)
            bias = est[:, k] - truth[k]
            r[f"{cn}_bias"] = bias.mean(); r[f"{cn}_bias_mcse"] = bias.std(ddof=1) / np.sqrt(R)
            esd = est[:, k].std(ddof=1)
            r[f"{cn}_empSE"] = esd; r[f"{cn}_empSE_mcse"] = esd / np.sqrt(2 * (R - 1))
            r[f"{cn}_modSE"] = np.sqrt(np.mean(se[:, k] ** 2))
            fin = np.isfinite(df[:, k])
            r[f"{cn}_df_mean"] = float(df[fin, k].mean()) if fin.any() else np.inf
        any_, both, rB, rC = holm(p[:, 0], p[:, 1])
        fw = np.zeros(R, bool)                       # familywise error over true nulls
        if null_flags[0]: fw |= rB
        if null_flags[1]: fw |= rC
        for nm, v in [("holm_any", any_), ("holm_both", both), ("holm_BvsA", rB),
                      ("holm_CvsA", rC), ("holm_FWER", fw)]:
            r[nm], r[nm + "_mcse"] = binom_se(v)
        if not (null_flags[0] or null_flags[1]):
            r["holm_FWER"] = np.nan; r["holm_FWER_mcse"] = np.nan
        rows[e] = r
    return rows


# ================================================================= analytic ===
def analytic_var(JA, JB, icc, R2, nbar, cv):
    de = 1 + ((cv ** 2 + 1) * nbar - 1) * icc
    return (1 - R2) * (1 / JA + 1 / JB) * de / nbar


def analytic_power(d, JA, JB, df, icc, R2, nbar, cv, alpha=ALPHA):
    ncp = d / np.sqrt(analytic_var(JA, JB, icc, R2, nbar, cv))
    tc = stats.t.ppf(1 - alpha / 2, df)
    return stats.nct.sf(tc, df, ncp) + stats.nct.cdf(-tc, df, ncp)


def analytic_mdes(JA, JB, df, icc, R2, nbar, cv, alpha=ALPHA, power=0.8):
    M = stats.t.ppf(1 - alpha / 2, df) + stats.t.ppf(power, df)
    return M * np.sqrt(analytic_var(JA, JB, icc, R2, nbar, cv))


# ================================================================ scenarios ===
def v1_sid(family, J, alloc, icc, R2, cv, attr, c, pattern, d):
    base = dict(family=family, J=J, alloc=alloc, icc=icc, R2=R2, cv=cv, attr=attr, c=c,
                pattern=pattern, d=d)
    return "|".join(f"{a}={base[a]}" for a in
                    ["family", "J", "alloc", "icc", "R2", "cv", "attr", "c", "pattern", "d"])


def scenarios():
    sc = []

    def add(sid, family, seed_key=None, reps=None, null=None, **kw):
        p = dict(DEFAULTS); p.update(kw)
        if null is None:
            null = (p["dB"] == 0 and p["dC"] == 0 and p["het"] is None)
        if reps is None:
            reps = 2000 if null else 1000
        sc.append(dict(scenario_id=sid, family=family, seed_key=seed_key or sid, reps=reps,
                       params=p))

    al = {"equal": "eq", "control_heavy": "ch"}
    # ---- base grid (J = 28 and 56); seeds identical to v1 (same data streams)
    for J in (28, 56):
        for alloc in ("equal", "control_heavy"):
            for icc in (0.02, 0.05, 0.10, 0.15):
                for R2 in (0.0, 0.3, 0.5):
                    for cv in (0.0, 0.3):
                        for d in (0.0, 0.2, 0.3, 0.4):
                            add(f"BASE-J{J}-{al[alloc]}-icc{icc}-R{R2}-cv{cv}-d{d}", "base",
                                seed_key=v1_sid("base", J, alloc, icc, R2, cv, 0.1, 0.0, "both", d),
                                J=J, alloc=alloc, icc=icc, R2=R2, cv=cv, dB=d, dC=d)
    # ---- partial null (B effective, C null), v1 seeds
    for J in (28, 56):
        for alloc in ("equal", "control_heavy"):
            for icc in (0.05, 0.10):
                for d in (0.3, 0.4):
                    add(f"PNULL-J{J}-{al[alloc]}-icc{icc}-dB{d}-dC0", "partial_null",
                        seed_key=v1_sid("partial_null", J, "equal" if alloc == "equal" else alloc,
                                        icc, 0.3, 0.3, 0.1, 0.0, "B_only", d),
                        reps=2000, null=True, J=J, alloc=alloc, icc=icc, dB=d, dC=0.0)
    # ---- v1 reproduction check: J = 28 fixed v1 layout, v1 seeds
    for alloc in ("equal", "control_heavy"):
        for icc in (0.02, 0.05, 0.10, 0.15):
            for d in (0.0, 0.2, 0.3, 0.4):
                add(f"LEGACY-J28-{al[alloc]}-icc{icc}-R0.3-cv0.3-d{d}", "legacy_check",
                    seed_key=v1_sid("base", 28, alloc, icc, 0.3, 0.3, 0.1, 0.0, "both", d),
                    J=28, alloc=alloc, icc=icc, R2=0.3, cv=0.3, dB=d, dC=d, layout="legacy")
    # ---- sample size (two offerings, J/2 groups each)
    for icc, Js in ((0.05, range(36, 58, 2)), (0.10, range(56, 86, 2))):
        for J in Js:
            add(f"SSIZE-J{J}-icc{icc}", "ssize", reps=2000, J=J, n_off=2, icc=icc)
    # ---- sensitivity families at J = 56 (equal allocation, R2 0.3, CV 0.3, 10 % attrition)
    for icc in (0.05, 0.10):
        t = f"icc{icc}"
        for d in (0.0, 0.3):
            for R2b in (0.0, 0.6):
                add(f"S1-R2w0.3-R2b{R2b}-{t}-d{d}", "S1_R2_by_level", icc=icc, R2b=R2b, dB=d, dC=d)
            for R2 in (0.1, 0.2):
                add(f"S2-R2{R2}-{t}-d{d}", "S2_low_R2", icc=icc, R2=R2, dB=d, dC=d)
            add(f"S3-bounded-{t}-d{d}", "S3_bounded", icc=icc, bounded=True, dB=d, dC=d)
            add(f"S4-MARx-{t}-d{d}", "S4_missing", icc=icc, miss="mar_x", dB=d, dC=d)
            add(f"S4-MNARy-{t}-d{d}", "S4_missing", icc=icc, miss="mnar_y", dB=d, dC=d)
            add(f"S4-diffarm-{t}-d{d}", "S4_missing", icc=icc, miss="diff_arm",
                miss_arm=(0.10, 0.15, 0.20), dB=d, dC=d)
            add(f"S5-consent-cluster-{t}-d{d}", "S5_consent", icc=icc, consent="cluster_beta", dB=d, dC=d)
            add(f"S5-consent-armdiff-x-{t}-d{d}", "S5_consent", icc=icc, consent="arm_diff_x", dB=d, dC=d)
            add(f"S5-lose2clusters-{t}-d{d}", "S5_consent", icc=icc, lose=2, dB=d, dC=d)
            add(f"S6-sdC1.2-{t}-d{d}", "S6_arm_variance", icc=icc, sdC=1.2, dB=d, dC=d)
            add(f"S8-offshift0.3-{t}-d{d}", "S8_offering", icc=icc, off_shift=0.3, dB=d, dC=d)
            add(f"S9-tutors-{t}-d{d}", "S9_tutors", icc=icc, tutor_share=0.03, dB=d, dC=d)
        for dB, dC in ((0.3, 0.15), (0.3, -0.3), (0.3, 0.0)):
            add(f"S7-dB{dB}-dC{dC}-{t}", "S7_unequal", icc=icc, dB=dB, dC=dC,
                null=(dC == 0), reps=2000 if dC == 0 else 1000)
        add(f"S8-het0.4-0.2-{t}", "S8_offering", icc=icc, dB=0.3, dC=0.3,
            het=((0.4, 0.4), (0.2, 0.2)), reps=1000, null=False)
        add(f"S8-het0.1--0.1-{t}", "S8_offering", icc=icc, dB=0.0, dC=0.0,
            het=((0.1, 0.1), (-0.1, -0.1)), reps=2000, null=True)
        for cA in (0.2, 0.4):
            for delta in (-0.3, 0.0, 0.3):
                add(f"S10-A-c{cA}-delta{delta}-{t}", "S10_noncompliance", icc=icc,
                    ncA=cA, ncA_delta=delta, reps=1000, null=False)
        for dB, dC in ((0.3, 0.3), (0.3, 0.15), (0.3, 0.0)):
            add(f"S10-Bleak0.2-dB{dB}-dC{dC}-{t}", "S10_noncompliance", icc=icc, leakB=0.2,
                dB=dB, dC=dC, reps=1000, null=False)
    return sc


def null_flags_of(truth):
    return [abs(truth[0]) < 1e-12, abs(truth[1]) < 1e-12]


def seeds(seed_key):
    k = zlib.crc32(seed_key.encode())
    return (np.random.SeedSequence(BASE_SEED, spawn_key=(k,)),
            np.random.SeedSequence(BASE_SEED, spawn_key=(k, 1)), k)


def run_scenario(s, batch=500, keep_raw=False):
    t0 = time.time()
    p = s["params"]
    st = structure(p["J"], p["n_off"])
    ss_data, ss_lay, _ = seeds(s["seed_key"])
    rng = np.random.default_rng(ss_data)
    rlay = np.random.default_rng(ss_lay)
    truth = truths(p)
    nf = null_flags_of(truth) if not p["bounded"] else [p["dB"] == 0, p["dC"] == 0]
    outs, ex, raws = [], [], []
    left = s["reps"]
    while left > 0:
        R = min(batch, left)
        if p["layout"] == "legacy":
            arms = np.repeat(legacy_arms(st, p["alloc"])[None], R, 0)
        else:
            arms = draw_arms(st, p["alloc"], rlay, R)
        x, y, w = gen(rng, p, st, arms)
        o, e = analyse(design_Z(st, arms), x, y, w)
        outs.append(o); ex.append(e); left -= R
    rows = perf(outs, truth, nf)
    T = np.bincount(legacy_arms(st, p["alloc"]), minlength=3)
    nbar_a = NBAR * (1 - p["attr"])
    recs = []
    for est, r in rows.items():
        rec = dict(scenario_id=s["scenario_id"], family=s["family"], J=p["J"], n_off=st["n_off"],
                   n_strata=st["G"], c=st["c"], alloc=p["alloc"], icc=p["icc"], R2=p["R2"],
                   R2b=p["R2"] if p["R2b"] is None else p["R2b"], cv=p["cv"], attr=p["attr"],
                   dB=p["dB"], dC=p["dC"], layout=p["layout"], nA=T[0], nB=T[1], nC=T[2],
                   estimator=est, estimator_label=LABELS[est],
                   true_BvsA=truth[0], true_CvsA=truth[1], true_BvsC=truth[2],
                   null_BvsA=nf[0], null_CvsA=nf[1])
        rec.update(r)
        rec["lmm_boundary_frac"] = float(np.mean(np.concatenate([e["lmm_boundary"] for e in ex])))
        rec["lmm_rho_hat_mean"] = float(np.mean(np.concatenate([e["lmm_rho"] for e in ex])))
        rec["N_analysed_mean"] = float(np.mean(np.concatenate([e["N"] for e in ex])))
        rec["J_obs_mean"] = float(np.mean(np.concatenate([e["Jobs"] for e in ex])))
        if not p["bounded"]:
            rec["analytic_power_BvsA"] = analytic_power(truth[0], T[0], T[1], p["J"] - st["c"],
                                                        p["icc"], p["R2"], nbar_a, p["cv"])
            rec["analytic_power_CvsA"] = analytic_power(truth[1], T[0], T[2], p["J"] - st["c"],
                                                        p["icc"], p["R2"], nbar_a, p["cv"])
        rec["seconds"] = time.time() - t0
        recs.append(rec)
    return recs


def manifest(sc):
    rows = []
    for s in sc:
        _, _, k = seeds(s["seed_key"])
        p = s["params"]
        st = structure(p["J"], p["n_off"])
        par = {k2: v for k2, v in p.items() if v != DEFAULTS[k2] or k2 in ("J", "icc", "dB", "dC")}
        rows.append(dict(scenario_id=s["scenario_id"], family=s["family"], J=p["J"],
                         n_offerings=st["n_off"], n_strata=st["G"], c=st["c"], df_planned=p["J"] - st["c"],
                         alloc=p["alloc"], layout=p["layout"],
                         parameters=json.dumps(par, sort_keys=True), replications=s["reps"],
                         base_seed=BASE_SEED, seed_key=s["seed_key"], seed_spawn_key_crc32=k,
                         contrast_cells=3, confirmatory_contrast_cells=2))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int); ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--families", default=None)
    ap.add_argument("--outdir", default=os.path.join(HERE, "shards"))
    ap.add_argument("--merge", action="store_true"); ap.add_argument("--manifest", action="store_true")
    a = ap.parse_args()
    resdir = os.path.join(HERE, "results")
    if a.manifest:
        os.makedirs(resdir, exist_ok=True)
        m = manifest(scenarios()); m.to_csv(os.path.join(resdir, "scenario_manifest.csv"), index=False)
        print(m.groupby("family").agg(n=("scenario_id", "size"), reps=("replications", "sum")))
    elif a.merge:
        fs = sorted(f for f in os.listdir(a.outdir) if f.endswith(".csv"))
        df = pd.concat([pd.read_csv(os.path.join(a.outdir, f)) for f in fs])
        order = {s["scenario_id"]: i for i, s in enumerate(scenarios())}
        df["_o"] = df.scenario_id.map(order); df["_e"] = df.estimator.map({e: i for i, e in enumerate(ESTIMATORS)})
        df = df.sort_values(["_o", "_e"]).drop(columns=["_o", "_e"])
        os.makedirs(resdir, exist_ok=True)
        df.to_csv(os.path.join(resdir, "rct_design_results_v2.csv"), index=False)
        print(df.shape, df.scenario_id.nunique())
    else:
        sc = scenarios()
        if a.families:
            fam = set(a.families.split(","))
            sc = [s for s in sc if s["family"] in fam]
        cost = [s["reps"] * s["params"]["J"] for s in sc]
        order = np.argsort(-np.array(cost), kind="stable")
        mine = [sc[i] for k, i in enumerate(order) if k % a.nshards == a.shard]
        os.makedirs(a.outdir, exist_ok=True)
        recs, t0 = [], time.time()
        for i, s in enumerate(mine):
            recs.extend(run_scenario(s))
            print(f"shard {a.shard}: {i+1}/{len(mine)} {s['scenario_id']} {time.time()-t0:.0f}s", flush=True)
            pd.DataFrame(recs).to_csv(os.path.join(a.outdir, f"res_{a.shard}.partial"), index=False)
        pd.DataFrame(recs).to_csv(os.path.join(a.outdir, f"res_{a.shard}.csv"), index=False)
        print(f"shard {a.shard} done {len(mine)} scenarios in {time.time()-t0:.0f}s")
