"""
validate_v2.py -- implementation checks for rct_sim_v2.py
  (1) custom REML random-intercept LMM vs statsmodels MixedLM (REML) on 60 simulated
      data sets (30 at J = 56 with 8 nested strata, 10 of them with two lost clusters;
      30 at J = 28): fixed effects, arm SEs, variance components.
  (2) CR2 SEs and Bell-McCaffrey df vs a dense direct implementation
      (A_j = (I - H_jj)^(-1/2), nu = tr(B)^2 / tr(B^2), B = G'G, G_j = (I-H)[:, j] A_j X_j M c).
  (3) OLS-HC1 vs statsmodels OLS(cov_type='HC1'); two-stage cluster-level analysis vs
      statsmodels OLS on cluster-mean residuals.
Outputs: validation/reml_vs_statsmodels.csv, validation/cr2_dense.csv, validation/validation_summary.json
"""
import json, os, sys, warnings
import numpy as np, pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import rct_sim_v2 as v2

warnings.filterwarnings("ignore")
OUT = os.path.join(HERE, "validation"); os.makedirs(OUT, exist_ok=True)


def dense_cr2(X, y, g, cvecs):
    Mo = np.linalg.inv(X.T @ X); b = Mo @ X.T @ y; e = y - X @ b
    H = X @ Mo @ X.T; IH = np.eye(len(y)) - H
    meat = np.zeros((X.shape[1],) * 2); A = {}
    for j in np.unique(g):
        ix = np.where(g == j)[0]
        ev, V = np.linalg.eigh(np.eye(len(ix)) - H[np.ix_(ix, ix)])
        A[j] = (ix, V @ np.diag(ev ** -0.5) @ V.T)
        v = X[ix].T @ A[j][1] @ e[ix]; meat += np.outer(v, v)
    Vc = Mo @ meat @ Mo
    se, df = [], []
    for c in cvecs:
        Gm = np.array([IH[:, ix] @ (Aj @ X[ix] @ Mo @ c) for ix, Aj in A.values()])
        Bm = Gm @ Gm.T
        se.append(np.sqrt(c @ Vc @ c)); df.append(np.trace(Bm) ** 2 / np.sum(Bm * Bm))
    return np.array(se), np.array(df)


