"""Regenerate every result of the grader-validation package.

Usage: python run_all.py --runs <extracted model_runs dir>   (graders located via GV_AUDIT or ../graders/v1.0)
Steps: mutants -> mutation tests (archived graders) -> cases -> case grading -> patched copies -> patched-copy
mutation/case grading -> archived-run regrading (archived, tier1, tier2) -> natural-defect scan.
The LLM-assisted audit (natural_output_audit.csv) is not rerun here: it calls a hosted model and is not deterministic.
"""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(args):
    print(">>", " ".join(args), flush=True)
    r = subprocess.run([sys.executable] + args, cwd=HERE, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    if r.returncode:
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--jobs", default="12")
    a = ap.parse_args()
    run(["mutate.py"])
    run(["run_mutation_tests.py", "--jobs", a.jobs])
    run(["make_cases.py"])
    run(["run_cases.py", "--jobs", a.jobs])
    run(["make_patched_copy.py"])
    for t in ("tier1", "tier2"):
        run(["run_mutation_tests.py", "--jobs", a.jobs, "--checker-dir", "patched_copy/" + t, "--tag", t])
        run(["run_cases.py", "--jobs", a.jobs, "--checker-dir", "patched_copy/" + t, "--tag", t])
    run(["regrade_archived.py", "--runs", a.runs, "--tag", "archived", "--jobs", a.jobs])
    for t in ("tier1", "tier2"):
        run(["regrade_archived.py", "--runs", a.runs, "--checker-dir", "patched_copy/" + t, "--tag", t, "--jobs", a.jobs])
    run(["natural_defect_scan.py", "--runs", a.runs])


if __name__ == "__main__":
    main()
