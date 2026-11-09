"""Audit analysis under grader v1.1 (tables, CSVs and LaTeX macros).

Usage: python audit_analysis_v2.py <root> <outdir>
<root>: layout of v11_merge.py plus judge/judge_scores_all.csv, judge/judge_analysis_v1.json,
        validation/{mutation_results_v11.csv, adversarial_results_v11.csv, adversarial_results.csv,
        positive_controls_v11.csv, probes_v11.json, coverage_matrix.csv, natural_output_audit_summary.json},
        sim/rct_design_summary_v2.json.
Writes <outdir>/*.csv, <outdir>/numbers.tex and <outdir>/tab_*.tex.
"""
import collections, glob, json, math, os, sys
import numpy as np, pandas as pd
ROOT, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]); os.makedirs(OUT, exist_ok=True)
J = lambda *a: os.path.join(ROOT, *a)
ORIG4 = ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-5", "claude-opus-5-5"]
MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-5", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
LAB = dict(zip(MODELS, ["Haiku 4.5", "Sonnet 4.5", "Sonnet 5", "Haiku 5.5", "Sonnet 5.5", "Opus 5.5"]))
MAC = dict(zip(MODELS, ["HaikuFourFive", "SonnetFourFive", "SonnetFive", "HaikuFiveFive", "SonnetFiveFive", "OpusFiveFive"]))
TASKS = ["T1", "T2", "T3", "APP", "DES"]; TMAC = dict(zip(TASKS, ["TOne", "TTwo", "TThree", "App", "Des"]))
APP_DB = ["A02", "A03", "A04", "A05", "A06", "A07"]; APP_S3 = ["A%02d" % i for i in range(8, 17)]
THEME_COUNT = {"th1": 39, "th2": 33, "th3": 16, "th4": 13, "th5": 17, "th6": 9, "th7": 6, "th8": 6}
THEME_LABEL = {"th1": "Security vs functionality behind the load balancer", "th2": "SDK coding for upload and retrieval",
               "th3": "NAT instance AMI changed by the provider", "th4": "Auto Scaling, scaling policies, target groups",
               "th5": "IAM roles and policies for EC2/S3 access", "th6": "Presigned URL for S3 access",
               "th7": "Private-subnet access through NAT", "th8": "Escaping characters in SQL queries"}
THEME_OF = {"T3.R5": "th1", "T3.R6": "th1", "T3.R13": "th1", "T2.R10": "th1", "T2.R8": "th1",
            "A08": "th2", "A09": "th2", "A10": "th2", "A11": "th2", "A14": "th2", "A15": "th2",
            "T3.R4": "th4", "T3.R8": "th4", "T3.R9": "th4", "T3.R11": "th5", "A16": "th5", "A12": "th6", "A13": "th6",
            "T3.R3": "th7", "A05": "th8", "A06": "th8"}
NCHK = {"T1": 9, "T2": 11, "T3": 16, "APP": 16, "DES": 10}
def wilson(k, n, z=1.959964):
    if n == 0: return float("nan"), float("nan")
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)
M = {}   # macros
def mac(name, val):
    assert name.isalpha(), name
    assert name not in M or M[name] == val, ("macro redefined with a different value", name, M[name], val)
    M[name] = val
def pct(x, d=0): return ("%." + str(d) + "f") % (100 * x)
def load(tag):
    o = {}
    for f in sorted(glob.glob(J("regrade", tag + "_out*.json"))): o.update(json.load(open(f, encoding="utf-8")))
    return o
G10, GF, GT2 = load("v10"), load("v11"), load("t2")
TU = pd.read_csv(J("derived", "turns_v11.csv")); EP = pd.read_csv(J("derived", "episodes_v11.csv")); BR = pd.read_csv(J("derived", "branches_v11.csv"))
MR = json.load(open(J("derived", "merge_report.json")))
for d in (TU, EP, BR):
    for c in ("all_pass", "stop", "final_pass", "stopped_clean"):
        if c in d: d[c] = d[c].astype(str).isin(["True", "true", "1"])
TU["failed_checks"] = TU["failed_checks"].fillna("")
def checks_of(row):
    f = set(x for x in row.failed_checks.split(";") if x)
    ids = (["%s.R%d" % (row.task, i) for i in range(1, NCHK[row.task] + 1)] if row.task in ("T1", "T2", "T3")
           else (["A%02d" % i for i in range(1, 17)] if row.task == "APP" else ["D%02d" % i for i in range(1, 11)]))
    return {i: i not in f for i in ids}
def lint_bad(row):
    v = row.lint_errors
    try: return float(v) > 0
    except Exception: return False
