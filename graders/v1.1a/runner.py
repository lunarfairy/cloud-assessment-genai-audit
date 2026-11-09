"""Agent loop for the GenAI capability audit.

Conditions
  S  single-shot: one submission, no feedback.
  P  platform feedback: after each submission the model sees only what the cloud platform or a
     public smoke test would show (cfn-lint errors for templates; public-test results and
     tracebacks for the application). The episode stops when that feedback is clean.
  A  autograder feedback: the model sees lint errors plus the full requirement-check report.
     The episode stops when every check passes.
Up to MAX_ROUNDS submissions per episode. The context of each revision request holds the brief,
the most recent submission and its feedback (bounded context).
"""
import json, os, re, sys, time, hashlib, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import checks_iac as CI
import checks_des as CD

BATTERY = json.load(open(os.path.join(HERE, "tasks", "battery.json"), encoding="utf-8"))
MAX_ROUNDS = 5
APP_PUBLIC = ["A01", "A03", "A08"]
APP_ALL = ["A%02d" % i for i in range(1, 17)]
USAGE_LIMIT_PAT = re.compile(r"usage limit|usage window", re.I)
SAFETY_PAT = re.compile(r"safeguard|content safety|stop_reason=refusal|refus", re.I)


# Non-revealing autograder messages for the design task (no correct values are disclosed).
DES_FEEDBACK = {
    "D01": "the bill of materials contains items that are not in the price sheet, invalid quantities, or an invalid instance type",
    "D02": "the stated proposed monthly cost does not match the cost of the listed bill of materials (tolerance 2 percent)",
    "D03": "the stated monthly cost of the original architecture is incorrect (tolerance 2 percent)",
    "D04": "the proposed architecture exceeds the monthly budget",
    "D05": "the maximum web-tier capacity is below the origin peak requirement in N1",
    "D06": "the availability requirement N2 is not met by the declared compute or database configuration",
    "D07": "the recovery requirement N3 is not met by the declared database configuration",
    "D08": "the bill of materials does not cost the instance-hours or database configuration implied by the declared design",
    "D09": "the CloudFront demand in N4 is not fully costed",
    "D10": "the justification does not address every pillar of the AWS Well-Architected Framework by name",
}


def brief_prompt(task):
    return BATTERY["common"] + "\n\n" + BATTERY["briefs"][task]


# ----------------------------------------------------------------------------- grading + feedback
def run_app_tests(code_text, path, which=None, timeout=90):
    with open(path, "w", encoding="utf-8") as f:
        f.write(code_text)
    out = path + ".res.json"
    if os.path.exists(out):
        os.remove(out)
    cmd = [sys.executable, os.path.join(HERE, "app_runner.py"), os.path.abspath(path), os.path.abspath(out)]
    if which:
        cmd.append(",".join(which))
    try:
        subprocess.run(cmd, timeout=timeout, capture_output=True, stdin=subprocess.DEVNULL, cwd=os.path.dirname(os.path.abspath(path)))
    except subprocess.TimeoutExpired:
        return {t: [False, "test run exceeded %d s" % timeout] for t in (which or APP_ALL)}
    if not os.path.exists(out):
        return {t: [False, "test runner produced no result (crash)"] for t in (which or APP_ALL)}
    return json.load(open(out))


def extract_code(text, langs=("python", "py")):
    return CI.extract_block(text, langs) if text else None


def grade(task, text, sub_path):
    """Return dict(checks={id:[pass,msg]}, lint=[...], extracted=bool, ...) for any task."""
    if task in ("T1", "T2", "T3"):
        return CI.grade_iac(task, text)
    if task == "APP":
        code = extract_code(text)
        if code is None or ("def " not in code):
            return {"extracted": False, "checks": {t: [False, "no Python module found in response"] for t in APP_ALL}}
        res = run_app_tests(code, sub_path)
        return {"extracted": True, "checks": res, "n_lines": len(code.splitlines())}
    if task == "DES":
        g = CD.grade_des(text)
        g["extracted"] = g["parse_ok"]
        return g
    raise ValueError(task)


def all_pass(g):
    ok = all(v[0] for v in g["checks"].values())
    if "lint_errors" in g:
        ok = ok and g["lint_errors"] == 0
    return ok


def _lint_lines(g, limit=25):
    errs = [m for m in g.get("lint", []) if m["level"] == "E"]
    lines = ["- %s (line %s): %s" % (m["rule"], m.get("line", "?"), m["message"]) for m in errs[:limit]]
    if len(errs) > limit:
        lines.append("- ... %d more errors" % (len(errs) - limit))
    return errs, lines


