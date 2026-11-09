"""Grade the positive controls and adversarial cases with the archived graders.

Usage: python make_cases.py && python run_cases.py [--jobs 12] [--checker-dir DIR] [--tag NAME]
Writes positive_controls.csv, adversarial_results.csv and case_results.json (or *_<tag>.* with --tag, e.g.
for a patched-copy checker). Verdict = accept iff every check passes and cfn-lint reports no errors (the
audit's all-pass definition). Outcome: TA/TR (correct), FA (false accept), FR (false reject), or AMB-A/AMB-R
for cases whose expected verdict is ambiguous under the brief. Check level: 'missed' = checks that should fail
under the brief but pass; 'spurious' = checks that fail although the brief is met for that requirement.
"""
import argparse, csv, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import grade_many, summarise  # noqa: E402


def probes(path):
    out = os.path.join(tempfile.mkdtemp(prefix="gvprobe_"), "p.json")
    subprocess.run([sys.executable, os.path.join(HERE, "app_probes.py"), path, out], timeout=120,
                   capture_output=True, stdin=subprocess.DEVNULL, cwd=os.path.dirname(out),
                   env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    return json.load(open(out)) if os.path.exists(out) else {"probe_error": "no output"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--checker-dir", default=None)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    man = json.load(open(os.path.join(HERE, "cases", "cases.json"), encoding="utf-8"))
    items = [{"key": c["id"], "task": c["task"], "path": os.path.join(HERE, c["path"])} for c in man]
    res = grade_many(items, jobs=a.jobs, checker_dir=os.path.abspath(a.checker_dir) if a.checker_dir else None)
    rows, full = {"positive": [], "adversarial": []}, {}
    for c in man:
        g = res[c["id"]]
        s = summarise(c["task"], g)
        verdict = "accept" if s["accepted"] else "reject"
        exp = c["expected"]
        if exp == "ambiguous":
            outcome = "AMB-A" if verdict == "accept" else "AMB-R"
        elif exp == "accept":
            outcome = "TA" if verdict == "accept" else "FR"
        else:
            outcome = "TR" if verdict == "reject" else "FA"
        fails = s["failed_checks"]
        missed = [k for k in c["expect_fail"] if k not in fails]
        spurious = [k for k in fails if k not in c["expect_fail"]] if exp != "ambiguous" else []
        reasons = "; ".join("%s: %s" % (k, g["checks"][k][1][:160]) for k in fails)
        pr = probes(os.path.join(HERE, c["path"])) if c["task"] == "APP" else {}
        row = {"id": c["id"], "task": c["task"], "category": c["category"], "expected": exp, "basis": c["basis"],
               "grader_verdict": verdict, "outcome": outcome, "lint_errors": g.get("lint_errors"),
               "lint_rules": ";".join(g.get("lint_rules", [])), "failed_checks": ";".join(fails),
               "expected_failing_checks": ";".join(c["expect_fail"]), "missed_checks": ";".join(missed),
               "spurious_failures": ";".join(spurious), "probes": ";".join(c["probes"]),
               "app_probes_failed": ";".join(k for k, v in pr.items() if v is not True and k != "P7_unicode_ci"),
               "description": c["rationale"], "grader_messages_for_failed_checks": reasons}
        rows[c["set"]].append(row)
        full[c["id"]] = {"meta": c, "grade": g, "app_probes": pr, "row": row}
    sfx = ("_" + a.tag) if a.tag else ""
    for k, fn in (("positive", "positive_controls"), ("adversarial", "adversarial_results")):
        with open(os.path.join(HERE, fn + sfx + ".csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[k][0]))
            w.writeheader(); w.writerows(rows[k])
    json.dump(full, open(os.path.join(HERE, "case_results%s.json" % sfx), "w", encoding="utf-8"), indent=1)
    for k in rows:
        cnt = {}
        for r in rows[k]:
            cnt[r["outcome"]] = cnt.get(r["outcome"], 0) + 1
        print(k, len(rows[k]), cnt)
        for r in rows[k]:
            if r["outcome"] in ("FA", "FR") or r["missed_checks"] or r["spurious_failures"]:
                print("  %-11s %-3s %-5s fail=%s missed=%s spurious=%s lint=%s" % (r["id"], r["task"], r["outcome"], r["failed_checks"],
                      r["missed_checks"], r["spurious_failures"], r["lint_rules"]))


if __name__ == "__main__":
    main()