# ================= reproduction and replay bookkeeping
mac("RegradeN", "{:,}".format(len(G10)))
mac("ReplayLiveUsed", str(MR["live_responses_used"])); mac("ReplayLiveTotal", str(MR["live_responses_total"]))
mac("ReplayEpisodesLive", str(MR.get("episodes_live", 0))); mac("ReplayEpisodesTotal", str(MR.get("episodes_live", 0) + MR.get("episodes_archived_only", 0)))
mac("ReplayBranchesNew", str(MR.get("branches_new_start_v11", 0))); mac("ReplayBranchesArch", str(MR.get("branches_archived_start", 0)))
mac("ReplayBranchesDropped", str(MR.get("branches_dropped_start_passes_v11", 0)))
mac("ReplayBranchesLive", str(int((BR.n_live > 0).sum()))); mac("ReplayBranchesTotal", str(len(BR)))
# ================= first submissions (pooled S/P/A round 1)
R1 = TU[(TU.family == "main") & (TU["round"] == 1)].copy()
R1["k10"] = [G10["main@@%s#r1" % i]["all_pass"] for i in R1.id]; R1["kt2"] = [GT2["main@@%s#r1" % i]["all_pass"] for i in R1.id]
R1["frac"] = R1.n_checks_passed / R1.n_checks
rows = []
for m in MODELS:
    for t in TASKS:
        g = R1[(R1.model == m) & (R1.task == t)]; k, n = int(g.all_pass.sum()), len(g); lo, hi = wilson(k, n)
        rows.append(dict(model=m, label=LAB[m], task=t, n=n, k=k, lo=lo, hi=hi, k_v10=int(g.k10.sum()), k_t2=int(g.kt2.sum()),
                         mean_frac=g.frac.mean(), lint_fail=int(g.apply(lint_bad, axis=1).sum())))
        mac("FS%s%sK" % (MAC[m], TMAC[t]), str(k)); mac("FS%s%sN" % (MAC[m], TMAC[t]), str(n))
        mac("FS%s%sLo" % (MAC[m], TMAC[t]), "%.2f" % lo); mac("FS%s%sHi" % (MAC[m], TMAC[t]), "%.2f" % hi)
        mac("FSvTen%s%sK" % (MAC[m], TMAC[t]), str(int(g.k10.sum()))); mac("FSTierTwo%s%sK" % (MAC[m], TMAC[t]), str(int(g.kt2.sum())))
        mac("FSFrac%s%s" % (MAC[m], TMAC[t]), pct(g.frac.mean()))
PR = pd.DataFrame(rows); PR.to_csv(os.path.join(OUT, "primary_first_submission.csv"), index=False)
for m in MODELS:
    g = PR[PR.model == m]; mac("FSAll%sK" % MAC[m], str(int(g.k.sum()))); mac("FSAll%sN" % MAC[m], str(int(g.n.sum())))
    mac("FSAllvTen%sK" % MAC[m], str(int(g.k_v10.sum())))
mac("FSTotalvTen", str(int(PR[PR.model.isin(ORIG4)].k_v10.sum()))); mac("FSTotalvEleven", str(int(PR[PR.model.isin(ORIG4)].k.sum())))
mac("FSTotalTemplatesOrig", str(int(len(R1[R1.model.isin(ORIG4)]))))
# turns changed by v1.1 (main battery, archived turns)
mains = [k for k in G10 if k.startswith("main@@")]
pf = sum(1 for k in mains if G10[k]["all_pass"] and not GF[k]["all_pass"]); fp = sum(1 for k in mains if not G10[k]["all_pass"] and GF[k]["all_pass"])
mac("VerdictPF", str(pf)); mac("VerdictFP", str(fp)); mac("MainTurnsN", str(len(mains)))
# ================= feedback regimes (main battery, final submissions)
fr = []
for m in MODELS:
    for t in TASKS:
        for c in ("S", "P", "A"):
            g = EP[(EP.model == m) & (EP.task == t) & (EP.cond == c)]
            if not len(g): continue
            fr.append(dict(model=m, label=LAB[m], task=t, cond=c, n=len(g), final_k=int(g.final_pass.sum()), mean_sub=g.n_sub.mean(),
                           stopped_clean=int(g.stopped_clean.sum()), v10_final_k=int(g.archived_final_pass_v10.sum()), n_live=int((g.n_live > 0).sum())))
FR = pd.DataFrame(fr); FR.to_csv(os.path.join(OUT, "feedback_regimes.csv"), index=False)
for m in MODELS:
    for c in ("S", "P", "A"):
        g = FR[(FR.model == m) & (FR.cond == c)]
        mac("Fin%s%sK" % (MAC[m], c), str(int(g.final_k.sum()))); mac("Fin%s%sN" % (MAC[m], c), str(int(g.n.sum())))
        gi = g[g.task != "DES"]; mac("FinImpl%s%sK" % (MAC[m], c), str(int(gi.final_k.sum()))); mac("FinImpl%s%sN" % (MAC[m], c), str(int(gi.n.sum())))
    for t in TASKS:
        for c in ("S", "P", "A"):
            g = FR[(FR.model == m) & (FR.task == t) & (FR.cond == c)]
            if len(g): mac("Fin%s%s%sK" % (MAC[m], TMAC[t], c), str(int(g.final_k.iloc[0]))); mac("Sub%s%s%s" % (MAC[m], TMAC[t], c), "%.1f" % g.mean_sub.iloc[0])
# ================= branching
BR["label"] = BR.model.map(LAB)
bt = BR.groupby(["model", "task", "regime"]).agg(n=("bid", "size"), repaired=("final_pass", "sum"), stopped_clean=("stopped_clean", "sum"),
                                              mean_sub_repaired=("n_sub", lambda s: s[BR.loc[s.index, "final_pass"]].mean() if BR.loc[s.index, "final_pass"].any() else np.nan),
                                              n_live=("n_live", lambda s: int((s > 0).sum()))).reset_index()
bt["label"] = bt.model.map(LAB); bt.to_csv(os.path.join(OUT, "branching_transitions.csv"), index=False)
ND = BR[BR.task != "DES"]
for reg in "RCPA":
    g = ND[ND.regime == reg]; mac("Br%sK" % reg, str(int(g.final_pass.sum()))); mac("Br%sN" % reg, str(len(g)))
    lo, hi = wilson(int(g.final_pass.sum()), len(g)); mac("Br%sLo" % reg, "%.2f" % lo); mac("Br%sHi" % reg, "%.2f" % hi)
    mac("BrStopClean%s" % reg, str(int(g.stopped_clean.sum())))
    if reg != "P":
        gd = BR[(BR.task == "DES") & (BR.regime == reg)]; mac("BrDes%sK" % reg, str(int(gd.final_pass.sum()))); mac("BrDes%sN" % reg, str(len(gd)))
