"""Build patched COPIES of the audit graders (the archived graders are never modified).

Usage: python make_patched_copy.py     -> patched_copy/tier1/, patched_copy/tier2/ (full copies of the audit dir)
                                           patched_copy/PATCH_tier1.diff, PATCH_tier2.diff
Tier 1 fixes defects demonstrated by the adversarial set or the natural-output audit (P1-P9, P11, P12, P14-P16, P18,
PA1-PA4, PA6).
Tier 2 adds four stricter readings that are debatable under the brief and that the gold APP itself fails
(P17 T2 fixed physical names against the unnumbered 'more than once' condition; P10 every CloudFront cache behaviour, not only the default, must use HTTPS; P13 admin-CIDR default must not be
0.0.0.0/0; PA5 '%'/'_' in a search term matched literally).
Each edit is an exact substitution asserted to match once.
"""
import difflib, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import AUDIT  # noqa: E402
from mutate import edit  # noqa: E402

IAC1 = [
    ("P1 parameter-referenced booleans resolved to the parameter Default",
     'def truthy(v):\n    return v is True or (isinstance(v, str) and v.strip().lower() == "true")\n',
     '_CUR = [None]\n\n\ndef truthy(v):\n    # PATCH P1: a Ref to a parameter is resolved to its Default (was: any Ref counted as false)\n'
     '    if isinstance(v, dict) and _CUR[0] is not None:\n        v = _CUR[0].literal_or_default(v)\n'
     '    return v is True or (isinstance(v, str) and v.strip().lower() == "true")\n'),
    ("P3 resources whose Condition is false under parameter defaults are dropped",
     '        self.O = tpl.get("Outputs", {}) or {}\n',
     '        self.O = tpl.get("Outputs", {}) or {}\n        _CUR[0] = self\n'
     '        # PATCH P3: drop resources whose Condition evaluates to false with parameter defaults\n'
     '        conds = tpl.get("Conditions", {}) or {}\n\n'
     '        def ev(x, depth=0):\n            if depth > 20 or not (isinstance(x, dict) and len(x) == 1):\n                return None\n'
     '            k, a = next(iter(x.items()))\n            if k == "Condition":\n                return ev(conds.get(a), depth + 1)\n'
     '            if k == "Fn::Equals" and isinstance(a, list) and len(a) == 2:\n'
     '                vals = [self.literal_or_default(i) if isinstance(i, dict) else i for i in a]\n'
     '                return None if None in vals else str(vals[0]) == str(vals[1])\n'
     '            if k == "Fn::Not" and isinstance(a, list) and a:\n                v = ev(a[0], depth + 1)\n                return None if v is None else (not v)\n'
     '            if k in ("Fn::And", "Fn::Or") and isinstance(a, list):\n                vs = [ev(i, depth + 1) for i in a]\n'
     '                return None if None in vs else (all(vs) if k == "Fn::And" else any(vs))\n            return None\n'
     '        self.cond_false = [lid for lid, r in list(self.R.items()) if isinstance(r, dict) and isinstance(r.get("Condition"), str)\n'
     '                           and ev(conds.get(r["Condition"])) is False]\n'
     '        for lid in self.cond_false:\n            del self.R[lid]\n'),
    ("P2 a NoEcho password parameter must not carry a literal Default",
     '    if r and r in T.P and truthy((T.P[r] or {}).get("NoEcho")):\n        return True, "NoEcho parameter"\n',
     '    if r and r in T.P and truthy((T.P[r] or {}).get("NoEcho")):\n'
     '        if (T.P[r] or {}).get("Default") is not None:  # PATCH P2\n'
     '            return False, "NoEcho parameter has a literal Default (plain-text password in the template)"\n'
     '        return True, "NoEcho parameter"\n'),
    ("P5 'from anywhere' for required-open web rules means IPv4 0.0.0.0/0 (T2.R7)",
     '        h80 = any(T.covers(r, 80) and T.from_anywhere(r) for r in rules)\n        h443 = any(T.covers(r, 443) and T.from_anywhere(r) for r in rules)\n',
     '        h80 = any(T.covers(r, 80) and r["cidr"] == ("lit", "0.0.0.0/0") for r in rules)  # PATCH P5\n'
     '        h443 = any(T.covers(r, 443) and r["cidr"] == ("lit", "0.0.0.0/0") for r in rules)\n'),
    ("P5 'from anywhere' for the ALB rule means IPv4 0.0.0.0/0 (T3.R5)",
     '    ok5 = any(any(T.covers(r, 80) and T.from_anywhere(r) for r in T.sg_rules(s)) for s in alb_sgs)\n',
     '    ok5 = any(any(T.covers(r, 80) and r["cidr"] == ("lit", "0.0.0.0/0") for r in T.sg_rules(s)) for s in alb_sgs)  # PATCH P5\n'),
    ("P6 S3 object resources must be exactly the bucket's object ARN (no inserted wildcards)",
     '            for rr in ress:\n                bucket_ref = any(("${%s}" % b in rr or "${%s.Arn}" % b in rr) for b in buckets)\n'
     '                if not (bucket_ref and rr.endswith("/*")):\n                    bad.append("resource %s" % rr)\n'
     '            if all(rr.endswith("/*") and any(("${%s}" % b in rr or "${%s.Arn}" % b in rr) for b in buckets) for rr in ress) and ress:\n',
     '            okset = set()\n            for b in buckets:  # PATCH P6\n'
     '                okset |= {"${%s.Arn}/*" % b, "arn:aws:s3:::${%s}/*" % b, "arn:${AWS::Partition}:s3:::${%s}/*" % b}\n'
     '            for rr in ress:\n                if rr not in okset:\n                    bad.append("resource %s" % rr)\n'
     '            if ress and all(rr in okset for rr in ress):\n'),
    ("P7 bucket policies that grant the role extra S3 actions count against R11",
     '        ok11 = prof_ok and not bad and good_put and good_get\n',
     '        for bp, bpr in T.of("AWS::S3::BucketPolicy").items():  # PATCH P7\n'
     '            for st in as_list(((bpr.get("Properties") or {}).get("PolicyDocument") or {}).get("Statement")):\n'
     '                if not isinstance(st, dict) or flat(st.get("Effect")) != "Allow":\n                    continue\n'
     '                pr = st.get("Principal")\n                aws = as_list(pr.get("AWS")) if isinstance(pr, dict) else [pr]\n'
     '                if not any(x == "*" or ref_of(x) == role or ("${%s" % role) in flat(x) for x in aws):\n'
     '                    continue\n                acts = [flat(a).lower() for a in as_list(st.get("Action"))]\n'
     '                if st.get("NotAction") is not None or any(a not in allowed for a in acts):\n'
     '                    bad.append("bucket policy %s grants %s" % (bp, acts))\n'
     '        ok11 = prof_ok and not bad and good_put and good_get\n'),
    ("P8 step/simple-scaling alarms must watch the ASG's EC2 CPU (namespace AWS/EC2, AutoScalingGroupName dimension)",
     '                      and lid in [ref_of(x) for x in as_list((ar.get("Properties") or {}).get("AlarmActions"))]]\n',
     '                      and lid in [ref_of(x) for x in as_list((ar.get("Properties") or {}).get("AlarmActions"))]\n'
     '                      and flat((ar.get("Properties") or {}).get("Namespace") or "AWS/EC2") == "AWS/EC2"  # PATCH P8\n'
     '                      and any(flat(dm.get("Name")) == "AutoScalingGroupName" and ref_of(dm.get("Value")) == asg\n'
     '                              for dm in as_list((ar.get("Properties") or {}).get("Dimensions")) if isinstance(dm, dict))]\n'),
    ("P9 MixedInstancesPolicy overrides must also be t3.micro",
     '             "t3.micro": str(T.literal_or_default(d.get("InstanceType"))) == "t3.micro",\n             "web_sg": bool(web_sgs)',
     '             "t3.micro": str(T.literal_or_default(d.get("InstanceType"))) == "t3.micro" and all(  # PATCH P9\n'
     '                 flat(o.get("InstanceType")) == "t3.micro" for o in as_list(((T.props(asg).get("MixedInstancesPolicy") or {})\n'
     '                 .get("LaunchTemplate") or {}).get("Overrides")) if isinstance(o, dict) and o.get("InstanceType") is not None),\n'
     '             "web_sg": bool(web_sgs)'),
    ("P11 R15 also flags AMI IDs in parameter defaults",
     '    for pn, pv in T.P.items():\n        dv = flat((pv or {}).get("Default")) if isinstance(pv, dict) else ""\n',
     '    for pn, pv in T.P.items():\n        dv = flat((pv or {}).get("Default")) if isinstance(pv, dict) else ""\n'
     '        if re.match(r"^ami-[0-9a-f]{8,17}$", (dv or "").strip()):  # PATCH P11\n'
     '            issues.append("parameter %s default AMI %s" % (pn, dv))\n'),
    ("P11 R15 also flags literal Availability Zone IDs",
     '                if AZ_RE.fullmatch(x.strip()):\n                    issues.append("%s hard-coded AZ %s" % (lid, x))\n',
     '                if AZ_RE.fullmatch(x.strip()):\n                    issues.append("%s hard-coded AZ %s" % (lid, x))\n'
     '                if re.fullmatch(r"[a-z]{2,4}\\d+-az\\d+", x.strip()):  # PATCH P11\n'
     '                    issues.append("%s hard-coded AZ ID %s" % (lid, x))\n'),
    ("P12 T1 user data: continuation lines joined; #cloud-config packages/write_files/runcmd understood",
     'def t1_checks(T):\n',
     'def _normalise_userdata(ud):  # PATCH P12\n    ud = re.sub(r"\\\\\\r?\\n[ \\t]*", " ", ud)\n'
     '    if ud.lstrip().lower().startswith("#cloud-config"):\n        try:\n            import yaml\n            d = yaml.safe_load(ud) or {}\n'
     '        except Exception:\n            return ud\n        if not isinstance(d, dict):\n            return ud\n        lines = []\n'
     '        pk = [str(x) for x in as_list(d.get("packages")) if isinstance(x, str)]\n        if pk:\n            lines.append("dnf install -y " + " ".join(pk))\n'
     '        for wf in as_list(d.get("write_files")):\n            if isinstance(wf, dict):\n                lines.append("write " + str(wf.get("path")))\n'
     '        for rc in as_list(d.get("runcmd")):\n            lines.append(" ".join(map(str, rc)) if isinstance(rc, list) else str(rc))\n'
     '        return ud + "\\n" + "\\n".join(lines)\n    return ud\n\n\ndef t1_checks(T):\n'),
    ("P12 (use)", '    ud = _userdata(T, p).lower()\n', '    ud = _normalise_userdata(_userdata(T, p)).lower()  # PATCH P12\n'),
    ("P14 T3.R1/R3 judge private subnets by their own routing, not by the ASG placement",
     '    priv = asg_sn if asg_sn else [s for s in subnets if s not in pub]\n    # R1\n',
     '    priv = asg_sn if asg_sn else [s for s in subnets if s not in pub]\n'
     '    # PATCH P14: structural private subnets (not public by routing or public-IP mapping), independent of the ASG\n'
     '    priv_struct = [s for s in subnets if s not in pub and not T.route_public(s) and not truthy(T.props(s).get("MapPublicIpOnLaunch"))]\n'
     '    if len(priv_struct) < 2:\n        priv_struct = priv\n    # R1\n'),
    ("P14 (R1)", '    ok_q, m_q = T.distinct_getazs(priv)\n    vpc_ok = any(',
     '    ok_q, m_q = T.distinct_getazs(priv_struct)\n    vpc_ok = any('),
    ("P14 (R1 overlap)", 'not (set(pub) & set(priv)), "VPC 10.0.0.0/16 %s | public %s: %s | private %s: %s" % (vpc_ok, pub, m_p, priv, m_q))',
     'not (set(pub) & set(priv_struct)), "VPC 10.0.0.0/16 %s | public %s: %s | private %s: %s" % (vpc_ok, pub, m_p, priv_struct, m_q))'),
    ("P14 (R3)", '    ok3 = bool(nats) and all(nat_ok) and len(priv) >= 2 and all(T.route_nat(s) for s in priv)\n',
     '    ok3 = bool(nats) and all(nat_ok) and len(priv_struct) >= 2 and all(T.route_nat(s) for s in priv_struct)\n'),
    ("P14 (R3 message)", '{s: T.route_nat(s) for s in priv}))', '{s: T.route_nat(s) for s in priv_struct}))'),
    ("P14 (R7) an explicit AssociatePublicIpAddress false overrides the subnet's public-IP mapping",
     '             "no_public_ip": not pub_ip and not any(truthy(T.props(s).get("MapPublicIpOnLaunch")) for s in priv),\n',
     '             "no_public_ip": not pub_ip and (any((ni or {}).get("AssociatePublicIpAddress") is not None and not truthy((ni or {}).get("AssociatePublicIpAddress"))\n'
     '                                                  for ni in as_list(d.get("NetworkInterfaces")) if isinstance(ni, dict))\n'
     '                                              or not any(truthy(T.props(s).get("MapPublicIpOnLaunch")) for s in priv)),  # PATCH P14\n'),
    ("P4 T2: every DB instance must be private, encrypted and without a plain-text password",
     '        res["T2.R9"] = _db_password_ok(T, p)\n',
     '        res["T2.R9"] = _db_password_ok(T, p)\n'
     '        for odb in dbs[1:]:  # PATCH P4\n            op = T.props(odb)\n'
     '            if truthy(op.get("PubliclyAccessible")) or op.get("DBSubnetGroupName") is None or not truthy(op.get("StorageEncrypted")):\n'
     '                res["T2.R8"] = (False, "additional DB instance %s is public or unencrypted" % odb)\n'
     '            if not _db_password_ok(T, op)[0]:\n                res["T2.R9"] = (False, "additional DB instance %s: %s" % (odb, _db_password_ok(T, op)[1]))\n'),
    ("P4 T3: every DB instance must be private, encrypted and without a plain-text password",
     '        res["T3.R12"] = (all(c.values()), "database %s (%s)" % (c, pw_m))\n',
     '        res["T3.R12"] = (all(c.values()), "database %s (%s)" % (c, pw_m))\n'
     '        for odb in dbs[1:]:  # PATCH P4\n            op = T.props(odb)\n'
     '            if (truthy(op.get("PubliclyAccessible")) or op.get("DBSubnetGroupName") is None or not truthy(op.get("StorageEncrypted"))\n'
     '                    or not _db_password_ok(T, op)[0]):\n'
     '                res["T3.R12"] = (False, "additional DB instance %s is public, unencrypted or has a plain-text password" % odb)\n'),
    ("P4 T3.R10: every bucket (not any bucket) must keep all four Block Public Access settings",
     '    res["T3.R10"] = (ok10, m10)\n',
     '    bad10 = [b for b in buckets if T.props(b).get("PublicAccessBlockConfiguration") is not None and not all(\n'
     '        truthy((T.props(b).get("PublicAccessBlockConfiguration") or {}).get(k)) for k in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"))]\n'
     '    if bad10:  # PATCH P4\n        ok10, m10 = False, "bucket(s) %s do not enable all four Block Public Access settings" % bad10\n'
     '    res["T3.R10"] = (ok10, m10)\n'),
    ("P4 T3: every Auto Scaling group (and its launch template and SGs) must meet R6-R8",
     '    res["T3.R8"] = (ok8, m8)\n',
     '    res["T3.R8"] = (ok8, m8)\n'
     '    for oasg in asgs[1:]:  # PATCH P4\n        op = T.props(oasg)\n'
     '        osn = [ref_of(x) for x in as_list(op.get("VPCZoneIdentifier")) if ref_of(x)]\n'
     '        if not (len(osn) >= 2 and all(T.route_private(s) for s in osn)) or flat(op.get("HealthCheckType")).upper() != "ELB":\n'
     '            res["T3.R8"] = (False, "additional Auto Scaling group %s is not a private, ELB-checked web tier" % oasg)\n'
     '        oltp = op.get("LaunchTemplate") or {}\n        olt = ref_of(oltp.get("LaunchTemplateId")) or ref_of(oltp.get("LaunchTemplateName"))\n'
     '        if olt and olt != lt:\n            od = T.props(olt).get("LaunchTemplateData") or {}\n'
     '            opub = any(truthy((ni or {}).get("AssociatePublicIpAddress")) for ni in as_list(od.get("NetworkInterfaces")) if isinstance(ni, dict))\n'
     '            if opub or str(T.literal_or_default(od.get("InstanceType"))) != "t3.micro":\n'
     '                res["T3.R7"] = (False, "launch template %s of additional ASG %s assigns public IPs or is not t3.micro" % (olt, oasg))\n'
     '            for s in _lt_sgs(T, olt):\n                if any(T.from_anywhere(r) for r in T.sg_rules(s)):\n'
     '                    res["T3.R6"] = (False, "security group %s of additional ASG %s is open to the world" % (s, oasg))\n'),
    ("P16 T2.R5: a launch template may not combine NetworkInterfaces with top-level security groups (EC2 rejects the launch)",
     '             "sg": bool(_lt_sgs(T, lt)),\n',
     '             "sg": bool(_lt_sgs(T, lt)) and not (d.get("NetworkInterfaces") and (d.get("SecurityGroupIds") or d.get("SecurityGroups"))),  # PATCH P16\n'),
    ("P16 T3.R7: a launch template may not combine NetworkInterfaces with top-level security groups (EC2 rejects the launch)",
     '"web_sg": bool(web_sgs), "instance_profile"',
     '"web_sg": bool(web_sgs) and not (d.get("NetworkInterfaces") and (d.get("SecurityGroupIds") or d.get("SecurityGroups"))),  # PATCH P16\n             "instance_profile"'),
    ("P18 T1.R8: Fn::ImportValue cannot resolve in the fresh account the brief deploys into",
     '    res["T1.R8"] = (not net, "creates network resources %s" % net if net else "uses default VPC")\n',
     '    res["T1.R8"] = (not net, "creates network resources %s" % net if net else "uses default VPC")\n'
     '    if "Fn::ImportValue" in json.dumps(T.t, default=str):  # PATCH P18\n'
     '        res["T1.R8"] = (False, "imports a cross-stack export (Fn::ImportValue); a fresh account has no exports, so the stack cannot deploy")\n'),
]
IAC2 = [
    ("P17 (tier 2) T2 redeployability (brief: 'possibly more than once in the same account and Region'): fixed physical names",
     '    res["T2.R11"] = (url and dbo, "website URL output %s; DB endpoint output %s" % (url, dbo))\n    return res\n',
     '    res["T2.R11"] = (url and dbo, "website URL output %s; DB endpoint output %s" % (url, dbo))\n'
     '    for lid, r in T.R.items():  # PATCH P17 (tier 2)\n        prop = FIXED_NAME_PROPS.get(r.get("Type")) if isinstance(r, dict) else None\n'
     '        v = (r.get("Properties") or {}).get(prop) if prop else None\n'
     '        if v is None or "AWS::StackName" in flat(v) or "AWS::StackId" in flat(v) or ref_of(v) in T.P:\n            continue\n'
     '        k = {"AWS::EC2::LaunchTemplate": "T2.R5", "AWS::RDS::DBInstance": "T2.R8", "AWS::RDS::DBSubnetGroup": "T2.R8"}.get(r.get("Type"))\n'
     '        if k:\n            res[k] = (False, "fixed physical name %s.%s=%s collides on a second deployment" % (lid, prop, flat(v)[:40]))\n'
     '    return res\n'),
    ("P10 (tier 2) every CloudFront cache behaviour must redirect or require HTTPS",
     '        ok14, m14 = o_ok and vpp == "redirect-to-https",',
     '        vpp_all = all(flat(cb.get("ViewerProtocolPolicy")) in ("redirect-to-https", "https-only")  # PATCH P10\n'
     '                      for cb in as_list(cfg.get("CacheBehaviors")) if isinstance(cb, dict))\n'
     '        ok14, m14 = o_ok and vpp == "redirect-to-https" and vpp_all,'),
    ("P13 (tier 2) the admin CIDR parameter must not default to 0.0.0.0/0",
     '    ssh_ok = bool(ssh) and all(x["cidr"] and x["cidr"][0] == "param" and x["from"] == 22 and x["to"] == 22 for x in ssh)\n',
     '    ssh_ok = bool(ssh) and all(x["cidr"] and x["cidr"][0] == "param" and x["from"] == 22 and x["to"] == 22 for x in ssh)\n'
     '    ssh_ok = ssh_ok and not any(flat(T.param_default(x["cidr"][1])) in ANYWHERE for x in ssh)  # PATCH P13 (tier 2)\n'),
]
DES1 = [
    ("P15 quantities must be positive JSON numbers",
     '            try:\n                float(it.get("quantity"))\n            except Exception:\n                bad_items.append("%s(quantity)" % it.get("item"))\n',
     '            q = it.get("quantity")\n            if isinstance(q, bool) or not isinstance(q, (int, float)) or not q > 0:  # PATCH P15\n'
     '                bad_items.append("%s(quantity %r)" % (it.get("item"), q))\n'),
    ("P15 D08: the declared database (and read replicas) must be costed for the whole month",
     '    rds_ok = bool(rds_items) and (not db.get("multi_az") or any(it.get("multi_az") is True for it in rds_items))\n',
     '    rds_ok = bool(rds_items) and (not db.get("multi_az") or any(it.get("multi_az") is True for it in rds_items))\n'
     '    _rr = num(db.get("read_replicas")) or 0  # PATCH P15\n'
     '    _rds_hours = sum(float(it["quantity"]) for it in rds_items if it["item"].endswith("_hour") and isinstance(it.get("quantity"), (int, float)))\n'
     '    rds_ok = rds_ok and _rds_hours >= 730 * (1 + _rr) - 1e-6\n'),
    ("P15 D10: justification within the 800-word limit",
     '    out["word_count"] = len(str(d.get("justification") or "").split())\n',
     '    _wc = len(str(d.get("justification") or "").split())\n    if _wc > 800:  # PATCH P15\n'
     '        c["D10"] = (False, "justification has %d words (limit 800)" % _wc)\n'
     '    out["word_count"] = len(str(d.get("justification") or "").split())\n'),
]
APP1 = [
    ("PA0 module path recorded for the POSIX re-import in A09", 'TESTS = {}\n', 'TESTS = {}\nMODPATH = [None]  # PATCH\n'),
    ("PA0", '    path, out = sys.argv[1], sys.argv[2]\n', '    path, out = sys.argv[1], sys.argv[2]\n    MODPATH[0] = path\n'),
    ("PA1 A03: search results must be dict objects",
     '    assert r[0]["s3_key"] == "photos/a/1.jpg"\n',
     '    assert r[0]["s3_key"] == "photos/a/1.jpg"\n    assert all(type(x) is dict for x in r), "rows are not dict objects"  # PATCH PA1\n'),
    ("PA2 A06: probe terms containing both quote characters",
     '    for term in ["zzz\' OR \'1\'=\'1", "zzz\') OR 1=1 --", "\\" OR \\"\\"=\\""]:\n',
     '    for term in ["zzz\' OR \'1\'=\'1", "zzz\') OR 1=1 --", "\\" OR \\"\\"=\\"", "a\' or 1=1 --\\"", "\\"\' or 1=1 --"]:  # PATCH PA2\n'),
    ("PA3 A08: the key segment must be a version-4 UUID",
     '    assert re.fullmatch(r"photos/[0-9a-f]{32}/holiday\\.jpg", k or ""), "key %r" % k\n',
     '    assert re.fullmatch(r"photos/[0-9a-f]{32}/holiday\\.jpg", k or ""), "key %r" % k\n'
     '    import uuid as _uuid\n    assert _uuid.UUID(k.split("/")[1]).version == 4, "key segment is not a uuid4"  # PATCH PA3\n'),
    ("PA4 A09: sanitiser must strip Windows directories when os.path is POSIX (Linux target)",
     '        assert k.split("/", 2)[-1] == safe and k.count("/") == 2, "filename %r gave key %r (expected safe name %r)" % (fn, k, safe)\n',
     '        assert k.split("/", 2)[-1] == safe and k.count("/") == 2, "filename %r gave key %r (expected safe name %r)" % (fn, k, safe)\n'
     '    import os as _os, posixpath as _pp  # PATCH PA4\n    _saved = _os.path\n    _os.path = _pp\n    try:\n'
     '        _spec = importlib.util.spec_from_file_location("photoapp_posix", MODPATH[0])\n        _mm = importlib.util.module_from_spec(_spec)\n'
     '        _spec.loader.exec_module(_mm)\n        _k = _mm.upload_photo(StubS3(), "b", "C:\\\\Users\\\\me\\\\my photo (1).png", b"x", "image/png")\n'
     '    finally:\n        _os.path = _saved\n'
     '    assert _k.split("/", 2)[-1] == "my_photo__1_.png", "sanitiser depends on the host path flavour: %r" % _k\n'),
    ("PA6 A16: client construction via import_module or .client('s3'), and access-key-like literals",
     '    assert not bad, "credentials or client construction found: %s" % bad\n',
     '    for _p in [r"import_module\\(\\s*[\'\\"]boto3", r"\\.client\\(\\s*[\'\\"]s3[\'\\"]", r"\\b(AKIA|ASIA)[A-Z0-9]{8,}", r"[\'\\"](AKIA|ASIA)[\'\\"]",\n'
     '               r"(?<![A-Za-z0-9/+])[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])"]:  # PATCH PA6\n'
     '        if re.search(_p, src):\n            bad.append(_p)\n'
     '    assert not bad, "credentials or client construction found: %s" % bad\n'),
]
APP2 = [
    ("PA5 (tier 2) A03: '%' and '_' in the term are matched literally ('contains term')",
     '    assert all(type(x) is dict for x in r), "rows are not dict objects"  # PATCH PA1\n',
     '    assert all(type(x) is dict for x in r), "rows are not dict objects"  # PATCH PA1\n'
     '    c2 = conn(); m.init_db(c2)  # PATCH PA5 (tier 2)\n'
     '    for t in ["100%", "abc", "a_b", "ab"]:\n        m.save_photo_metadata(c2, t, None, "k")\n'
     '    assert [x["title"] for x in m.search_photos(c2, "%")] == ["100%"] and [x["title"] for x in m.search_photos(c2, "_")] == ["a_b"], \\\n'
     '        "wildcard characters in the term are not matched literally"\n'),
]


