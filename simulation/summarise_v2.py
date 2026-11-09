"""
summarise_v2.py -- derive all reported tables and rct_design_summary_v2.json from
results/rct_design_results_v2.csv, results/scenario_manifest.csv, the v1 results
(for the J = 28 checks; path via env RCT_V1_RESULTS, default ../inp/rct_design_results.csv)
and validation/validation_summary.json.
"""
import json, os, sys
import numpy as np, pandas as pd
from scipy import stats
import statsmodels.api as sm

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import rct_sim_v2 as v2

RES = os.path.join(HERE, "results")
df = pd.read_csv(os.path.join(RES, "rct_design_results_v2.csv"))
man = pd.read_csv(os.path.join(RES, "scenario_manifest.csv"))
V1 = os.environ.get("RCT_V1_RESULTS", os.path.join(HERE, "inputs", "rct_design_results_v1.csv"))
S = {}
r4 = lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4)
PL, BM = "LMM_tJc", "CR2_BM"

# ------------------------------------------------------------- manifest ----
assert set(man.scenario_id) == set(df.scenario_id) and len(df) == 6 * len(man)
nrep = df.groupby("scenario_id").n_rep.first()
assert (nrep.reindex(man.scenario_id).values == man.replications.values).all()
fam = man.groupby("family").agg(scenarios=("scenario_id", "size"), simulated_trials=("replications", "sum"))
fam["contrast_cells"] = 3 * fam.scenarios; fam["confirmatory_contrast_cells"] = 2 * fam.scenarios
S["manifest"] = dict(
    terminology="scenario = one parameter combination (one row of scenario_manifest.csv); contrast cell = scenario x contrast "
                "(3 per scenario: B-A, C-A confirmatory; B-C exploratory); every estimator is applied to the same simulated trials",
    total_scenarios=int(len(man)), total_simulated_trials=int(man.replications.sum()),
    total_contrast_cells=int(3 * len(man)), total_confirmatory_contrast_cells=int(2 * len(man)),
    estimator_fits=int(6 * man.replications.sum()),
    by_family={k: {c: int(v) for c, v in r.items()} for k, r in fam.iterrows()})
fam.to_csv(os.path.join(RES, "manifest_reconciliation.csv"))

# ------------------------------------------------------- long contrast cells
long = []
for cn in v2.CONTRASTS:
    cols = [c for c in df.columns if c.startswith(cn + "_")]
    t = df[["scenario_id", "family", "J", "c", "alloc", "icc", "R2", "R2b", "cv", "dB", "dC", "estimator",
            "estimator_label", "n_rep", "true_" + cn]].copy()
    t["contrast"] = cn
    t = t.rename(columns={"true_" + cn: "truth"})
    for c in cols:
        t[c[len(cn) + 1:]] = df[c].values
    t["holm_rej"] = df["holm_" + cn] if cn != "BvsC" else np.nan
    t["holm_rej_mcse"] = df["holm_" + cn + "_mcse"] if cn != "BvsC" else np.nan
    t["is_null"] = (t.truth.abs() < 1e-12) if True else None
    long.append(t)
long = pd.concat(long, ignore_index=True)
long.to_csv(os.path.join(RES, "contrast_cells_long.csv"), index=False)

# ------------------------------------------------------------ type I error ---
base = df[df.family == "base"]
nul = base[base.dB == 0]
t1 = []
for J in (28, 56):
    for e in v2.ESTIMATORS:
        s = nul[(nul.J == J) & (nul.estimator == e)]
        v = np.concatenate([s.BvsA_rej.values, s.CvsA_rej.values])
        lo, hi = 0.05 - 1.96 * np.sqrt(0.05 * 0.95 / 2000), 0.05 + 1.96 * np.sqrt(0.05 * 0.95 / 2000)
        t1.append(dict(J=J, c=int(s.c.iloc[0]), df_planned=J - int(s.c.iloc[0]), estimator=e,
                       label=v2.LABELS[e], n_cells=len(v), mean=v.mean(), min=v.min(), max=v.max(),
                       n_above_mc_band=int((v > hi).sum()), n_below_mc_band=int((v < lo).sum()),
                       BvsC_mean=s.BvsC_rej.mean(), BvsC_max=s.BvsC_rej.max(),
                       holm_FWER_mean=s.holm_FWER.mean(), holm_FWER_max=s.holm_FWER.max()))
