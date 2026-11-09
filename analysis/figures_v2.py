"""Audit figures (grader v1.1). Usage: python figures_v2.py <root> <results_dir> <fig_dir>"""
import json, math, os, sys
import numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fig_style import apply_figure_style
ROOT, RES, FIG = [os.path.abspath(a) for a in sys.argv[1:4]] if len(sys.argv) > 3 else (ROOT, RES, FIG)
os.makedirs(FIG, exist_ok=True)
try:
    apply_figure_style(sizes=(8, 7, 6))
except NameError:
    plt.rcParams.update({"font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "xtick.labelsize": 6, "ytick.labelsize": 6, "legend.fontsize": 7,
                         "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42, "savefig.dpi": 300, "legend.frameon": False})
MODELS = ["claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929", "claude-sonnet-5", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
LAB = dict(zip(MODELS, ["Haiku 4.5", "Sonnet 4.5", "Sonnet 5", "Haiku 5.5", "Sonnet 5.5", "Opus 5.5"]))
COL = dict(zip(MODELS, ["#E69F00", "#56B4E9", "#009E73", "#0072B2", "#D55E00", "#CC79A7"]))
TASKS = ["T1", "T2", "T3", "APP", "DES"]
TL = {"T1": "Stage 1\ntemplate", "T2": "Stage 2\ntemplate", "T3": "Stage 3\ntemplate", "APP": "Stages 2–3\napplication", "DES": "Stage 4\ndesign"}
def wilson(k, n, z=1.959964):
    p = k / n; d = 1 + z * z / n; c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)
def letter(ax, s, dx=-0.16):
    ax.text(dx, 1.04, s, transform=ax.transAxes, fontweight="bold", fontsize=9, va="bottom", ha="left")
def save(fig, name):
    fig.savefig(os.path.join(FIG, name + ".pdf")); fig.savefig(os.path.join(FIG, name + ".png"), dpi=300); plt.close(fig)
# ---------------- Figure: first-submission completion
PR = pd.read_csv(os.path.join(RES, "primary_first_submission.csv"))
fig, ax = plt.subplots(figsize=(5.4, 2.6)); w = 0.12
for i, t in enumerate(TASKS):
    for j, m in enumerate(MODELS):
        r = PR[(PR.model == m) & (PR.task == t)].iloc[0]; x = i + (j - 2.5) * w; p = r.k / r.n
        ax.errorbar(x, p, yerr=[[p - r.lo], [r.hi - p]], fmt="o", ms=4, color=COL[m], elinewidth=0.8, capsize=0, zorder=3, label=LAB[m] if i == 0 else None)
        if r.k_v10 != r.k: ax.plot(x, r.k_v10 / r.n, marker="o", ms=4.5, mfc="white", mec=COL[m], mew=0.9, ls="none", zorder=2)
ax.plot([], [], marker="o", ms=4.5, mfc="white", mec="0.3", ls="none", label="original graders (v1.0)")
ax.set_xticks(range(5)); ax.set_xticklabels([TL[t] for t in TASKS]); ax.set_ylabel("Static full pass,\nfirst submission")
ax.set_ylim(-0.04, 1.04); ax.set_xlim(-0.5, 4.5)
ax.legend(ncol=4, loc="lower center", bbox_to_anchor=(0.5, 1.0), handletextpad=0.3, columnspacing=0.9)
fig.tight_layout(); save(fig, "fig_completability")
# ---------------- Figure: feedback regimes
FR = pd.read_csv(os.path.join(RES, "feedback_regimes.csv")); BR = pd.read_csv(os.path.join(ROOT, "derived", "branches_v11.csv"))
BR["final_pass"] = BR.final_pass.astype(str).isin(["True", "true", "1"])
fig, (a1, a2) = plt.subplots(1, 2, figsize=(5.4, 2.55), gridspec_kw=dict(width_ratios=[1.55, 1]))
cl = {"S": "single-shot (S)", "P": "lint and public tests (P)", "A": "requirement-level autograder (A)"}; mk = {"S": "o", "P": "s", "A": "^"}
for j, m in enumerate(MODELS):
    g = FR[(FR.model == m) & (FR.task != "DES")]
    for ci, c in enumerate("SPA"):
        gg = g[g.cond == c]; k = int(gg.final_k.sum()); n = int(gg.n.sum()); lo, hi = wilson(k, n); x = j + (ci - 1) * 0.24
        a1.errorbar(x, k / n, yerr=[[k / n - lo], [hi - k / n]], fmt=mk[c], ms=4, color=COL[m], elinewidth=0.8, mfc=COL[m] if c != "P" else "white")
a1.set_xticks(range(6)); a1.set_xticklabels([LAB[m].replace(" ", "\n") for m in MODELS])
a1.set_ylabel("Full pass at final submission"); a1.set_ylim(-0.04, 1.08); a1.set_xlim(-0.5, 5.5)
for c in "SPA": a1.plot([], [], mk[c], color="0.35", mfc="0.35" if c != "P" else "white", ms=4, ls="none", label=cl[c])
a1.legend(loc="lower right", fontsize=6, handletextpad=0.2, borderaxespad=0.1)
a1.set_title("Main battery, implementation tasks", loc="left")
nd = BR[BR.task != "DES"]; dsx = BR[BR.task == "DES"]
for i, reg in enumerate("RCPA"):
    g = nd[nd.regime == reg]; k = int(g.final_pass.sum()); n = len(g); lo, hi = wilson(k, n)
    a2.errorbar(i, k / n, yerr=[[k / n - lo], [hi - k / n]], fmt="o", ms=4.5, color="0.15", elinewidth=0.9)
    a2.annotate("%d/%d" % (k, n), (i, k / n), xytext=(5, -9), textcoords="offset points", fontsize=6)
    if reg != "P":
        g = dsx[dsx.regime == reg]; a2.plot(i + 0.2, g.final_pass.mean(), "D", ms=3.5, mfc="white", mec="0.15", ls="none")
a2.plot([], [], "o", color="0.15", ms=4, ls="none", label="implementation tasks"); a2.plot([], [], "D", mfc="white", mec="0.15", ms=3.5, ls="none", label="design task")
a2.legend(loc="upper left", fontsize=6, handletextpad=0.2, borderaxespad=0.1)
a2.set_xticks(range(4)); a2.set_xticklabels(["R\nretry only", "C\nscore", "P\nlint/public", "A\nchecks"])
a2.set_ylim(-0.04, 1.08); a2.set_xlim(-0.5, 3.6); a2.set_ylabel("Repaired within five submissions"); a2.set_title("Matched failing starts", loc="left")
letter(a1, "a", -0.13); letter(a2, "b", -0.25)
fig.tight_layout(w_pad=1.2); save(fig, "fig_feedback")
# ---------------- Figure: estimated scores
MK = pd.read_csv(os.path.join(RES, "estimated_scores.csv")); MS = pd.read_csv(os.path.join(RES, "estimated_scores_summary.csv"))
fig, (a1, a2) = plt.subplots(1, 2, figsize=(5.4, 2.5), gridspec_kw=dict(width_ratios=[1.3, 1]))
for j, m in enumerate(MODELS):
    for ci, c in enumerate("SPA"):
        x = j + (ci - 1) * 0.24; g = MK[(MK.model == m) & (MK.cond == c)].pct.values
        a1.plot(np.full(len(g), x), g, "_", color=COL[m], ms=5, alpha=0.6)
        a1.plot(x, g.mean(), mk[c], color=COL[m], ms=4, mfc=COL[m] if c != "P" else "white")
a1.set_xticks(range(6)); a1.set_xticklabels([LAB[m].replace(" ", "\n") for m in MODELS]); a1.set_ylabel("Estimated score (%)")
for c in "SPA": a1.plot([], [], mk[c], color="0.35", mfc="0.35" if c != "P" else "white", ms=4, ls="none", label=c)
a1.legend(loc="lower right", ncol=3, fontsize=6, handletextpad=0.1, columnspacing=0.6); a1.set_title("By feedback condition", loc="left")
VAR = [("pct", "primary"), ("pct_ungated", "no lint gate"), ("pct_det", "design: checks only"), ("pct_opus", "design: Opus 5 judge"),
       ("pct_sonnet", "design: Sonnet 4.6 judge"), ("pct_w50", "sub-weights 50/50"), ("pct_w80", "sub-weights 80/20"), ("pct_notheory", "no theory test")]
for j, m in enumerate(MODELS):
    r = MS[(MS.model == m) & (MS.cond == "S")].iloc[0]
    vals = [r[v] for v, _ in VAR]; ys = np.arange(len(VAR))
    a2.plot(vals, ys + (j - 2.5) * 0.09, "o", ms=2.5, color=COL[m])
a2.set_yticks(range(len(VAR))); a2.set_yticklabels([l for _, l in VAR]); a2.invert_yaxis(); a2.set_xlabel("Single-shot estimated score (%)")
a2.set_title("Sensitivity of single-shot scores", loc="left")
letter(a1, "a", -0.2); letter(a2, "b", -0.62)
fig.tight_layout(w_pad=0.8); save(fig, "fig_marks")
# ---------------- Figure: design checks heatmap (first submissions, administered brief)
TU = pd.read_csv(os.path.join(ROOT, "derived", "turns_v11.csv")); TU["failed_checks"] = TU.failed_checks.fillna("")
d1 = TU[(TU.family == "main") & (TU.task == "DES") & (TU["round"] == 1)]
D = ["D%02d" % i for i in range(1, 11)]
mat = np.array([[1 - d1[d1.model == m].failed_checks.apply(lambda s: c in s.split(";")).mean() for c in D] for m in MODELS])
fig, ax = plt.subplots(figsize=(5.4, 2.1))
im = ax.imshow(mat, cmap="cividis", vmin=0, vmax=1, aspect="auto")
for i in range(len(MODELS)):
    for j in range(len(D)):
        ax.text(j, i, "%.1f" % mat[i, j], ha="center", va="center", fontsize=6, color="white" if mat[i, j] < 0.55 else "black")
DL = ["schema", "proposed\ncost", "original\ncost", "budget", "peak\ncapacity", "avail-\nability", "recovery", "BoM vs\ndesign", "CDN\ndemand", "six\npillars"]
ax.set_xticks(range(10)); ax.set_xticklabels(["%s\n%s" % (c, l) for c, l in zip(D, DL)], fontsize=6); ax.set_yticks(range(6)); ax.set_yticklabels([LAB[m] for m in MODELS])
cb = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02); cb.set_label("Share of first submissions\npassing (n = 10)", fontsize=6); cb.ax.tick_params(labelsize=6)
for s in ax.spines.values(): s.set_visible(False)
ax.tick_params(length=0); fig.tight_layout(); save(fig, "fig_design_checks")
# ---------------- Figure: themes, two unlike indicators side by side
TH = pd.read_csv(os.path.join(RES, "theme_alignment.csv")).sort_values("student", ascending=True)
fig, (a1, a2) = plt.subplots(1, 2, figsize=(5.4, 2.3), sharey=True, gridspec_kw=dict(width_ratios=[1, 1.3], wspace=0.06))
y = np.arange(len(TH))
a1.barh(y, TH.student, color="0.6", height=0.6); a1.invert_xaxis(); a1.set_xlabel("Occurrences in student\nreflections (anchor course)")
for yy, v in zip(y, TH.student): a1.text(v - 0.8, yy, "%d" % v, ha="left", va="center", fontsize=6, color="white")
a1.set_yticks(y); a1.set_yticklabels(TH.label, fontsize=6)
for j, m in enumerate(MODELS):
    a2.plot(TH["rate_" + ["HaikuFourFive", "SonnetFourFive", "SonnetFive", "HaikuFiveFive", "SonnetFiveFive", "OpusFiveFive"][j]], y + (j - 2.5) * 0.1, "o", ms=2.8, color=COL[m], label=LAB[m])
a2.set_xlabel("Failure rate of mapped static checks,\nfirst submissions"); a2.set_xlim(-0.01, max(0.25, float(np.nanmax(TH[[c for c in TH.columns if c.startswith("rate_")]].values)) + 0.03))
a2.legend(loc="lower right", fontsize=6, ncol=2, handletextpad=0.1, columnspacing=0.5, borderaxespad=0.1)
a1.set_title("Student-reported challenges", loc="left"); a2.set_title("Model artefacts", loc="left")
fig.tight_layout(); save(fig, "fig_divergence")
print("figures written")
