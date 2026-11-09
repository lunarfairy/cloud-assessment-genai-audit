"""Re-score every archived model turn from its raw response text.

Usage: python regrade_archived.py --runs <extracted model_runs dir> [--checker-dir DIR] [--tag NAME] [--jobs 14]
Reads every turns.jsonl / raw.jsonl under --runs (recursive; the Sonnet 4.5 folder lacks the runs/ level), writes each
response text to a cache directory, grades it with runner.grade() of the archived audit (default) or of a patched
COPY (--checker-dir), and writes regrade_<tag>.json with per-turn checks, lint and all-pass, plus a comparison with
the verdicts recorded in turns.jsonl. This is a static re-scoring: episodes under feedback conditions were driven
by the original grader's feedback, so rounds after the first are not what a patched grader would have produced.
"""
import argparse, glob, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import grade_many  # noqa: E402


def load_runs(runs):
    turns, raws = [], {}
    for f in sorted(glob.glob(os.path.join(runs, "**", "turns.jsonl"), recursive=True)):
        turns += [json.loads(l) for l in open(f, encoding="utf-8")]
    for f in sorted(glob.glob(os.path.join(runs, "**", "raw.jsonl"), recursive=True)):
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            if r["result"].get("text") is not None:
                raws[(r["eid"], r["round"])] = r["result"]["text"]
    return turns, raws


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--checker-dir", default=None)
    ap.add_argument("--tag", default="archived")
    ap.add_argument("--jobs", type=int, default=14)
    ap.add_argument("--tasks", default="T1,T2,T3,APP,DES")
    a = ap.parse_args()
    tasks = set(a.tasks.split(","))
    turns, raws = load_runs(a.runs)
    cache = os.path.join(HERE, "_cache_texts")
    os.makedirs(cache, exist_ok=True)
    items, meta = [], {}
    for t in turns:
        if t["task"] not in tasks:
            continue
        key = "%s#r%d" % (t["eid"], t["round"])
        text = raws.get((t["eid"], t["round"]))
        if text is None:
            meta[key] = {"turn": t, "missing_text": True}
            continue
        p = os.path.join(cache, hashlib.md5(key.encode()).hexdigest() + ".txt")
        open(p, "w", encoding="utf-8").write(text)
        items.append({"key": key, "task": t["task"], "path": p, "raw": True})
        meta[key] = {"turn": t}
    res = grade_many(items, jobs=a.jobs, checker_dir=os.path.abspath(a.checker_dir) if a.checker_dir else None)
    out, n_same_checks, n_same_pass = {}, 0, 0
    for key, m in meta.items():
        t = m["turn"]
        if m.get("missing_text"):
            out[key] = {"missing_text": True}
            continue
        g = res[key]
        ok = all(v[0] for v in g["checks"].values()) and (g.get("lint_errors") in (None, 0))
        rec_checks = {k: bool(v[0]) for k, v in t["checks"].items()}
        new_checks = {k: bool(v[0]) for k, v in g["checks"].items()}
        same_c = rec_checks == new_checks and (t.get("lint_errors") == g.get("lint_errors") or t["task"] in ("APP", "DES"))
        n_same_checks += same_c
        n_same_pass += (ok == bool(t["all_pass"]))
        out[key] = {"model": t["model"], "task": t["task"], "cond": t["cond"], "rep": t["rep"], "round": t["round"],
                    "recorded_all_pass": bool(t["all_pass"]), "recorded_lint_errors": t.get("lint_errors"),
                    "recorded_checks": rec_checks, "checks": new_checks, "lint_errors": g.get("lint_errors"),
                    "lint_rules": g.get("lint_rules", []), "all_pass": ok, "same_as_recorded": same_c,
                    "messages": {k: v[1][:200] for k, v in g["checks"].items() if not v[0]}}
    json.dump(out, open(os.path.join(HERE, "regrade_%s.json" % a.tag), "w", encoding="utf-8"), indent=0)
    print("turns graded %d (missing text %d); identical checks+lint to recorded %d; identical all-pass %d" % (
        len(items), sum(1 for m in meta.values() if m.get("missing_text")), n_same_checks, n_same_pass))


if __name__ == "__main__":
    main()
