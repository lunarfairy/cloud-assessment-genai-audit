"""
rct_sim.py -- Design analysis (ADEMP simulation study) for a pre-registered
three-arm cluster-randomised trial of generative-AI policies in an
undergraduate cloud-computing course.

Arms (cluster = tutorial group):
  A = AI prohibited (process logging + use declaration)      [reference]
  B = institution-provided Socratic AI tutor (hints only)
  C = unrestricted AI + mandatory individual verification viva
Confirmatory contrasts: B-A and C-A (two-sided, Holm, FWER 0.05); B-C exploratory.

Data-generating model (standardised outcome, total SD 1):
  x_ij = sqrt(rho) a_j + sqrt(1-rho) b_ij                     (a, b ~ N(0,1))
  y_ij = tau_arm(j) + sqrt(R2) x_ij + sqrt(rho (1-R2)) u_j
         + sqrt((1-rho)(1-R2)) e_ij + d * NC_ij * 1[arm(j)=A]   (u, e ~ N(0,1))
  so the outcome ICC is rho, the covariate explains R2 of both the between-
  and within-cluster variance, and the residual ICC is also rho.
  NC_ij ~ Bernoulli(c): arm-A students who use AI anyway (ITT dilution).
  Cluster sizes: m_j = 25 (CV 0) or round(Gamma(shape 1/CV^2, scale 25 CV^2))
  clipped to [12, 75]. MCAR attrition: each outcome missing w.p. `attr`.
  Strata: 4, clusters assigned round-robin; arms allocated within strata
  (largest-remainder rule).  No stratum effect in the DGM (no credit taken).

Estimators (design X = [1, B, C, S2, S3, S4, x], p = 7):
  OLS_HC1     individual-level OLS, HC1 SEs, t(N-p)
  LMM_z       REML random-intercept LMM, Wald z
  LMM_t       same, t with J-6 df (between-within: J minus the 6 cluster-level
              fixed-effect columns 1,B,C,S2..S4)
  CR2_BM      OLS + CR2 (Bell-McCaffrey) SEs, Satterthwaite df per contrast
              (working-independence model; = clubSandwich Satterthwaite for lm)
  CR2_tJ6     OLS + CR2 SEs, t with J-6 df
  CL_HM       Hayes-Moulton two-stage cluster-level analysis: stage 1 OLS of y on
              [1, strata, x] ignoring arm; stage 2 unweighted OLS of cluster-mean
              residuals on [1, B, C, strata], t with (#non-empty clusters - 6) df.

Usage:
  python rct_sim.py --validate
  python rct_sim.py --shard k --nshards K      -> shards/res_k.csv
  python rct_sim.py --merge                    -> rct_design_results.csv
"""
import argparse, json, os, sys, time, zlib
import numpy as np
import pandas as pd
from scipy import stats

BASE_SEED = 20261104
ALPHA = 0.05
NBAR = 25
P = 7
IDX = {"BvsA": np.array([0, 1, 0, 0, 0, 0, 0.]),
       "CvsA": np.array([0, 0, 1, 0, 0, 0, 0.]),
       "BvsC": np.array([0, 1, -1, 0, 0, 0, 0.])}
CONTRASTS = list(IDX)
ESTIMATORS = ["OLS_HC1", "LMM_z", "LMM_t", "CR2_BM", "CR2_tJ6", "CL_HM"]


# ----------------------------------------------------------------- design ---
def arm_totals(J, alloc):
    if alloc == "equal":
        nb = J // 3
        return np.array([J - 2 * nb, nb, nb])
    na = int(round(3 * J / 7))            # control-heavy 12:8:8 (J=28)
    nb = (J - na) // 2
    return np.array([J - 2 * nb, nb, nb])


