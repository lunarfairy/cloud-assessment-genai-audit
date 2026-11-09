"""Deterministically regenerate the grader mutants from the gold solutions.

Usage: python mutate.py            (writes mutants/<TASK>/<id>.<ext> and mutants/manifest.json)

The template (T1-T3) and design (DES) mutants of the original audit were created interactively and
not archived; this script re-creates each catalogued mutant (results/grader_mutation_tests.csv of the
audit) from gold/ following the catalogue description. Each edit is an exact text substitution that
must match the stated number of times (assertion), so the output is deterministic and every mutant
differs from gold only by the edit named in its description. The 15 archived application mutants
(audit/mutants_app/app_00..app_14) are copied unchanged; one new targeted A01 mutant is generated.
"""
import copy, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import AUDIT  # noqa: E402

GOLD = os.path.join(AUDIT, "gold")
OUT = os.path.join(HERE, "mutants")


def edit(text, old, new, count=1):
    n = text.count(old)
    assert n == count, "anchor found %d times (expected %d): %r" % (n, count, old[:80])
    return text.replace(old, new)


# ------------------------------------------------------------------------------------------ T1
T1 = [
    ("T1_M01", "T1.R1", "key name not a parameter", [
        ("  KeyName:\n    Type: AWS::EC2::KeyPair::KeyName\n", ""),
        ("KeyName: !Ref KeyName", "KeyName: my-key-pair")]),
    ("T1_M02", "T1.R2", "hard-coded AMI ID", [
        ("  LatestAmiId:\n    Type: AWS::SSM::Parameter::Value<AWS::EC2::Image::Id>\n"
         "    Default: /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64\n", ""),
        ("ImageId: !Ref LatestAmiId", "ImageId: ami-0abcdef1234567890")]),
    ("T1_M03", "T1.R2", "Amazon Linux 2 SSM path instead of AL2023", [
        ("al2023-ami-kernel-default-x86_64", "amzn2-ami-hvm-x86_64-gp2")]),
    ("T1_M04", "T1.R3", "t2.micro", [("Default: t3.micro", "Default: t2.micro")]),
    ("T1_M05", "T1.R4", "HTTPS rule replaced by HTTP", [
        ("FromPort: 443\n          ToPort: 443", "FromPort: 80\n          ToPort: 80")]),
    ("T1_M06", "T1.R5", "SSH open to world", [("CidrIp: !Ref AdminCidr", "CidrIp: 0.0.0.0/0")]),
    ("T1_M07", "T1.R6", "extra HTTP rule", [
        ("          ToPort: 443\n          CidrIp: 0.0.0.0/0\n",
         "          ToPort: 443\n          CidrIp: 0.0.0.0/0\n        - IpProtocol: tcp\n          FromPort: 80\n"
         "          ToPort: 80\n          CidrIp: 0.0.0.0/0\n")]),
    ("T1_M08", "T1.R7", "user data does not enable httpd", [("          systemctl enable httpd\n", "")]),
    ("T1_M09", "T1.R7", "user data omits mod_ssl", [("dnf install -y httpd mod_ssl", "dnf install -y httpd")]),
    ("T1_M10", "T1.R8", "creates a VPC", [
        ("Resources:\n", "Resources:\n  ExtraVPC:\n    Type: AWS::EC2::VPC\n    Properties:\n      CidrBlock: 10.0.0.0/16\n")]),
    ("T1_M11", "T1.R9", "http URL output", [("'https://${WebServer.PublicDnsName}'", "'http://${WebServer.PublicDnsName}'")]),
]

