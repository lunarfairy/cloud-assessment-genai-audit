"""Deterministic checks for the Stage 4 design task (DES)."""
import json, math, os, re

_HERE = os.path.dirname(os.path.abspath(__file__))
_PS = json.load(open(os.path.join(_HERE, "tasks", "price_sheet.json")))
PRICES = _PS["price_sheet"]["prices"]
CAP = _PS["price_sheet"]["capacity_requests_per_second_per_instance_at_70pct_cpu"]
ORIG = _PS["original_bom"]
MULT = PRICES["rds_multiaz_multiplier"]
ORIGIN_PEAK = 750
PEAK_HOURS = 60
BUDGET = 750.0
TOL = 0.02
PILLARS = {
    "operational excellence": r"operational\s+excellence",
    "security": r"\bsecurity\b",
    "reliability": r"\breliability\b",
    "performance efficiency": r"performance\s+efficiency",
    "cost optimisation": r"cost\s+optimi[sz]ation",
    "sustainability": r"\bsustainability\b",
}
KEYS = ["proposed_bom", "compute", "database", "stated_original_monthly_cost_usd", "stated_proposed_monthly_cost_usd", "justification", "comparison"]


def item_cost(it):
    p = PRICES[it["item"]]
    if not isinstance(p, (int, float)):
        raise KeyError(it["item"])
    m = MULT if (it.get("multi_az") is True and it["item"].startswith("rds_")) else 1.0
    return p * float(it["quantity"]) * m


ORIG_COST = sum(item_cost(i) for i in ORIG)


def extract_json(text):
    if text is None:
        return None, "empty response"
    blocks = re.findall(r"```([A-Za-z0-9_-]*)[ \t]*\r?\n(.*?)```", text, re.S)
    cands = [b for l, b in blocks if l.lower() == "json"] or [b for l, b in blocks]
    if not cands:
        i, j = text.find("{"), text.rfind("}")
        cands = [text[i:j + 1]] if i >= 0 and j > i else []
    for c in cands:
        try:
            return json.loads(c, strict=False), ""
        except Exception as e:
            err = str(e)
    return None, "no parseable JSON object (%s)" % (err if cands else "no block")


def grade_des(text):
    ids = ["D%02d" % i for i in range(1, 11)]
    d, err = extract_json(text)
    out = {"parse_ok": d is not None, "checks": {}, "recomputed_proposed": None, "word_count": None}
    if d is None or not isinstance(d, dict):
        out["checks"] = {k: [False, "design not parseable: %s" % err] for k in ids}
        return out
    c = {}
    # D01 schema
    miss = [k for k in KEYS if k not in d]
    bad_items = []
    bom = d.get("proposed_bom") if isinstance(d.get("proposed_bom"), list) else []
    for it in bom:
        if not isinstance(it, dict) or it.get("item") not in PRICES or not isinstance(PRICES.get(it.get("item")), (int, float)):
            bad_items.append(it.get("item") if isinstance(it, dict) else str(it)[:30])
        else:
            try:
                float(it.get("quantity"))
            except Exception:
                bad_items.append("%s(quantity)" % it.get("item"))
    comp = d.get("compute") if isinstance(d.get("compute"), dict) else {}
    db = d.get("database") if isinstance(d.get("database"), dict) else {}
    it_ok = comp.get("instance_type") in CAP
    c["D01"] = (not miss and not bad_items and bool(bom) and it_ok,
                "missing keys %s; unknown price-sheet items %s; instance type valid %s" % (miss, bad_items[:4], it_ok))
    valid_bom = [it for it in bom if isinstance(it, dict) and it.get("item") in PRICES and isinstance(PRICES.get(it.get("item")), (int, float))]
    try:
        rec = sum(item_cost(it) for it in valid_bom)
    except Exception:
        rec = None
    out["recomputed_proposed"] = rec

    def num(x):
        try:
            return float(x)
        except Exception:
            return None
    sp, so = num(d.get("stated_proposed_monthly_cost_usd")), num(d.get("stated_original_monthly_cost_usd"))
    # D02 arithmetic of proposed
    c["D02"] = (rec is not None and sp is not None and not bad_items and abs(sp - rec) <= TOL * max(rec, 1),
                "stated proposed %s vs recomputed %s" % (sp, None if rec is None else round(rec, 2)))
    # D03 original
    c["D03"] = (so is not None and abs(so - ORIG_COST) <= TOL * ORIG_COST, "stated original %s vs correct %.2f" % (so, ORIG_COST))
    # D04 budget
    c["D04"] = (rec is not None and not bad_items and rec <= BUDGET, "recomputed proposed cost %s vs budget %.0f" % (None if rec is None else round(rec, 2), BUDGET))
    # D05 capacity
    itype = comp.get("instance_type")
    amax, amin, azs = num(comp.get("asg_max")), num(comp.get("asg_min")), num(comp.get("availability_zones"))
    cap = CAP.get(itype)
    need = math.ceil(ORIGIN_PEAK / cap) if cap else None
    c["D05"] = (cap is not None and amax is not None and amax * cap >= ORIGIN_PEAK,
                "asg_max %s x %s rps = %s vs origin peak %d" % (amax, cap, None if (cap is None or amax is None) else amax * cap, ORIGIN_PEAK))
    # D06 availability
    c["D06"] = (amin is not None and amin >= 2 and azs is not None and azs >= 2 and db.get("multi_az") is True,
                "asg_min %s, AZs %s, database multi_az %s" % (amin, azs, db.get("multi_az")))
    # D07 RPO/RTO
    br = num(db.get("backup_retention_days"))
    c["D07"] = (db.get("point_in_time_recovery") is True and br is not None and br >= 1,
                "point-in-time recovery %s, retention %s days" % (db.get("point_in_time_recovery"), br))
    # D08 BoM consistency with declared architecture
    hrs = sum(float(it["quantity"]) for it in valid_bom if it["item"] == "ec2_%s_hour" % itype)
    need_hrs = None
    if cap and amin is not None:
        need_hrs = amin * 730 + max(0, need - amin) * PEAK_HOURS
    rds_items = [it for it in valid_bom if it["item"].startswith("rds_mysql_")]
    rds_ok = bool(rds_items) and (not db.get("multi_az") or any(it.get("multi_az") is True for it in rds_items))
    c["D08"] = (need_hrs is not None and hrs >= need_hrs - 1e-6 and rds_ok,
                "costed %s instance-hours %.0f vs required %s; RDS costed consistently %s" % (itype, hrs, need_hrs, rds_ok))
    # D09 CDN demand costed
    gb = sum(float(it["quantity"]) for it in valid_bom if it["item"] == "cloudfront_gb_out")
    rq = sum(float(it["quantity"]) for it in valid_bom if it["item"] == "cloudfront_requests_per_10000")
    c["D09"] = (gb >= 2000 and rq >= 4000, "CloudFront GB %.0f (need 2000), request units %.0f (need 4000)" % (gb, rq))
    # D10 pillars
    j = str(d.get("justification") or "") + " " + str(d.get("comparison") or "")
    low = j.lower()
    have = {p: re.search(rx, low) is not None for p, rx in PILLARS.items()}
    c["D10"] = (all(have.values()), "pillars named: %s" % [p for p, v in have.items() if not v] and ("missing %s" % [p for p, v in have.items() if not v]) or "all six pillars named")
    out["word_count"] = len(str(d.get("justification") or "").split())
    out["checks"] = {k: [bool(v[0]), str(v[1])[:300]] for k, v in c.items()}
    out["design"] = {"compute": comp, "database": db}
    return out