def layout(J, alloc, n_strata=4):
    strata = np.arange(J) % n_strata
    strata = np.sort(strata)
    T = arm_totals(J, alloc).astype(float)
    arms = np.empty(J, int)
    remaining = T.copy()
    rem_size = J
    for s in range(n_strata):
        idx = np.where(strata == s)[0]
        m = len(idx)
        q = remaining * m / rem_size
        f = np.floor(q).astype(int)
        extra = m - f.sum()
        order = np.argsort(-(q - f), kind="stable")
        f[order[:extra]] += 1
        arms[idx] = np.repeat([0, 1, 2], f)
        remaining -= f
        rem_size -= m
    Z = np.zeros((J, 6))
    Z[:, 0] = 1
    Z[:, 1] = arms == 1
    Z[:, 2] = arms == 2
    for s in range(1, n_strata):
        Z[:, 2 + s] = strata == s
    return arms, strata, Z


# ---------------------------------------------------------- data generation ---
def gen(rng, arms, icc, R2, cv, attr, tau, c_nc, d_nc, R):
    J = len(arms)
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
    y = (tau[arms][None, :, None] + np.sqrt(R2) * x
         + np.sqrt(icc * (1 - R2)) * u[..., None]
         + np.sqrt((1 - icc) * (1 - R2)) * e)
    if c_nc > 0:
        nc = rng.random((R, J, nmax)) < c_nc
        y = y + d_nc * nc * (arms == 0)[None, :, None]
    w = (np.arange(nmax)[None, None, :] < m[..., None])
    if attr > 0:
        w &= rng.random((R, J, nmax)) >= attr
    return x, y, w.astype(float)


# -------------------------------------------------------------- estimators ---
def assemble(Z, n, Sx, Sxx, Sy, Sxy):
    """X'X (R,7,7) and X'y (R,7) from cluster sufficient statistics."""
    R = n.shape[0]
    XtX = np.empty((R, P, P))
    XtX[:, :6, :6] = np.einsum("rj,ja,jb->rab", n, Z, Z)
    zx = Sx @ Z
    XtX[:, :6, 6] = zx
    XtX[:, 6, :6] = zx
    XtX[:, 6, 6] = Sxx.sum(1)
    Xty = np.empty((R, P))
    Xty[:, :6] = Sy @ Z
    Xty[:, 6] = Sxy.sum(1)
    return XtX, Xty


def sym_fn(Mat, fn):
    """Apply fn to eigenvalues of batched symmetric 2x2 matrices."""
    ev, V = np.linalg.eigh(Mat)
    return np.einsum("...ik,...k,...jk->...ij", V, fn(ev), V)


def reml_fit(Z, n, Sx, Sxx, Sy, Sxy, Syy, XtX, Xty, grid_n=31, rho_max=0.6, iters=22):
    """Exact REML for the random-intercept LMM using cluster sufficient stats.
    Profiles sigma^2; maximises over rho_r = s_u^2/(s_u^2+s_e^2) in [0, rho_max]."""
    R, J = n.shape
    s = np.concatenate([n[..., None] * Z[None], Sx[..., None]], axis=2)  # (R,J,7) = X_j'1
    SS = np.einsum("rja,rjb->rjab", s, s).reshape(R, J, P * P)
    Sy_s = s * Sy[..., None]                                              # (R,J,7)
    yy = Syy.sum(1)
    N = n.sum(1)

    def evalf(rho):  # rho shape (R,G)
        lam = rho / (1 - rho)
        wgt = lam[..., None] / (1 + n[:, None, :] * lam[..., None])       # (R,G,J)
        M = XtX[:, None] - (wgt @ SS).reshape(R, -1, P, P)
        v = Xty[:, None] - wgt @ Sy_s
        c = yy[:, None] - np.einsum("rgj,rj->rg", wgt, Sy ** 2)
        beta = np.linalg.solve(M, v[..., None])[..., 0]
        rss = c - np.einsum("rgp,rgp->rg", v, beta)
        _, ld = np.linalg.slogdet(M)
        ldH = np.log1p(n[:, None, :] * lam[..., None]).sum(-1)
        ll = -0.5 * ((N[:, None] - P) * np.log(rss / (N[:, None] - P)) + ldH + ld)
        return ll, beta, rss, M

    grid = np.linspace(0, rho_max, grid_n)
    llg, _, _, _ = evalf(np.broadcast_to(grid, (R, grid_n)).copy())
    k = llg.argmax(1)
    lo = grid[np.clip(k - 1, 0, grid_n - 1)]
    hi = grid[np.clip(k + 1, 0, grid_n - 1)]
    gr = (np.sqrt(5) - 1) / 2
    x1 = hi - gr * (hi - lo); x2 = lo + gr * (hi - lo)
    f1 = evalf(x1[:, None])[0][:, 0]; f2 = evalf(x2[:, None])[0][:, 0]
    for _ in range(iters):                       # golden-section maximisation
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
    return beta, V, rho_hat, ll[:, 0]