mac("BrStarts", str(ND.start_eid.nunique())); mac("BrStartsDes", str(BR[BR.task == "DES"].start_eid.nunique()))
# paired comparisons on matched starts (implementation tasks)
pv = ND.pivot_table(index="start_eid", columns="regime", values="final_pass", aggfunc="first")
from scipy.stats import binomtest
pairs = {}
for a, b in [("A", "R"), ("A", "C"), ("C", "R"), ("A", "P")]:
    x = pv[[a, b]].dropna().astype(bool); n10 = int((x[a] & ~x[b]).sum()); n01 = int((~x[a] & x[b]).sum())
    p = binomtest(n10, n10 + n01, 0.5).pvalue if n10 + n01 else 1.0
    pairs[a + b] = dict(n10=n10, n01=n01, p=p); mac("Pair%s%sTen" % (a, b), str(n10)); mac("Pair%s%sOne" % (a, b), str(n01)); mac("Pair%s%sP" % (a, b), ("%.3f" % p) if p >= 0.001 else "<0.001")
json.dump(pairs, open(os.path.join(OUT, "branching_pairs.json"), "w"), indent=1)
# DES branching mean checks under A
gdA = BR[(BR.task == "DES") & (BR.regime == "A")]
mac("BrDesAFirstChecks", "%.2f" % gdA.first_checks.mean()); mac("BrDesAFinalChecks", "%.2f" % gdA.final_checks.mean())
# Sonnet 4.5 T3 repair under A
s45 = BR[(BR.model == MODELS[1]) & (BR.task == "T3")]
for reg in "RCPA":
    g = s45[s45.regime == reg]; mac("BrSonFFTThree%sK" % reg, str(int(g.final_pass.sum()))); mac("BrSonFFTThree%sN" % reg, str(len(g)))
# ================= brief variants: anchor (single shot) and corrected DES
ABJ = json.load(open(J("runs", "anchor_briefs.json"), encoding="utf-8"))["check_specification"]
an = []
for k, g in GF.items():
    if not k.startswith("anchor@@"): continue
    eid = k.split("@@")[1].rsplit("#r", 1)[0]; m, t = eid.split("|")[:2]
    si = [c for c, v in ABJ[t].items() if v != "unspecified"]
    lintok = bool(g.get("extracted")) and g.get("lint_errors") == 0
    an.append(dict(model=m, task=t, eid=eid, full=g["all_pass"], full_v10=G10[k]["all_pass"], stated_implied=lintok and all(g["checks"][c][0] for c in si),
                   frac=np.mean([v[0] for v in g["checks"].values()]), lint_fail=not lintok))
AN = pd.DataFrame(an); at = AN.groupby(["model", "task"]).agg(n=("eid", "size"), full=("full", "sum"), full_v10=("full_v10", "sum"), si=("stated_implied", "sum"), frac=("frac", "mean"), lintfail=("lint_fail", "sum")).reset_index()
at.to_csv(os.path.join(OUT, "anchor_variants.csv"), index=False)
for _, r in at.iterrows():
    mac("Anc%s%sK" % (MAC[r.model], TMAC[r.task]), str(int(r.full))); mac("AncSI%s%sK" % (MAC[r.model], TMAC[r.task]), str(int(r.si)))
    mac("AncFrac%s%s" % (MAC[r.model], TMAC[r.task]), pct(r.frac))
for t in ("T1", "T2", "T3"):
    g = at[at.task == t]; mac("AncAll%sK" % TMAC[t], str(int(g.full.sum()))); mac("AncAllSI%sK" % TMAC[t], str(int(g.si.sum()))); mac("AncAll%sN" % TMAC[t], str(int(g.n.sum())))
dc = []
for k, g in GF.items():
    if not k.startswith("des_corrected@@"): continue
    eid, r = k.split("@@")[1].rsplit("#r", 1); m, t, c, rp = eid.split("|"); dc.append(dict(model=m, cond=c, rep=int(rp), round=int(r), all_pass=g["all_pass"], stop=g["stop"]))
DC = pd.DataFrame(dc); DCf = DC.sort_values("round").groupby(["model", "cond", "rep"]).tail(1); DC1 = DC[DC["round"] == 1]
dct = []
for m in MODELS:
    r1 = DC1[DC1.model == m]; fa = DCf[(DCf.model == m) & (DCf.cond == "A")]
    dct.append(dict(model=m, first_k=int(r1.all_pass.sum()), first_n=len(r1), finalA_k=int(fa.all_pass.sum()), finalA_n=len(fa)))
    mac("DesCorr%sK" % MAC[m], str(int(r1.all_pass.sum()))); mac("DesCorr%sN" % MAC[m], str(len(r1))); mac("DesCorrA%sK" % MAC[m], str(int(fa.all_pass.sum())))
pd.DataFrame(dct).to_csv(os.path.join(OUT, "des_corrected.csv"), index=False)
# ================= MCQ
mcq = []
for m in MODELS:
    for r in [json.loads(l) for l in open(J("runs", "model_runs", m, "mcq.jsonl"), encoding="utf-8")]:
        mcq.append(dict(model=m, rep=int(r["rep"]), score=float(r["score"])))
MQ = pd.DataFrame(mcq)
for m in MODELS:
    g = MQ[MQ.model == m]; mac("MCQ%s" % MAC[m], "%.1f" % (30 * g.score.mean())); mac("MCQMin%s" % MAC[m], str(int(round(30 * g.score.min())))); mac("MCQMax%s" % MAC[m], str(int(round(30 * g.score.max()))))
