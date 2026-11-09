"""Reconstruct final grader-v1.1 trajectories (main battery and branching) from archived and live responses.

Usage: python v11_merge.py <root>
<root>/regrade/{v10,v11a,v11,t2}_out*.json : grades of every stored response (keys '<src>@@<id>#r<k>', live
    responses 'live@@<tid>#r<k>') under grader v1.0, pre-release v1.1 (v11a, used to drive the first live
    generation), final v1.1 and the tier-2 sensitivity reading; produced by regrade_all.py.
<root>/live/gen1/{wave1,part1,part2,part3}/turns.jsonl : first live generation (driven by v11a feedback).
<root>/live/gen2/part1/turns.jsonl + <root>/gen2_parents.json : second generation (driven by final v1.1).
Rule. Thread state is Markov in (last response, last feedback): the runner sends only the brief, the last
submission and its feedback. A stored response for round k+1 is a valid draw for the final-v1.1 trajectory if its
predecessor is the current round-k response and the feedback it was generated from equals the final-v1.1
feedback of that response, after masking 32-hex identifiers, cfn-lint line numbers and the print order of
Python sets in cfn-lint messages (both vary with hash seeds for identical templates). Preference: archived >
gen1 > gen2. Every trajectory must end with the final-v1.1 stopping rule or at submission 5.
Writes <root>/derived/{turns_v11,episodes_v11,branches_v11}.csv and merge_report.json.
"""
import csv, glob, json, os, re, sys, collections
ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
J = lambda *a: os.path.join(ROOT, *a)
def jl(p): return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
def load(tag):
    o = {}
    for f in sorted(glob.glob(J("regrade", tag + "_out*.json"))): o.update(json.load(open(f, encoding="utf-8")))
    return o
def _ss(m): return "{" + ", ".join(sorted(m.group(1).split(", "))) + "}"
def norm(s):
    s = re.sub(r"[0-9a-f]{32}", "<H>", s or ""); s = re.sub(r"\(line \d+\)", "(line N)", s)
    return re.sub(r"\{('[^'{}]+'(?:, '[^'{}]+')+)\}", _ss, s)
G10, G11A, GF, GT2 = load("v10"), load("v11a"), load("v11"), load("t2")
# ----- pool of candidates: (tid, round) -> [dict(gkey, pred, parent_fb, gen)]
pool = collections.defaultdict(list)
for k in G10:
    src, rest = k.split("@@", 1)
    if src not in ("main", "branch"): continue
    eid, r = rest.rsplit("#r", 1); r = int(r); tid = src + "@@" + eid
    pool[(tid, r)].append(dict(gkey=k, pred=None if r == 1 else "%s#r%d" % (tid, r - 1), parent=None if r == 1 else norm(G10["%s#r%d" % (tid, r - 1)]["fb"]), gen="archived"))
for k in GF:
    if k.startswith("branchnew@@"):
        tid = k.rsplit("#r", 1)[0]; pool[(tid, 1)].append(dict(gkey=k, pred=None, parent=None, gen="archived"))
usage = {}
g1 = {}
for sub in ("wave1", "part1", "part2", "part3"):
    for t in jl(J("live", "gen1", sub, "turns.jsonl")):
        assert (t["tid"], t["round"]) not in g1; g1[(t["tid"], t["round"])] = t
for (tid, r), t in g1.items():
    gk = "live@@%s#r%d" % (tid, r)
    if (tid, r - 1) in g1: pred, pfb = "live@@%s#r%d" % (tid, r - 1), g1[(tid, r - 1)]["grade"]["fb"]
    else: pred = "%s#r%d" % (tid, r - 1); pfb = G11A[pred]["fb"]
    pool[(tid, r)].append(dict(gkey=gk, pred=pred, parent=norm(pfb), gen="gen1")); usage[gk] = t.get("usage")
g2 = {}; GF2 = {}
par2 = json.load(open(J("gen2_parents.json")))
for t in jl(J("live", "gen2", "part1", "turns.jsonl")):
    g2[(t["tid"], t["round"])] = t
for (tid, r), t in g2.items():
    gk = "gen2@@%s#r%d" % (tid, r); GF2[gk] = t["grade"]; usage[gk] = t.get("usage")
    if (tid, r - 1) in g2: pred, pfb = "gen2@@%s#r%d" % (tid, r - 1), g2[(tid, r - 1)]["grade"]["fb"]
    else:
        assert par2[tid]["r"] == r - 1; pred = par2[tid]["gkey"]; pfb = GF[pred]["fb"]
    pool[(tid, r)].append(dict(gkey=gk, pred=pred, parent=norm(pfb), gen="gen2"))
def grade(gk): return GF2[gk] if gk.startswith("gen2@@") else GF[gk]
def same_pred(c, cur):
    if c["gen"] == "archived": return cur["gen"] == "archived" and c["pred"] == cur["gkey"]
    return c["pred"] == cur["gkey"]
