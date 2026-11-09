"""Matplotlib settings used for the published figures (font ladder, open frame, tight bounding box, 300 dpi, Type-42 fonts)."""
import matplotlib as mpl
def apply_figure_style(sizes=(8, 7, 6)):
    base, secondary, tick = sizes
    mpl.rcParams.update({"font.family": "sans-serif", "font.size": base, "axes.labelsize": base, "axes.titlesize": base,
        "legend.fontsize": secondary, "xtick.labelsize": tick, "ytick.labelsize": tick, "axes.linewidth": 0.6,
        "xtick.direction": "out", "ytick.direction": "out", "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6, "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": True, "axes.spines.bottom": True, "axes.grid": False, "legend.frameon": False,
        "figure.dpi": 200, "savefig.dpi": 300, "savefig.bbox": "tight", "axes.titleweight": "normal",
        "axes.titlelocation": "left", "axes.labelweight": "normal", "lines.linewidth": 1.2, "patch.linewidth": 0.6,
        "pdf.fonttype": 42, "ps.fonttype": 42})