# ================= judged rationale
JS = pd.read_csv(J("judge", "judge_scores_all.csv")); JS = JS[JS.kind == "sub"]
JO = JS[JS.set == "original"]
jm = JO.groupby(["model", "judge"]).total.mean().unstack()
for m in MODELS:
    mac("JudgeOpus%s" % MAC[m], "%.1f" % jm.loc[m, "claude-opus-5"]); mac("JudgeSonnet%s" % MAC[m], "%.1f" % jm.loc[m, "claude-sonnet-4-6"])
JA = json.load(open(J("judge", "judge_analysis_v1.json")))
judged = JO.groupby("id").total.mean() / 20.0
# ---- judge agreement over all original-brief designs (6 models x 10)
def icc_2way(X):
    n, k = X.shape; gm = X.mean(); r = X.mean(axis=1); c = X.mean(axis=0)
    msr = k * ((r - gm) ** 2).sum() / (n - 1); msc = n * ((c - gm) ** 2).sum() / (k - 1)
    mse = ((X - r[:, None] - c[None, :] + gm) ** 2).sum() / ((n - 1) * (k - 1))
    return (msr - mse) / (msr + (k - 1) * mse + k * (msc - mse) / n), (msr - mse) / (msr + (k - 1) * mse)
from scipy.stats import spearmanr
PV = JO.pivot_table(index="id", columns="judge", values="total")[["claude-opus-5", "claude-sonnet-4-6"]]
X = PV.values.astype(float); i21, i31 = icc_2way(X)
bs = []; rb = np.random.default_rng(20261106)
for _ in range(4000):
    s = X[rb.integers(0, len(X), len(X))]; bs.append(icc_2way(s)[0])
mac("JudgeDesignsN", str(len(X))); mac("JudgeICCTwo", "%.2f" % i21); mac("JudgeICCThree", "%.2f" % i31)
lo_, hi_ = np.percentile(bs, [2.5, 97.5]); mac("JudgeICCTwoLo", "%.2f" % lo_); mac("JudgeICCTwoHi", "%.2f" % hi_)
mac("JudgeSpearman", "%.2f" % spearmanr(X[:, 0], X[:, 1]).statistic); mac("JudgeMeanDiff", "%.2f" % (X[:, 1] - X[:, 0]).mean())
crit = {}
for cj in ("J1", "J2", "J3", "J4", "J5"):
    Pc = JO.pivot_table(index="id", columns="judge", values=cj)[["claude-opus-5", "claude-sonnet-4-6"]].values.astype(float); crit[cj] = icc_2way(Pc)[0]
    mac("JudgeCritICC%s" % {"J1": "One", "J2": "Two", "J3": "Three", "J4": "Four", "J5": "Five"}[cj], "%.2f" % crit[cj])
# retest (ten designs, both judges, scored twice)
JV1 = pd.read_csv(J("judge", "judge_scores_v1.csv")); rt = JV1[JV1.kind == "retest"].merge(JV1[JV1.kind == "sub"], on=["id", "judge"], suffixes=("_rt", "_b"))
mac("RetestN", str(rt.id.nunique())); mac("RetestSpearman", "%.2f" % spearmanr(rt.total_rt, rt.total_b).statistic); mac("RetestMAD", "%.2f" % (rt.total_rt - rt.total_b).abs().mean())
mac("RetestExact", pct((rt.total_rt == rt.total_b).mean()))
# length: total on log words with model fixed effects, per judge
wc = {k.split("@@")[1].rsplit("#r", 1)[0]: v.get("word_count") for k, v in GF.items() if k.startswith("main@@") and "|DES|" in k}
FINALd = TU[(TU.family == "main") & (TU.task == "DES")].sort_values("round").groupby("id").tail(1)
lastround = dict(zip(FINALd.id, FINALd["round"]))
words = {i: GF["main@@%s#r%d" % (i, lastround[i])].get("word_count") for i in lastround}
import statsmodels.formula.api as smf
LW = JO.assign(words=JO.id.map(words)).dropna(subset=["words"]); LW["lw"] = np.log(LW.words.astype(float))
for jn, jm_ in (("Opus", "claude-opus-5"), ("Sonnet", "claude-sonnet-4-6")):
    d = LW[LW.judge == jm_]; f = smf.ols("total ~ lw + C(model)", d).fit(cov_type="HC1")
    mac("Len%sCoef" % jn, "%.2f" % f.params["lw"]); mac("Len%sLo" % jn, "%.2f" % f.conf_int().loc["lw", 0]); mac("Len%sHi" % jn, "%.2f" % f.conf_int().loc["lw", 1]); mac("Len%sP" % jn, "%.3f" % f.pvalues["lw"])
for m in MODELS: mac("Words%s" % MAC[m], "%d" % np.median([words[i] for i in words if i.startswith(m + "|")]))
cal = {(c["id"], c["judge"]): c["total"] for c in JA["calibration_v2"]}
mac("CalRevOpus", "%.1f" % cal[("C0R_revised_reference", "claude-opus-5")]); mac("CalRevSonnet", "%.1f" % cal[("C0R_revised_reference", "claude-sonnet-4-6")])
mac("CalPadOpus", "%.1f" % cal[("C5_padded_gold", "claude-opus-5")]); mac("CalPadSonnet", "%.1f" % cal[("C5_padded_gold", "claude-sonnet-4-6")])
cal1 = pd.read_csv(J("judge", "judge_calibration_v1.csv")).set_index(["id", "judge"]).total
mac("CalGoldOpus", "%.1f" % cal1[("C0_gold", "claude-opus-5")]); mac("CalGoldSonnet", "%.1f" % cal1[("C0_gold", "claude-sonnet-4-6")])
mac("CalRevWords", str(JA["revised_reference_words"])); mac("CalPadWords", str(JA["padded_gold_words"])); mac("CalGoldWords", str(JA["gold_words"]))
judged_op = JO[JO.judge == "claude-opus-5"].set_index("id").total / 20.0; judged_sn = JO[JO.judge == "claude-sonnet-4-6"].set_index("id").total / 20.0
# ================= estimated battery scores
FINAL = TU[TU.family == "main"].sort_values("round").groupby("id").tail(1).set_index("id")
def frac(row, ids, gate):
    if gate and lint_bad(row): return 0.0
    ch = checks_of(row); return float(np.mean([ch[i] for i in ids]))
