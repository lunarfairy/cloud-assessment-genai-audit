"""Re-run the analysis in a fresh process and diff every output against the files reported in the article.

Usage: python reproduce_and_diff.py [--regrade-sample N | --regrade-full] [--keep]

Default steps (about 2-3 minutes): copy data/ to a temporary directory, delete derived/, then run
  analysis/v11_merge.py        -> derived/{turns_v11,episodes_v11,branches_v11}.csv, merge_report.json
  analysis/audit_analysis_v2.py -> results/*.csv, *.json and numbers.tex (every macro used in the article)
  analysis/tables_v2.py        -> tables/tab_*.tex
  analysis/figures_v2.py and analysis/fig_overview.py -> figures/*.pdf, *.png
and compare derived files, results, macros and tables byte for byte (after normalising line endings) with
data/derived, results/ and tables/. Figures embed timestamps and font subsets, so they are checked for
presence and pixel size only. With --regrade-sample N (or --regrade-full) the stored responses are also
regraded with every grader version (regrade_all.py) and verdicts, checks and feedback are compared with
data/regrade/*_out*.json after masking 32-hex identifiers, cfn-lint line numbers and Python set print order.
Exit status 0 means every comparison matched.
"""
import argparse, filecmp, glob, json, os, re, shutil, subprocess, sys, tempfile
A = os.path.dirname(os.path.abspath(__file__)); PY = sys.executable
ap = argparse.ArgumentParser(); ap.add_argument("--regrade-sample", type=int, default=0); ap.add_argument("--regrade-full", action="store_true"); ap.add_argument("--keep", action="store_true")
a = ap.parse_args(); T = tempfile.mkdtemp(prefix="repro_"); ROOT = os.path.join(T, "data")
shutil.copytree(os.path.join(A, "data"), ROOT, ignore=shutil.ignore_patterns("inputs")); shutil.rmtree(os.path.join(ROOT, "derived"))
RES, TAB, FIG = (os.path.join(T, d) for d in ("results", "tables", "figures"))
for d in (RES, TAB, FIG): os.makedirs(d, exist_ok=True)
def run(*args):
    r = subprocess.run([PY] + [str(x) for x in args], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0"))
    print("$", os.path.basename(str(args[0])), "->", r.returncode, (r.stdout.strip().splitlines() or [""])[-1][:120], flush=True)
    if r.returncode: print(r.stderr[-3000:]); sys.exit(2)
S = lambda n: os.path.join(A, "analysis", n)
run(S("v11_merge.py"), ROOT); run(S("audit_analysis_v2.py"), ROOT, RES); run(S("tables_v2.py"), ROOT, RES, TAB)
run(S("figures_v2.py"), ROOT, RES, FIG); run(S("fig_overview.py"), FIG)
def same(p, q):
    return open(p, "rb").read().replace(b"\r\n", b"\n") == open(q, "rb").read().replace(b"\r\n", b"\n")
bad = []; n = 0
for new_dir, ref_dir in ((os.path.join(ROOT, "derived"), os.path.join(A, "data", "derived")), (RES, os.path.join(A, "results")), (TAB, os.path.join(A, "tables"))):
    ref = {os.path.relpath(p, ref_dir) for p in glob.glob(os.path.join(ref_dir, "**", "*"), recursive=True) if os.path.isfile(p)}
    new = {os.path.relpath(p, new_dir) for p in glob.glob(os.path.join(new_dir, "**", "*"), recursive=True) if os.path.isfile(p)}
    for f in sorted(ref | new):
        n += 1
        if f not in new or f not in ref or not same(os.path.join(new_dir, f), os.path.join(ref_dir, f)): bad.append(os.path.join(os.path.basename(ref_dir), f))
try:
    from PIL import Image
except ImportError:
    Image = None
for p in sorted(glob.glob(os.path.join(A, "figures", "*"))):
    q = os.path.join(FIG, os.path.basename(p)); n += 1
    if not os.path.exists(q): bad.append("figures/" + os.path.basename(p) + " (missing)")
    elif Image and p.endswith(".png") and Image.open(p).size != Image.open(q).size: bad.append("figures/" + os.path.basename(p) + " (size)")
print("compared %d files; %d differences" % (n, len(bad))); [print("  DIFF", b) for b in bad]
if a.regrade_sample or a.regrade_full:
    out = os.path.join(T, "regrade"); args = [os.path.join(A, "regrade_all.py"), "--out", out]
    if a.regrade_sample: args += ["--sample", a.regrade_sample]
    run(*args)
    def norm(s):
        s = re.sub(r"[0-9a-f]{32}", "<H>", s or ""); s = re.sub(r"\(line \d+\)", "(line N)", s)
        return re.sub(r"\{('[^'{}]+'(?:, '[^'{}]+')+)\}", lambda m: "{" + ", ".join(sorted(m.group(1).split(", "))) + "}", s)
    for tag in ("v10", "v11a", "v11", "t2"):
        ref = {}; new = {}
        for f in glob.glob(os.path.join(A, "data", "regrade", tag + "_out*.json")): ref.update(json.load(open(f, encoding="utf-8")))
        for f in glob.glob(os.path.join(out, tag + "_out*.json")): new.update(json.load(open(f, encoding="utf-8")))
        sig = lambda v: (v.get("all_pass"), norm(json.dumps(v.get("checks"), sort_keys=True)), norm(v.get("fb")))
        mism = [k for k, v in new.items() if sig(v) != sig(ref[k])]
        print("regrade %s: %d items compared, %d mismatches" % (tag, len(new), len(mism))); bad += ["regrade " + k for k in mism]
if not a.keep: shutil.rmtree(T, ignore_errors=True)
else: print("outputs kept in", T)
sys.exit(1 if bad else 0)