ORDER = {"archived": 0, "gen1": 1, "gen2": 2}
def walk(tid, static=False):
    cands = pool[(tid, 1)]; assert len(cands) == 1, tid
    cur, r, traj = cands[0], 1, []
    while True:
        g = grade(cur["gkey"]); traj.append((r, cur, g))
        if static or g["stop"] or r >= 5: return traj
        nxt = sorted([c for c in pool.get((tid, r + 1), []) if same_pred(c, cur) and c["parent"] == norm(g["fb"])], key=lambda c: ORDER[c["gen"]])
        if not nxt: raise AssertionError("no valid continuation for %s after round %d" % (tid, r))
        cur, r = nxt[0], r + 1
def tok(u):
    if not isinstance(u, dict): return 0, 0
    return sum(int(u.get(x) or 0) for x in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")), int(u.get("output_tokens") or 0)
turn_rows, ep_rows, br_rows, used = [], [], [], set()
rep = collections.Counter()
def emit(family, tid, model, task, cond, traj, extra):
    for (r, c, g) in traj:
        used.add(c["gkey"]); fails = [k for k, v in g["checks"].items() if not v[0]]; ti, to = tok(usage.get(c["gkey"]))
        row = dict(family=family, id=tid, model=model, task=task, cond=cond, round=r, source=c["gen"], all_pass=bool(g["all_pass"]),
                   n_checks_passed=len(g["checks"]) - len(fails), n_checks=len(g["checks"]), lint_errors=g.get("lint_errors"),
                   extracted=g.get("extracted"), failed_checks=";".join(fails), stop=bool(g["stop"]), tokens_in=ti, tokens_out=to)
        row.update(extra); turn_rows.append(row)
        rep["turns_" + c["gen"]] += 1
mains = sorted({k.split("@@", 1)[1].rsplit("#r", 1)[0] for k in G10 if k.startswith("main@@")})
first = {e: GF["main@@%s#r1" % e]["all_pass"] for e in mains}
for eid in mains:
    model, task, cond, rp = eid.split("|"); tid = "main@@" + eid
    traj = walk(tid, static=(cond == "S")); emit("main", eid, model, task, cond, traj, {})
    rk = max(r for (t, r) in pool if t == tid and any(c["gen"] == "archived" for c in pool[(t, r)]))
    last = traj[-1][2]
    ep_rows.append(dict(eid=eid, model=model, task=task, cond=cond, rep=int(rp), first_pass_v10=G10[tid + "#r1"]["all_pass"],
                        first_pass_v11=first[eid], first_pass_t2=GT2[tid + "#r1"]["all_pass"], n_sub=traj[-1][0],
                        final_pass=bool(last["all_pass"]), stopped_clean=bool(last["stop"]) and not last["all_pass"],
                        n_live=sum(1 for t in traj if t[1]["gen"] != "archived"),
                        archived_final_pass_v10=bool(G10["%s#r%d" % (tid, rk)]["all_pass"]), archived_n_sub=rk,
                        final_frac=sum(v[0] for v in last["checks"].values()) / len(last["checks"])))
    rep["episodes_" + ("live" if ep_rows[-1]["n_live"] else "archived_only")] += 1
for tid in sorted({t for (t, r) in pool if t.startswith(("branch@@", "branchnew@@"))}):
    model, bid = tid.split("@@")[1].split("::"); _, task, c0, rp, reg = bid.split("|"); start = "|".join(bid.split("|")[:4])
    if first[start]: rep["branches_dropped_start_passes_v11"] += 1; continue
    traj = walk(tid); origin = "new_start_v11" if tid.startswith("branchnew@@") else "archived_start"
    emit("branch", bid, model, task, reg, traj, dict(start_eid=start, origin=origin))
    last = traj[-1][2]
    br_rows.append(dict(bid=bid, model=model, task=task, regime=reg, start_eid=start, origin=origin, n_sub=traj[-1][0],
                        final_pass=bool(last["all_pass"]), stopped_clean=bool(last["stop"]) and not last["all_pass"],
                        n_live=sum(1 for t in traj if t[1]["gen"] != "archived"),
                        first_checks=traj[0][2].get("n_passed", sum(v[0] for v in traj[0][2]["checks"].values())),
                        final_checks=last.get("n_passed", sum(v[0] for v in last["checks"].values())), n_checks=last.get("n_checks", len(last["checks"]))))
    rep["branches_" + origin] += 1
live_all = {c["gkey"] for cl in pool.values() for c in cl if c["gen"] != "archived"}
rep["live_responses_total"] = len(live_all); rep["live_responses_used"] = len(live_all & used)
os.makedirs(J("derived"), exist_ok=True)
for name, rows in [("turns_v11.csv", turn_rows), ("episodes_v11.csv", ep_rows), ("branches_v11.csv", br_rows)]:
    with open(J("derived", name), "w", newline="", encoding="utf-8") as f:
        fn = list(dict.fromkeys(k for r in rows for k in r)); w = csv.DictWriter(f, fieldnames=fn); w.writeheader(); w.writerows(rows)
json.dump(dict(rep), open(J("derived", "merge_report.json"), "w"), indent=1)
print(json.dumps(dict(rep)))
