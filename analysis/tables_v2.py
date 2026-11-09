"""Generate LaTeX tables from analysis outputs. Usage: python tables_v2.py <root> <results_dir> <out_dir>"""
import json, os, sys, math
import pandas as pd, numpy as np
ROOT, RES, OUT = [os.path.abspath(a) for a in sys.argv[1:4]]; os.makedirs(OUT, exist_ok=True)
MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-5", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
LAB = dict(zip(MODELS, ["Haiku 4.5", "Sonnet 4.5", "Sonnet 5", "Haiku 5.5", "Sonnet 5.5", "Opus 5.5"]))
TASKS = ["T1", "T2", "T3", "APP", "DES"]
def W(name, s): open(os.path.join(OUT, name), "w", encoding="utf-8").write(s)
def ci(lo, hi): return "{\\scriptsize[%.2f, %.2f]}" % (lo, hi)
# ---- Table: first-submission static full pass
PR = pd.read_csv(os.path.join(RES, "primary_first_submission.csv"))
rows = []
for m in MODELS:
    cells = []
    for t in TASKS:
        r = PR[(PR.model == m) & (PR.task == t)].iloc[0]
        c = "%d/%d %s" % (r.k, r.n, ci(r.lo, r.hi))
        if r.k_v10 != r.k: c += "$^{%d}$" % r.k_v10
        cells.append(c)
    rows.append(LAB[m] + " & " + " & ".join(cells) + "\\\\")
W("tab_primary.tex", r"""\begin{table*}[t]
\caption{Static full pass at the first submission, by model and deliverable (grader v1.1). Cells give passing submissions out of first submissions with Wilson 95\% intervals; the fifteen first submissions per implementation task are pooled over the three conditions, whose first prompts are identical, and the design task has ten. A full pass means that every requirement check of the deliverable passes and, for templates, that the template passes the lint gate; for the design it means the ten deterministic checks. A superscript gives the count under the original graders (v1.0) where it differs. Intervals describe repeated generation for a fixed brief and model configuration.}
\label{tab:primary}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{lccccc}
\toprule
Model & Stage 1 template & Stage 2 template & Stage 3 template & Application & Stage 4 design\\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table*}
""")
# ---- Table: feedback regimes and branching by model and task (supplement-sized, but compact enough for main text)
FR = pd.read_csv(os.path.join(RES, "feedback_regimes.csv")); BT = pd.read_csv(os.path.join(RES, "branching_transitions.csv"))
rows = []
for m in MODELS:
    for t in TASKS:
        g = FR[(FR.model == m) & (FR.task == t)]
        cell = []
        for c in ("S", "P", "A"):
            x = g[g.cond == c]
            cell.append("--" if not len(x) else ("%d/%d" % (x.final_k.iloc[0], x.n.iloc[0]) + ("" if c == "S" else " (%.1f)" % x.mean_sub.iloc[0])))
        b = BT[(BT.model == m) & (BT.task == t)]
        bc = []
        for reg in "RCPA":
            x = b[b.regime == reg]
            bc.append("--" if not len(x) else "%d/%d" % (x.repaired.iloc[0], x.n.iloc[0]))
        if all(v == "--" for v in bc) and g.final_k.sum() == g.n.sum(): continue
        rows.append("%s & %s & %s & %s\\\\" % (LAB[m], {"T1": "Stage 1", "T2": "Stage 2", "T3": "Stage 3", "APP": "Application", "DES": "Design"}[t], " & ".join(cell), " & ".join(bc)))