t1 = pd.DataFrame(t1); t1.to_csv(os.path.join(RES, "type1_by_estimator.csv"), index=False)
S["type1_error_base_nulls"] = dict(
    note="96 contrast cells (48 null scenarios x B-A, C-A) per J, 2,000 replications each (MC SE ~0.0049 at 0.05; "
         "95% MC band 0.0404-0.0596)",
    table={f"J{r.J}_{r.estimator}": dict(label=r.label, mean=r4(r["mean"]), min=r4(r["min"]), max=r4(r["max"]),
                                          n_above_band=int(r.n_above_mc_band), n_below_band=int(r.n_below_mc_band),
                                          holm_FWER_max=r4(r.holm_FWER_max)) for _, r in t1.iterrows()})

# ------------------------------------------------------------ headline power -
hp = []
for J in (28, 56):
    for alloc in ("equal", "control_heavy"):
        for icc in (0.05, 0.10):
            for d in (0.2, 0.3, 0.4):
                for e in (PL, BM):
                    r = base[(base.J == J) & (base.alloc == alloc) & (base.icc == icc) & (base.R2 == 0.3)
                             & (base.cv == 0.3) & (base.dB == d) & (base.estimator == e)].iloc[0]
                    hp.append(dict(J=J, df_planned=J - r.c, alloc=alloc, icc=icc, d=d, estimator=e, label=v2.LABELS[e],
                                   unadj_BvsA=r.BvsA_rej, unadj_BvsA_mcse=r.BvsA_rej_mcse,
                                   holm_BvsA=r.holm_BvsA, holm_BvsA_mcse=r.holm_BvsA_mcse,
                                   holm_CvsA=r.holm_CvsA, holm_CvsA_mcse=r.holm_CvsA_mcse,
                                   holm_both=r.holm_both, holm_both_mcse=r.holm_both_mcse,
                                   holm_any=r.holm_any, holm_any_mcse=r.holm_any_mcse,
                                   analytic_unadj_BvsA=r.analytic_power_BvsA, n_rep=r.n_rep))
hp = pd.DataFrame(hp); hp.to_csv(os.path.join(RES, "power_headline.csv"), index=False)
S["power_headline"] = dict(
    note="R2 0.3, cluster-size CV 0.3, 10% MCAR attrition, d for both B and C vs A; 1,000 replications; "
         "'holm_*' = Holm-adjusted marginal power per contrast; 'holm_both' = probability of rejecting both; "
         "analytic = unadjusted alpha 0.05 noncentral-t on J-c df (Eldridge design effect)",
    rows=[{k: (r4(v) if isinstance(v, (float, np.floating)) else (int(v) if isinstance(v, (np.integer,)) else v))
           for k, v in r.items()} for r in hp.to_dict("records")])

# analytic vs simulated unadjusted power, all base alternative cells
alt = base[(base.dB > 0) & (base.estimator == PL)]
dd = np.concatenate([alt.BvsA_rej - alt.analytic_power_BvsA, alt.CvsA_rej - alt.analytic_power_CvsA])
S["analytic_vs_simulated_unadjusted_power"] = {
    f"J{J}": dict(n_contrast_cells=int(2 * (alt.J == J).sum()),
                  min_diff=r4(np.concatenate([(alt.BvsA_rej - alt.analytic_power_BvsA)[alt.J == J],
                                               (alt.CvsA_rej - alt.analytic_power_CvsA)[alt.J == J]]).min()),
                  max_diff=r4(np.concatenate([(alt.BvsA_rej - alt.analytic_power_BvsA)[alt.J == J],
                                               (alt.CvsA_rej - alt.analytic_power_CvsA)[alt.J == J]]).max()),
                  mean_diff=r4(np.concatenate([(alt.BvsA_rej - alt.analytic_power_BvsA)[alt.J == J],
                                                (alt.CvsA_rej - alt.analytic_power_CvsA)[alt.J == J]]).mean()))
    for J in (28, 56)}

# ------------------------------------------------------------- partial null --
pn = df[(df.family == "partial_null") & df.estimator.isin([PL, BM, "TwoStage_CL", "CR2_tJc", "LMM_z"])]
S["partial_null_holm_FWER"] = {f"J{J}_{e}": dict(max=r4(g.holm_FWER.max()), mean=r4(g.holm_FWER.mean()),
                                                  n_scenarios=int(len(g)), mcse_typ=r4(g.holm_FWER_mcse.mean()))
                               for (J, e), g in pn.groupby(["J", "estimator"])}
pn.to_csv(os.path.join(RES, "partial_null_results.csv"), index=False)

