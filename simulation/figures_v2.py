"""figures_v2.py -- Figures for the v2 design analysis (PNG + PDF) from results/*.csv."""
import os, sys
import numpy as np, pandas as pd
import matplotlib
import matplotlib.ticker
import matplotlib.pyplot as plt
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import rct_sim_v2 as v2

RES = os.path.join(HERE, "results"); FIG = os.path.join(HERE, "figures")
EST_COL = {"OLS_HC1": "#9e9e9e", "LMM_z": "#e08a3c", "LMM_tJc": "#1f4e9c", "CR2_tJc": "#b07cc6",
           "CR2_BM": "#2a9d8f", "TwoStage_CL": "#6d6d2f"}
J_COL = {28: "#c2571a", 56: "#1f4e9c"}
BAND = 1.96 * np.sqrt(0.05 * 0.95 / 2000)


def _save(fig, name):
    os.makedirs(FIG, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(FIG, f"{name}.{ext}"), dpi=300, bbox_inches="tight")


def fig_type1(df):
    base = df[(df.family == "base") & (df.dB == 0)]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.0), sharey=True, gridspec_kw=dict(wspace=0.06))
    order = v2.ESTIMATORS
    for ax, J in zip(axes, (28, 56)):
        c = 6 if J == 28 else 10
        ax.axvspan(0.05 - BAND, 0.05 + BAND, color="#e6e6e6", lw=0, zorder=0)
        ax.axvline(0.05, color="#555555", lw=0.8, zorder=1)
        for i, e in enumerate(order):
            s = base[(base.J == J) & (base.estimator == e)]
            v = np.concatenate([s.BvsA_rej.values, s.CvsA_rej.values])
            jit = np.random.default_rng(i).uniform(-0.22, 0.22, len(v))
            ax.scatter(v, i + jit, s=6, color=EST_COL[e], alpha=0.55, lw=0, zorder=2)
            ax.plot([np.mean(v)] * 2, [i - 0.32, i + 0.32], color="black", lw=1.4, zorder=3)
        ax.set_xscale("log")
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.set_xticks([0.03, 0.05, 0.1, 0.2, 0.4]); ax.set_xticklabels(["0.03", "0.05", "0.10", "0.20", "0.40"])
        ax.set_xlim(0.03, 0.55)
        ax.set_title(f"J = {J}: {'1 offering, 4 strata' if J == 28 else '2 offerings x 4 strata'}, t(J-c) = t({J - c})",
                     loc="left")
        ax.set_xlabel("Rejection rate under the null (log scale)")
    axes[0].set_yticks(range(len(order)))
    axes[0].set_yticklabels([v2.LABELS[e] for e in order])
    axes[0].set_ylim(len(order) - 0.5, -0.5)
    axes[1].text(0.085, 3.5, "grey band: 95% MC range\nfor 2,000 replications", fontsize=6, va="center", ha="left",
                 color="#555555")
    fig.suptitle("Type I error of confirmatory contrasts by estimator (96 null contrast cells per panel; black tick = mean)",
                 x=0.01, ha="left", fontsize=8)
    _save(fig, "fig_type1_by_estimator")
    return fig