W("tab_feedback.tex", r"""\begin{table*}[t]
\caption{Feedback regimes (grader v1.1). Main battery: full passes at the final submission out of five episodes, with the mean number of submissions in parentheses. Branching: matched failing first submissions repaired within five submissions under each regime. Rows in which every main-battery episode passed and no branching start existed are omitted. Under P the episode stops when the visible feedback is clean, which can happen while hidden checks still fail; the design task has no P condition.}
\label{tab:feedback}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{llccccccc}
\toprule
& & \multicolumn{3}{c}{Main battery} & \multicolumn{4}{c}{Paired branching}\\
\cmidrule(lr){3-5}\cmidrule(lr){6-9}
Model & Deliverable & S & P & A & R & C & P & A\\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table*}
""")
# ---- Table: brief variants
AV = pd.read_csv(os.path.join(RES, "anchor_variants.csv")); DC = pd.read_csv(os.path.join(RES, "des_corrected.csv"))
rows = []
for m in MODELS:
    c = []
    for t in ("T1", "T2", "T3"):
        r = AV[(AV.model == m) & (AV.task == t)].iloc[0]; c.append("%d/%d & %d/%d" % (r.full, r.n, r.si, r.n))
    d = DC[DC.model == m].iloc[0]; P0 = PR[(PR.model == m) & (PR.task == "DES")].iloc[0]
    rows.append("%s & %s & %d/%d & %d/%d & %d/%d\\\\" % (LAB[m], " & ".join(c), P0.k, P0.n, d.first_k, d.first_n, d.finalA_k, d.finalA_n))
W("tab_variants.tex", r"""\begin{table*}[t]
\caption{Brief variants (grader v1.1). Anchor-style briefs for stages 1 to 3, single-shot: full pass on all checks (All) and on the checks the brief states or implies (S+I), out of five. Stage 4: first-submission full pass with the administered brief, and first-submission and final (condition A) full pass with the corrected brief.}
\label{tab:variants}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{lcccccccccc}
\toprule
& \multicolumn{2}{c}{Stage 1} & \multicolumn{2}{c}{Stage 2} & \multicolumn{2}{c}{Stage 3} & \multicolumn{3}{c}{Stage 4 design}\\
\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-7}\cmidrule(lr){8-10}
Model & All & S+I & All & S+I & All & S+I & Administered & Corrected & Corrected, A\\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table*}
""")
# ---- Table: estimated scores
MS = pd.read_csv(os.path.join(RES, "estimated_scores_summary.csv"))
rows = []
for m in MODELS:
    c = []
    for cond in "SPA":
        r = MS[(MS.model == m) & (MS.cond == cond)].iloc[0]; c.append("%.1f {\\scriptsize[%.1f, %.1f]}" % (r.pct, r.pct_lo, r.pct_hi))
    r = MS[(MS.model == m) & (MS.cond == "S")].iloc[0]
    sens = [r[v] for v in ("pct_ungated", "pct_det", "pct_opus", "pct_sonnet", "pct_w50", "pct_w80", "pct_notheory")]
    rows.append("%s & %s & %.1f--%.1f\\\\" % (LAB[m], " & ".join(c), min(sens), max(sens)))
W("tab_marks.tex", r"""\begin{table}[t]
\caption{Estimated battery scores (\% of the 90 auditable marks; grader v1.1): mean over five synthetic profiles with bootstrap 95\% intervals, and the range of the single-shot mean over seven sensitivity analyses (no lint gate; design scored by checks only or by either judge alone; sub-weights 50/50 or 80/20; theory test removed, out of 70). Primary within-stage sub-weights are 60/40 (stage-2 template and database tests) and 70/30 (stage-3 template and storage tests). The P totals reuse the single-shot design and theory scores, because neither task had a P condition, and cells in which no episode used feedback differ from S only through independent first submissions. The scores are not course grades.}
\label{tab:marks}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{lcccc}
\toprule
Model & S & P & A & S, sensitivity range\\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table}
""")
# ---- Table: themes
TH = pd.read_csv(os.path.join(RES, "theme_alignment.csv")).sort_values("student", ascending=False)
rows = []
for _, r in TH.iterrows():
    rows.append("%s & %d & %d & %d/%d {\\scriptsize[%.3f, %.3f]} & %d & %d/%d\\\\" % (r.label, r.student, r.n_checks, r.fails, r.n, r.lo, r.hi, r.fails_gated, r.fails_xA09, r.n_xA09))