def feedback(task, cond, g, sub_path):
    """Return (feedback_text, stop_flag)."""
    revise = "\n\nRevise your submission to address this feedback. Return the complete revised deliverable in the same output format as before, and nothing else."
    if task in ("T1", "T2", "T3"):
        errs, lines = _lint_lines(g)
        if not g.get("extracted"):
            return "No CloudFormation template was found in your response." + revise, False
        if cond == "P":
            if not errs:
                return "", True
            return "CloudFormation template validation failed with the following errors:\n" + "\n".join(lines) + revise, False
        if cond == "A":
            fails = [(k, v[1]) for k, v in g["checks"].items() if not v[0]]
            if not errs and not fails:
                return "", True
            parts = []
            if errs:
                parts.append("Template validation errors:\n" + "\n".join(lines))
            else:
                parts.append("Template validation: no errors.")
            if fails:
                parts.append("Marking checks failed:\n" + "\n".join("- %s: %s" % (k.split(".")[1], m) for k, m in fails))
            return "Autograder report\n" + "\n\n".join(parts) + revise, False
    if task == "APP":
        if not g.get("extracted"):
            return "No Python module was found in your response." + revise, False
        if cond == "P":
            pub = {k: g["checks"][k] for k in APP_PUBLIC}
            fails = [(k, v[1]) for k, v in pub.items() if not v[0]]
            if not fails:
                return "", True
            return "Public smoke tests (3 of the course tests) failed:\n" + "\n".join("- %s: %s" % (k, m) for k, m in fails) + revise, False
        if cond == "A":
            fails = [(k, v[1]) for k, v in g["checks"].items() if not v[0]]
            if not fails:
                return "", True
            return "Autograder report: %d of %d tests failed:\n" % (len(fails), len(g["checks"])) + "\n".join("- %s: %s" % (k, m) for k, m in fails) + revise, False
    if task == "DES":
        if cond == "A":
            if not g.get("parse_ok"):
                return "Autograder report: the submission could not be parsed as the required JSON object." + revise, False
            fails = [k for k, v in g["checks"].items() if not v[0]]
            if not fails:
                return "", True
            return "Autograder report on the design submission (checks failed):\n" + "\n".join("- %s: %s" % (k, DES_FEEDBACK[k]) for k in fails) + revise, False
    return "", True


# ----------------------------------------------------------------------------- episodes
def plan_episodes(tasks_conds, reps):
    eps = []
    for task, conds in tasks_conds:
        for cond in conds:
            for r in range(reps):
                eps.append({"task": task, "cond": cond, "rep": r})
    return eps


def _usage(r):
    u = r.get("usage") or {}
    return {k: u.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}


