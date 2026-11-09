"""Judged scoring of the written Stage 4 design rationale (half of the design mark).

This module reproduces, as a standalone script, the judging procedure used in the audit:
two judge models (claude-opus-5 and claude-sonnet-4-6, reasoning disabled) score the written
reasoning on five criteria (0-4 each, total 0-20); judges see the brief and the submission
(design fields, bill of materials, justification, comparison) but not the deterministic results.
Calibration: the reference (gold) justification and four degraded variants, three judgements each.
Retest: ten final designs drawn with random.Random(7), judged a second time.
Requests use max_tokens=1500; replies that cannot be parsed (all of them truncated claude-opus-5
replies that wrote prose before the JSON) are re-issued once with max_tokens=8000 and replace the
truncated reply.
"""
import copy, json, random
import checks_des as CD

JUDGES = ["claude-opus-5", "claude-sonnet-4-6"]
RUBRIC = """Score the written design submission on five criteria, each an integer from 0 to 4 (0 = absent, 1 = weak, 2 = adequate, 3 = good, 4 = excellent):
J1 Diagnosis: correctly identifies the scalability, reliability and cost weaknesses of the original architecture against the new requirements.
J2 Design rationale: explains why each major design choice meets the requirements, including the trade-offs accepted.
J3 Cost reasoning: explains the main cost drivers and how the design stays within budget, consistently with its bill of materials.
J4 Comparison: compares the original and proposed architectures explicitly and fairly.
J5 Technical accuracy: statements about AWS services and architecture are correct (deduct for each factual error).
Judge only the written reasoning; do not recompute the arithmetic. No tools are available. Return only a fenced json block: {"J1": int, "J2": int, "J3": int, "J4": int, "J5": int, "errors_noted": "<short text>"}"""
CRIT = ["J1", "J2", "J3", "J4", "J5"]


def judge_prompt(brief, sub_json_text):
    return ("You are an experienced university examiner in cloud computing marking the Stage 4 design assessment below.\n\n=== ASSESSMENT BRIEF ===\n"
            + brief + "\n\n=== STUDENT SUBMISSION ===\n" + sub_json_text + "\n\n=== MARKING INSTRUCTIONS ===\n" + RUBRIC)


def sub_text(d):
    keep = {k: d.get(k) for k in ["compute", "database", "stated_original_monthly_cost_usd", "stated_proposed_monthly_cost_usd", "justification", "comparison"]}
    keep["proposed_bom"] = d.get("proposed_bom")
    return json.dumps(keep, indent=1)


def calibration_set(gold_des, cost_sentence="Cost optimisation: the design costs about US$582 per month, within the US$750 budget, because capacity above the baseline is paid for only during the 60 peak hours. "):
    """C0 reference; C1 generic text; C2 three inserted factual errors; C3 comparison replaced by a
    one-line assertion AND the diagnosis sentence removed; C4 the explicit cost-optimisation sentence
    removed (the priced bill of materials and stated costs remain visible)."""
    cal = {"C0_gold": gold_des}
    c1 = copy.deepcopy(gold_des)
    c1["justification"] = ("Our new design is scalable, reliable, secure and cost-effective. It follows best practices for operational excellence, security, reliability, performance efficiency, cost optimisation and sustainability. "
                           "We used good AWS services that work well together and will handle the traffic. The design is better in every way and is within budget.")
    cal["C1_generic"] = c1
    c2 = copy.deepcopy(gold_des)
    c2["justification"] = gold_des["justification"].replace(
        "Reliability improves through a NAT gateway in each Availability Zone",
        "Reliability improves because NAT gateways allow the load balancer to reach the instances from the internet").replace(
        "a Multi-AZ db.t3.medium database with automated backups and point-in-time recovery",
        "a Multi-AZ db.t3.medium database whose standby serves read traffic, so no backups are needed") + " CloudFront also encrypts the data stored in RDS."
    cal["C2_errors"] = c2
    c3 = copy.deepcopy(gold_des)
    c3["comparison"] = "The new design is better."
    c3["justification"] = c3["justification"].replace(
        "The existing design cannot meet the new peak: four t3.micro instances supply 160 requests per second against an origin peak of 750. ", "")
    cal["C3_no_comparison"] = c3
    c4 = copy.deepcopy(gold_des)
    c4["justification"] = c4["justification"].replace(cost_sentence, "Cost optimisation is also considered. ")
    cal["C4_no_cost"] = c4
    return cal


def parse(text):
    d, _ = CD.extract_json(text or "")
    ok = isinstance(d, dict) and all(isinstance(d.get(k), (int, float)) for k in CRIT)
    return ({k: d[k] for k in CRIT} if ok else None), (d.get("errors_noted") if ok else None)


def run_judging(llm, items, brief, judges=JUDGES, reps=None, max_tokens=1500, retry_tokens=8000, concurrency=16):
    """items: list of (kind, id, design_dict). reps: dict kind -> number of judgements (default 1).
    Returns list of records {kind,id,judge,rep,text,usage,scores,errors_noted,rerun_max_tokens}."""
    reps = reps or {}
    reqs, meta = [], []
    for kind, iid, d in items:
        for j in judges:
            for rp in range(reps.get(kind, 1)):
                reqs.append({"prompt": judge_prompt(brief, sub_text(d)), "model": j, "max_tokens": max_tokens, "thinking": {"type": "disabled"}})
                meta.append((kind, iid, j, rp))
    out = []
    for i in range(0, len(reqs), 32):
        out += llm(reqs[i:i + 32], max_concurrency=concurrency)
    recs = []
    for (kind, iid, j, rp), q, o in zip(meta, reqs, out):
        sc, en = parse(o.get("text"))
        recs.append({"kind": kind, "id": iid, "judge": j, "rep": rp, "text": o.get("text"), "error": o.get("error"),
                     "usage": o.get("usage"), "scores": sc, "errors_noted": en, "_req": q})
    redo = [r for r in recs if r["scores"] is None]
    if redo:
        o2 = llm([dict(r["_req"], max_tokens=retry_tokens) for r in redo], max_concurrency=concurrency)
        for r, o in zip(redo, o2):
            r.update(text=o.get("text"), error=o.get("error"), usage=o.get("usage"), rerun_max_tokens=retry_tokens)
            r["scores"], r["errors_noted"] = parse(o.get("text"))
    for r in recs:
        r.pop("_req", None)
    return recs


def retest_sample(sub_items, k=10, seed=7):
    return random.Random(seed).sample(sub_items, k)
