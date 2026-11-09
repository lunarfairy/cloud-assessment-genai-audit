"""Paired-branching feedback experiment for the GenAI capability audit.

Every branch starts from the SAME archived failing first submission (round 1 of an original
episode), so the feedback regimes are compared on matched starting points with an equal
submission budget (at most runner.MAX_ROUNDS submissions in total, the first being the archived one).

Regimes
  R  retry without diagnostics: the model is told only that the submission did not pass the
     automated checks. The branch stops when every check passes (pass/fail oracle only).
  C  score only: the model is told how many of the automated checks passed (k of N; for templates
     the lint gate counts as one check). Stops when every check passes.
  P  lint and public-test feedback, exactly as runner.feedback(cond="P"); stops when that
     visible feedback is clean (not used for DES, which has no platform response).
  A  requirement-level autograder feedback, exactly as runner.feedback(cond="A"); stops when
     every check passes.

Outputs (in out_dir): branches_turns.jsonl (one line per graded submission, including the
replayed round 1), branches_raw.jsonl (every API response), branches_state.json (resume state).
"""
import json, os, random, hashlib, time
import runner as RN

REVISE = ("\n\nRevise your submission to address this feedback. Return the complete revised deliverable "
          "in the same output format as before, and nothing else.")
SEED = 20261106
CAP_PER_CELL = 8


def n_checks(task, g):
    n = len(g["checks"])
    return n + 1 if task in ("T1", "T2", "T3") else n


def n_passed(task, g):
    k = sum(1 for v in g["checks"].values() if v[0])
    if task in ("T1", "T2", "T3"):
        k += 1 if (g.get("extracted") and g.get("lint_errors", 1) == 0) else 0
    return k


def branch_feedback(task, cond, g, sub_path):
    """Return (feedback_text, stop_flag) for regimes R, C, P, A."""
    if cond in ("P", "A"):
        return RN.feedback(task, cond, g, sub_path)
    passed = RN.all_pass(g)
    if passed:
        return "", True
    if cond == "R":
        return "Autograder report: your submission did not pass the assessment's automated checks." + REVISE, False
    if cond == "C":
        if task == "DES" and not g.get("parse_ok"):
            return "Autograder report: your submission passed 0 of %d automated checks." % len(g["checks"]) + REVISE, False
        return "Autograder report: your submission passed %d of %d automated checks." % (n_passed(task, g), n_checks(task, g)) + REVISE, False
    raise ValueError(cond)


def conds_for(task):
    return ["R", "C", "A"] if task == "DES" else ["R", "C", "P", "A"]


def select_starts(turns, raws, model, cap=CAP_PER_CELL, seed=SEED, tasks=("T1", "T2", "T3", "APP", "DES")):
    """Failing round-1 submissions of `model` (pooled over S/P/A, whose first prompts are identical).
    turns, raws: lists of dicts read from turns.jsonl / raw.jsonl. Returns list of start dicts."""
    text_by = {}
    for r in raws:
        if int(r["round"]) == 1:
            text_by[r["eid"]] = (r.get("result") or {}).get("text")
    starts = []
    rng = random.Random(seed)
    for task in tasks:
        fails = sorted(t["eid"] for t in turns
                       if t["model"] == model and t["task"] == task and int(t["round"]) == 1
                       and str(t["all_pass"]) not in ("True", "true", "1") and t["all_pass"] is not True)
        fails = [e for e in fails if text_by.get(e)]
        pick = fails if len(fails) <= cap else sorted(rng.sample(fails, cap))
        for e in pick:
            starts.append({"start_eid": e, "model": model, "task": task, "text": text_by[e]})
    return starts