def analyse(Z, x, y, w):
    """Return dict est -> (est[R,3], se[R,3], df[R,3] or inf), plus extras."""
    R, J, _ = x.shape
    n = w.sum(-1)
    wx, wy = w * x, w * y
    Sx, Sy = wx.sum(-1), wy.sum(-1)
    Sxx, Sxy, Syy = (wx * x).sum(-1), (wx * y).sum(-1), (wy * y).sum(-1)
    N = n.sum(1)
    XtX, Xty = assemble(Z, n, Sx, Sxx, Sy, Sxy)
    Mo = np.linalg.inv(XtX)
    beta = np.einsum("rab,rb->ra", Mo, Xty)
    Cm = np.stack(list(IDX.values()))                      # (3,7)
    out = {}

    def con(V):
        return np.sqrt(np.einsum("ka,rab,kb->rk", Cm, V, Cm))

    est_ols = beta @ Cm.T
    # residuals
    fit_c = beta[:, :6] @ Z.T                              # (R,J)
    res = w * (y - fit_c[..., None] - beta[:, 6, None, None] * x)
    se2 = (res * res).sum(-1); se2x = (res * res * x).sum(-1); se2xx = (res * res * x * x).sum(-1)
    meat = np.empty((R, P, P))
    meat[:, :6, :6] = np.einsum("rj,ja,jb->rab", se2, Z, Z)
    meat[:, :6, 6] = se2x @ Z; meat[:, 6, :6] = meat[:, :6, 6]
    meat[:, 6, 6] = se2xx.sum(1)
    V_hc1 = (N / (N - P))[:, None, None] * Mo @ meat @ Mo
    dfo = np.repeat((N - P)[:, None], 3, 1)
    out["OLS_HC1"] = (est_ols, con(V_hc1), dfo)

    # ---- CR2 (Bell-McCaffrey) via 2x2 per-cluster algebra
    Ue = np.stack([res.sum(-1), (res * x).sum(-1)], -1)    # (R,J,2) = U_j' e_j
    W = np.empty((R, J, 2, 2))
    W[..., 0, 0] = n; W[..., 0, 1] = W[..., 1, 0] = Sx; W[..., 1, 1] = Sxx
    Cj = np.zeros((J, 2, P)); Cj[:, 0, :6] = Z; Cj[:, 1, 6] = 1
    G = np.einsum("jap,rpq,jbq->rjab", Cj, Mo, Cj)
    tol = 1e-10
    Rs = sym_fn(W, lambda ev: np.sqrt(np.clip(ev, 0, None)))
    Ri = sym_fn(W, lambda ev: np.where(ev > tol, 1 / np.sqrt(np.clip(ev, tol, None)), 0.0))
    K = Rs @ G @ Rs
    E1 = sym_fn(K, lambda ev: 1 / np.sqrt(1 - ev))
    E2 = sym_fn(K, lambda ev: 1 / (1 - ev))
    UAe = np.einsum("rjab,rjb->rja", Rs @ E1 @ Ri, Ue)
    XAe = np.einsum("jap,rja->rjp", Cj, UAe)               # (R,J,7)
    V_cr2 = Mo @ np.einsum("rja,rjb->rab", XAe, XAe) @ Mo
    se_cr2 = con(V_cr2)
    UAU = Rs @ E1 @ Rs; UA2U = Rs @ E2 @ Rs
    nonempty = (n > 0).astype(float)
    df_bm = np.empty((R, 3))
    for k, cvec in enumerate(Cm):
        Mc = Mo @ cvec                                     # (R,7)
        t = np.einsum("jap,rp->rja", Cj, Mc)               # (R,J,2)
        gg = np.einsum("rja,rjab,rjb->rj", t, UA2U, t) * nonempty
        q = np.einsum("jap,rjab,rjb->rjp", Cj, UAU, t) * nonempty[..., None]
        B = -np.einsum("rjp,rpq,rkq->rjk", q, Mo, q)
        B[:, np.arange(J), np.arange(J)] += gg
        trB = np.einsum("rjj->r", B)
        df_bm[:, k] = trB ** 2 / (B * B).sum((1, 2))
    out["CR2_BM"] = (est_ols, se_cr2, df_bm)
    out["CR2_tJ6"] = (est_ols, se_cr2, np.full((R, 3), J - 6.0))

    # ---- LMM (REML)
    bl, Vl, rho_hat, _ = reml_fit(Z, n, Sx, Sxx, Sy, Sxy, Syy, XtX, Xty)
    est_l = bl @ Cm.T; se_l = con(Vl)
    out["LMM_z"] = (est_l, se_l, np.full((R, 3), np.inf))
    out["LMM_t"] = (est_l, se_l, np.full((R, 3), J - 6.0))

    # ---- Hayes-Moulton two-stage cluster-level analysis
    keep = [0, 3, 4, 5, 6]
    b1 = np.linalg.solve(XtX[:, keep][:, :, keep], Xty[:, keep][..., None])[..., 0]
    Z1 = Z[:, [0, 3, 4, 5]]
    rsum = Sy - n * (b1[:, :4] @ Z1.T) - b1[:, 4, None] * Sx
    rbar = np.where(n > 0, rsum / np.maximum(n, 1), 0.0)
    ZtWZ = np.einsum("rj,ja,jb->rab", nonempty, Z, Z)
    ZtWr = np.einsum("rj,ja,rj->ra", nonempty, Z, rbar)
    Mi = np.linalg.inv(ZtWZ)
    th = np.einsum("rab,rb->ra", Mi, ZtWr)
    r2 = nonempty * (rbar - th @ Z.T) ** 2
    dfc = nonempty.sum(1) - 6
    s2 = r2.sum(1) / dfc
    Vc = s2[:, None, None] * Mi
    Cm6 = Cm[:, :6]
    out["CL_HM"] = (th @ Cm6.T, np.sqrt(np.einsum("ka,rab,kb->rk", Cm6, Vc, Cm6)),
                    np.repeat(dfc[:, None], 3, 1))
    extras = {"lmm_boundary": float(np.mean(rho_hat < 1e-6)),
              "lmm_rho_mean": float(rho_hat.mean()),
              "N_mean": float(N.mean())}
    return out, extras