def fig_power(df):
    base = df[(df.family == "base") & (df.alloc == "equal") & (df.R2 == 0.3) & (df.cv == 0.3)]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9), sharey=True, gridspec_kw=dict(wspace=0.06))
    dgrid = np.linspace(0, 0.45, 91)
    for ax, icc in zip(axes, (0.05, 0.10)):
        for J in (28, 56):
            c = 6 if J == 28 else 10
            T = v2.arm_totals(J, "equal")
            an = [v2.analytic_power(d, T[0], T[1], J - c, icc, 0.3, 22.5, 0.3) if d > 0 else 0.05 for d in dgrid]
            ax.plot(dgrid, an, ls="--", lw=1.0, color=J_COL[J], zorder=2)
            s = base[(base.J == J) & (base.icc == icc) & (base.estimator == "LMM_tJc")].sort_values("dB")
            ax.errorbar(s.dB, s.BvsA_rej, yerr=1.96 * s.BvsA_rej_mcse, fmt="o", ms=4, color=J_COL[J],
                        capsize=2, lw=1, zorder=3)
            ax.errorbar(s.dB + 0.008, s.holm_BvsA, yerr=1.96 * s.holm_BvsA_mcse, fmt="s", ms=3.5, mfc="white",
                        color=J_COL[J], capsize=2, lw=0.8, zorder=3)
        ax.axhline(0.8, color="#888888", lw=0.6, ls=":")
        ax.set_xlim(-0.02, 0.52); ax.set_ylim(0, 1.02)
        ax.set_xticks([0, 0.1, 0.2, 0.3, 0.4])
        ax.set_xlabel("True effect d (B vs A, SD units)")
        ax.set_title(f"ICC {icc:.2f}", loc="left")
    axes[0].set_ylabel("Power, B vs A")
    for k, (J, c) in enumerate(((56, 10), (28, 6))):
        axes[0].text(0.50, 0.16 - 0.08 * k, f"J = {J}, t({J - c})", color=J_COL[J], fontsize=7, ha="right", va="center")
    from matplotlib.lines import Line2D
    h = [Line2D([], [], ls="--", color="#444444", lw=1.0),
         Line2D([], [], marker="o", ls="", color="#444444", ms=4),
         Line2D([], [], marker="s", ls="", mfc="white", color="#444444", ms=3.5)]
    axes[0].legend(h, ["analytic, unadjusted", "simulated, unadjusted", "simulated, Holm-adjusted"],
                   loc="upper left", frameon=False, fontsize=6)
    fig.suptitle("Power of the planned LMM t(J-c) for B vs A (R2 0.3, CV 0.3, 10% attrition, equal allocation; "
                 "bars = 95% MC intervals, 1,000 replications)", x=0.01, ha="left", fontsize=8)
    _save(fig, "fig_power_BvsA")
    return fig


def _lab(sid, panel="a"):
    m = {"S1-R2w0.3-R2b0.0": "S1 between-R2 0 (within 0.3)", "S1-R2w0.3-R2b0.6": "S1 between-R2 0.6 (within 0.3)",
         "S2-R20.1": "S2 total R2 0.1", "S2-R20.2": "S2 total R2 0.2", "S3-bounded": "S3 bounded 0-100, ceiling, 5-pt steps",
         "S4-MARx": "S4 MAR on pre-test", "S4-MNARy": "S4 MNAR on outcome", "S4-diffarm": "S4 attrition A/B/C 10/15/20%",
         "S5-consent-cluster": "S5 consent varies by cluster", "S5-consent-armdiff-x": "S5 consent by arm and pre-test",
         "S5-lose2clusters": "S5 two clusters lost", "S6-sdC1.2": "S6 arm C residual SD x1.2",
         "S8-offshift0.3": "S8 offering shift 0.3", "S9-tutors": "S9 crossed tutors (share 0.03)",
         "S7-dB0.3-dC0.0": "S7 partial null (0.3, 0): C vs A", "S8-het0.1--0.1": "S8 offering effects +0.1/-0.1",
         "S10-Bleak0.2-dB0.3-dC0.0": "S10 B leakage, (0.3, 0): C vs A",
         "S8-het0.4-0.2": "S8 offering effects 0.4/0.2", "S7-dB0.3-dC0.15": "S7 (dB, dC) = (0.3, 0.15)",
         "S7-dB0.3-dC-0.3": "S7 (dB, dC) = (0.3, -0.3)",
         "S10-Bleak0.2-dB0.3-dC0.3": "S10 B leakage 0.2, dC 0.3", "S10-Bleak0.2-dB0.3-dC0.15": "S10 B leakage 0.2, dC 0.15"}
    key = sid.split("-icc")[0]
    if panel == "b" and key == "S7-dB0.3-dC0.0":
        return "S7 (dB, dC) = (0.3, 0)"
    if panel == "b" and key == "S10-Bleak0.2-dB0.3-dC0.0":
        return "S10 B leakage 0.2, dC 0"
    if key.startswith("S10-A"):
        c, dlt = key.split("-c")[1].split("-delta")
        return f"S10 covert AI in A: c {c}, delta {dlt}"
    return m.get(key, key)