# ------------------------------------------------------------------------------------------ T2
PRIV2_AZ1 = "CidrBlock: 10.0.12.0/24\n      AvailabilityZone: !Select [1, !GetAZs '']"
PRIV2_AZ0 = "CidrBlock: 10.0.12.0/24\n      AvailabilityZone: !Select [0, !GetAZs '']"
LITERAL_PW = ("ManageMasterUserPassword: true", "MasterUserPassword: 'Sup3rSecretPass1'")
DB_FROM_CIDR = ("          SourceSecurityGroupId: !Ref WebSecurityGroup", "          CidrIp: 10.0.0.0/16")
T2 = [
    ("T2_M01", "T2.R1", "DNS hostnames disabled", [("EnableDnsHostnames: true", "EnableDnsHostnames: false")]),
    ("T2_M02", "T2.R2", "both private subnets in same AZ", [(PRIV2_AZ1, PRIV2_AZ0)]),
    ("T2_M03", "T2.R2", "hard-coded AZ name", [
        ("CidrBlock: 10.0.1.0/24\n      AvailabilityZone: !Select [0, !GetAZs '']",
         "CidrBlock: 10.0.1.0/24\n      AvailabilityZone: us-east-1a")]),
    ("T2_M04", "T2.R3", "public route table not associated with subnet 2", [
        ("  PublicSubnet2Assoc:\n    Type: AWS::EC2::SubnetRouteTableAssociation\n    Properties:\n"
         "      SubnetId: !Ref PublicSubnet2\n      RouteTableId: !Ref PublicRouteTable\n", "")]),
    ("T2_M05", "T2.R4", "private subnet 1 associated with public route table", [
        ("SubnetId: !Ref PrivateSubnet1\n      RouteTableId: !Ref PrivateRouteTable",
         "SubnetId: !Ref PrivateSubnet1\n      RouteTableId: !Ref PublicRouteTable")]),
    ("T2_M06", "T2.R5", "launch template instance type t2.micro", [("InstanceType: t3.micro", "InstanceType: t2.micro")]),
    ("T2_M07", "T2.R6", "no Elastic IP association", [("      Domain: vpc\n      InstanceId: !Ref WebServer\n", "      Domain: vpc\n")]),
    ("T2_M08", "T2.R6", "instance in private subnet", [
        ("      SubnetId: !Ref PublicSubnet1\n  WebEIP:", "      SubnetId: !Ref PrivateSubnet1\n  WebEIP:")]),
    ("T2_M09", "T2.R7", "SSH from world", [("CidrIp: !Ref AdminCidr", "CidrIp: 0.0.0.0/0")]),
    ("T2_M10", "T2.R8", "database publicly accessible", [("PubliclyAccessible: false", "PubliclyAccessible: true")]),
    ("T2_M11", "T2.R8", "storage not encrypted", [("StorageEncrypted: true", "StorageEncrypted: false")]),
    ("T2_M12", "T2.R9", "literal master password", [LITERAL_PW]),
    ("T2_M13", "T2.R10", "MySQL open to VPC CIDR", [DB_FROM_CIDR]),
    ("T2_M14", "T2.R11", "no DB endpoint output", [("  DatabaseEndpoint:\n    Value: !GetAtt Database.Endpoint.Address\n", "")]),
]