rng = np.random.default_rng(20261106)
mk = []
for m in MODELS:
    mqs = MQ[MQ.model == m].sort_values("rep").score.tolist()
    for c in ("S", "P", "A"):
        for rp in range(5):
            def ep(t, cc): return FINAL.loc["%s|%s|%s|%d" % (m, t, cc, rp)]
            t1, t2, t3, ap = ep("T1", c), ep("T2", c), ep("T3", c), ep("APP", c); de = ep("DES", "A" if c == "A" else "S")
            deid = "%s|DES|%s|%d" % (m, "A" if c == "A" else "S", rp)
            ids = lambda r: list(checks_of(r).keys())
            ddet = frac(de, ids(de), False); adb = frac(ap, APP_DB, False); as3 = frac(ap, APP_S3, False)
            s1, s2, s3 = frac(t1, ids(t1), True), frac(t2, ids(t2), True), frac(t3, ids(t3), True)
            u1, u2, u3 = frac(t1, ids(t1), False), frac(t2, ids(t2), False), frac(t3, ids(t3), False)
            dj, djo, djs = judged[deid], judged_op[deid], judged_sn[deid]
            base = dict(model=m, cond=c, rep=rp, mcq=20 * mqs[rp])
            def tot(w2=0.6, w3=0.7, gate=True, design="both", theory=True):
                a1, a2, a3 = (s1, s2, s3) if gate else (u1, u2, u3)
                dz = {"both": 0.5 * ddet + 0.5 * dj, "det": ddet, "opus": 0.5 * ddet + 0.5 * djo, "sonnet": 0.5 * ddet + 0.5 * djs}[design]
                v = 5 * a1 + 15 * (w2 * a2 + (1 - w2) * adb) + 20 * (w3 * a3 + (1 - w3) * as3) + 30 * dz + (20 * mqs[rp] if theory else 0)
                return 100 * v / (90 if theory else 70)
            base.update(stage1=5 * s1, stage2=15 * (0.6 * s2 + 0.4 * adb), stage3=20 * (0.7 * s3 + 0.3 * as3), design=30 * (0.5 * ddet + 0.5 * dj),
                        pct=tot(), pct_ungated=tot(gate=False), pct_det=tot(design="det"), pct_opus=tot(design="opus"), pct_sonnet=tot(design="sonnet"),
                        pct_w50=tot(0.5, 0.5), pct_w80=tot(0.8, 0.8), pct_notheory=tot(theory=False))
            base["total90"] = 0.9 * base["pct"]; mk.append(base)
MK = pd.DataFrame(mk); MK.to_csv(os.path.join(OUT, "estimated_scores.csv"), index=False)
VAR = ["pct", "pct_ungated", "pct_det", "pct_opus", "pct_sonnet", "pct_w50", "pct_w80", "pct_notheory"]
ms = []
for (m, c), g in MK.groupby(["model", "cond"]):
    row = dict(model=m, cond=c)
    for v in VAR:
        x = g[v].values; bs = [rng.choice(x, len(x), replace=True).mean() for _ in range(4000)]
        row[v] = x.mean(); row[v + "_lo"], row[v + "_hi"] = np.percentile(bs, [2.5, 97.5]); row[v + "_min"], row[v + "_max"] = x.min(), x.max()
    ms.append(row)
MS = pd.DataFrame(ms); MS.to_csv(os.path.join(OUT, "estimated_scores_summary.csv"), index=False)
VM = dict(zip(VAR, ["", "Ungated", "Det", "OpusJ", "SonnetJ", "WFifty", "WEighty", "NoTheory"]))
for _, r in MS.iterrows():
    for v in VAR:
        mac("Mark%s%s%s" % (VM[v], MAC[r.model], r.cond), "%.1f" % r[v])
    mac("MarkMin%s%s" % (MAC[r.model], r.cond), "%.1f" % r.pct_min); mac("MarkMax%s%s" % (MAC[r.model], r.cond), "%.1f" % r.pct_max)
    mac("MarkLo%s%s" % (MAC[r.model], r.cond), "%.1f" % r.pct_lo); mac("MarkHi%s%s" % (MAC[r.model], r.cond), "%.1f" % r.pct_hi)
# ================= themes (first submissions, v1.1)
pc = []
for _, r in R1.iterrows():
    ch = checks_of(r); lb = lint_bad(r)
    for cid, ok in ch.items():
        if cid in THEME_OF:
            pc.append(dict(model=r.model, task=r.task, check=cid, theme=THEME_OF[cid], fail=not ok, fail_gated=(not ok) or (lb and r.task in ("T1", "T2", "T3"))))