def apply(dst, fname, patches, log):
    p = os.path.join(dst, fname)
    old = open(p, encoding="utf-8").read()
    new = old
    for name, a, b in patches:
        new = edit(new, a, b)
        log.append("%s: %s" % (fname, name))
    open(p, "w", encoding="utf-8", newline="\n").write(new)
    return old, new


def main():
    base = os.path.join(HERE, "patched_copy")
    if os.path.isdir(base):
        shutil.rmtree(base)
    for tier, sets in (("tier1", {"checks_iac.py": IAC1, "checks_des.py": DES1, "app_runner.py": APP1}),
                       ("tier2", {"checks_iac.py": IAC1 + IAC2, "checks_des.py": DES1, "app_runner.py": APP1 + APP2})):
        dst = os.path.join(base, tier)
        shutil.copytree(AUDIT, dst, ignore=shutil.ignore_patterns("__pycache__"))
        log, diffs = [], []
        for fname, patches in sets.items():
            old, new = apply(dst, fname, patches, log)
            diffs += difflib.unified_diff(old.splitlines(True), new.splitlines(True), "audit/" + fname, "patched_copy/%s/%s" % (tier, fname))
        open(os.path.join(base, "PATCH_%s.diff" % tier), "w", encoding="utf-8", newline="\n").write("".join(diffs))
        print(tier, len(log), "edits")


if __name__ == "__main__":
    main()
