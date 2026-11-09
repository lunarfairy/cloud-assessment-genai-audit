"""Grade every mutant (76 catalogued + new A01) with the archived, unmodified graders.

Usage:
  python mutate.py && python run_mutation_tests.py [--jobs 10]       writes expected_outputs.json, mutation_results.csv
  python run_mutation_tests.py --verify                              regrades and diffs against expected_outputs.json

For each mutant: does the target check fail (detection), which other checks fail (collateral), and
does the observed collateral set equal the collateral recorded in the archived catalogue
(catalogue/grader_mutation_tests.csv, copied from the audit results)?
"""
import argparse, csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import AUDIT, grade_many, grader_hashes, summarise  # noqa: E402

CAT = os.path.join(HERE, "catalogue", "grader_mutation_tests.csv")
GOLDS = {"T1": "gold/T1.yaml", "T2": "gold/T2.yaml", "T3": "gold/T3.yaml", "APP": "gold/photoapp.py", "DES": "gold/DES.json"}


def compact(g):
    return {"checks": {k: bool(v[0]) for k, v in g["checks"].items()}, "lint_errors": g.get("lint_errors"),
            "lint_rules": g.get("lint_rules", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--checker-dir", default=None, help="grade with a patched COPY instead of the archived graders")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    man = json.load(open(os.path.join(HERE, "mutants", "manifest.json"), encoding="utf-8"))
    cat = list(csv.DictReader(open(CAT, encoding="utf-8")))
    cat_key = {(r["task"], r["target"], r["desc"]): r for r in cat}
    sp = os.path.join(HERE, "mutants", "supplementary.json")
    supp = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else []
    supp_ids = {m["id"] for m in supp}
    man = man + supp
    items = [{"key": m["id"], "task": m["task"], "path": os.path.join(HERE, m["path"])} for m in man]
    items += [{"key": "GOLD_" + t, "task": t, "path": os.path.join(AUDIT, p)} for t, p in GOLDS.items()]
    cdir = os.path.abspath(a.checker_dir) if a.checker_dir else None
    res = grade_many(items, jobs=a.jobs, checker_dir=cdir)
    sfx = ("_" + a.tag) if a.tag else ""
    gold_ok = {t: all(v[0] for v in res["GOLD_" + t]["checks"].values()) and res["GOLD_" + t].get("lint_errors") in (None, 0)
               for t in GOLDS}
    out = {"grader_sha256": grader_hashes(cdir or AUDIT), "checker_dir": "archived audit" if not cdir else os.path.relpath(cdir, HERE).replace("\\", "/"), "gold_baseline": {t: compact(res["GOLD_" + t]) for t in GOLDS},
           "gold_all_pass": gold_ok, "mutants": {}}
    rows = []
    for m in man:
        g = res[m["id"]]
        s = summarise(m["task"], g)
        fails = s["failed_checks"]
        detected = m["target"] in fails
        coll = sorted(f for f in fails if f != m["target"])
        c = cat_key.get((m["task"], m["target"], m["desc"]))
        cat_coll = sorted(x for x in (c["collateral"].split(";") if c and c["collateral"] else []) if x)
        match = (coll == cat_coll) if c else None
        out["mutants"][m["id"]] = dict(compact(g), target=m["target"], desc=m["desc"], target_detected=detected,
                                       collateral=coll, failed_checks=fails)
        rows.append({"id": m["id"], "set": "supplementary" if m["id"] in supp_ids else "main", "task": m["task"], "target": m["target"], "desc": m["desc"], "source": m["source"],
                     "in_catalogue": bool(c), "target_detected": detected, "catalogue_detected": c["detected"] if c else "",
                     "collateral_observed": ";".join(coll), "collateral_catalogue": ";".join(cat_coll) if c else "(new)",
                     "collateral_matches_catalogue": "" if match is None else match,
                     "lint_errors": g.get("lint_errors"), "lint_rules": ";".join(g.get("lint_rules", []))})
    if a.verify:
        ref = json.load(open(os.path.join(HERE, "expected_outputs.json"), encoding="utf-8"))
        diffs = [k for k in out["mutants"] if {x: out["mutants"][k][x] for x in ("checks", "lint_errors")} !=
                 {x: ref["mutants"].get(k, {}).get(x) for x in ("checks", "lint_errors")}]
        diffs += [t for t in GOLDS if out["gold_baseline"][t] != ref["gold_baseline"][t]]
        print("verify: %d mutants, %d differences %s" % (len(out["mutants"]), len(diffs), diffs[:10]))
        sys.exit(1 if diffs else 0)
    json.dump(out, open(os.path.join(HERE, "expected_outputs%s.json" % sfx), "w", encoding="utf-8"), indent=1, sort_keys=True)
    with open(os.path.join(HERE, "mutation_results%s.csv" % sfx), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    main_rows = [r for r in rows if r["set"] == "main"]
    for r in rows:
        if r["set"] != "main":
            print("supplementary %s target %s detected %s collateral %s" % (r["id"], r["target"], r["target_detected"], r["collateral_observed"]))
    rows_all, rows = rows, main_rows
    n_det = sum(r["target_detected"] for r in rows)
    mism = [r["id"] for r in rows if r["collateral_matches_catalogue"] is False]
    print("gold all pass: %s" % gold_ok)
    print("mutants %d; target detected %d; catalogue rows matched %d; collateral mismatches %d %s" % (
        len(rows), n_det, sum(r["in_catalogue"] for r in rows), len(mism), mism))


if __name__ == "__main__":
    main()