PC = pd.DataFrame(pc)
cl = PC.groupby(["check", "theme"]).agg(n=("fail", "size"), fails=("fail", "sum"), fails_gated=("fail_gated", "sum")).reset_index(); cl.to_csv(os.path.join(OUT, "theme_check_failures.csv"), index=False)
th = PC.groupby("theme").agg(n=("fail", "size"), fails=("fail", "sum"), fails_gated=("fail_gated", "sum"), n_checks=("check", "nunique")).reset_index()
th["student"] = th.theme.map(THEME_COUNT); th["label"] = th.theme.map(THEME_LABEL)
thx = PC[PC.check != "A09"].groupby("theme").agg(n_xA09=("fail", "size"), fails_xA09=("fail", "sum")).reset_index(); th = th.merge(thx, on="theme", how="left")
for m in MODELS:
    g = PC[PC.model == m].groupby("theme").fail.agg(["sum", "size"]); th["rate_" + MAC[m]] = th.theme.map(g["sum"] / g["size"])
lo, hi = zip(*[wilson(int(a), int(b)) for a, b in zip(th.fails, th.n)]); th["lo"], th["hi"] = lo, hi
th.to_csv(os.path.join(OUT, "theme_alignment.csv"), index=False)
TN = {"th1": "One", "th2": "Two", "th4": "Four", "th5": "Five", "th6": "Six", "th7": "Seven", "th8": "Eight"}
for _, r in th.iterrows():
    mac("Th%sK" % TN[r.theme], str(int(r.fails))); mac("Th%sN" % TN[r.theme], str(int(r.n))); mac("Th%sGK" % TN[r.theme], str(int(r.fails_gated)))
    mac("Th%sXK" % TN[r.theme], str(int(r.fails_xA09))); mac("Th%sXN" % TN[r.theme], str(int(r.n_xA09)))
# ================= tokens and cost of the re-audit
tk = TU.groupby(["family", "model"]).agg(tin=("tokens_in", "sum"), tout=("tokens_out", "sum")).reset_index(); tk.to_csv(os.path.join(OUT, "tokens_live.csv"), index=False)
mac("LiveTokIn", "{:,}".format(int(TU[TU.source != "archived"].tokens_in.sum()))); mac("LiveTokOut", "{:,}".format(int(TU[TU.source != "archived"].tokens_out.sum())))
# ================= grader validation
V = lambda f: os.path.join(ROOT, "validation", f)
mut = pd.read_csv(V("mutation_results_v11.csv")); mut10 = pd.read_csv(V("mutation_results.csv")); pos10 = pd.read_csv(V("positive_controls.csv")); adv11 = pd.read_csv(V("adversarial_results_v11.csv")); adv10 = pd.read_csv(V("adversarial_results.csv"))
pos = pd.read_csv(V("positive_controls_v11.csv")); prb = json.load(open(V("probes_v11.json"))); cov = pd.read_csv(V("coverage_matrix.csv"))
nat = json.load(open(V("natural_output_audit_summary.json")))
mac("MutN", str(int((~mut.iloc[:, 0].astype(str).str.contains("S01")).sum())))
mac("MutDetvTen", str(int(mut10[~mut10.id.astype(str).str.contains("S01")].target_detected.sum()))); mac("MutDetvEleven", str(int(mut[~mut.id.astype(str).str.contains("S01")].target_detected.sum()))); mac("PosAccvTen", str(int((pos10.grader_verdict == "accept").sum()))); mac("PosAccvEleven", str(int((pos.grader_verdict == "accept").sum()))); mac("AdvN", str(len(adv10))); mac("AltValidN", str(len(pos)))
for tag, d in (("vTen", adv10), ("vEleven", adv11)):
    vc = d.outcome.value_counts()
    for o in ("FA", "FR", "TA", "TR"): mac("Adv%s%s" % (tag, o), str(int(vc.get(o, 0))))
    mac("Adv%sAMB" % tag, str(int(vc.get("AMB-A", 0) + vc.get("AMB-R", 0))))
mac("ProbeN", str(len(prb["v11"]))); mac("ProbeVTenFR", str(prb["v10_false_rejects"])); mac("ProbeVElevenErr", str(prb["v11_errors"]))
mac("NatN", str(nat["n"])); mac("NatConfirmed", str(nat["with_confirmed_fa"])); mac("NatBlocking", str(nat["blocking"]))
mac("GraderFixesN", str(nat["n_fixes_v11"])); mac("GraderTierTwoN", str(nat["n_tier2"]))
et = cov["evidence_type"].map(lambda v: "mixed" if "+" in v else {"declarative configuration": "declarative", "executed unit-test behaviour": "executed_unit_test", "computed arithmetic": "computed_arithmetic", "keyword presence": "keyword_presence"}[v]).value_counts()
mac("CovDeclarative", str(int(et.get("declarative", 0)))); mac("CovComputed", str(int(et.get("computed_arithmetic", 0)))); mac("CovTest", str(int(et.get("executed_unit_test", 0))))
mac("CovKeyword", str(int(et.get("keyword_presence", 0)))); mac("CovMixed", str(int(et.get("mixed", 0))))
# ================= simulation (design analysis) macros and tables
SS = json.load(open(J("sim", "rct_design_summary_v2.json")))
mf = SS["manifest"]; mac("SimScenarios", "{:,}".format(mf["total_scenarios"])); mac("SimTrials", "{:,}".format(mf["total_simulated_trials"]))
mac("SimCells", "{:,}".format(mf["total_contrast_cells"])); mac("SimFits", "{:,}".format(mf["estimator_fits"]))
mac("TSdfPlan", str(SS["design"]["J56"]["df"])); mac("TSdfSmall", str(SS["design"]["J28"]["df"]))
PH = pd.DataFrame(SS["power_headline"]["rows"])
def ph(J_, icc, d, est="LMM_tJc", alloc="equal"):
    r = PH[(PH.J == J_) & (PH.icc == icc) & (PH.d == d) & (PH.estimator == est) & (PH.alloc == alloc)]; assert len(r) == 1, (J_, icc, d, est, alloc, len(r)); return r.iloc[0]