# -------------------------------------------------------- performance ---
def pvals(est, se, df):
    t = est / se
    p = np.where(np.isinf(df), 2 * stats.norm.sf(np.abs(t)),
                 2 * stats.t.sf(np.abs(t), np.where(np.isinf(df), 1e6, df)))
    crit = np.where(np.isinf(df), stats.norm.ppf(0.975),
                    stats.t.ppf(0.975, np.where(np.isinf(df), 1e6, df)))
    return p, crit


def perf(outs, truth):
    """Pool lists of replicate outputs into performance measures per estimator."""
    rows = {}
    for e in ESTIMATORS:
        est = np.concatenate([o[e][0] for o in outs]); se = np.concatenate([o[e][1] for o in outs])
        df = np.concatenate([o[e][2] for o in outs])
        R = est.shape[0]
        p, crit = pvals(est, se, df)
        r = {"n_rep": R}
        for k, cname in enumerate(CONTRASTS):
            rej = p[:, k] < ALPHA
            cov = np.abs(est[:, k] - truth[k]) <= crit[:, k] * se[:, k]
            r[f"{cname}_rej"] = rej.mean(); r[f"{cname}_rej_mcse"] = np.sqrt(rej.mean() * (1 - rej.mean()) / R)
            r[f"{cname}_cov"] = cov.mean(); r[f"{cname}_cov_mcse"] = np.sqrt(cov.mean() * (1 - cov.mean()) / R)
            bias = est[:, k] - truth[k]
            r[f"{cname}_bias"] = bias.mean(); r[f"{cname}_bias_mcse"] = bias.std(ddof=1) / np.sqrt(R)
            r[f"{cname}_empSE"] = est[:, k].std(ddof=1)
            r[f"{cname}_modSE"] = np.sqrt(np.mean(se[:, k] ** 2))
            r[f"{cname}_df_mean"] = float(np.mean(np.where(np.isinf(df[:, k]), np.nan, df[:, k]))) if np.isfinite(df[:, k]).any() else np.inf
        # Holm on the two confirmatory contrasts
        pb, pc = p[:, 0], p[:, 1]
        pmin, pmax = np.minimum(pb, pc), np.maximum(pb, pc)
        step1 = pmin <= ALPHA / 2
        both = step1 & (pmax <= ALPHA)
        rejB = np.where(pb <= pc, step1, both)
        rejC = np.where(pc < pb, step1, both)
        for nm, v in [("holm_any", step1), ("holm_both", both), ("holm_BvsA", rejB), ("holm_CvsA", rejC)]:
            r[nm] = v.mean(); r[nm + "_mcse"] = np.sqrt(v.mean() * (1 - v.mean()) / R)
        rows[e] = r
    return rows