def main():
    rng_master = np.random.default_rng(20261106)
    rows, crow = [], []
    specs = ([dict(J=56, icc=[0.02, 0.05, 0.10, 0.15][i % 4], lose=2 if i >= 20 else 0, off_shift=0.3)
              for i in range(30)] +
             [dict(J=28, icc=[0.02, 0.05, 0.10, 0.15][i % 4]) for i in range(30)])
    for i, sp in enumerate(specs):
        p = dict(v2.DEFAULTS); p.update(sp); p.update(dB=0.3, dC=0.2)
        st = v2.structure(p["J"])
        arms = v2.draw_arms(st, "equal", rng_master, 1)
        x, y, w = v2.gen(rng_master, p, st, arms)
        Z = v2.design_Z(st, arms)
        out, ex = v2.analyse(Z, x, y, w, return_fits=True)
        c = st["c"]
        jj, ii = np.where(w[0] > 0)
        df = pd.DataFrame(dict(y=y[0, jj, ii], x=x[0, jj, ii], g=jj, armB=Z[0, jj, 1], armC=Z[0, jj, 2],
                               stratum=st["stratum"][jj]))
        X = np.column_stack([Z[0, jj, :], df.x.values])
        # ---- (1) statsmodels MixedLM, REML
        md = smf.mixedlm("y ~ armB + armC + C(stratum) + x", df, groups=df.g)
        best = None
        for meth in ("lbfgs", "bfgs", "nm"):
            try:
                f = md.fit(reml=True, method=meth, gtol=1e-10) if meth != "nm" else md.fit(reml=True, method=meth, maxiter=20000)
                if np.isfinite(f.llf) and np.all(np.isfinite(f.fe_params)) and (best is None or f.llf > best.llf + 1e-9):
                    best = f
            except Exception:
                pass
        mm = best
        fe_sm = mm.fe_params.values                          # order: Intercept, B, C, strata..., x
        names = list(mm.fe_params.index)
        order = [names.index("Intercept"), names.index("armB"), names.index("armC")] + \
                [names.index(f"C(stratum)[T.{g}]") for g in range(1, st["G"])] + [names.index("x")]
        fe_sm = fe_sm[order]
        s2u_sm, s2e_sm = float(mm.cov_re.iloc[0, 0]), float(mm.scale)
        # GLS SE at statsmodels' variance estimates (dense V)
        Vinv_blocks = np.zeros((len(df), len(df)))
        for j in np.unique(jj):
            ix = np.where(jj == j)[0]; nj = len(ix)
            Vj = s2e_sm * np.eye(nj) + s2u_sm * np.ones((nj, nj))
            Vinv_blocks[np.ix_(ix, ix)] = np.linalg.inv(Vj)
        Vgls = np.linalg.inv(X.T @ Vinv_blocks @ X)
        bl = ex["beta_lmm"][0]; Vl = ex["V_lmm"][0]
        bse_sm = mm.bse_fe.values[order]
        rows.append(dict(dataset=i, J=p["J"], J_obs=int(ex["Jobs"][0]), icc=p["icc"], N=len(df),
                         converged=bool(mm.converged), sm_method=mm.method if hasattr(mm, "method") else "",
                         max_abs_diff_fixed_effects=float(np.max(np.abs(bl - fe_sm))),
                         diff_B=float(bl[1] - fe_sm[1]), diff_C=float(bl[2] - fe_sm[2]),
                         se_B_custom=float(np.sqrt(Vl[1, 1])), se_B_statsmodels_hessian=float(bse_sm[1]),
                         se_B_gls_at_statsmodels_vc=float(np.sqrt(Vgls[1, 1])),
                         se_C_custom=float(np.sqrt(Vl[2, 2])), se_C_statsmodels_hessian=float(bse_sm[2]),
                         se_C_gls_at_statsmodels_vc=float(np.sqrt(Vgls[2, 2])),
                         s2u_custom=float(ex["s2u"][0]), s2u_statsmodels=s2u_sm,
                         s2e_custom=float(ex["sig2"][0]), s2e_statsmodels=s2e_sm,
                         llf_statsmodels=float(mm.llf)))
        # ---- (2) dense CR2 / BM ; (3) HC1 and two-stage
        Cm = v2.contrast_matrix(c)
        se_d, df_d = dense_cr2(X, df.y.values, jj, Cm)
        ols = sm.OLS(df.y.values, X).fit(cov_type="HC1")
        se_hc1 = np.sqrt(np.einsum("ka,ab,kb->k", Cm, ols.cov_params(), Cm))
        X1 = np.column_stack([Z[0, jj][:, [0] + list(range(3, c))], df.x.values])
        r1 = sm.OLS(df.y.values, X1).fit().resid
        rbar = pd.Series(r1).groupby(jj).mean()
        Zc = Z[0, rbar.index.values, :]
        s2 = sm.OLS(rbar.values, Zc).fit()
        se2 = np.sqrt(np.einsum("ka,ab,kb->k", Cm[:, :c], s2.cov_params(), Cm[:, :c]))
        for k, cn in enumerate(v2.CONTRASTS):
            crow.append(dict(dataset=i, J=p["J"], J_obs=int(ex["Jobs"][0]), contrast=cn,
                             cr2_se_custom=out["CR2_BM"][1][0, k], cr2_se_dense=se_d[k],
                             bm_df_custom=out["CR2_BM"][2][0, k], bm_df_dense=df_d[k],
                             hc1_se_custom=out["OLS_HC1"][1][0, k], hc1_se_statsmodels=se_hc1[k],
                             twostage_est_custom=out["TwoStage_CL"][0][0, k],
                             twostage_est_statsmodels=float(Cm[k, :c] @ s2.params),
                             twostage_se_custom=out["TwoStage_CL"][1][0, k], twostage_se_statsmodels=se2[k],
                             twostage_df_custom=out["TwoStage_CL"][2][0, k], twostage_df_statsmodels=s2.df_resid))
        print(i, flush=True)
    R = pd.DataFrame(rows); C = pd.DataFrame(crow)
    R.to_csv(os.path.join(OUT, "reml_vs_statsmodels.csv"), index=False)
    C.to_csv(os.path.join(OUT, "cr2_dense.csv"), index=False)
    rel = lambda a, b: float(np.max(np.abs(a / b - 1)))
    summ = dict(
        n_datasets=len(R), n_J56=int((R.J == 56).sum()), n_J56_two_clusters_lost=int((R.J_obs == 54).sum()),
        n_J28=int((R.J == 28).sum()), statsmodels_all_converged=bool(R.converged.all()),
        reml_max_abs_diff_fixed_effects=float(R.max_abs_diff_fixed_effects.max()),
        reml_max_abs_diff_s2u=float((R.s2u_custom - R.s2u_statsmodels).abs().max()),
        reml_max_abs_diff_s2e=float((R.s2e_custom - R.s2e_statsmodels).abs().max()),
        reml_max_rel_diff_se_vs_gls_at_statsmodels_vc=max(rel(R.se_B_custom, R.se_B_gls_at_statsmodels_vc),
                                                          rel(R.se_C_custom, R.se_C_gls_at_statsmodels_vc)),
        reml_max_rel_diff_se_vs_statsmodels_hessian=max(rel(R.se_B_custom, R.se_B_statsmodels_hessian),
                                                        rel(R.se_C_custom, R.se_C_statsmodels_hessian)),
        cr2_max_abs_diff_se=float((C.cr2_se_custom - C.cr2_se_dense).abs().max()),
        bm_max_abs_diff_df=float((C.bm_df_custom - C.bm_df_dense).abs().max()),
        hc1_max_abs_diff_se=float((C.hc1_se_custom - C.hc1_se_statsmodels).abs().max()),
        twostage_max_abs_diff_est=float((C.twostage_est_custom - C.twostage_est_statsmodels).abs().max()),
        twostage_max_abs_diff_se=float((C.twostage_se_custom - C.twostage_se_statsmodels).abs().max()),
        twostage_df_match=bool((C.twostage_df_custom == C.twostage_df_statsmodels).all()),
        statsmodels_version=sm.__version__ if hasattr(sm, "__version__") else __import__("statsmodels").__version__)
    json.dump(summ, open(os.path.join(OUT, "validation_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