NM = {0.05: "Five", 0.1: "Ten"}; DN = {0.2: "Two", 0.3: "Three", 0.4: "Four"}
for J_, jn in ((56, "Big"), (28, "Small")):
    for icc in (0.05, 0.1):
        for d in sorted(set(PH.d)):
            if d not in DN: continue
            try: r = ph(J_, icc, d)
            except AssertionError: continue
            tag = "Pow%sIcc%sD%s" % (jn, NM[icc], DN[d])
            mac(tag + "BA", "%.3f" % r.holm_BvsA); mac(tag + "BAse", "%.3f" % r.holm_BvsA_mcse); mac(tag + "CA", "%.3f" % r.holm_CvsA)
            mac(tag + "Both", "%.3f" % r.holm_both); mac(tag + "Unadj", "%.3f" % r.unadj_BvsA); mac(tag + "Analytic", "%.3f" % r.analytic_unadj_BvsA)
for J_, jn in ((56, "Big"), (28, "Small")):
    for icc in (0.05, 0.1):
        for alloc in sorted(set(PH.alloc)):
            r = PH[(PH.J == J_) & (PH.icc == icc) & (PH.d == 0.3) & (PH.estimator == "LMM_tJc") & (PH.alloc == alloc)]
            if len(r) and alloc != "equal": mac("Pow%sIcc%sDThreeCtrlHeavyBA" % (jn, NM[icc]), "%.3f" % r.iloc[0].holm_BvsA)
MD = pd.DataFrame(SS["analytic_mdes"]["rows"])
for J_, jn in ((56, "Big"), (28, "Small")):
    for icc in (0.05, 0.1):
        r = MD[(MD.J == J_) & (MD.icc == icc) & (MD.alpha == 0.05)].iloc[0]; mac("Mdes%sIcc%s" % (jn, NM[icc]), "%.2f" % r.mdes_BvsA)
        r = MD[(MD.J == J_) & (MD.icc == icc) & (MD.alpha == 0.025)].iloc[0]; mac("MdesBonf%sIcc%s" % (jn, NM[icc]), "%.2f" % r.mdes_BvsA)
CN = SS["clusters_needed_80pct_power_d0.3"]["results"]
for icc, k in ((0.05, "icc_0.05"), (0.1, "icc_0.1")):
    mac("NeedMarg%s" % NM[icc], str(CN[k]["marginal_each_contrast"]["smallest_grid_J_with_point_estimate_ge_0_80"]))
    mac("NeedJoint%s" % NM[icc], str(CN[k]["joint_both_rejected"]["smallest_grid_J_with_point_estimate_ge_0_80"]))
    mac("NeedAnalytic%s" % NM[icc], str(CN[k]["analytic_unadjusted_alpha_0.05_J"]))
T1E = SS["type1_error_base_nulls"]["table"]
EN = {"OLS_HC1": "Ols", "LMM_z": "Lmmz", "LMM_tJc": "Lmmt", "CR2_tJc": "Crt", "CR2_BM": "Crbm", "TwoStage_CL": "Twostage"}
for k, v in T1E.items():
    J_, est = k.split("_", 1)
    if est in EN:
        jn = "Big" if J_ == "J56" else "Small"
        mac("Size%s%sMean" % (jn, EN[est]), "%.3f" % v["mean"]); mac("Size%s%sMin" % (jn, EN[est]), "%.3f" % v["min"]); mac("Size%s%sMax" % (jn, EN[est]), "%.3f" % v["max"])
        mac("Size%s%sFwer" % (jn, EN[est]), "%.3f" % v["holm_FWER_max"])
av = SS["analytic_vs_simulated_unadjusted_power"]
for J_, jn in (("J28", "Small"), ("J56", "Big")):
    mac("AnaDiffMin%s" % jn, "%.3f" % av[J_]["min_diff"]); mac("AnaDiffMax%s" % jn, "%.3f" % av[J_]["max_diff"])
va = SS["validation"]; mac("ValRemlDiff", "%.1e" % va["reml_max_abs_diff_fixed_effects"]); mac("ValCrDiff", "%.0e" % max(va["cr2_max_abs_diff_se"], va["bm_max_abs_diff_df"]))
mac("ValDatasets", str(va["n_datasets"]))
bc = SS["bias_coverage_base_grid"]["J56_LMM_tJc"] if "J56_LMM_tJc" in SS["bias_coverage_base_grid"] else SS["bias_coverage_base_grid"]["J28_LMM_tJc"]
mac("CovMinBig", "%.3f" % bc["coverage_min"]); mac("CovMaxBig", "%.3f" % bc["coverage_max"])
mac("BoundaryBig", "%.3f" % SS["lmm_boundary_fraction_base_max"]["J56"]); mac("BoundarySmall", "%.3f" % SS["lmm_boundary_fraction_base_max"]["J28"])
SR = pd.DataFrame(SS["sensitivity_J56"]["rows"]); SR.to_csv(os.path.join(OUT, "sim_sensitivity_J56.csv"), index=False)
nul = SR[(SR.estimator == "LMM_tJc") & (SR.is_null)]
mac("SensSizeMin", "%.3f" % nul.value.min()); mac("SensSizeMax", "%.3f" % nul.value.max()); mac("SensNullN", str(len(nul)))
alt = SR[(SR.estimator == "LMM_tJc") & (~SR.is_null) & (SR.contrast == "BvsA")]
def sv(sid): r = alt[alt.scenario_id == sid]; assert len(r) == 1, sid; return r.iloc[0]
for icc, sfx in ((0.05, "icc0.05"), (0.1, "icc0.1")):
    n = NM[icc]
    for name, sid in (("Consent", "S5-consent-cluster-%s-d0.3"), ("NoBetweenRsq", "S1-R2w0.3-R2b0.0-%s-d0.3"), ("Tutors", "S9-tutors-%s-d0.3"),
                      ("Noncomp", "S10-A-c0.4-delta0.3-%s"), ("LoseTwo", "S5-lose2clusters-%s-d0.3"), ("Mnar", "S4-MNARy-%s-d0.3"),
                      ("LowRsq", "S2-R20.1-%s-d0.3"), ("ArmVar", "S6-sdC1.2-%s-d0.3"), ("Leak", "S10-Bleak0.2-dB0.3-dC0.3-%s")):
        r = sv(sid % sfx); mac("Sens%s%s" % (name, n), "%.3f" % r.value); mac("Sens%s%sBoth" % (name, n), "%.3f" % r.holm_both)
