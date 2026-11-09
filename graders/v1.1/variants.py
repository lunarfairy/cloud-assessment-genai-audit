"""Brief-variant runs for the GenAI capability audit.

run_anchor(llm, model, out_dir, reps=5)
    Single-shot runs of the anchor-style (less explicit) Stage 1-3 briefs in tasks/anchor_briefs.json.
    Graded with the unchanged checkers; tasks/anchor_briefs.json also classifies every check as
    stated, implied or unspecified by the anchor-style brief.
run_des_corrected(llm, model, out_dir, reps=5, conds=("S", "A"))
    Stage 4 runs with the corrected brief in tasks/des_corrected.json (N1 made consistent with N4).
    D08 uses PEAK_HOURS = 5 to match the corrected N1; every other check is unchanged.

Both functions temporarily override runner.BATTERY briefs (and checks_des.PEAK_HOURS) and restore
them afterwards. Output layout is identical to runner.run_battery (state.json, turns.jsonl, raw.jsonl).
"""
import json, os, contextlib
import runner as RN
import checks_des as CD

HERE = os.path.dirname(os.path.abspath(__file__))
ANCHOR = json.load(open(os.path.join(HERE, "tasks", "anchor_briefs.json"), encoding="utf-8"))
DESV2 = json.load(open(os.path.join(HERE, "tasks", "des_corrected.json"), encoding="utf-8"))


@contextlib.contextmanager
def overrides(briefs=None, peak_hours=None):
    saved = dict(RN.BATTERY["briefs"]), CD.PEAK_HOURS
    try:
        if briefs:
            RN.BATTERY["briefs"].update(briefs)
        if peak_hours is not None:
            CD.PEAK_HOURS = peak_hours
        yield
    finally:
        RN.BATTERY["briefs"].clear()
        RN.BATTERY["briefs"].update(saved[0])
        CD.PEAK_HOURS = saved[1]


def run_anchor(llm, model, out_dir, reps=5, **kw):
    eps = RN.plan_episodes([("T1", ["S"]), ("T2", ["S"]), ("T3", ["S"])], reps)
    with overrides(briefs=ANCHOR["briefs"]):
        return RN.run_battery(llm, model, eps, out_dir, **kw)


def run_des_corrected(llm, model, out_dir, reps=5, conds=("S", "A"), **kw):
    eps = RN.plan_episodes([("DES", list(conds))], reps)
    with overrides(briefs={"DES": DESV2["brief"]}, peak_hours=DESV2["peak_hours"]):
        return RN.run_battery(llm, model, eps, out_dir, **kw)


def grade_des_corrected(text):
    with overrides(peak_hours=DESV2["peak_hours"]):
        return CD.grade_des(text)
