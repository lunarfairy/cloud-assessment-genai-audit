import os,sys
FIG=sys.argv[1]

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fig_style import apply_figure_style
apply_figure_style()
from matplotlib.patches import FancyBboxPatch
fig = plt.figure(figsize=(5.5, 2.9)); ax = fig.add_axes([0.005, 0.005, 0.99, 0.99]); ax.set_xlim(0, 100); ax.set_ylim(0, 56); ax.axis("off")
def box(x, y, w, h, title, body, dashed=False, fc="white"):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2", lw=0.9, ec="0.15", fc=fc, ls=(0, (4, 2)) if dashed else "-")
    ax.add_patch(p); ax.text(x + 1.2, y + h - 1.4, title, fontsize=6.5, fontweight="bold", va="top")
    ax.text(x + 1.2, y + h - 5.6, body, fontsize=5.4, va="top", linespacing=1.3)
def arrow(x0, y0, x1, y1): ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="-|>", lw=0.8, color="0.25"))
box(1, 30, 22, 24, "Battery", "Four-stage project re-\nspecified as 5 deliverables\n(3 templates, application,\ndesign) + 30-item theory\ntest; 62 static checks")
box(27, 30, 25, 24, "Graders (v1.1)", "Lint gate + checks;\nverified by mutants, alter-\nnative valid solutions,\nadversarial cases and a\nnatural-output audit;\ncorrected before analysis")
box(56, 30, 43, 24, "Capability audit (6 models, static only)", "Main battery: S, P, A regimes, 5 episodes each\nPaired branching: R, C, P, A from matched\nfailing starts; anchor-style and corrected briefs\nOutputs: first-submission full pass, repair,\nestimated scores, judged design rationale,\ndescriptive comparison with student themes")
box(1, 2, 45, 22, "Design analysis (simulation)", "720,000 simulated trials of the planned\ncluster-randomised design: Type I error, power,\nprecision and sensitivity of candidate analyses\n(J = 28 and 56 tutorial groups)")
box(52, 2, 47, 22, "Proposed trial (not run)", "Three AI-use policy packages (A, B, C) randomised\nby tutorial group; common verification viva;\nprimary outcome scored by new graders built and\nvalidated with the same method", dashed=True, fc="#f4f4f4")
arrow(23.6, 42, 26.4, 42); arrow(52.6, 42, 55.4, 42); arrow(77, 29.4, 77, 24.8); arrow(46.6, 13, 51.4, 13)
ax.text(78, 27, "informs threat model\nand outcome design", fontsize=5.5, va="center", ha="left", color="0.3")
ax.text(49, 9.5, "sample\nsize", fontsize=5, ha="center", va="top", color="0.3")

fig=plt.gcf(); fig.savefig(os.path.join(FIG,"fig_overview.pdf")); fig.savefig(os.path.join(FIG,"fig_overview.png"),dpi=300)