# --------------------------------------------------------------- analytic ---
def analytic_var(JA, JB, icc, R2, nbar, cv):
    """Variance of a pairwise contrast (Raudenbush 1997 / Bloom 2005, with
    Eldridge et al. 2006 CV-inflated design effect)."""
    de = 1 + ((cv ** 2 + 1) * nbar - 1) * icc
    return (1 - R2) * (1 / JA + 1 / JB) * de / nbar


def analytic_power(d, JA, JB, J, icc, R2, nbar, cv, alpha=ALPHA, df=None):
    df = J - 6 if df is None else df
    ncp = d / np.sqrt(analytic_var(JA, JB, icc, R2, nbar, cv))
    tc = stats.t.ppf(1 - alpha / 2, df)
    return stats.nct.sf(tc, df, ncp) + stats.nct.cdf(-tc, df, ncp)


def analytic_mdes(JA, JB, J, icc, R2, nbar, cv, alpha=ALPHA, power=0.8, df=None):
    df = J - 6 if df is None else df
    M = stats.t.ppf(1 - alpha / 2, df) + stats.t.ppf(power, df)
    return M * np.sqrt(analytic_var(JA, JB, icc, R2, nbar, cv))


def clusters_needed(d, icc, R2, cv, attr=0.1, alpha=ALPHA, target=0.8):
    for J in range(9, 400):
        T = arm_totals(J, "equal")
        if T.min() < 2 or J - 6 < 2:
            continue
        if analytic_power(d, T[0], T[1], J, icc, R2, NBAR * (1 - attr), cv, alpha) >= target:
            return J
    return None