W("tab_themes.tex", r"""\begin{table*}[t]
\caption{Student-reported challenge themes in the anchor course and failures of the mapped static checks in first submissions of all six models (grader v1.1). Student counts are theme occurrences in reflections without denominators; model counts are failed check evaluations out of evaluations. Lint-gated counts treat every mapped template check as failed when the template fails the lint gate. The last column excludes the host-dependent filename test A09. The two indicators are not commensurable, and the comparison is descriptive.}
\label{tab:themes}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{p{5.2cm}cccccc}
\toprule
Theme & Student occurrences & Mapped checks & Model failures [95\% CI] & Lint-gated & Excluding A09\\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}
\end{table*}
""")
# ---- Table: grader verification summary
adv10 = pd.read_csv(os.path.join(ROOT, "validation", "adversarial_results.csv")); adv11 = pd.read_csv(os.path.join(ROOT, "validation", "adversarial_results_v11.csv"))
mut = pd.read_csv(os.path.join(ROOT, "validation", "mutation_results_v11.csv")); pos = pd.read_csv(os.path.join(ROOT, "validation", "positive_controls_v11.csv"))
mut10 = pd.read_csv(os.path.join(ROOT, "validation", "mutation_results.csv")); pos10 = pd.read_csv(os.path.join(ROOT, "validation", "positive_controls.csv"))
M10 = mut10[~mut10.id.astype(str).str.contains("S01")]; M11 = mut[~mut.id.astype(str).str.contains("S01")]
prb = json.load(open(os.path.join(ROOT, "validation", "probes_v11.json")))
def oc(d, o): return int((d.outcome == o).sum())
n_amb10 = oc(adv10, "AMB-A") + oc(adv10, "AMB-R"); n_amb11 = oc(adv11, "AMB-A") + oc(adv11, "AMB-R")
pa = sum(1 for k, v in prb["expected"].items() if v == "accept"); pr_ = len(prb["expected"]) - pa
W("tab_grader.tex", r"""\begin{table}[t]
\caption{Grader verification under the original (v1.0) and corrected (v1.1) graders. FA, false accept; FR, false reject. Adversarial expected verdicts were fixed before grading; three cases are ambiguous under the brief and are not scored. The targeted probes test the three corrections added after the brief-variant runs.}
\label{tab:grader}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{lcc}
\toprule
Test set & v1.0 & v1.1\\
\midrule
Single-fault mutants detected & %d/%d & %d/%d\\
Alternative valid solutions accepted & %d/%d & %d/%d\\
Targeted probes, valid variants accepted & %d/%d & %d/%d\\
Targeted probes, invalid variants rejected & %d/%d & %d/%d\\
Adversarial cases, FA & %d & %d\\
Adversarial cases, FR & %d & %d\\
Adversarial cases, correct (of %d scored) & %d & %d\\
\bottomrule
\end{tabular}
\end{table}
""" % (int(M10.target_detected.sum()), len(M10), int(M11.target_detected.sum()), len(M11),
       int((pos10.grader_verdict == "accept").sum()), len(pos10), int((pos.grader_verdict == "accept").sum()), len(pos),
       pa - prb["v10_false_rejects"], pa, sum(1 for k, v in prb["expected"].items() if v == "accept" and prb["v11"][k]["accepted"]), pa,
       pr_, pr_, sum(1 for k, v in prb["expected"].items() if v == "reject" and not prb["v11"][k]["accepted"]), pr_,
       oc(adv10, "FA"), oc(adv11, "FA"), oc(adv10, "FR"), oc(adv11, "FR"), len(adv10) - n_amb10, oc(adv10, "TA") + oc(adv10, "TR"), oc(adv11, "TA") + oc(adv11, "TR")))
# ---- Table: sensitivity
rows = open(os.path.join(RES, "tab_sensitivity_rows.tex"), encoding="utf-8").read()
W("tab_sensitivity.tex", r"""\begin{table*}[t]
\caption{Sensitivity of the planned analysis at $J=56$ (LMM, $t$ on $J-10=46$ degrees of freedom), $d=0.3$ for B--A unless stated, $R^2=0.3$, cluster-size CV 0.3 and 10\% attrition unless varied. Marginal: Holm-adjusted power for B--A; joint: probability that both confirmatory contrasts are rejected; 1,000 replications per cell (Monte Carlo SE at most 0.016).}
\label{tab:sensitivity}
\footnotesize
\setlength{\tabcolsep}{3.5pt}
\begin{tabular}{llcccc}
\toprule
& & \multicolumn{2}{c}{ICC 0.05} & \multicolumn{2}{c}{ICC 0.10}\\
\cmidrule(lr){3-4}\cmidrule(lr){5-6}
Family & Scenario & Marginal & Joint & Marginal & Joint\\
\midrule
""" + rows + r"""\bottomrule
\end{tabular}
\end{table*}
""")
print("tables written")