# ------------------------------------------------------------------------------------------ T3
T3 = [
    ("T3_M01", "T3.R1", "private subnets in same AZ", [(PRIV2_AZ1, PRIV2_AZ0)]),
    ("T3_M02", "T3.R2", "IGW not attached", [
        ("  GatewayAttachment:\n    Type: AWS::EC2::VPCGatewayAttachment\n    Properties:\n      VpcId: !Ref VPC\n"
         "      InternetGatewayId: !Ref InternetGateway\n", ""),
        ("    DependsOn: GatewayAttachment\n", "", 2)]),
    ("T3_M03", "T3.R3", "private default route to IGW", [("      NatGatewayId: !Ref NatGateway", "      GatewayId: !Ref InternetGateway")]),
    ("T3_M04", "T3.R3", "NAT gateway in private subnet", [
        ("AllocationId: !GetAtt NatEIP.AllocationId\n      SubnetId: !Ref PublicSubnet1",
         "AllocationId: !GetAtt NatEIP.AllocationId\n      SubnetId: !Ref PrivateSubnet1")]),
    ("T3_M05", "T3.R4", "internal load balancer", [("Scheme: internet-facing", "Scheme: internal")]),
    ("T3_M06", "T3.R4", "health check on /", [("HealthCheckPath: /health", "HealthCheckPath: /")]),
    ("T3_M07", "T3.R5", "ALB SG allows only 443", [
        ("GroupDescription: Load balancer\n      VpcId: !Ref VPC\n      SecurityGroupIngress:\n        - IpProtocol: tcp\n"
         "          FromPort: 80\n          ToPort: 80",
         "GroupDescription: Load balancer\n      VpcId: !Ref VPC\n      SecurityGroupIngress:\n        - IpProtocol: tcp\n"
         "          FromPort: 443\n          ToPort: 443")]),
    ("T3_M08", "T3.R6", "web SG open to world", [
        ("          SourceSecurityGroupId: !Ref ALBSecurityGroup\n",
         "          SourceSecurityGroupId: !Ref ALBSecurityGroup\n        - IpProtocol: tcp\n          FromPort: 80\n"
         "          ToPort: 80\n          CidrIp: 0.0.0.0/0\n")]),
    ("T3_M09", "T3.R7", "no instance profile on launch template", [
        ("        IamInstanceProfile:\n          Arn: !GetAtt WebInstanceProfile.Arn\n", "")]),
    ("T3_M10", "T3.R7", "public IP on instances", [
        ("        SecurityGroupIds:\n          - !Ref WebSecurityGroup\n        UserData:",
         "        NetworkInterfaces:\n          - DeviceIndex: 0\n            AssociatePublicIpAddress: true\n"
         "            Groups:\n              - !Ref WebSecurityGroup\n        UserData:")]),
    ("T3_M11", "T3.R8", "ASG in public subnets", [
        ("      VPCZoneIdentifier:\n        - !Ref PrivateSubnet1\n        - !Ref PrivateSubnet2",
         "      VPCZoneIdentifier:\n        - !Ref PublicSubnet1\n        - !Ref PublicSubnet2")]),
    ("T3_M12", "T3.R8", "EC2 health checks", [("HealthCheckType: ELB", "HealthCheckType: EC2")]),
    ("T3_M13", "T3.R8", "max size 3", [("MaxSize: '4'", "MaxSize: '3'")]),
    ("T3_M14", "T3.R9", "target 85 percent", [("TargetValue: 60", "TargetValue: 85")]),
    ("T3_M15", "T3.R10", "one public access block setting off", [("RestrictPublicBuckets: true", "RestrictPublicBuckets: false")]),
    ("T3_M16", "T3.R11", "wildcard S3 action", [
        ("                Action:\n                  - s3:PutObject\n                  - s3:GetObject\n                  - s3:DeleteObject\n",
         "                Action:\n                  - s3:*\n")]),
    ("T3_M17", "T3.R11", "wildcard resource", [("Resource: !Sub '${PhotoBucket.Arn}/*'", "Resource: '*'")]),
    ("T3_M18", "T3.R11", "AmazonS3FullAccess managed policy", [
        ("  WebRole:\n    Type: AWS::IAM::Role\n    Properties:\n",
         "  WebRole:\n    Type: AWS::IAM::Role\n    Properties:\n      ManagedPolicyArns:\n"
         "        - arn:aws:iam::aws:policy/AmazonS3FullAccess\n")]),
    ("T3_M19", "T3.R12", "single-AZ database", [("MultiAZ: true", "MultiAZ: false")]),
    ("T3_M20", "T3.R12", "literal master password", [LITERAL_PW]),
    ("T3_M21", "T3.R13", "MySQL open to VPC CIDR", [DB_FROM_CIDR]),
    ("T3_M22", "T3.R14", "viewer policy allow-all", [("ViewerProtocolPolicy: redirect-to-https", "ViewerProtocolPolicy: allow-all")]),
    ("T3_M23", "T3.R14", "origin protocol https-only", [("OriginProtocolPolicy: http-only", "OriginProtocolPolicy: https-only")]),
    ("T3_M24", "T3.R15", "fixed bucket name", [
        ("  PhotoBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n",
         "  PhotoBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      BucketName: photo-site-uploads\n")]),
    ("T3_M25", "T3.R15", "fixed role name", [
        ("  WebRole:\n    Type: AWS::IAM::Role\n    Properties:\n",
         "  WebRole:\n    Type: AWS::IAM::Role\n    Properties:\n      RoleName: PhotoWebRole\n")]),
    ("T3_M26", "T3.R16", "no CloudFront output", [("  CloudFrontDomain:\n    Value: !GetAtt Distribution.DomainName\n", "")]),
]