# -------------------------------------------------------------- scenarios ---
def scenarios():
    sc = []
    def add(**k):
        base = dict(attr=0.1, c=0.0, pattern="both", reps=None, family="base")
        base.update(k)
        if base["reps"] is None:
            base["reps"] = 2000 if base["d"] == 0 or base["pattern"] == "B_only" else 1000
        base["sid"] = "|".join(f"{a}={base[a]}" for a in
                               ["family", "J", "alloc", "icc", "R2", "cv", "attr", "c", "pattern", "d"])
        sc.append(base)
    for J in (28, 56):
        for alloc in ("equal", "control_heavy"):
            for icc in (0.02, 0.05, 0.10, 0.15):
                for R2 in (0.0, 0.3, 0.5):
                    for cv in (0.0, 0.3):
                        for d in (0.0, 0.2, 0.3, 0.4):
                            add(J=J, alloc=alloc, icc=icc, R2=R2, cv=cv, d=d)
    for J in (28, 56):                                   # attrition 20 % sensitivity
        for icc in (0.02, 0.05, 0.10, 0.15):
            for d in (0.0, 0.2, 0.3, 0.4):
                add(family="attr20", J=J, alloc="equal", icc=icc, R2=0.3, cv=0.3, d=d, attr=0.2)
    for J in (28, 56):                                   # non-compliance in arm A
        for alloc in ("equal", "control_heavy"):
            for icc in (0.05, 0.10):
                for c in (0.2, 0.4):
                    for d in (0.2, 0.3, 0.4):
                        add(family="noncomp", J=J, alloc=alloc, icc=icc, R2=0.3, cv=0.3, d=d, c=c)
    for J in (28, 56):                                   # partial null (only B effective)
        for alloc in ("equal", "control_heavy"):
            for icc in (0.05, 0.10):
                for d in (0.3, 0.4):
                    add(family="partial_null", J=J, alloc=alloc, icc=icc, R2=0.3, cv=0.3, d=d,
                        pattern="B_only")
    seen = set()                                         # sample-size verification
    for icc in (0.05, 0.10):
        for alpha in (0.05, 0.025):
            Jn = clusters_needed(0.3, icc, 0.3, 0.3, alpha=alpha)
            if (Jn, icc) in seen or Jn in (28, 56):
                continue
            seen.add((Jn, icc))
            add(family="ssize", J=Jn, alloc="equal", icc=icc, R2=0.3, cv=0.3, d=0.3, reps=2000)
    # bracket the J giving 80 % Holm-adjusted power per contrast (between the
    # alpha=0.05 and alpha=0.025 analytic answers)
    for icc, Js in ((0.05, (40, 42, 44)), (0.10, (58, 60, 62, 64))):
        for Jn in Js:
            add(family="ssize", J=Jn, alloc="equal", icc=icc, R2=0.3, cv=0.3, d=0.3, reps=2000)
    return sc


def run_scenario(s, batch=500):
    t0 = time.time()
    arms, strata, Z = layout(s["J"], s["alloc"])
    d = s["d"]
    tau = np.array([0.0, d, d if s["pattern"] == "both" else 0.0])
    tA = s["c"] * d                                      # ITT mean shift in arm A
    truth = np.array([tau[1] - tA, tau[2] - tA, tau[1] - tau[2]])
    ss = np.random.SeedSequence(BASE_SEED, spawn_key=(zlib.crc32(s["sid"].encode()),))
    rng = np.random.default_rng(ss)
    outs, ex = [], []
    left = s["reps"]
    while left > 0:
        R = min(batch, left)
        x, y, w = gen(rng, arms, s["icc"], s["R2"], s["cv"], s["attr"], tau, s["c"], d, R)
        o, e = analyse(Z, x, y, w)
        outs.append(o); ex.append(e); left -= R
    rows = perf(outs, truth)
    T = np.bincount(arms, minlength=3)
    recs = []
    for est, r in rows.items():
        rec = {k: s[k] for k in ["sid", "family", "J", "alloc", "icc", "R2", "cv", "attr", "c", "pattern", "d"]}
        rec.update(nA=T[0], nB=T[1], nC=T[2], estimator=est,
                   true_BvsA=truth[0], true_CvsA=truth[1], true_BvsC=truth[2])
        rec.update(r)
        rec["lmm_boundary_frac"] = np.mean([e["lmm_boundary"] for e in ex])
        rec["lmm_rho_hat_mean"] = np.mean([e["lmm_rho_mean"] for e in ex])
        rec["N_analysed_mean"] = np.mean([e["N_mean"] for e in ex])
        nbar = NBAR * (1 - s["attr"])
        rec["analytic_power_BvsA"] = analytic_power(truth[0], T[0], T[1], s["J"], s["icc"], s["R2"], nbar, s["cv"])
        rec["analytic_power_CvsA"] = analytic_power(truth[1], T[0], T[2], s["J"], s["icc"], s["R2"], nbar, s["cv"])
        rec["seconds"] = time.time() - t0
        recs.append(rec)
    return recs