def fig_sensitivity(sr):
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 6.4), gridspec_kw=dict(wspace=1.15, width_ratios=[1, 1]))
    # (a) size: null contrast cells (B-A and C-A pooled as two points per scenario)
    nul = sr[sr.is_null]
    keys = list(dict.fromkeys(_lab(s) for s in nul.scenario_id))
    ax = axes[0]
    ax.axvspan(0.05 - BAND, 0.05 + BAND, color="#e6e6e6", lw=0, zorder=0); ax.axvline(0.05, color="#555", lw=0.8)
    for est, off in (("LMM_tJc", -0.15), ("CR2_BM", 0.15)):
        for icc, mk in ((0.05, "o"), (0.10, "^")):
            s = nul[(nul.estimator == est) & (nul.icc == icc)]
            y = [keys.index(_lab(x)) + off for x in s.scenario_id]
            ax.errorbar(s.value, y, xerr=1.96 * s.value_mcse, fmt=mk, ms=3.2, color=EST_COL[est], lw=0.6,
                        capsize=0, alpha=0.9, mfc=EST_COL[est] if icc == 0.05 else "white")
    ax.set_yticks(range(len(keys))); ax.set_yticklabels(keys); ax.set_ylim(len(keys) - 0.5, -0.5)
    ax.set_xlim(0.02, 0.085); ax.set_xlabel("Size of a true-null contrast (alpha 0.05)")
    ax.set_title("a  Size of true-null contrasts", loc="left")
    # (b) power: Holm marginal B vs A, alternatives
    alt = sr[(~sr.is_null) & (sr.contrast == "BvsA")]
    keys2 = list(dict.fromkeys(_lab(s, "b") for s in alt.scenario_id))
    ax = axes[1]
    for est, off in (("LMM_tJc", -0.15), ("CR2_BM", 0.15)):
        for icc, mk in ((0.05, "o"), (0.10, "^")):
            s = alt[(alt.estimator == est) & (alt.icc == icc)]
            y = [keys2.index(_lab(x, "b")) + off for x in s.scenario_id]
            ax.errorbar(s.value, y, xerr=1.96 * s.value_mcse, fmt=mk, ms=3.2, color=EST_COL[est], lw=0.6,
                        capsize=0, mfc=EST_COL[est] if icc == 0.05 else "white")
    ax.set_yticks(range(len(keys2))); ax.set_yticklabels(keys2); ax.set_ylim(len(keys2) - 0.5, -0.5)
    ax.axvline(0.8, color="#888", lw=0.6, ls=":")
    ax.set_xlim(0.2, 1.02); ax.set_xlabel("Holm-adjusted power, B vs A")
    ax.set_title("b  Power, J = 56, d = 0.3 unless stated", loc="left")
    from matplotlib.lines import Line2D
    h = [Line2D([], [], marker="s", ls="", color=EST_COL["LMM_tJc"], ms=4),
         Line2D([], [], marker="s", ls="", color=EST_COL["CR2_BM"], ms=4),
         Line2D([], [], marker="o", ls="", color="#444", ms=3.5),
         Line2D([], [], marker="^", ls="", color="#444", mfc="white", ms=3.5)]
    fig.legend(h, [v2.LABELS["LMM_tJc"], v2.LABELS["CR2_BM"], "ICC 0.05 (filled)", "ICC 0.10 (open)"],
               loc="lower center", ncol=4, frameon=False, fontsize=6, bbox_to_anchor=(0.5, -0.04))
    fig.suptitle("Sensitivity families at J = 56 (t(46)); bars = 95% MC intervals; size from 2,000 and power from "
                 "1,000 replications", x=0.01, ha="left", fontsize=8)
    fig.subplots_adjust(bottom=0.11, left=0.30, right=0.98, top=0.93)
    _save(fig, "fig_sensitivity_noncompliance")
    return fig


def main(style=None):
    df = pd.read_csv(os.path.join(RES, "rct_design_results_v2.csv"))
    sr = pd.read_csv(os.path.join(RES, "sensitivity_summary.csv"))
    return fig_type1(df), fig_power(df), fig_sensitivity(sr)


if __name__ == "__main__":
    matplotlib.rcParams.update({"font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "xtick.labelsize": 6,
                                "ytick.labelsize": 6, "legend.fontsize": 7, "axes.spines.top": False,
                                "axes.spines.right": False, "pdf.fonttype": 42})
    main()