# --------------------------------------------------------------- MDES -------
md = []
for J in (28, 56):
    st = v2.structure(J); T = v2.arm_totals(J, "equal"); dfp = J - st["c"]
    for icc in (0.05, 0.10):
        for alpha in (0.05, 0.025):
            md.append(dict(J=J, c=st["c"], df=dfp, icc=icc, R2=0.3, cv=0.3, nbar_analysed=22.5, alpha=alpha,
                           arms=f"{T[0]}:{T[1]}:{T[2]}",
                           mdes_BvsA=v2.analytic_mdes(T[0], T[1], dfp, icc, 0.3, 22.5, 0.3, alpha),
                           mdes_BvsC=v2.analytic_mdes(T[1], T[2], dfp, icc, 0.3, 22.5, 0.3, alpha)))
md = pd.DataFrame(md); md.to_csv(os.path.join(RES, "analytic_mdes.csv"), index=False)
S["analytic_mdes"] = dict(note="ANALYTIC (closed-form), unadjusted, 80% power, noncentral-t approximation on J-c df; "
                               "alpha 0.025 rows are a Bonferroni approximation, not Holm",
                          rows=[{k: (r4(v) if isinstance(v, float) else v) for k, v in r.items()} for r in md.to_dict("records")])

# --------------------------------------------------------------- sample size -
ss = df[(df.family == "ssize") & (df.estimator == PL)].copy()
b56 = base[(base.J == 56) & (base.alloc == "equal") & (base.R2 == 0.3) & (base.cv == 0.3) & (base.dB == 0.3) & (base.estimator == PL)]
rows, need = [], {}
for icc, g in ss.groupby("icc"):
    g = g.sort_values("J")
    g["holm_min_marginal"] = g[["holm_BvsA", "holm_CvsA"]].min(1)
    for _, r in g.iterrows():
        rows.append(dict(icc=icc, J=int(r.J), per_offering=int(r.J // 2), arms=f"{r.nA}:{r.nB}:{r.nC}", c=int(r.c),
                         df=int(r.J - r.c), holm_BvsA=r.holm_BvsA, holm_BvsA_mcse=r.holm_BvsA_mcse,
                         holm_CvsA=r.holm_CvsA, holm_CvsA_mcse=r.holm_CvsA_mcse, holm_both=r.holm_both,
                         holm_both_mcse=r.holm_both_mcse, unadj_BvsA=r.BvsA_rej,
                         analytic_unadj_BvsA=r.analytic_power_BvsA, n_rep=int(r.n_rep)))
    out = {}
    for crit, col in (("marginal_each_contrast", "holm_min_marginal"), ("joint_both_rejected", "holm_both")):
        ok = g[g[col] >= 0.80]
        Jmin = int(ok.J.min()) if len(ok) else None
        # probit fit of rejection counts on J (pooled B and C for marginal uses the min series)
        y = np.round(g[col] * g.n_rep).values; nn = g.n_rep.values
        X = sm.add_constant(g.J.values.astype(float))
        fit = sm.GLM(np.column_stack([y, nn - y]), X, family=sm.families.Binomial(sm.families.links.Probit())).fit()
        Jstar = (stats.norm.ppf(0.8) - fit.params[0]) / fit.params[1]
        out[crit] = dict(smallest_grid_J_with_point_estimate_ge_0_80=Jmin,
                         power_at_that_J=r4(ok[col].iloc[0]) if len(ok) else None,
                         mcse_at_that_J=r4(np.sqrt(ok[col].iloc[0] * (1 - ok[col].iloc[0]) / 2000)) if len(ok) else None,
                         probit_fit_crossing_J=r4(Jstar), probit_fit_crossing_J_even_ceiling=int(2 * np.ceil(Jstar / 2)))
    # analytic, even J split equally over two offerings, df J-10
    for alpha in (0.05, 0.025):
        for J in range(20, 200, 2):
            st = v2.structure(J, 2); T = v2.arm_totals(J, "equal", 2)
            pw = min(v2.analytic_power(0.3, T[0], T[1], J - st["c"], icc, 0.3, 22.5, 0.3, alpha),
                     v2.analytic_power(0.3, T[0], T[2], J - st["c"], icc, 0.3, 22.5, 0.3, alpha))
            if pw >= 0.8:
                out[f"analytic_unadjusted_alpha_{alpha}_J"] = J; break
    need[f"icc_{icc}"] = out
pd.DataFrame(rows).to_csv(os.path.join(RES, "sample_size_grid.csv"), index=False)
S["clusters_needed_80pct_power_d0.3"] = dict(
    note="planned analysis LMM t(J-c), c = 10 (two offerings x 4 strata), J split equally over two offerings, "
         "R2 0.3, CV 0.3, 10% attrition, equal allocation, 2,000 replications per grid J; marginal = Holm-adjusted power "
         "of EACH confirmatory contrast >= 0.80 (min of B-A and C-A); joint = P(both rejected) >= 0.80",
    results=need)

# ----------------------------------------------------- bias / coverage (base) -
bc = long[(long.family == "base") & long.estimator.isin([PL, BM]) & long.contrast.isin(["BvsA", "CvsA", "BvsC"])].copy()
bc["modSE_over_empSE"] = bc.modSE / bc.empSE
bc[["scenario_id", "J", "c", "alloc", "icc", "R2", "cv", "dB", "estimator", "estimator_label", "contrast", "truth", "n_rep",
    "bias", "bias_mcse", "empSE", "empSE_mcse", "modSE", "modSE_over_empSE", "cov", "cov_mcse"]].to_csv(
    os.path.join(RES, "bias_coverage_base.csv"), index=False)
S["bias_coverage_base_grid"] = {}
for (J, e), g in bc.groupby(["J", "estimator"]):
    S["bias_coverage_base_grid"][f"J{J}_{e}"] = dict(
        label=v2.LABELS[e], n_contrast_cells=int(len(g)),
        coverage_min=r4(g["cov"].min()), coverage_max=r4(g["cov"].max()), coverage_mean=r4(g["cov"].mean()),
        n_coverage_below_0_93=int((g["cov"] < 0.93).sum()),
        max_abs_bias=r4(g.bias.abs().max()), max_abs_bias_over_mcse=r4((g.bias / g.bias_mcse).abs().max()),
        n_abs_bias_over_mcse_gt_3=int(((g.bias / g.bias_mcse).abs() > 3).sum()),
        modSE_over_empSE_min=r4(g.modSE_over_empSE.min()), modSE_over_empSE_max=r4(g.modSE_over_empSE.max()),
        modSE_over_empSE_mean=r4(g.modSE_over_empSE.mean()))

# ------------------------------------------------------------- sensitivity --
sens = df[df.family.str.match(r"^S\d")].copy()
srows = []
for _, r in sens[sens.estimator.isin([PL, BM])].iterrows():
    for cn in ("BvsA", "CvsA"):
        isnull = bool(r[f"null_{cn}"])
        srows.append(dict(scenario_id=r.scenario_id, family=r.family, icc=r.icc, estimator=r.estimator,
                          label=v2.LABELS[r.estimator], contrast=cn, truth=r[f"true_{cn}"], is_null=isnull,
                          measure="size (unadjusted)" if isnull else "power (Holm marginal)",
                          value=r[f"{cn}_rej"] if isnull else r[f"holm_{cn}"],
                          value_mcse=r[f"{cn}_rej_mcse"] if isnull else r[f"holm_{cn}_mcse"],
                          unadj_rej=r[f"{cn}_rej"], holm_rej=r[f"holm_{cn}"], holm_both=r.holm_both,
                          holm_both_mcse=r.holm_both_mcse, holm_FWER=r.holm_FWER, holm_FWER_mcse=r.holm_FWER_mcse,
                          bias=r[f"{cn}_bias"], bias_mcse=r[f"{cn}_bias_mcse"], coverage=r[f"{cn}_cov"],
                          coverage_mcse=r[f"{cn}_cov_mcse"], empSE=r[f"{cn}_empSE"], modSE=r[f"{cn}_modSE"],
                          df_mean=r[f"{cn}_df_mean"], J_obs_mean=r.J_obs_mean, N_analysed_mean=r.N_analysed_mean,
                          n_rep=int(r.n_rep)))
srows = pd.DataFrame(srows); srows.to_csv(os.path.join(RES, "sensitivity_summary.csv"), index=False)
S["sensitivity_J56"] = dict(
    note="J = 56 (c = 10, df 46), equal 10:9:9 per offering, R2 0.3, CV 0.3, d 0.3, 10% MCAR attrition unless varied; "
         "size = unadjusted rejection of a true-null contrast (2,000 replications); power = Holm-adjusted marginal "
         "(1,000 replications); S3 truth is on the raw 0-100 scale",
    rows=[{k: (r4(v) if isinstance(v, (float, np.floating)) else (bool(v) if isinstance(v, (bool, np.bool_)) else v))
           for k, v in r.items()} for r in srows.to_dict("records")])

# ------------------------------------------------------------ J = 28 checks --
if os.path.exists(V1):
    o = pd.read_csv(V1)
    mp = {"LMM_t": "LMM_tJc", "CR2_tJ6": "CR2_tJc", "CL_HM": "TwoStage_CL"}
    o["estimator"] = o.estimator.replace(mp)
    leg = df[df.family == "legacy_check"]
    keymap = {s["scenario_id"]: s["seed_key"] for s in v2.scenarios()}
    leg = leg.assign(sid=leg.scenario_id.map(keymap))
    m = leg.merge(o, on=["sid", "estimator"], suffixes=("", "_v1"))
    metric_cols = [c for c in o.columns if (c.startswith(("BvsA_", "CvsA_", "BvsC_", "holm_")) or c in
                   ("lmm_boundary_frac", "lmm_rho_hat_mean", "N_analysed_mean")) and c + "_v1" in m.columns]
    A_ = m[metric_cols].values.astype(float); B_ = m[[c + "_v1" for c in metric_cols]].values.astype(float)
    same = (A_ == B_) | (np.isnan(A_) & np.isnan(B_))
    diffs = np.where(same, 0.0, np.abs(A_ - B_))
    assert np.isfinite(diffs).all()
    # full v2 J=28 re-run (per-replicate randomisation) vs v1
    b28 = base[base.J == 28].copy()
    b28["sid"] = b28.scenario_id.map(keymap)
    m2 = b28.merge(o, on=["sid", "estimator"], suffixes=("", "_v1"))
    zz = {}
    for col in ("BvsA_rej", "CvsA_rej", "holm_BvsA", "holm_both"):
        dlt = m2[col] - m2[col + "_v1"]
        se = np.sqrt(m2[col + "_mcse"] ** 2 + m2[col + "_mcse_v1"] ** 2)
        z = dlt / se.replace(0, np.nan)
        zz[col] = dict(max_abs_diff=r4(dlt.abs().max()), mean_diff=r4(dlt.mean()),
                       max_abs_z_independent_approx=r4(z.abs().max()), share_abs_z_gt_2=r4((z.abs() > 2).mean()))
    t28 = t1[t1.J == 28].set_index("estimator")
    v1null = o[(o.family == "base") & (o.J == 28) & (o.d == 0)]
    v1t1 = {e: r4(np.concatenate([g.BvsA_rej, g.CvsA_rej]).mean()) for e, g in v1null.groupby("estimator")}
    S["J28_checks"] = dict(
        legacy_reproduction=dict(n_scenarios=int(leg.scenario_id.nunique()), n_rows_matched=int(len(m)),
                                 n_metrics=len(metric_cols), max_abs_diff=float(diffs.max()),
                                 note="v2 code with the fixed v1 layout and the v1 seeds reproduces v1 J=28 results "
                                      "(R2 0.3, CV 0.3, both allocations, all ICC and d); residual differences are numerical noise"),
        full_rerun_with_per_replicate_randomisation=dict(
            n_scenarios=int(b28.scenario_id.nunique()), n_rows_matched=int(len(m2)), comparisons=zz,
            note="same data streams as v1, but fresh allocation per replicate; differences are Monte Carlo variation "
                 "(z treats the two runs as independent; they share data streams, so z is approximate)"),
        type1_mean_v1_vs_v2={e: dict(v1=v1t1.get(e), v2=r4(t28.loc[e, "mean"])) for e in v2.ESTIMATORS})

# ------------------------------------------------------------- validation ---
vp = os.path.join(HERE, "validation", "validation_summary.json")
if os.path.exists(vp):
    S["validation"] = json.load(open(vp))

S["lmm_boundary_fraction_base_max"] = {f"J{J}": r4(g.lmm_boundary_frac.max()) for J, g in base[base.estimator == PL].groupby("J")}
S["design"] = dict(J28=dict(offerings=1, strata=4, c=6, df=22, equal="10:9:9", control_heavy="12:8:8"),
                   J56=dict(offerings=2, strata_total=8, strata_per_offering=4, c=10, df=46, equal="20:18:18 (10:9:9 per offering)",
                            control_heavy="24:16:16 (12:8:8 per offering)"),
                   randomisation="fresh stratified allocation per simulated trial (extras {A,A,B,C} permuted over the 4 strata "
                                 "of each offering; arm labels permuted over groups within each stratum)",
                   estimator_labels=v2.LABELS)
json.dump(S, open(os.path.join(RES, "rct_design_summary_v2.json"), "w"), indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
print("written", os.path.join(RES, "rct_design_summary_v2.json"))