# ------------------------------------------------------------------------------------------ DES
def _restate(d):
    """Keep the stated proposed cost consistent with the BoM (so only the intended check fails)."""
    import checks_des as CD
    d["stated_proposed_monthly_cost_usd"] = round(sum(CD.item_cost(i) for i in d["proposed_bom"]), 2)
    return d


def _item(d, name):
    return [i for i in d["proposed_bom"] if i["item"] == name][0]


def des_m01(d):  # unknown price item (stated cost left unchanged)
    _item(d, "elasticache_cache.t3.medium_hour")["item"] = "elasticache_cache.t3.small_hour"
    return d


def des_m02(d):
    d["stated_proposed_monthly_cost_usd"] = 520.00
    return d


def des_m03(d):  # original priced without the Multi-AZ multiplier
    d["stated_original_monthly_cost_usd"] = 118.50
    return d


def des_m04(d):  # database upsized to db.r6g.large Multi-AZ: over budget, arithmetic kept consistent
    _item(d, "rds_mysql_db.t3.medium_singleaz_hour")["item"] = "rds_mysql_db.r6g.large_singleaz_hour"
    d["database"]["instance_class"] = "db.r6g.large"
    return _restate(d)


def des_m05(d):
    d["compute"]["asg_max"] = 4
    return d


def des_m06(d):
    d["database"]["multi_az"] = False
    for i in d["proposed_bom"]:
        if i["item"].startswith("rds_"):
            i["multi_az"] = False
    return _restate(d)


def des_m07(d):
    d["database"]["point_in_time_recovery"] = False
    return d


def des_m08(d):
    _item(d, "ec2_t3.medium_hour")["quantity"] = 1460
    return _restate(d)


def des_m09(d):
    d["proposed_bom"] = [i for i in d["proposed_bom"] if i["item"] != "cloudfront_requests_per_10000"]
    return _restate(d)


def des_m10(d):
    s = (" Sustainability is served by scaling in after peaks so idle capacity is not left running, and by serving "
         "cached content from edge locations close to users.")
    assert s in d["justification"]
    d["justification"] = d["justification"].replace(s, "")
    return d


DES = [("DES_M01", "D01", "unknown price item", des_m01), ("DES_M02", "D02", "arithmetic error", des_m02),
       ("DES_M03", "D03", "original mis-priced", des_m03), ("DES_M04", "D04", "over budget", des_m04),
       ("DES_M05", "D05", "insufficient peak capacity", des_m05), ("DES_M06", "D06", "single-AZ database", des_m06),
       ("DES_M07", "D07", "no PITR", des_m07), ("DES_M08", "D08", "peak hours not costed", des_m08),
       ("DES_M09", "D09", "CDN requests not costed", des_m09), ("DES_M10", "D10", "sustainability pillar omitted", des_m10)]

# ------------------------------------------------------------------------------------------ APP
APP_ARCHIVED = [("A02", "no AUTOINCREMENT"), ("A03", "unordered search"), ("A04", "case-sensitive search"),
                ("A05", "string-built INSERT"), ("A06", "string-built SELECT"), ("A07", "naive local timestamp"),
                ("A08", "key without uuid"), ("A09", "no filename sanitisation"), ("A10", "no content-type check"),
                ("A11", "size check off by one"), ("A12", "presign put_object"), ("A13", "no expiry bound"),
                ("A14", "no compensating delete"), ("A15", "metadata stores filename not key"),
                ("A16", "embedded credentials")]
A01_EDIT = [("def photo_url(s3, bucket, key, expires=3600):", "def get_photo_url(s3, bucket, key, expires=3600):")]

