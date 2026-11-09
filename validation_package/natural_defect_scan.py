"""Prevalence of the defect types confirmed in the natural-output audit, across ALL archived submissions.

Usage: python natural_defect_scan.py --runs <model_runs dir>      -> natural_defect_scan.csv, natural_defect_scan_summary.json
Static scans (decoded with the archived cfn-lint decoder; graders unchanged):
  S1 T2 fixed physical name (FIXED_NAME_PROPS literal not derived from AWS::StackName or a parameter): collides on the
     second deployment in the same account and Region that the T2 brief announces; T2 has no check for it.
  S2 launch template with both NetworkInterfaces and top-level SecurityGroupIds/SecurityGroups (T2, T3): EC2 rejects the
     launch with InvalidParameterCombination.
  S3 Fn::ImportValue anywhere (T1-T3): the brief deploys into a fresh account, which has no exports.
  S4 APP: app_probes.py P2_literal (LIKE wildcards in the term) and P4_posix_base (host-dependent basename).
"""
import argparse, collections, csv, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import AUDIT  # noqa: E402
from regrade_archived import load_runs  # noqa: E402

sys.path.insert(0, AUDIT)
import checks_iac as CI  # noqa: E402


def walk_keys(v):
    if isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from walk_keys(x)
    elif isinstance(v, list):
        for x in v:
            yield from walk_keys(x)


def scan_template(task, text):
    body = CI.extract_block(text)
    if body is None:
        return None
    tpl, err = CI.decode(body)
    if tpl is None:
        return None
    T = CI.Tpl(tpl)
    s1 = []
    if task == "T2":
        for lid, r in T.R.items():
            prop = CI.FIXED_NAME_PROPS.get((r or {}).get("Type")) if isinstance(r, dict) else None
            v = (r.get("Properties") or {}).get(prop) if prop else None
            if v is not None:
                fv = CI.flat(v)
                if not ("AWS::StackName" in fv or "AWS::StackId" in fv or CI.ref_of(v) in T.P):
                    s1.append("%s.%s=%s" % (lid, prop, fv[:40]))
    s2 = []
    if task in ("T2", "T3"):
        for lid in T.of("AWS::EC2::LaunchTemplate"):
            d = T.props(lid).get("LaunchTemplateData") or {}
            if d.get("NetworkInterfaces") and (d.get("SecurityGroupIds") or d.get("SecurityGroups")):
                s2.append(lid)
    s3 = "Fn::ImportValue" in set(walk_keys(tpl))
    return {"S1_fixed_name_T2": ";".join(s1), "S2_lt_ni_and_sg": ";".join(s2), "S3_importvalue": s3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    a = ap.parse_args()
    turns, raws = load_runs(a.runs)
    rows = []
    for t in turns:
        text = raws.get((t["eid"], t["round"]))
        row = {"model": t["model"], "task": t["task"], "cond": t["cond"], "rep": t["rep"], "round": t["round"],
               "archived_all_pass": bool(t["all_pass"])}
        if t["task"] in ("T1", "T2", "T3"):
            r = scan_template(t["task"], text)
            if r is None:
                continue
            row.update(r)
        elif t["task"] == "APP":
            code = CI.extract_block(text, ("python", "py"))
            if not code or "def " not in code:
                continue
            d = tempfile.mkdtemp(prefix="gvscan_")
            p = os.path.join(d, "photoapp.py")
            open(p, "w", encoding="utf-8").write(code)
            out = os.path.join(d, "p.json")
            subprocess.run([sys.executable, os.path.join(HERE, "app_probes.py"), p, out], timeout=120, capture_output=True,
                           stdin=subprocess.DEVNULL, cwd=d, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            pr = json.load(open(out)) if os.path.exists(out) else {}
            row.update({"S4_like_wildcards": pr.get("P2_literal") is not True, "S4_posix_basename": pr.get("P4_posix_base") is not True,
                        "S4_injection": pr.get("P1_injection") is not True, "S4_not_dicts": pr.get("P3_dicts") is not True,
                        "S4_not_uuid4": pr.get("P5_uuid4") is not True, "S4_client_or_key": pr.get("P6_no_client") is not True})
        else:
            continue
        rows.append(row)
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(HERE, "natural_defect_scan.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader(); w.writerows(rows)
    summ = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        for scope in ("all_turns", "round1", "round1_all_pass"):
            if scope == "round1" and r["round"] != 1:
                continue
            if scope == "round1_all_pass" and not (r["round"] == 1 and r["archived_all_pass"]):
                continue
            key = "%s|%s|%s" % (scope, r["task"], r["model"])
            summ[key]["n"] += 1
            for k, v in r.items():
                if k.startswith("S") and v:
                    summ[key][k] += 1
    json.dump({k: dict(v) for k, v in sorted(summ.items())}, open(os.path.join(HERE, "natural_defect_scan_summary.json"), "w"), indent=1)
    print("rows %d" % len(rows))


if __name__ == "__main__":
    main()
