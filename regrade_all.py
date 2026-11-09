"""Regrade every stored response with each grader version.

Usage: python regrade_all.py [--archive .] [--tags v10,v11a,v11,t2] [--jobs 8] [--out DIR] [--sample N]

Inputs  : data/regrade/inputs/items_*.json (1,644 stored responses; each item carries its key, task, condition,
          mode, source and the full response text exactly as sent to the grader).
Graders : graders/v1.0, graders/v1.1a (pre-release v1.1 that produced the feedback seen by the first live
          generation; differs from v1.1 only by the verdict-neutral split of patch P16), graders/v1.1, graders/tier2.
Subsets : v10 = all items except live continuations and new branching starts (1,366); v11a = v10 plus the new
          branching starts (1,434); v11 = all items (1,644); t2 = main battery and anchor-style briefs (576).
Output  : <out>/<tag>_out<k>.json, one file per worker, in the same format as data/regrade/<tag>_out*.json.
Requires cfn-lint 1.59.0 on PATH (see requirements.txt). A full run takes roughly 30-60 minutes on 8 cores.
"""
import argparse, glob, json, os, subprocess, sys, random
ap = argparse.ArgumentParser(); ap.add_argument("--archive", default=os.path.dirname(os.path.abspath(__file__)))
ap.add_argument("--tags", default="v10,v11a,v11,t2"); ap.add_argument("--jobs", type=int, default=8)
ap.add_argument("--out", default=None); ap.add_argument("--sample", type=int, default=0)
a = ap.parse_args(); A = os.path.abspath(a.archive); OUT = os.path.abspath(a.out or os.path.join(A, "regrade_rerun")); os.makedirs(OUT, exist_ok=True)
GR = {"v10": "v1.0", "v11a": "v1.1a", "v11": "v1.1", "t2": "tier2"}
items = []
for f in sorted(glob.glob(os.path.join(A, "data", "regrade", "inputs", "items_*.json"))): items += json.load(open(f, encoding="utf-8"))
def keep(tag, it):
    s = it["key"].split("@@")[0]
    if tag == "v10": return s not in ("live", "branchnew")
    if tag == "v11a": return s != "live"
    if tag == "t2": return s in ("main", "anchor")
    return True
for tag in a.tags.split(","):
    sel = [it for it in items if keep(tag, it)]
    if a.sample: random.Random(20261106).shuffle(sel); sel = sel[:a.sample]
    chunks = [sel[i::a.jobs] for i in range(a.jobs)]; procs = []
    for k, ch in enumerate(chunks):
        fi = os.path.join(OUT, "%s_in%d.json" % (tag, k)); json.dump(ch, open(fi, "w", encoding="utf-8"))
        procs.append(subprocess.Popen([sys.executable, os.path.join(A, "data", "regrade", "worker.py"), fi, os.path.join(OUT, "%s_out%d.json" % (tag, k)), os.path.join(A, "graders", GR[tag])],
                                      env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", OMP_NUM_THREADS="1")))
    rc = [p.wait() for p in procs]; print(tag, len(sel), "items; worker exit codes", rc, flush=True)