# Supplementary (not in the 77): a strictly targeted case-sensitive search. The archived app_02 mutant for the
# same label also wraps the term in literal '%' for instr(), which breaks substring search altogether.
SUPP_APP = [("APP_S01", "A04", "case-sensitive search (targeted: instr on raw columns, term unchanged)", [
    ('    like = "%" + term.lower() + "%"\n', '    like = term\n'),
    ("\"WHERE lower(title) LIKE ? OR lower(coalesce(description, '')) LIKE ? ORDER BY id ASC\"",
     "\"WHERE instr(title, ?) > 0 OR instr(coalesce(description, ''), ?) > 0 ORDER BY id ASC\"")])]


def main():
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    manifest = []
    for task, rows in (("T1", T1), ("T2", T2), ("T3", T3)):
        gold = open(os.path.join(GOLD, task + ".yaml"), encoding="utf-8").read()  # universal newlines -> \n
        os.makedirs(os.path.join(OUT, task), exist_ok=True)
        for mid, target, desc, edits in rows:
            t = gold
            for e in edits:
                t = edit(t, e[0], e[1], e[2] if len(e) > 2 else 1)
            assert t != gold
            p = os.path.join(OUT, task, mid + ".yaml")
            open(p, "w", encoding="utf-8", newline="\n").write(t)
            manifest.append({"id": mid, "task": task, "target": target, "desc": desc, "path": "mutants/%s/%s.yaml" % (task, mid),
                             "source": "regenerated from gold/%s.yaml by mutate.py" % task})
    sys.path.insert(0, AUDIT)
    gold_des = json.load(open(os.path.join(GOLD, "DES.json"), encoding="utf-8"))
    os.makedirs(os.path.join(OUT, "DES"), exist_ok=True)
    for mid, target, desc, fn in DES:
        d = fn(copy.deepcopy(gold_des))
        p = os.path.join(OUT, "DES", mid + ".json")
        json.dump(d, open(p, "w", encoding="utf-8", newline="\n"), indent=1)
        manifest.append({"id": mid, "task": "DES", "target": target, "desc": desc, "path": "mutants/DES/%s.json" % mid,
                         "source": "regenerated from gold/DES.json by mutate.py"})
    os.makedirs(os.path.join(OUT, "APP"), exist_ok=True)
    g = open(os.path.join(GOLD, "photoapp.py"), encoding="utf-8").read()
    for old, new in A01_EDIT:
        g = edit(g, old, new)
    open(os.path.join(OUT, "APP", "APP_M01.py"), "w", encoding="utf-8", newline="\n").write(g)
    manifest.append({"id": "APP_M01", "task": "APP", "target": "A01", "desc": "required function photo_url missing (renamed get_photo_url)",
                     "path": "mutants/APP/APP_M01.py", "source": "new in v2, generated from gold/photoapp.py by mutate.py"})
    supp = []
    for mid, target, desc, edits in SUPP_APP:
        t = open(os.path.join(GOLD, "photoapp.py"), encoding="utf-8").read()
        for old, new in edits:
            t = edit(t, old, new)
        open(os.path.join(OUT, "APP", mid + ".py"), "w", encoding="utf-8", newline="\n").write(t)
        supp.append({"id": mid, "task": "APP", "target": target, "desc": desc, "path": "mutants/APP/%s.py" % mid,
                     "source": "supplementary (not catalogued), generated from gold/photoapp.py by mutate.py"})
    json.dump(supp, open(os.path.join(OUT, "supplementary.json"), "w", encoding="utf-8"), indent=1)
    for i, (target, desc) in enumerate(APP_ARCHIVED):
        mid = "APP_M%02d" % (i + 2)
        shutil.copyfile(os.path.join(AUDIT, "mutants_app", "app_%02d.py" % i), os.path.join(OUT, "APP", mid + ".py"))
        manifest.append({"id": mid, "task": "APP", "target": target, "desc": desc, "path": "mutants/APP/%s.py" % mid,
                         "source": "archived audit/mutants_app/app_%02d.py (copied unchanged)" % i})
    json.dump(manifest, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), indent=1)
    print("wrote %d mutants" % len(manifest))


if __name__ == "__main__":
    main()