# --------------------------------------------------------------- validate ---
def validate():
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    rng = np.random.default_rng(1)
    arms, strata, Z = layout(28, "equal")
    x, y, w = gen(rng, arms, 0.08, 0.3, 0.3, 0.1, np.array([0, .3, .2]), 0.0, 0.0, 4)
    out, _ = analyse(Z, x, y, w)
    report = {}
    for r in range(4):
        rows = []
        for j in range(28):
            for i in range(x.shape[2]):
                if w[r, j, i] > 0:
                    rows.append(dict(y=y[r, j, i], x=x[r, j, i], g=j, B=Z[j, 1], C=Z[j, 2],
                                     S2=Z[j, 3], S3=Z[j, 4], S4=Z[j, 5]))
        df = pd.DataFrame(rows)
        X = sm.add_constant(df[["B", "C", "S2", "S3", "S4", "x"]]).values
        ols = sm.OLS(df.y.values, X).fit(cov_type="HC1")
        mm = smf.mixedlm("y ~ B + C + S2 + S3 + S4 + x", df, groups=df.g).fit(reml=True)
        # dense CR2 + BM df
        Mo = np.linalg.inv(X.T @ X); e = df.y.values - X @ (Mo @ X.T @ df.y.values)
        H = X @ Mo @ X.T; meat = np.zeros((7, 7)); g = df.g.values
        Aj = {}
        for j in range(28):
            ix = np.where(g == j)[0]
            ev, V = np.linalg.eigh(np.eye(len(ix)) - H[np.ix_(ix, ix)])
            Aj[j] = (ix, V @ np.diag(ev ** -0.5) @ V.T)
            v = X[ix].T @ Aj[j][1] @ e[ix]; meat += np.outer(v, v)
        Vcr2 = Mo @ meat @ Mo
        c = IDX["BvsA"]; IH = np.eye(len(e)) - H
        hs = []
        for j in range(28):
            ix, A = Aj[j]
            gj = A @ X[ix] @ Mo @ c
            h = IH[:, ix] @ gj; hs.append(h)
        Hm = np.array(hs); Bm = Hm @ Hm.T
        dfbm = np.trace(Bm) ** 2 / np.sum(Bm * Bm)
        report[r] = dict(
            ols_est=(out["OLS_HC1"][0][r, 0], ols.params[1]),
            hc1_se=(out["OLS_HC1"][1][r, 0], ols.bse[1]),
            lmm_est=(out["LMM_z"][0][r, 0], mm.fe_params["B"]),
            lmm_se=(out["LMM_z"][1][r, 0], mm.bse_fe["B"]),
            cr2_se=(out["CR2_BM"][1][r, 0], np.sqrt(c @ Vcr2 @ c)),
            bm_df=(out["CR2_BM"][2][r, 0], dfbm))
    maxdiff = {k: max(abs(report[r][k][0] - report[r][k][1]) for r in report) for k in report[0]}
    return report, maxdiff


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int); ap.add_argument("--nshards", type=int, default=1)
    ap.add_argument("--merge", action="store_true"); ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    if a.validate:
        rep, md = validate(); print(json.dumps({k: float(v) for k, v in md.items()}, indent=1))
    elif a.merge:
        fs = sorted(f for f in os.listdir("shards") if f.endswith(".csv"))
        df = pd.concat([pd.read_csv(os.path.join("shards", f)) for f in fs])
        df.to_csv("rct_design_results.csv", index=False); print(df.shape)
    else:
        sc = scenarios()
        os.makedirs("shards", exist_ok=True)
        # interleave by cost so shards are balanced
        mine = [s for i, s in enumerate(sc) if i % a.nshards == a.shard]
        recs, t0 = [], time.time()
        for i, s in enumerate(mine):
            recs.extend(run_scenario(s))
            if i % 10 == 0:
                print(f"shard {a.shard}: {i+1}/{len(mine)} {time.time()-t0:.0f}s", flush=True)
                pd.DataFrame(recs).to_csv(f"shards/res_{a.shard}.partial", index=False)
        pd.DataFrame(recs).to_csv(f"shards/res_{a.shard}.csv", index=False)
        print(f"shard {a.shard} done {len(mine)} scenarios in {time.time()-t0:.0f}s")