def run_branching(llm, starts, out_dir, max_tokens=32000, max_concurrency=8, chunk=16, log=print, max_calls=None):
    """Run (or resume) all branches for the given starts. Returns a status string."""
    os.makedirs(os.path.join(out_dir, "subs"), exist_ok=True)
    sp = os.path.join(out_dir, "branches_state.json")
    tp = os.path.join(out_dir, "branches_turns.jsonl")
    rp = os.path.join(out_dir, "branches_raw.jsonl")
    state = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}

    def record(bid, s, rnd, text, g, fb, usage=None, stop_reason=None):
        turn = {"bid": bid, "start_eid": s["start_eid"], "model": s["model"], "task": s["task"], "cond": s["cond"],
                "round": rnd, "replayed": rnd == 1, "stop_reason": stop_reason, "usage": usage,
                "extracted": g.get("extracted"), "lint_errors": g.get("lint_errors"),
                "lint_rules": sorted({m["rule"] for m in g.get("lint", []) if m["level"] == "E"}),
                "checks": g["checks"], "all_pass": RN.all_pass(g), "n_passed": n_passed(s["task"], g),
                "n_checks": n_checks(s["task"], g), "feedback": fb[:6000], "resp_chars": len(text or "")}
        with open(tp, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn) + "\n")

    # initialise: grade the replayed first submission once per branch
    for st in starts:
        for cond in conds_for(st["task"]):
            bid = "%s|%s" % (st["start_eid"], cond)
            if bid in state:
                continue
            s = {"start_eid": st["start_eid"], "model": st["model"], "task": st["task"], "cond": cond,
                 "round": 1, "done": False, "status": "pending", "errors": 0}
            sub = os.path.join(out_dir, "subs", hashlib.md5(bid.encode()).hexdigest()[:10] + "_r1.py")
            g = RN.grade(st["task"], st["text"], sub)
            fb, stop = branch_feedback(st["task"], cond, g, sub)
            record(bid, s, 1, st["text"], g, fb)
            s["last_text"], s["last_feedback"] = st["text"], fb
            if stop:
                s.update(done=True, status="passed" if RN.all_pass(g) else "stopped_clean_feedback")
            state[bid] = s
    json.dump(state, open(sp, "w", encoding="utf-8"), indent=0)

    calls = 0
    while True:
        active = [k for k, v in state.items() if not v["done"]]
        if not active:
            json.dump(state, open(sp, "w", encoding="utf-8"), indent=0)
            return "finished"
        batch = active[:chunk]
        reqs = []
        for bid in batch:
            s = state[bid]
            msgs = [{"role": "user", "content": RN.brief_prompt(s["task"])},
                    {"role": "assistant", "content": s["last_text"] or "(empty response)"},
                    {"role": "user", "content": s["last_feedback"]}]
            reqs.append({"messages": msgs, "model": s["model"], "max_tokens": max_tokens})
        t0 = time.time()
        try:
            res = llm(reqs, max_concurrency=max_concurrency)
        except RuntimeError as e:
            json.dump(state, open(sp, "w", encoding="utf-8"), indent=0)
            return "runtime_error: " + str(e)[:200]
        calls += 1
        halt = False
        for bid, r in zip(batch, res):
            s = state[bid]
            with open(rp, "a", encoding="utf-8") as f:
                f.write(json.dumps({"bid": bid, "round": s["round"] + 1, "t": time.time(),
                                    "result": {k: r.get(k) for k in ("text", "model", "usage", "stop_reason", "error", "omitted")}}) + "\n")
            if "error" in r and r.get("text") is None:
                err = str(r["error"])
                if RN.USAGE_LIMIT_PAT.search(err):
                    halt = True
                    continue
                if RN.SAFETY_PAT.search(err):
                    s.update(done=True, status="safety_filtered", error=err[:300])
                    continue
                s["errors"] += 1
                if s["errors"] >= 3:
                    s.update(done=True, status="api_error", error=err[:300])
                continue
            text = r.get("text") or ""
            s["round"] += 1
            sub = os.path.join(out_dir, "subs", hashlib.md5(bid.encode()).hexdigest()[:10] + "_r%d.py" % s["round"])
            g = RN.grade(s["task"], text, sub)
            fb, stop = branch_feedback(s["task"], s["cond"], g, sub)
            record(bid, s, s["round"], text, g, fb, RN._usage(r), r.get("stop_reason"))
            s["last_text"], s["last_feedback"] = text, fb
            if stop or s["round"] >= RN.MAX_ROUNDS:
                s["done"] = True
                s["status"] = "passed" if RN.all_pass(g) else ("stopped_clean_feedback" if stop else "final")
        json.dump(state, open(sp, "w", encoding="utf-8"), indent=0)
        log("branching batch %d: %d requests in %.0f s; %d/%d branches done"
            % (calls, len(batch), time.time() - t0, sum(v["done"] for v in state.values()), len(state)))
        if halt:
            return "usage_limit"
        if max_calls and calls >= max_calls:
            return "max_calls"
