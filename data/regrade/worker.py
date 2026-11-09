
import json,sys,os,tempfile,hashlib,re
AUD=sys.argv[3]; sys.path.insert(0,AUD); os.chdir(tempfile.mkdtemp(prefix="rg11_"))
import runner as RN, checks_des as CD, branching as BR
DESV2=json.load(open(os.path.join(AUD,"tasks","des_corrected.json"),encoding="utf-8"))
base=CD.PEAK_HOURS
items=json.load(open(sys.argv[1],encoding="utf-8")); out={}
for it in items:
    sub=os.path.join(os.getcwd(),hashlib.md5(it["key"].encode()).hexdigest()[:12]+".py")
    CD.PEAK_HOURS = DESV2["peak_hours"] if it["src"]=="des_corrected" else base
    try:
        g=RN.grade(it["task"],it["text"],sub)
        if it["mode"]=="branch": fb,stop=BR.branch_feedback(it["task"],it["cond"],g,sub)
        elif it["cond"]=="S": fb,stop="",True
        else: fb,stop=RN.feedback(it["task"],it["cond"],g,sub)
        o={k:g.get(k) for k in ("extracted","lint_errors","parse_ok","recomputed_proposed","word_count")}
        o.update(checks=g["checks"],all_pass=RN.all_pass(g),lint_rules=sorted({m["rule"] for m in g.get("lint",[]) if m["level"]=="E"}),fb=fb,stop=stop)
        if it["mode"]=="branch": o.update(n_passed=BR.n_passed(it["task"],g),n_checks=BR.n_checks(it["task"],g))
    except Exception as e:
        o={"error":repr(e)[:500]}
    out[it["key"]]=o
json.dump(out,open(sys.argv[2],"w",encoding="utf-8"),default=str)
