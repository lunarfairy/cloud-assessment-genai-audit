"""Shared helpers for the grader-validation package (v2).

The archived graders are imported read-only from the audit harness directory, located by
(1) the GV_AUDIT environment variable or (2) the directory ../graders/v1.0 relative to this package.
Nothing in the audit directory is modified. Grading of many items is sharded over independent
subprocess workers (python gvlib.py worker <in.json> <out.json>), because multiprocessing pools
are unavailable on some sandboxed Windows hosts.
"""
import hashlib, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.abspath(os.environ.get("GV_AUDIT") or os.path.join(HERE, "..", "graders", "v1.0"))
if AUDIT not in sys.path:
    sys.path.insert(0, AUDIT)

N_REQ = {"T1": 9, "T2": 11, "T3": 16}
APP_ALL = ["A%02d" % i for i in range(1, 17)]
DES_ALL = ["D%02d" % i for i in range(1, 11)]
GRADER_FILES = ["checks_iac.py", "checks_des.py", "app_runner.py", "runner.py"]


def check_ids(task):
    if task in N_REQ:
        return ["%s.R%d" % (task, i) for i in range(1, N_REQ[task] + 1)]
    return APP_ALL if task == "APP" else DES_ALL


def grader_hashes(audit=AUDIT):
    return {f: hashlib.sha256(open(os.path.join(audit, f), "rb").read()).hexdigest() for f in GRADER_FILES}


def rel(p):
    return os.path.relpath(os.path.abspath(p), HERE).replace("\\", "/")


def grade_file(task, path, do_lint=True, checker_dir=None, raw=False):
    """Grade one artefact file with the archived (or a patched-copy) grader.

    Returns {"checks": {id: [bool, msg]}, "lint_errors": int|None, "lint_rules": [...], "parse_ok": bool}.
    Template and design files are wrapped in a fenced block exactly as a model response would be.
    """
    text = open(path, encoding="utf-8").read()
    if checker_dir and checker_dir not in sys.path:
        sys.path.insert(0, checker_dir)
    if raw:  # full model response text, graded exactly as the archived runner graded it
        import importlib
        RN = importlib.import_module("runner")
        sub = os.path.join(tempfile.mkdtemp(prefix="gvraw_"), "sub.py")
        g = RN.grade(task, text, sub)
        rules = sorted({m["rule"] for m in g.get("lint", []) if m["level"] == "E"})
        return {"checks": g["checks"], "lint_errors": g.get("lint_errors"), "lint_rules": rules,
                "parse_ok": g.get("parse_ok", g.get("extracted")), "extracted": g.get("extracted")}
    if task in N_REQ:
        import importlib
        CI = importlib.import_module("checks_iac")
        g = CI.grade_iac(task, "```yaml\n" + text + "\n```", do_lint=do_lint)
        rules = sorted({m["rule"] for m in g.get("lint", []) if m["level"] == "E"})
        return {"checks": g["checks"], "lint_errors": g.get("lint_errors") if do_lint else None,
                "lint_rules": rules, "parse_ok": g.get("parse_ok")}
    if task == "DES":
        import importlib
        CD = importlib.import_module("checks_des")
        g = CD.grade_des("```json\n" + text + "\n```")
        return {"checks": g["checks"], "lint_errors": None, "lint_rules": [], "parse_ok": g["parse_ok"],
                "recomputed_proposed": g.get("recomputed_proposed")}
    if task == "APP":
        runner = os.path.join(checker_dir or AUDIT, "app_runner.py")
        tmpd = tempfile.mkdtemp(prefix="gvapp_")
        src = os.path.join(tmpd, "photoapp.py")
        open(src, "w", encoding="utf-8").write(text)
        out = os.path.join(tmpd, "res.json")
        try:
            subprocess.run([sys.executable, runner, src, out], timeout=120, capture_output=True,
                           stdin=subprocess.DEVNULL, cwd=tmpd, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            res = json.load(open(out)) if os.path.exists(out) else {t: [False, "runner crash"] for t in APP_ALL}
        except subprocess.TimeoutExpired:
            res = {t: [False, "timeout"] for t in APP_ALL}
        return {"checks": res, "lint_errors": None, "lint_rules": [], "parse_ok": True}
    raise ValueError(task)


def summarise(task, g):
    fails = [k for k, v in g["checks"].items() if not v[0]]
    lint_ok = (g.get("lint_errors") in (None, 0))
    return {"failed_checks": fails, "all_checks_pass": not fails, "lint_ok": lint_ok,
            "accepted": (not fails) and lint_ok}


def grade_many(items, jobs=8, do_lint=True, checker_dir=None, log=print):
    """items: list of {"key", "task", "path"}; returns {key: grade dict}. Sharded subprocess workers."""
    if not items:
        return {}
    jobs = max(1, min(jobs, len(items)))
    tmpd = tempfile.mkdtemp(prefix="gvshard_")
    procs = []
    env = dict(os.environ, GV_AUDIT=AUDIT, OMP_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    for j in range(jobs):
        shard = items[j::jobs]
        fin, fout = os.path.join(tmpd, "in%d.json" % j), os.path.join(tmpd, "out%d.json" % j)
        json.dump({"items": shard, "do_lint": do_lint, "checker_dir": checker_dir}, open(fin, "w"))
        procs.append((subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker", fin, fout],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                       stdin=subprocess.DEVNULL), fout))
    out = {}
    for p, fout in procs:
        _, err = p.communicate()
        if p.returncode != 0 or not os.path.exists(fout):
            raise RuntimeError("worker failed: %s" % err.decode(errors="replace")[-2000:])
        out.update(json.load(open(fout)))
    return out


def _worker(fin, fout):
    spec = json.load(open(fin))
    res = {}
    for it in spec["items"]:
        try:
            res[it["key"]] = grade_file(it["task"], it["path"], spec.get("do_lint", True), spec.get("checker_dir"), it.get("raw", False))
        except Exception as e:  # recorded, never silently dropped
            res[it["key"]] = {"checks": {k: [False, "harness error %r" % e] for k in check_ids(it["task"])},
                              "lint_errors": None, "lint_rules": [], "parse_ok": False, "error": repr(e)}
    json.dump(res, open(fout, "w"))


if __name__ == "__main__" and len(sys.argv) == 4 and sys.argv[1] == "worker":
    _worker(sys.argv[2], sys.argv[3])