def run_battery(llm, model, episodes, out_dir, max_tokens=32000, max_concurrency=8, chunk=16, log=print, max_calls=None):
    """Run (or resume) the listed episodes for one model. Returns a status string."""
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "subs"), exist_ok=True)
    state_path = os.path.join(out_dir, "state.json")
    turns_path = os.path.join(out_dir, "turns.jsonl")
    raw_path = os.path.join(out_dir, "raw.jsonl")
    if os.path.exists(state_path):
        state = json.load(open(state_path, encoding="utf-8"))
    else:
        state = {}
    for e in episodes:
        eid = "%s|%s|%s|%d" % (model, e["task"], e["cond"], e["rep"])
        if eid not in state:
            state[eid] = {"task": e["task"], "cond": e["cond"], "rep": e["rep"], "round": 0, "done": False,
                          "status": "pending", "last_text": None, "last_feedback": None, "errors": 0}
    calls = 0
    while True:
        active = [k for k, v in state.items() if not v["done"] and k.startswith(model + "|")]
        if not active:
            json.dump(state, open(state_path, "w", encoding="utf-8"), indent=0)
            return "finished"
        batch = active[:chunk]
        reqs = []
        for eid in batch:
            s = state[eid]
            msgs = [{"role": "user", "content": brief_prompt(s["task"])}]
            if s["round"] > 0:
                msgs += [{"role": "assistant", "content": s["last_text"] or "(empty response)"},
                         {"role": "user", "content": s["last_feedback"]}]
            reqs.append({"messages": msgs, "model": model, "max_tokens": max_tokens})
        t0 = time.time()
        try:
            res = llm(reqs, max_concurrency=max_concurrency)
        except RuntimeError as e:
            msg = str(e)
            log("RuntimeError: %s" % msg[:300])
            json.dump(state, open(state_path, "w", encoding="utf-8"), indent=0)
            return "runtime_error: " + msg[:200]
        wall = time.time() - t0
        calls += 1
        halt = False
        for eid, r in zip(batch, res):
            s = state[eid]
            with open(raw_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"eid": eid, "round": s["round"] + 1, "t": time.time(), "result": {k: r.get(k) for k in ("text", "model", "usage", "stop_reason", "error", "omitted")}}) + "\n")
            if "error" in r and r.get("text") is None:
                err = str(r["error"])
                if USAGE_LIMIT_PAT.search(err):
                    halt = True
                    continue
                if SAFETY_PAT.search(err):
                    s.update(done=True, status="safety_filtered", error=err[:300])
                    continue
                s["errors"] += 1
                if s["errors"] >= 3:
                    s.update(done=True, status="api_error", error=err[:300])
                continue
            text = r.get("text") or ""
            s["round"] += 1
            sub_path = os.path.join(out_dir, "subs", hashlib.md5(eid.encode()).hexdigest()[:10] + "_r%d.py" % s["round"])
            g = grade(s["task"], text, sub_path)
            fb, stop = ("", True) if s["cond"] == "S" else feedback(s["task"], s["cond"], g, sub_path)
            passed = all_pass(g)
            turn = {"eid": eid, "model": model, "task": s["task"], "cond": s["cond"], "rep": s["rep"], "round": s["round"],
                    "stop_reason": r.get("stop_reason"), "usage": _usage(r), "batch_wall_s": round(wall, 1), "batch_n": len(batch),
                    "resp_chars": len(text), "extracted": g.get("extracted"), "lint_errors": g.get("lint_errors"),
                    "lint_rules": sorted({m["rule"] for m in g.get("lint", []) if m["level"] == "E"}),
                    "checks": g["checks"], "all_pass": passed, "feedback": fb[:6000]}
            for extra in ("recomputed_proposed", "word_count", "design", "n_lines"):
                if extra in g:
                    turn[extra] = g[extra]
            with open(turns_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn) + "\n")
            s["last_text"], s["last_feedback"] = text, fb
            if stop or s["round"] >= MAX_ROUNDS or s["cond"] == "S":
                s["done"] = True
                s["status"] = "passed" if passed else ("stopped_clean_feedback" if stop and s["cond"] != "S" else "final")
        json.dump(state, open(state_path, "w", encoding="utf-8"), indent=0)
        n_done = sum(1 for v in state.values() if v["done"])
        log("%s batch %d: %d requests in %.0f s; %d/%d episodes done" % (model, calls, len(batch), wall, n_done, len(state)))
        if halt:
            return "usage_limit"
        if max_calls and calls >= max_calls:
            return "max_calls"


# ----------------------------------------------------------------------------- MCQ
def mcq_prompt():
    lines = [BATTERY["common"], "", "# Assessment task: Theory test (multiple choice)", "",
             "Answer each question with the single best option.", ""]
    for q in BATTERY["mcq"]:
        lines.append("%s. %s" % (q["id"], q["stem"]))
        for k in "ABCD":
            lines.append("   %s) %s" % (k, q["options"][k]))
        lines.append("")
    lines.append('Output format: return a single fenced code block marked json containing one object that maps each question id to its answer letter, for example {"Q01": "A", "Q02": "C"}, and nothing else.')
    return "\n".join(lines)


def run_mcq(llm, model, reps, out_dir, max_tokens=16000, log=print):
    os.makedirs(out_dir, exist_ok=True)
    reqs = [{"prompt": mcq_prompt(), "model": model, "max_tokens": max_tokens} for _ in range(reps)]
    res = llm(reqs, max_concurrency=reps)
    key = {q["id"]: q["key"] for q in BATTERY["mcq"]}
    rows = []
    for i, r in enumerate(res):
        rec = {"model": model, "rep": i, "usage": _usage(r) if "usage" in r else None, "stop_reason": r.get("stop_reason"),
               "error": r.get("error"), "text": r.get("text")}
        ans = {}
        if r.get("text"):
            d, err = CD.extract_json(r["text"])
            if isinstance(d, dict):
                ans = {k: str(v).strip().upper()[:1] for k, v in d.items()}
        rec["answers"] = ans
        rec["correct"] = {qid: ans.get(qid) == k for qid, k in key.items()}
        rec["score"] = sum(rec["correct"].values()) / len(key)
        rows.append(rec)
    with open(os.path.join(out_dir, "mcq.jsonl"), "a", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec) + "\n")
    log("%s MCQ scores %s" % (model, [round(r["score"], 3) for r in rows]))
    return rows