# S6 arm-variance size check across estimators
s6 = SR[(SR.family == "S6_arm_variance") & (SR.is_null) & (SR.contrast == "CvsA")]
for est, en in (("LMM_tJc", "Lmmt"), ("CR2_BM", "Crbm")):
    x = s6[s6.estimator == est].value
    if len(x): mac("SixSize%sMax" % en, "%.3f" % x.max()); mac("SixSize%sMin" % en, "%.3f" % x.min())
# sensitivity table (LaTeX), Holm marginal power for B-A and joint power, planned analysis, d 0.3
fam_lab = {"S1": "Covariate $R^2$ by level", "S2": "Low covariate $R^2$", "S3": "Bounded outcome", "S4": "Missing outcomes", "S5": "Consent and cluster loss",
           "S6": "Unequal arm variance", "S7": "Unequal arm effects", "S8": "Offering effects", "S9": "Tutor effects", "S10": "Policy non-compliance"}
SL = {"S1-R2w0.3-R2b0.0": "no between-cluster $R^2$", "S1-R2w0.3-R2b0.6": "between-cluster $R^2$ 0.6", "S2-R20.1": "$R^2$ 0.1", "S2-R20.2": "$R^2$ 0.2",
      "S3-bounded": "ceiling-bounded scores", "S4-MARx": "MAR on covariate", "S4-MNARy": "MNAR on outcome", "S4-diffarm": "arm-differential attrition",
      "S5-consent-cluster": "consent 75\\%, cluster-varying", "S5-consent-armdiff-x": "consent differs by arm", "S5-lose2clusters": "two clusters lost",
      "S6-sdC1.2": "SD in C 1.2 times A", "S7-dB0.3-dC0.15": "$d_C=0.15$", "S7-dB0.3-dC-0.3": "$d_C=-0.3$", "S7-dB0.3-dC0.0": "$d_C=0$",
      "S8-offshift0.3": "offering shift 0.3 SD", "S8-het0.4-0.2": "effect 0.4 vs 0.2 by offering", "S9-tutors": "tutor random effects",
      "S10-A-c0.2-delta-0.3": "20\\% of A use AI, $\\delta=-0.3$", "S10-A-c0.2-delta0.0": "20\\% of A use AI, $\\delta=0$", "S10-A-c0.2-delta0.3": "20\\% of A use AI, $\\delta=+0.3$",
      "S10-A-c0.4-delta-0.3": "40\\% of A use AI, $\\delta=-0.3$", "S10-A-c0.4-delta0.0": "40\\% of A use AI, $\\delta=0$", "S10-A-c0.4-delta0.3": "40\\% of A use AI, $\\delta=+0.3$",
      "S10-Bleak0.2-dB0.3-dC0.3": "20\\% leakage B$\\to$C", "S10-Bleak0.2-dB0.3-dC0.15": "leakage, $d_C=0.15$", "S10-Bleak0.2-dB0.3-dC0.0": "leakage, $d_C=0$"}
def base_id(sid): return re.sub(r"-icc0\.(05|1)(-d0\.3)?$", "", sid)
import re
alt = alt.assign(base=alt.scenario_id.map(base_id))
lines = []
for b in SL:
    r5 = alt[(alt.base == b) & (alt.icc == 0.05)]; r10 = alt[(alt.base == b) & (alt.icc == 0.1)]
    if not len(r5) or not len(r10): continue
    r5, r10 = r5.iloc[0], r10.iloc[0]
    lines.append("%s & %s & %.2f & %.2f & %.2f & %.2f\\\\" % (fam_lab[b.split("-")[0]], SL[b], r5.value, r5.holm_both, r10.value, r10.holm_both))
open(os.path.join(OUT, "tab_sensitivity_rows.tex"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

for _, r in PR.iterrows(): mac("Lint%s%s" % (MAC[r.model], TMAC[r.task]), str(int(r.lint_fail)))
bcj = SS["bias_coverage_base_grid"]["J56_LMM_tJc"]; mac("SeRatioMinBig", "%.2f" % bcj["modSE_over_empSE_min"]); mac("SeRatioMaxBig", "%.2f" % bcj["modSE_over_empSE_max"])
sS = MS[MS.cond == "S"].set_index("model")[VAR].round(1); dS = sS[[v for v in VAR if v != "pct"]].sub(sS.pct, axis=0)
mac("SensMaxDevOthers", "%.1f" % dS.drop(MODELS[0]).abs().values.max())
mac("MarkNoTheoryDropHaikuFourFive", "%.1f" % -dS.loc[MODELS[0], "pct_notheory"])
# ================= write
with open(os.path.join(OUT, "numbers.tex"), "w", encoding="utf-8") as f:
    f.write("%% generated by audit_analysis_v2.py; do not edit\n")
    for k in sorted(M): f.write("\\newcommand{\\%s}{%s}\n" % (k, M[k]))
print(len(M), "macros")
