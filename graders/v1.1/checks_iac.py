"""Semantic checker for the CloudFormation tasks T1-T3 of the GenAI capability audit.

Each check returns (passed: bool, message: str). Checks operate on the template decoded by
cfn-lint's decoder (short-form intrinsics are expanded to long form).
"""
import re, json, os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKGS = os.path.join(os.path.dirname(_HERE), 'iacpkgs')
if os.path.isdir(_PKGS) and _PKGS not in sys.path:
    sys.path.append(_PKGS)
import cfnlint.decode
from cfnlint.api import lint, ManualArgs

ANYWHERE = {"0.0.0.0/0", "::/0"}

# ----------------------------------------------------------------------------- extraction / lint
def extract_block(text, langs=("yaml", "yml")):
    if text is None:
        return None
    pat = re.compile(r"```([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.S)
    blocks = pat.findall(text)
    for lang, body in blocks:
        if lang.lower() in langs:
            return body
    if blocks:
        return max(blocks, key=lambda b: len(b[1]))[1]
    t = text.strip()
    if t.startswith("AWSTemplateFormatVersion") or t.startswith("Resources:") or t.startswith("Description:"):
        return t
    return None


def run_lint(body, region="us-east-1"):
    try:
        ms = lint(body, config=ManualArgs(regions=[region]))
    except Exception as e:  # pragma: no cover
        return [{"rule": "LINT_CRASH", "level": "E", "line": 0, "message": str(e)[:300]}]
    out = []
    for m in ms:
        rid = m.rule.id
        out.append({"rule": rid, "level": rid[0], "line": getattr(m, "linenumber", 0), "message": str(m.message)[:300]})
    return out


def decode(body):
    try:
        tpl, matches = cfnlint.decode.decode_str(body)
    except Exception as e:
        return None, str(e)[:300]
    if tpl is None or not isinstance(tpl, dict):
        msg = "; ".join(str(m.message) for m in (matches or []))[:300]
        return None, msg or "template could not be parsed"
    return tpl, ""

# ----------------------------------------------------------------------------- helpers
def _s(v):
    return v if isinstance(v, str) else None


def ref_of(v):
    """Logical id referenced by Ref or GetAtt (any attribute) or None."""
    if isinstance(v, dict) and len(v) == 1:
        k, x = next(iter(v.items()))
        if k == "Ref" and isinstance(x, str):
            return x
        if k == "Fn::GetAtt":
            if isinstance(x, list) and x:
                return x[0]
            if isinstance(x, str):
                return x.split(".")[0]
    return None


def flat(v):
    """Best-effort flattening of an intrinsic expression to a string, refs as ${X} / ${X.Attr}."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return ",".join(flat(x) for x in v)
    if isinstance(v, dict) and len(v) == 1:
        k, x = next(iter(v.items()))
        if k == "Ref":
            return "${%s}" % x
        if k == "Fn::GetAtt":
            if isinstance(x, list):
                return "${%s}" % ".".join(str(i) for i in x)
            return "${%s}" % x
        if k == "Fn::Sub":
            if isinstance(x, list):
                s = flat(x[0])
                if len(x) > 1 and isinstance(x[1], dict):
                    for var, val in x[1].items():
                        s = s.replace("${%s}" % var, flat(val))
                return s
            return flat(x)
        if k == "Fn::Join" and isinstance(x, list) and len(x) == 2:
            sep = flat(x[0])
            parts = x[1] if isinstance(x[1], list) else [x[1]]
            return sep.join(flat(p) for p in parts)
        if k == "Fn::Base64":
            return flat(x)
        if k == "Fn::If" and isinstance(x, list) and len(x) == 3:
            return flat(x[1])
        if k == "Fn::Select" and isinstance(x, list) and len(x) == 2:
            return "${Select:%s}" % flat(x[0])
        return "${%s}" % k
    if isinstance(v, dict):
        return json.dumps({k: flat(x) for k, x in v.items()})
    return str(v)


def to_int(v, default=None):
    try:
        return int(str(v).strip())
    except Exception:
        return default


_CUR = [None]


def truthy(v):
    # PATCH P1: a Ref to a parameter is resolved to its Default (was: any Ref counted as false)
    if isinstance(v, dict) and _CUR[0] is not None:
        v = _CUR[0].literal_or_default(v)
    return v is True or (isinstance(v, str) and v.strip().lower() == "true")


def lv(v):
    # PATCH P19 (v1.1): literal value, or the Default of a referenced parameter, as a string
    if isinstance(v, dict) and _CUR[0] is not None:
        x = _CUR[0].literal_or_default(v)
        if x is not None:
            return flat(x)
    return flat(v)


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


class Tpl:
    def __init__(self, tpl):
        self.t = tpl
        self.R = tpl.get("Resources", {}) or {}
        self.P = tpl.get("Parameters", {}) or {}
        self.O = tpl.get("Outputs", {}) or {}
        _CUR[0] = self
        # PATCH P3: drop resources whose Condition evaluates to false with parameter defaults
        conds = tpl.get("Conditions", {}) or {}

        def ev(x, depth=0):
            if depth > 20 or not (isinstance(x, dict) and len(x) == 1):
                return None
            k, a = next(iter(x.items()))
            if k == "Condition":
                return ev(conds.get(a), depth + 1)
            if k == "Fn::Equals" and isinstance(a, list) and len(a) == 2:
                vals = [self.literal_or_default(i) if isinstance(i, dict) else i for i in a]
                return None if None in vals else str(vals[0]) == str(vals[1])
            if k == "Fn::Not" and isinstance(a, list) and a:
                v = ev(a[0], depth + 1)
                return None if v is None else (not v)
            if k in ("Fn::And", "Fn::Or") and isinstance(a, list):
                vs = [ev(i, depth + 1) for i in a]
                return None if None in vs else (all(vs) if k == "Fn::And" else any(vs))
            return None
        self.cond_false = [lid for lid, r in list(self.R.items()) if isinstance(r, dict) and isinstance(r.get("Condition"), str)
                           and ev(conds.get(r["Condition"])) is False]
        for lid in self.cond_false:
            del self.R[lid]

    def of(self, typ):
        return {k: v for k, v in self.R.items() if isinstance(v, dict) and v.get("Type") == typ}

    def props(self, lid):
        r = self.R.get(lid) or {}
        return r.get("Properties", {}) or {}

    def typ(self, lid):
        r = self.R.get(lid) or {}
        return r.get("Type")

    def param_type(self, name):
        p = self.P.get(name)
        return p.get("Type") if isinstance(p, dict) else None

    def param_default(self, name):
        p = self.P.get(name)
        return p.get("Default") if isinstance(p, dict) else None

    # --- value resolution
    def literal_or_default(self, v):
        """Literal value, or the Default of a referenced parameter."""
        if isinstance(v, (str, int, float, bool)):
            return v
        r = ref_of(v)
        if r and r in self.P:
            return self.param_default(r)
        return None

    # --- networking
    def az_desc(self, sid):
        az = self.props(sid).get("AvailabilityZone")
        if az is None:
            if self.props(sid).get("AvailabilityZoneId") is not None:
                return ("azid", flat(self.props(sid).get("AvailabilityZoneId")))
            return ("none", None)
        if isinstance(az, str):
            return ("literal", az)
        if isinstance(az, dict) and "Fn::Select" in az:
            x = az["Fn::Select"]
            if isinstance(x, list) and len(x) == 2:
                idx = to_int(x[0])
                src = x[1]
                if isinstance(src, dict) and "Fn::GetAZs" in src and idx is not None:
                    return ("getazs", idx)
                r = ref_of(src)
                if r and r in self.P and idx is not None:
                    return ("paramlist", idx)
        r = ref_of(az)
        if r and r in self.P:
            return ("param", r)
        return ("other", flat(az))

    def distinct_getazs(self, sids):
        descs = [self.az_desc(s) for s in sids]
        if len(sids) < 2:
            return False, "fewer than two subnets"
        if not all(d[0] == "getazs" for d in descs):
            return False, "Availability Zones not selected with Fn::GetAZs for %s" % ", ".join(
                "%s(%s)" % (s, d[0]) for s, d in zip(sids, descs))
        idx = [d[1] for d in descs]
        if len(set(idx)) < 2:
            return False, "subnets %s are in the same Availability Zone index %s" % (sids, idx)
        return True, "subnets in distinct Availability Zones %s" % idx

    def subnet_rt(self):
        m = {}
        for lid, r in self.of("AWS::EC2::SubnetRouteTableAssociation").items():
            p = r.get("Properties", {}) or {}
            s, rt = ref_of(p.get("SubnetId")), ref_of(p.get("RouteTableId"))
            if s and rt:
                m.setdefault(s, set()).add(rt)
        return m

    def routes(self, rt):
        out = []
        for lid, r in self.of("AWS::EC2::Route").items():
            p = r.get("Properties", {}) or {}
            if ref_of(p.get("RouteTableId")) != rt:
                continue
            dest = flat(p.get("DestinationCidrBlock")) or flat(p.get("DestinationIpv6CidrBlock"))
            tgt = None
            if p.get("GatewayId") is not None:
                g = ref_of(p.get("GatewayId"))
                tgt = ("igw", g) if g in self.of("AWS::EC2::InternetGateway") else ("gw", g)
            elif p.get("NatGatewayId") is not None:
                tgt = ("nat", ref_of(p.get("NatGatewayId")))
            elif p.get("InstanceId") is not None:
                tgt = ("instance", ref_of(p.get("InstanceId")))
            else:
                tgt = ("other", None)
            out.append((dest, tgt))
        return out

    def rt_has(self, rt, kind):
        return any(d in ("0.0.0.0/0",) and t[0] == kind for d, t in self.routes(rt))

    def rt_any_igw(self, rt):
        return any(t[0] == "igw" for d, t in self.routes(rt))

    def route_public(self, sid):
        rts = self.subnet_rt().get(sid, set())
        return any(self.rt_has(rt, "igw") for rt in rts)

    def route_nat(self, sid):
        rts = self.subnet_rt().get(sid, set())
        return bool(rts) and all(self.rt_has(rt, "nat") and not self.rt_any_igw(rt) for rt in rts)

    def route_private(self, sid):
        rts = self.subnet_rt().get(sid, set())
        return bool(rts) and not any(self.rt_any_igw(rt) for rt in rts)

    def igw_attached(self):
        for lid, r in self.of("AWS::EC2::VPCGatewayAttachment").items():
            p = r.get("Properties", {}) or {}
            if ref_of(p.get("InternetGatewayId")) in self.of("AWS::EC2::InternetGateway"):
                return True
        return False

    # --- security groups
    def sg_rules(self, sg):
        rules = []
        for rule in as_list(self.props(sg).get("SecurityGroupIngress")):
            if isinstance(rule, dict):
                rules.append(self._norm_rule(rule))
        for lid, r in self.of("AWS::EC2::SecurityGroupIngress").items():
            p = r.get("Properties", {}) or {}
            if ref_of(p.get("GroupId")) == sg or ref_of(p.get("GroupName")) == sg:
                rules.append(self._norm_rule(p))
        return rules

    def _norm_rule(self, r):
        proto = str(flat(r.get("IpProtocol"))).lower()
        fp, tp = to_int(r.get("FromPort")), to_int(r.get("ToPort"))
        if proto in ("-1", "all"):
            fp, tp = 0, 65535
        cidr = None
        if r.get("CidrIp") is not None:
            v = r.get("CidrIp")
            cidr = ("param", ref_of(v)) if (ref_of(v) in self.P) else ("lit", flat(v))
        elif r.get("CidrIpv6") is not None:
            v = r.get("CidrIpv6")
            cidr = ("param", ref_of(v)) if (ref_of(v) in self.P) else ("lit", flat(v))
        src = ref_of(r.get("SourceSecurityGroupId")) or ref_of(r.get("SourceSecurityGroupName"))
        return {"proto": proto, "from": fp, "to": tp, "cidr": cidr, "src": src}

    @staticmethod
    def covers(rule, port):
        if rule["proto"] not in ("tcp", "6", "-1", "all"):
            return False
        if rule["from"] is None or rule["to"] is None:
            return False
        return rule["from"] <= port <= rule["to"]

    @staticmethod
    def from_anywhere(rule):
        return rule["cidr"] is not None and rule["cidr"][0] == "lit" and rule["cidr"][1] in ANYWHERE

    # --- IAM
    def role_statements(self, role):
        stmts = []
        for pol in as_list(self.props(role).get("Policies")):
            if isinstance(pol, dict):
                stmts += as_list((pol.get("PolicyDocument") or {}).get("Statement"))
        for typ in ("AWS::IAM::Policy", "AWS::IAM::ManagedPolicy", "AWS::IAM::RolePolicy"):
            for lid, r in self.of(typ).items():
                p = r.get("Properties", {}) or {}
                roles = [ref_of(x) or flat(x) for x in as_list(p.get("Roles"))]
                if typ == "AWS::IAM::RolePolicy":
                    roles = [ref_of(p.get("RoleName")) or flat(p.get("RoleName"))]
                attached = role in roles
                if typ == "AWS::IAM::ManagedPolicy":
                    for arn in as_list(self.props(role).get("ManagedPolicyArns")):
                        if ref_of(arn) == lid:
                            attached = True
                if attached:
                    stmts += as_list((p.get("PolicyDocument") or {}).get("Statement"))
        return [s for s in stmts if isinstance(s, dict)]

    def role_managed_arns(self, role):
        out = []
        for arn in as_list(self.props(role).get("ManagedPolicyArns")):
            if ref_of(arn) in self.R:
                continue
            out.append(flat(arn))
        return out

    def trusts_ec2(self, role):
        doc = self.props(role).get("AssumeRolePolicyDocument") or {}
        for st in as_list(doc.get("Statement")):
            if not isinstance(st, dict):
                continue
            pr = st.get("Principal") or {}
            svc = pr.get("Service") if isinstance(pr, dict) else None
            if any("ec2." in flat(x) for x in as_list(svc)):
                return True
        return False

# ----------------------------------------------------------------------------- shared sub-checks
def _userdata(T, props):
    return flat(props.get("UserData"))


def _sg_ids(v):
    return [ref_of(x) for x in as_list(v) if ref_of(x)]


def _lt_sgs(T, lt):
    d = T.props(lt).get("LaunchTemplateData") or {}
    sgs = _sg_ids(d.get("SecurityGroupIds")) + _sg_ids(d.get("SecurityGroups"))
    for ni in as_list(d.get("NetworkInterfaces")):
        if isinstance(ni, dict):
            sgs += _sg_ids(ni.get("Groups"))
    return [s for s in sgs if T.typ(s) == "AWS::EC2::SecurityGroup"]


def _db_password_ok(T, p):
    if truthy(p.get("ManageMasterUserPassword")) and p.get("MasterUserPassword") is None:
        return True, "ManageMasterUserPassword"
    pw = p.get("MasterUserPassword")
    if pw is None:
        return False, "no master password mechanism (ManageMasterUserPassword not set)"
    if "{{resolve:secretsmanager:" in flat(pw):
        return True, "Secrets Manager dynamic reference"
    r = ref_of(pw)
    if r and r in T.P and truthy((T.P[r] or {}).get("NoEcho")):
        if (T.P[r] or {}).get("Default") is not None:  # PATCH P2
            return False, "NoEcho parameter has a literal Default (plain-text password in the template)"
        return True, "NoEcho parameter"
    if r and T.typ(r) == "AWS::SecretsManager::Secret":
        return False, "Ref to a secret returns its ARN, not the password"
    return False, "master password supplied as plain text or non-NoEcho parameter"


def _rds(T):
    dbs = T.of("AWS::RDS::DBInstance")
    return list(dbs)


def _db_subnets(T, db):
    g = ref_of(T.props(db).get("DBSubnetGroupName"))
    if not g or T.typ(g) != "AWS::RDS::DBSubnetGroup":
        return None
    return [ref_of(x) for x in as_list(T.props(g).get("SubnetIds")) if ref_of(x)]


def _db_sgs(T, db):
    return [s for s in _sg_ids(T.props(db).get("VPCSecurityGroups")) if T.typ(s) == "AWS::EC2::SecurityGroup"]


def _only_from_sg(T, sg, port, src_sgs):
    rules = T.sg_rules(sg)
    if not rules:
        return False, "%s has no inbound rules" % sg
    bad = [r for r in rules if not (r["src"] in src_sgs and T.covers(r, port) and r["from"] == port and r["to"] == port)]
    if bad:
        return False, "%s has inbound rules other than TCP %d from %s: %s" % (sg, port, "/".join(src_sgs), bad[:2])
    return True, "only TCP %d from %s" % (port, "/".join(src_sgs))

# ----------------------------------------------------------------------------- T1
def _t1_instance(T):
    inst = list(T.of("AWS::EC2::Instance"))
    return inst[0] if len(inst) == 1 else (inst[0] if inst else None)


def _t1_sgs(T, inst):
    p = T.props(inst)
    sgs = _sg_ids(p.get("SecurityGroupIds")) + _sg_ids(p.get("SecurityGroups"))
    for ni in as_list(p.get("NetworkInterfaces")):  # PATCH P20 (v1.1): interface-level security groups
        if isinstance(ni, dict):
            sgs += _sg_ids(ni.get("GroupSet"))
    return [s for s in sgs if T.typ(s) == "AWS::EC2::SecurityGroup"]


def _normalise_userdata(ud):  # PATCH P12
    ud = re.sub(r"\\\r?\n[ \t]*", " ", ud)
    if ud.lstrip().lower().startswith("#cloud-config"):
        try:
            import yaml
            d = yaml.safe_load(ud) or {}
        except Exception:
            return ud
        if not isinstance(d, dict):
            return ud
        lines = []
        pk = [str(x) for x in as_list(d.get("packages")) if isinstance(x, str)]
        if pk:
            lines.append("dnf install -y " + " ".join(pk))
        for wf in as_list(d.get("write_files")):
            if isinstance(wf, dict):
                lines.append("write " + str(wf.get("path")))
        for rc in as_list(d.get("runcmd")):
            lines.append(" ".join(map(str, rc)) if isinstance(rc, list) else str(rc))
        return ud + "\n" + "\n".join(lines)
    return ud


def t1_checks(T):
    res = {}
    inst = _t1_instance(T)
    if not inst:
        return {k: (False, "no EC2 instance") for k in ["T1.R1", "T1.R2", "T1.R3", "T1.R4", "T1.R5", "T1.R6", "T1.R7", "T1.R8", "T1.R9"]}
    p = T.props(inst)
    # R1
    kn = ref_of(p.get("KeyName"))
    cidr_params = [k for k, v in T.P.items() if isinstance(v, dict) and v.get("Type") == "String"]
    ok = kn in T.P and T.param_type(kn) == "AWS::EC2::KeyPair::KeyName"
    sgs = _t1_sgs(T, inst)
    rules = [r for s in sgs for r in T.sg_rules(s)]
    ssh_param = [r for r in rules if T.covers(r, 22) and r["cidr"] and r["cidr"][0] == "param"]
    res["T1.R1"] = (ok and bool(ssh_param), "key pair parameter %s; admin CIDR parameter used in SSH rule: %s" % ("ok" if ok else "missing/wrong type", bool(ssh_param)))
    # R2
    img = p.get("ImageId")
    r = ref_of(img)
    target = "al2023-ami-kernel-default-x86_64"
    ok2, msg2 = False, "ImageId is %s" % flat(img)[:80]
    if r and r in T.P:
        pt = T.param_type(r) or ""
        if pt.startswith("AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>") and target in flat(T.param_default(r)):
            ok2, msg2 = True, "SSM parameter type with AL2023 path"
        else:
            msg2 = "parameter %s type %s default %s" % (r, pt, flat(T.param_default(r))[:80])
    elif "{{resolve:ssm:" in flat(img) and target in flat(img):
        ok2, msg2 = True, "SSM dynamic reference"
    res["T1.R2"] = (ok2, msg2)
    # R3
    it = T.literal_or_default(p.get("InstanceType"))
    res["T1.R3"] = (str(it) == "t3.micro", "instance type %s" % it)
    # R4/R5/R6
    https = [x for x in rules if T.covers(x, 443) and x["from"] == 443 and x["to"] == 443 and x["cidr"] == ("lit", "0.0.0.0/0")]
    res["T1.R4"] = (bool(https), "HTTPS from anywhere present" if https else "no TCP 443 rule from 0.0.0.0/0")
    ssh = [x for x in rules if T.covers(x, 22)]
    ssh_ok = bool(ssh) and all(x["cidr"] and x["cidr"][0] == "param" and x["from"] == 22 and x["to"] == 22 for x in ssh)
    res["T1.R5"] = (ssh_ok, "SSH rules: %s" % ssh[:3])
    other = [x for x in rules if x not in https and x not in ssh]
    wide_ssh = [x for x in ssh if not (x["cidr"] and x["cidr"][0] == "param")]
    res["T1.R6"] = (bool(rules) and not other and not wide_ssh and len(https) >= 1,
                    "extra inbound rules: %s" % (other + wide_ssh)[:3] if (other or wide_ssh) else "only HTTPS and SSH rules")
    # R7
    ud = _normalise_userdata(_userdata(T, p)).lower()  # PATCH P12
    c = {
        "httpd": re.search(r"(dnf|yum)\s+(-y\s+)?install[^\n]*\bhttpd\b", ud) is not None,
        "mod_ssl": "mod_ssl" in ud,
        "index": "index.html" in ud,
        "start": re.search(r"systemctl\s+(start|enable\s+--now|restart)\s+httpd", ud) is not None or "enable --now httpd" in ud,
        "enable": re.search(r"systemctl\s+enable\s+(--now\s+)?httpd", ud) is not None,
    }
    res["T1.R7"] = (all(c.values()), "user data components: %s" % c)
    # R8
    net = [lid for lid, r in T.R.items() if isinstance(r, dict) and r.get("Type") in ("AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::EC2::InternetGateway", "AWS::EC2::RouteTable")]
    res["T1.R8"] = (not net, "creates network resources %s" % net if net else "uses default VPC")
    if "Fn::ImportValue" in json.dumps(T.t, default=str):  # PATCH P18
        res["T1.R8"] = (False, "imports a cross-stack export (Fn::ImportValue); a fresh account has no exports, so the stack cannot deploy")
    # R9
    outs = [flat((o or {}).get("Value")) for o in T.O.values() if isinstance(o, dict)]
    dns = any("${%s.PublicDnsName}" % inst in o for o in outs)
    url = any(o.startswith("https://") and ("${%s.PublicDnsName}" % inst in o or "${%s.PublicIp}" % inst in o) for o in outs)
    res["T1.R9"] = (dns and url, "public DNS output %s; https URL output %s" % (dns, url))
    return res

# ----------------------------------------------------------------------------- T2
def t2_checks(T):
    res = {}
    vpcs = list(T.of("AWS::EC2::VPC"))
    vp = T.props(vpcs[0]) if vpcs else {}
    dns_support = vp.get("EnableDnsSupport") is None or truthy(vp.get("EnableDnsSupport"))  # AWS default: true
    res["T2.R1"] = (bool(vpcs) and lv(vp.get("CidrBlock")) == "10.0.0.0/16" and dns_support and truthy(vp.get("EnableDnsHostnames")),
                    "VPC %s cidr %s dns %s/%s" % (bool(vpcs), flat(vp.get("CidrBlock")), vp.get("EnableDnsSupport"), vp.get("EnableDnsHostnames")))
    subnets = list(T.of("AWS::EC2::Subnet"))
    pub = [s for s in subnets if truthy(T.props(s).get("MapPublicIpOnLaunch"))]
    priv = [s for s in subnets if s not in pub]
    ok_p, m_p = T.distinct_getazs(pub)
    ok_q, m_q = T.distinct_getazs(priv)
    res["T2.R2"] = (len(pub) >= 2 and len(priv) >= 2 and ok_p and ok_q, "public %s: %s | private %s: %s" % (pub, m_p, priv, m_q))
    srt = T.subnet_rt()
    ok3 = T.igw_attached() and len(pub) >= 2 and all(any(T.rt_has(rt, "igw") for rt in srt.get(s, ())) for s in pub)
    res["T2.R3"] = (ok3, "IGW attached %s; public subnets routed to IGW %s" % (T.igw_attached(), {s: any(T.rt_has(rt, 'igw') for rt in srt.get(s, ())) for s in pub}))
    ok4 = len(priv) >= 2 and all(T.route_private(s) for s in priv)
    res["T2.R4"] = (ok4, "private subnets with explicit route table and no IGW route: %s" % {s: T.route_private(s) for s in priv})
    # R5
    lts = list(T.of("AWS::EC2::LaunchTemplate"))
    lc = list(T.of("AWS::AutoScaling::LaunchConfiguration"))
    ok5, m5 = False, "no launch template"
    web_sg = None
    if lts:
        lt = lts[0]
        d = T.props(lt).get("LaunchTemplateData") or {}
        img = ref_of(d.get("ImageId"))
        c = {"ami_param": bool(img and T.param_type(img) == "AWS::EC2::Image::Id"),
             "t3.micro": str(T.literal_or_default(d.get("InstanceType"))) == "t3.micro",
             "sg": bool(_lt_sgs(T, lt)),
             "no_template_level_sg_with_network_interfaces": not (d.get("NetworkInterfaces") and (d.get("SecurityGroupIds") or d.get("SecurityGroups"))),  # PATCH P16 (EC2 rejects SecurityGroupIds alongside NetworkInterfaces)
             "userdata": ("httpd" in flat(d.get("UserData")).lower() and "php" in flat(d.get("UserData")).lower()),
             "no_launch_config": not lc}
        ok5, m5 = all(c.values()), "launch template components %s" % c
        web_sg = (_lt_sgs(T, lt) or [None])[0]
    elif lc:
        m5 = "uses deprecated launch configuration %s" % lc
    res["T2.R5"] = (ok5, m5)
    # R6
    insts = list(T.of("AWS::EC2::Instance"))
    ok6, m6 = False, "no instance"
    for i in insts:
        p = T.props(i)
        ltr = ref_of((p.get("LaunchTemplate") or {}).get("LaunchTemplateId")) or ref_of((p.get("LaunchTemplate") or {}).get("LaunchTemplateName"))
        sn = ref_of(p.get("SubnetId"))
        if sn is None:
            for ni in as_list(p.get("NetworkInterfaces")):
                if isinstance(ni, dict):
                    sn = ref_of(ni.get("SubnetId"))
        eip = any(ref_of(T.props(e).get("InstanceId")) == i for e in T.of("AWS::EC2::EIP")) or \
              any(ref_of(T.props(a).get("InstanceId")) == i for a in T.of("AWS::EC2::EIPAssociation"))
        c = {"from_lt": ltr in lts, "public_subnet": sn in pub and T.route_public(sn), "eip": eip}
        ok6, m6 = all(c.values()), "instance %s %s" % (i, c)
        if ok6:
            break
    res["T2.R6"] = (ok6, m6)
    # R7
    if web_sg is None and insts:
        cand = _sg_ids(T.props(insts[0]).get("SecurityGroupIds")) + [g for ni in as_list(T.props(insts[0]).get("NetworkInterfaces")) if isinstance(ni, dict) for g in _sg_ids(ni.get("GroupSet"))]  # PATCH P20
        web_sg = cand[0] if cand else None
    ok7, m7 = False, "no web security group"
    if web_sg:
        rules = T.sg_rules(web_sg)
        h80 = any(T.covers(r, 80) and r["cidr"] == ("lit", "0.0.0.0/0") for r in rules)  # PATCH P5
        h443 = any(T.covers(r, 443) and r["cidr"] == ("lit", "0.0.0.0/0") for r in rules)
        ssh = [r for r in rules if T.covers(r, 22)]
        ssh_ok = bool(ssh) and all(r["cidr"] and r["cidr"][0] == "param" for r in ssh)
        ok7, m7 = h80 and h443 and ssh_ok, "web SG %s: 80 %s 443 %s ssh-from-param %s" % (web_sg, h80, h443, ssh_ok)
    res["T2.R7"] = (ok7, m7)
    # R8 / R9 / R10
    dbs = _rds(T)
    if not dbs:
        for k in ("T2.R8", "T2.R9", "T2.R10"):
            res[k] = (False, "no RDS DB instance")
    else:
        db = dbs[0]; p = T.props(db)
        sn = _db_subnets(T, db) or []
        c = {"mysql": lv(p.get("Engine")).lower() == "mysql", "class": lv(p.get("DBInstanceClass")) == "db.t3.micro",
             "private_subnets": len(sn) >= 2 and set(sn) <= set(priv) and all(T.route_private(s) for s in sn),
             "not_public": not truthy(p.get("PubliclyAccessible")), "encrypted": truthy(p.get("StorageEncrypted"))}
        res["T2.R8"] = (all(c.values()), "database %s" % c)
        res["T2.R9"] = _db_password_ok(T, p)
        for odb in dbs[1:]:  # PATCH P4
            op = T.props(odb)
            if truthy(op.get("PubliclyAccessible")) or op.get("DBSubnetGroupName") is None or not truthy(op.get("StorageEncrypted")):
                res["T2.R8"] = (False, "additional DB instance %s is public or unencrypted" % odb)
            if not _db_password_ok(T, op)[0]:
                res["T2.R9"] = (False, "additional DB instance %s: %s" % (odb, _db_password_ok(T, op)[1]))
        dsg = _db_sgs(T, db)
        if not dsg or not web_sg:
            res["T2.R10"] = (False, "database security group or web security group missing")
        else:
            res["T2.R10"] = _only_from_sg(T, dsg[0], 3306, [web_sg])
    # R11
    outs = [flat((o or {}).get("Value")) for o in T.O.values() if isinstance(o, dict)]
    eips = list(T.of("AWS::EC2::EIP"))
    url = any(("${%s}" % e in o or "${%s.PublicIp}" % e in o) for e in eips for o in outs) or \
          any("${%s.PublicIp}" % i in o for i in insts for o in outs)
    dbo = any("${%s.Endpoint.Address}" % d in o for d in dbs for o in outs)
    res["T2.R11"] = (url and dbo, "website URL output %s; DB endpoint output %s" % (url, dbo))
    return res

# ----------------------------------------------------------------------------- T3
FIXED_NAME_PROPS = {
    "AWS::S3::Bucket": "BucketName", "AWS::IAM::Role": "RoleName", "AWS::IAM::InstanceProfile": "InstanceProfileName",
    "AWS::RDS::DBInstance": "DBInstanceIdentifier", "AWS::RDS::DBSubnetGroup": "DBSubnetGroupName",
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "Name", "AWS::ElasticLoadBalancingV2::TargetGroup": "Name",
    "AWS::AutoScaling::AutoScalingGroup": "AutoScalingGroupName", "AWS::EC2::LaunchTemplate": "LaunchTemplateName",
    "AWS::IAM::ManagedPolicy": "ManagedPolicyName", "AWS::CloudWatch::Alarm": "AlarmName",
    "AWS::SecretsManager::Secret": "Name",
}
AZ_RE = re.compile(r"\b[a-z]{2}(-gov)?-[a-z]+-\d[a-z]\b")


def _walk(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)
    else:
        yield v


def t3_checks(T):
    res = {}
    albs = [a for a in T.of("AWS::ElasticLoadBalancingV2::LoadBalancer") if flat(T.props(a).get("Type") or "application") == "application"]
    asgs = list(T.of("AWS::AutoScaling::AutoScalingGroup"))
    subnets = list(T.of("AWS::EC2::Subnet"))
    alb = albs[0] if albs else None
    asg = asgs[0] if asgs else None
    alb_sn = [ref_of(x) for x in as_list(T.props(alb).get("Subnets"))] if alb else []
    for sm in as_list(T.props(alb).get("SubnetMappings")) if alb else []:
        if isinstance(sm, dict):
            alb_sn.append(ref_of(sm.get("SubnetId")))
    alb_sn = [s for s in alb_sn if s]
    asg_sn = [ref_of(x) for x in as_list(T.props(asg).get("VPCZoneIdentifier"))] if asg else []
    asg_sn = [s for s in asg_sn if s]
    pub = alb_sn if alb_sn else [s for s in subnets if T.route_public(s)]
    priv = asg_sn if asg_sn else [s for s in subnets if s not in pub]
    # PATCH P14: structural private subnets (not public by routing or public-IP mapping), independent of the ASG
    priv_struct = [s for s in subnets if s not in pub and not T.route_public(s) and not truthy(T.props(s).get("MapPublicIpOnLaunch"))]
    if len(priv_struct) < 2:
        priv_struct = priv
    # R1
    ok_p, m_p = T.distinct_getazs(pub)
    ok_q, m_q = T.distinct_getazs(priv_struct)
    vpc_ok = any(lv(T.props(v).get("CidrBlock")) == "10.0.0.0/16" for v in T.of("AWS::EC2::VPC"))
    res["T3.R1"] = (vpc_ok and ok_p and ok_q and not (set(pub) & set(priv_struct)), "VPC 10.0.0.0/16 %s | public %s: %s | private %s: %s" % (vpc_ok, pub, m_p, priv_struct, m_q))
    # R2
    ok2 = T.igw_attached() and len(pub) >= 2 and all(T.route_public(s) for s in pub)
    res["T3.R2"] = (ok2, "IGW attached %s; public subnets routed to IGW %s" % (T.igw_attached(), {s: T.route_public(s) for s in pub}))
    # R3
    nats = list(T.of("AWS::EC2::NatGateway"))
    nat_ok = []
    for n in nats:
        p = T.props(n)
        alloc = ref_of(p.get("AllocationId"))
        nat_ok.append(alloc in T.of("AWS::EC2::EIP") and T.route_public(ref_of(p.get("SubnetId"))))
    ok3 = bool(nats) and all(nat_ok) and len(priv_struct) >= 2 and all(T.route_nat(s) for s in priv_struct)
    res["T3.R3"] = (ok3, "NAT gateways %s with EIP in public subnet %s; private subnets default-routed to NAT and no IGW %s" % (nats, nat_ok, {s: T.route_nat(s) for s in priv_struct}))
    # R4
    tgs = T.of("AWS::ElasticLoadBalancingV2::TargetGroup")
    lst = T.of("AWS::ElasticLoadBalancingV2::Listener")
    fwd_tg = None
    ok4, m4 = False, "no application load balancer"
    if alb:
        p = T.props(alb)
        scheme = flat(p.get("Scheme") or "internet-facing")
        l_ok = False
        for l, r in lst.items():
            lp = r.get("Properties", {}) or {}
            if ref_of(lp.get("LoadBalancerArn")) != alb or to_int(lp.get("Port")) != 80 or flat(lp.get("Protocol")).upper() != "HTTP":
                continue
            for a in as_list(lp.get("DefaultActions")):
                if not isinstance(a, dict) or flat(a.get("Type")).lower() != "forward":
                    continue
                t = ref_of(a.get("TargetGroupArn"))
                if t is None:
                    for tgx in as_list((a.get("ForwardConfig") or {}).get("TargetGroups")):
                        if isinstance(tgx, dict):
                            t = ref_of(tgx.get("TargetGroupArn"))
                if t in tgs:
                    fwd_tg = t; l_ok = True
        hc = False
        if fwd_tg:
            tp = T.props(fwd_tg)
            hc = lv(tp.get("HealthCheckPath")) == "/health" and flat(tp.get("HealthCheckProtocol") or "HTTP").upper() == "HTTP"
        ok_sn, _ = T.distinct_getazs(alb_sn)
        c = {"internet_facing": scheme == "internet-facing", "public_subnets": len(alb_sn) >= 2 and ok_sn and all(T.route_public(s) for s in alb_sn),
             "listener_80_forward": l_ok, "health_check": hc}
        ok4, m4 = all(c.values()), "ALB %s" % c
    res["T3.R4"] = (ok4, m4)
    # R5
    alb_sgs = [s for s in _sg_ids(T.props(alb).get("SecurityGroups"))] if alb else []
    ok5 = any(any(T.covers(r, 80) and r["cidr"] == ("lit", "0.0.0.0/0") for r in T.sg_rules(s)) for s in alb_sgs)  # PATCH P5
    res["T3.R5"] = (ok5, "ALB security groups %s allow TCP 80 from anywhere: %s" % (alb_sgs, ok5))
    # R7 (launch template) - computed before R6 because it identifies the web SG
    lts = list(T.of("AWS::EC2::LaunchTemplate"))
    lcs = list(T.of("AWS::AutoScaling::LaunchConfiguration"))
    asg_lt = None
    if asg:
        ltp = T.props(asg).get("LaunchTemplate") or {}
        asg_lt = ref_of(ltp.get("LaunchTemplateId")) or ref_of(ltp.get("LaunchTemplateName"))
        if asg_lt is None:
            mip = T.props(asg).get("MixedInstancesPolicy") or {}
            spec = ((mip.get("LaunchTemplate") or {}).get("LaunchTemplateSpecification") or {})
            asg_lt = ref_of(spec.get("LaunchTemplateId")) or ref_of(spec.get("LaunchTemplateName"))
    lt = asg_lt if asg_lt in lts else (lts[0] if lts else None)
    web_sgs = _lt_sgs(T, lt) if lt else []
    ok7, m7 = False, ("uses deprecated launch configuration" if lcs else "no launch template")
    if lt:
        d = T.props(lt).get("LaunchTemplateData") or {}
        img = ref_of(d.get("ImageId"))
        prof = d.get("IamInstanceProfile") or {}
        prof_ref = ref_of(prof.get("Arn")) or ref_of(prof.get("Name"))
        pub_ip = any(truthy((ni or {}).get("AssociatePublicIpAddress")) for ni in as_list(d.get("NetworkInterfaces")) if isinstance(ni, dict))
        c = {"ami_param": bool(img and T.param_type(img) == "AWS::EC2::Image::Id"),
             "t3.micro": str(T.literal_or_default(d.get("InstanceType"))) == "t3.micro" and all(  # PATCH P9
                 lv(o.get("InstanceType")) == "t3.micro" for o in as_list(((T.props(asg).get("MixedInstancesPolicy") or {})
                 .get("LaunchTemplate") or {}).get("Overrides")) if isinstance(o, dict) and o.get("InstanceType") is not None),
             "web_sg": bool(web_sgs),
             "no_template_level_sg_with_network_interfaces": not (d.get("NetworkInterfaces") and (d.get("SecurityGroupIds") or d.get("SecurityGroups"))),  # PATCH P16 (EC2 rejects SecurityGroupIds alongside NetworkInterfaces)
             "instance_profile": prof_ref in T.of("AWS::IAM::InstanceProfile"),
             "no_public_ip": not pub_ip and (any((ni or {}).get("AssociatePublicIpAddress") is not None and not truthy((ni or {}).get("AssociatePublicIpAddress"))
                                                  for ni in as_list(d.get("NetworkInterfaces")) if isinstance(ni, dict))
                                              or not any(truthy(T.props(s).get("MapPublicIpOnLaunch")) for s in priv)),  # PATCH P14
             "no_launch_config": not lcs}
        ok7, m7 = all(c.values()), "launch template %s %s" % (lt, c)
    res["T3.R7"] = (ok7, m7)
    # R6
    if web_sgs:
        allr = [r for s in web_sgs for r in T.sg_rules(s)]
        from_alb = any(T.covers(r, 80) and r["src"] in alb_sgs for r in allr)
        open_any = [r for r in allr if T.from_anywhere(r)]
        res["T3.R6"] = (from_alb and not open_any, "web SG %s: TCP 80 from ALB SG %s; open-to-world rules %s" % (web_sgs, from_alb, open_any[:2]))
    else:
        res["T3.R6"] = (False, "no web security group on the launch template")
    # R8
    ok8, m8 = False, "no Auto Scaling group"
    if asg:
        p = T.props(asg)
        ok_sn, msn = T.distinct_getazs(asg_sn)
        c = {"launch_template": asg_lt in lts, "private_subnets": len(asg_sn) >= 2 and ok_sn and all(T.route_private(s) for s in asg_sn),
             "min2": to_int(T.literal_or_default(p.get("MinSize"))) == 2, "max4": to_int(T.literal_or_default(p.get("MaxSize"))) == 4,
             "desired2": to_int(T.literal_or_default(p.get("DesiredCapacity"))) == 2,
             "target_group": bool(fwd_tg) and fwd_tg in [ref_of(x) for x in as_list(p.get("TargetGroupARNs"))],
             "elb_health": lv(p.get("HealthCheckType")).upper() == "ELB"}
        ok8, m8 = all(c.values()), "ASG %s" % c
    res["T3.R8"] = (ok8, m8)
    for oasg in asgs[1:]:  # PATCH P4
        op = T.props(oasg)
        osn = [ref_of(x) for x in as_list(op.get("VPCZoneIdentifier")) if ref_of(x)]
        if not (len(osn) >= 2 and all(T.route_private(s) for s in osn)) or flat(op.get("HealthCheckType")).upper() != "ELB":
            res["T3.R8"] = (False, "additional Auto Scaling group %s is not a private, ELB-checked web tier" % oasg)
        oltp = op.get("LaunchTemplate") or {}
        olt = ref_of(oltp.get("LaunchTemplateId")) or ref_of(oltp.get("LaunchTemplateName"))
        if olt and olt != lt:
            od = T.props(olt).get("LaunchTemplateData") or {}
            opub = any(truthy((ni or {}).get("AssociatePublicIpAddress")) for ni in as_list(od.get("NetworkInterfaces")) if isinstance(ni, dict))
            if opub or str(T.literal_or_default(od.get("InstanceType"))) != "t3.micro":
                res["T3.R7"] = (False, "launch template %s of additional ASG %s assigns public IPs or is not t3.micro" % (olt, oasg))
            for s in _lt_sgs(T, olt):
                if any(T.from_anywhere(r) for r in T.sg_rules(s)):
                    res["T3.R6"] = (False, "security group %s of additional ASG %s is open to the world" % (s, oasg))
    # R9
    ok9, m9 = False, "no scaling policy attached to the ASG"
    for lid, r in T.of("AWS::AutoScaling::ScalingPolicy").items():
        p = r.get("Properties", {}) or {}
        if asg is None or ref_of(p.get("AutoScalingGroupName")) != asg:
            continue
        ptype = flat(p.get("PolicyType") or "SimpleScaling")
        if ptype == "TargetTrackingScaling":
            tt = p.get("TargetTrackingConfiguration") or {}
            pm = flat((tt.get("PredefinedMetricSpecification") or {}).get("PredefinedMetricType"))
            cm = tt.get("CustomizedMetricSpecification") or {}
            tv = tt.get("TargetValue")
            try:
                tv = float(flat(tv))
            except Exception:
                tv = None
            cpu = pm == "ASGAverageCPUUtilization" or flat(cm.get("MetricName")) == "CPUUtilization"
            ok9, m9 = cpu and tv is not None and tv <= 70, "target tracking metric %s target %s" % (pm or flat(cm.get("MetricName")), tv)
        elif ptype in ("StepScaling", "SimpleScaling"):
            alarms = [a for a, ar in T.of("AWS::CloudWatch::Alarm").items()
                      if flat((ar.get("Properties") or {}).get("MetricName")) == "CPUUtilization"
                      and lid in [ref_of(x) for x in as_list((ar.get("Properties") or {}).get("AlarmActions"))]
                      and flat((ar.get("Properties") or {}).get("Namespace") or "AWS/EC2") == "AWS/EC2"  # PATCH P8
                      and any(flat(dm.get("Name")) == "AutoScalingGroupName" and ref_of(dm.get("Value")) == asg
                              for dm in as_list((ar.get("Properties") or {}).get("Dimensions")) if isinstance(dm, dict))]
            ok9, m9 = bool(alarms), "%s policy with CPU alarm %s" % (ptype, alarms)
        if ok9:
            break
    res["T3.R9"] = (ok9, m9)
    # R10
    buckets = list(T.of("AWS::S3::Bucket"))
    ok10, m10 = False, "no S3 bucket"
    for b in buckets:
        if T.props(b).get("PublicAccessBlockConfiguration") is None:
            # Since April 2023 all four settings are enabled by default on new buckets.
            ok10, m10 = True, "bucket %s uses the default Block Public Access configuration (all enabled)" % b
            break
        pab = T.props(b).get("PublicAccessBlockConfiguration") or {}
        c = {k: truthy(pab.get(k)) for k in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets")}
        ok10, m10 = all(c.values()), "bucket %s block public access %s" % (b, c)
        if ok10:
            break
    bad10 = [b for b in buckets if T.props(b).get("PublicAccessBlockConfiguration") is not None and not all(
        truthy((T.props(b).get("PublicAccessBlockConfiguration") or {}).get(k)) for k in ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"))]
    if bad10:  # PATCH P4
        ok10, m10 = False, "bucket(s) %s do not enable all four Block Public Access settings" % bad10
    res["T3.R10"] = (ok10, m10)
    # R11
    ok11, m11 = False, "no EC2 role"
    allowed = {"s3:putobject", "s3:getobject", "s3:deleteobject"}
    for role in T.of("AWS::IAM::Role"):
        if not T.trusts_ec2(role):
            continue
        prof_ok = any(role in [ref_of(x) for x in as_list(T.props(ip).get("Roles"))] for ip in T.of("AWS::IAM::InstanceProfile"))
        bad, good_put, good_get = [], False, False
        for arn in T.role_managed_arns(role):
            if re.search(r"S3|AdministratorAccess|PowerUserAccess|ReadOnlyAccess", arn):
                bad.append("managed policy %s" % arn)
        for st in T.role_statements(role):
            if flat(st.get("Effect")) != "Allow":
                continue
            if st.get("NotAction") is not None or st.get("NotResource") is not None:
                bad.append("NotAction/NotResource"); continue
            acts = [flat(a).lower() for a in as_list(st.get("Action"))]
            s3acts = [a for a in acts if a.startswith("s3:") or a == "*"]
            if not s3acts:
                continue
            if any(a not in allowed for a in s3acts):
                bad.append("actions %s" % s3acts)
            ress = [flat(x) for x in as_list(st.get("Resource"))]
            okset = set()
            for b in buckets:  # PATCH P6
                okset |= {"${%s.Arn}/*" % b, "arn:aws:s3:::${%s}/*" % b, "arn:${AWS::Partition}:s3:::${%s}/*" % b}
            for rr in ress:
                if rr not in okset:
                    bad.append("resource %s" % rr)
            if ress and all(rr in okset for rr in ress):
                good_put |= "s3:putobject" in s3acts
                good_get |= "s3:getobject" in s3acts
        for bp, bpr in T.of("AWS::S3::BucketPolicy").items():  # PATCH P7
            for st in as_list(((bpr.get("Properties") or {}).get("PolicyDocument") or {}).get("Statement")):
                if not isinstance(st, dict) or flat(st.get("Effect")) != "Allow":
                    continue
                pr = st.get("Principal")
                aws = as_list(pr.get("AWS")) if isinstance(pr, dict) else [pr]
                if not any(x == "*" or ref_of(x) == role or ("${%s" % role) in flat(x) for x in aws):
                    continue
                acts = [flat(a).lower() for a in as_list(st.get("Action"))]
                if st.get("NotAction") is not None or any(a not in allowed for a in acts):
                    bad.append("bucket policy %s grants %s" % (bp, acts))
        ok11 = prof_ok and not bad and good_put and good_get
        m11 = "role %s instance profile %s put %s get %s violations %s" % (role, prof_ok, good_put, good_get, bad[:3])
        if ok11:
            break
    res["T3.R11"] = (ok11, m11)
    # R12 / R13
    dbs = _rds(T)
    if not dbs:
        res["T3.R12"] = (False, "no RDS DB instance"); res["T3.R13"] = (False, "no RDS DB instance")
    else:
        db = dbs[0]; p = T.props(db)
        sn = _db_subnets(T, db) or []
        pw_ok, pw_m = _db_password_ok(T, p)
        ok_sn, _ = T.distinct_getazs(sn)
        c = {"mysql": lv(p.get("Engine")).lower() == "mysql", "class": lv(p.get("DBInstanceClass")) == "db.t3.micro",
             "multi_az": truthy(p.get("MultiAZ")), "private_subnets": len(sn) >= 2 and ok_sn and all(T.route_private(s) for s in sn),
             "not_public": not truthy(p.get("PubliclyAccessible")), "encrypted": truthy(p.get("StorageEncrypted")), "password": pw_ok}
        res["T3.R12"] = (all(c.values()), "database %s (%s)" % (c, pw_m))
        for odb in dbs[1:]:  # PATCH P4
            op = T.props(odb)
            if (truthy(op.get("PubliclyAccessible")) or op.get("DBSubnetGroupName") is None or not truthy(op.get("StorageEncrypted"))
                    or not _db_password_ok(T, op)[0]):
                res["T3.R12"] = (False, "additional DB instance %s is public, unencrypted or has a plain-text password" % odb)
        dsg = _db_sgs(T, db)
        if not dsg or not web_sgs:
            res["T3.R13"] = (False, "database or web security group missing")
        else:
            res["T3.R13"] = _only_from_sg(T, dsg[0], 3306, web_sgs)
    # R14
    ok14, m14 = False, "no CloudFront distribution"
    for d in T.of("AWS::CloudFront::Distribution"):
        cfg = T.props(d).get("DistributionConfig") or {}
        origins = [o for o in as_list(cfg.get("Origins")) if isinstance(o, dict)]
        o_ok = any(alb and flat(o.get("DomainName")) == "${%s.DNSName}" % alb and
                   flat((o.get("CustomOriginConfig") or {}).get("OriginProtocolPolicy")) == "http-only" for o in origins)
        vpp = flat((cfg.get("DefaultCacheBehavior") or {}).get("ViewerProtocolPolicy"))
        ok14, m14 = o_ok and vpp == "redirect-to-https", "ALB custom origin http-only %s; viewer policy %s" % (o_ok, vpp)
        if ok14:
            break
    res["T3.R14"] = (ok14, m14)
    # R15
    issues = []
    for lid, r in T.R.items():
        if not isinstance(r, dict):
            continue
        prop = FIXED_NAME_PROPS.get(r.get("Type"))
        p = r.get("Properties", {}) or {}
        if prop and p.get(prop) is not None:
            v = p.get(prop)
            fv = flat(v)
            fj = json.dumps(v)  # PATCH P21 (v1.1): stack-derived names inside Select/Split expressions
            if not ("AWS::StackName" in fv or "AWS::StackId" in fv or "AWS::StackName" in fj or "AWS::StackId" in fj or (ref_of(v) in T.P)):
                issues.append("%s.%s fixed name '%s'" % (lid, prop, fv[:40]))
        for x in _walk(p):
            if isinstance(x, str):
                if re.match(r"^ami-[0-9a-f]{8,17}$", x):
                    issues.append("%s hard-coded AMI %s" % (lid, x))
                if AZ_RE.fullmatch(x.strip()):
                    issues.append("%s hard-coded AZ %s" % (lid, x))
                if re.fullmatch(r"[a-z]{2,4}\d+-az\d+", x.strip()):  # PATCH P11
                    issues.append("%s hard-coded AZ ID %s" % (lid, x))
    for pn, pv in T.P.items():
        dv = flat((pv or {}).get("Default")) if isinstance(pv, dict) else ""
        if re.match(r"^ami-[0-9a-f]{8,17}$", (dv or "").strip()):  # PATCH P11
            issues.append("parameter %s default AMI %s" % (pn, dv))
        if AZ_RE.search(dv or ""):
            issues.append("parameter %s default AZ %s" % (pn, dv))
    res["T3.R15"] = (not issues, "; ".join(issues[:4]) if issues else "no fixed names, AMI IDs or AZ names")
    # R16
    outs = [flat((o or {}).get("Value")) for o in T.O.values() if isinstance(o, dict)]
    dists = list(T.of("AWS::CloudFront::Distribution"))
    cf = any("${%s.DomainName}" % d in o for d in dists for o in outs)
    lb = any(alb and "${%s.DNSName}" % alb in o for o in outs)
    res["T3.R16"] = (cf and lb, "CloudFront domain output %s; ALB DNS output %s" % (cf, lb))
    return res

# ----------------------------------------------------------------------------- driver
CHECKERS = {"T1": t1_checks, "T2": t2_checks, "T3": t3_checks}
N_REQ = {"T1": 9, "T2": 11, "T3": 16}


def grade_iac(task, response_text, do_lint=True):
    body = extract_block(response_text)
    ids = ["%s.R%d" % (task, i) for i in range(1, N_REQ[task] + 1)]
    out = {"task": task, "extracted": body is not None, "parse_ok": False, "lint": [], "lint_errors": 0,
           "checks": {}, "n_lines": len(body.splitlines()) if body else 0}
    if body is None:
        out["checks"] = {k: [False, "no template found in response"] for k in ids}
        return out
    tpl, err = decode(body)
    if tpl is None:
        out["checks"] = {k: [False, "template not parseable: %s" % err] for k in ids}
        out["lint"] = [{"rule": "PARSE", "level": "E", "line": 0, "message": err}]
        out["lint_errors"] = 1
        return out
    out["parse_ok"] = True
    if do_lint:
        out["lint"] = run_lint(body)
        out["lint_errors"] = sum(1 for m in out["lint"] if m["level"] == "E")
    try:
        res = CHECKERS[task](Tpl(tpl))
    except Exception as e:
        res = {k: (False, "checker exception: %r" % e) for k in ids}
    for k in ids:
        v = res.get(k, (False, "check not evaluated"))
        out["checks"][k] = [bool(v[0]), str(v[1])[:400]]
    return out
