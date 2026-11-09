"""Generate the adversarial cases (from gold/ by exact text edits) and the case manifest.

Usage: python make_cases.py      (writes cases/adversarial/* and cases/cases.json)

Every case records the verdict a careful marker applying the brief would give ("accept", "reject", or
"ambiguous" where the brief does not settle it), the basis of that verdict ("letter" = the brief's wording;
"intent" = the stated purpose of the requirement, e.g. "deployed in any commercial Region"), the checks that
SHOULD fail under the brief (expect_fail), and the checks the case was designed to probe. Positive controls
(cases/positive/) are hand-written alternative-valid solutions; their metadata is listed here too.
"""
import copy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gvlib import AUDIT  # noqa: E402
from mutate import edit  # noqa: E402

sys.path.insert(0, AUDIT)
import checks_des as CD  # noqa: E402

GOLD = os.path.join(AUDIT, "gold")
OUTD = os.path.join(HERE, "cases", "adversarial")


def gold(name):
    return open(os.path.join(GOLD, name), encoding="utf-8").read()


CASES = []


def case(cid, task, category, expected, basis, expect_fail, probes, rationale, text=None, edits=None, base=None):
    if text is None:
        text = gold(base)
        for e in edits:
            text = edit(text, e[0], e[1], e[2] if len(e) > 2 else 1)
    ext = {"APP": ".py", "DES": ".json"}.get(task, ".yaml")
    CASES.append({"id": cid, "set": "adversarial", "task": task, "category": category, "expected": expected,
                  "basis": basis, "expect_fail": expect_fail, "probes": probes, "rationale": rationale,
                  "path": "cases/adversarial/%s%s" % (cid, ext), "_text": text})


DF, SW, UV = "interacting double fault", "superficially valid but wrong", "unusual but valid"

# ------------------------------------------------------------------------------------------ T1
T1 = "T1.yaml"
SSH_RULE = "          FromPort: 22\n          ToPort: 22\n          CidrIp: !Ref AdminCidr\n"
HTTPS_RULE = "          ToPort: 443\n          CidrIp: 0.0.0.0/0\n"
case("ADV_T1_01", "T1", SW, "reject", "letter", ["T1.R5", "T1.R6"], ["T1.R5", "T1.R6"],
     "Adds SSH from ::/0 (IPv6 anywhere) beside the admin-CIDR rule; SSH is no longer limited to the admin CIDR.",
     base=T1, edits=[(SSH_RULE, SSH_RULE + "        - IpProtocol: tcp\n          FromPort: 22\n          ToPort: 22\n          CidrIpv6: ::/0\n")])
case("ADV_T1_02", "T1", SW, "reject", "letter", ["T1.R6"], ["T1.R4", "T1.R6"],
     "Adds HTTPS from ::/0; R6 requires exactly the two listed inbound rules.",
     base=T1, edits=[(HTTPS_RULE, HTTPS_RULE + "        - IpProtocol: tcp\n          FromPort: 443\n          ToPort: 443\n          CidrIpv6: ::/0\n")])
UD_GOLD = ("        Fn::Base64: |\n          #!/bin/bash\n          dnf install -y httpd mod_ssl\n"
           "          echo \"<h1>Stage 1 web server</h1>\" > /var/www/html/index.html\n          systemctl enable httpd\n          systemctl start httpd\n")
case("ADV_T1_03", "T1", UV, "accept", "letter", [], ["T1.R7"],
     "User data written as cloud-init #cloud-config (packages, write_files, runcmd) instead of a shell script; it installs httpd and mod_ssl, writes index.html and enables and starts httpd.",
     base=T1, edits=[(UD_GOLD, "        Fn::Base64: |\n          #cloud-config\n          packages:\n            - httpd\n            - mod_ssl\n"
                      "          write_files:\n            - path: /var/www/html/index.html\n              content: \"<h1>Stage 1 web server</h1>\"\n"
                      "          runcmd:\n            - systemctl enable --now httpd\n")])
case("ADV_T1_04", "T1", UV, "accept", "letter", [], ["T1.R7"],
     "Shell user data splits the install command over continuation lines (dnf install -y \\ / httpd \\ / mod_ssl).",
     base=T1, edits=[("          dnf install -y httpd mod_ssl\n", "          dnf install -y \\\n            httpd \\\n            mod_ssl\n")])
case("ADV_T1_05", "T1", SW, "reject", "letter", ["T1.R5", "T1.R6"], ["T1.R5", "T1.R6"],
     "The admin rule opens TCP 0-65535 (not just 22) to the admin CIDR: extra inbound traffic beyond SSH.",
     base=T1, edits=[(SSH_RULE, "          FromPort: 0\n          ToPort: 65535\n          CidrIp: !Ref AdminCidr\n")])
case("ADV_T1_06", "T1", SW, "reject", "letter", ["T1.R4", "T1.R5", "T1.R6"], ["T1.R4", "T1.R6"],
     "HTTPS rule replaced by IpProtocol -1 (all traffic) from 0.0.0.0/0.",
     base=T1, edits=[("        - IpProtocol: tcp\n          FromPort: 443\n          ToPort: 443\n          CidrIp: 0.0.0.0/0\n",
                      "        - IpProtocol: '-1'\n          CidrIp: 0.0.0.0/0\n")])
case("ADV_T1_07", "T1", SW, "reject", "intent", ["T1.R5"], ["T1.R1", "T1.R5"],
     "Admin CIDR parameter defaults to 0.0.0.0/0, so a default deployment opens SSH to the world while the rule still references the parameter.",
     base=T1, edits=[("    Default: 203.0.113.10/32\n", "    Default: 0.0.0.0/0\n")])
case("ADV_T1_08", "T1", DF, "reject", "letter", ["T1.R4", "T1.R6", "T1.R7"], ["T1.R4", "T1.R6", "T1.R7"],
     "Double fault: HTTPS rule changed to HTTP and mod_ssl dropped (an HTTP-only server whose faults are mutually consistent).",
     base=T1, edits=[("FromPort: 443\n          ToPort: 443", "FromPort: 80\n          ToPort: 80"),
                     ("dnf install -y httpd mod_ssl", "dnf install -y httpd")])

# ------------------------------------------------------------------------------------------ T2
T2 = "T2.yaml"
T2_PARAMS = "Parameters:\n  CustomAmiId:\n    Type: AWS::EC2::Image::Id\n"
case("ADV_T2_01", "T2", SW, "reject", "letter", ["T2.R8"], ["T2.R8"],
     "PubliclyAccessible taken from a parameter whose default is 'true': a default deployment creates a publicly accessible database.",
     base=T2, edits=[(T2_PARAMS, T2_PARAMS + "  DBPublic:\n    Type: String\n    Default: 'true'\n    AllowedValues: ['true', 'false']\n"),
                     ("PubliclyAccessible: false", "PubliclyAccessible: !Ref DBPublic")])
case("ADV_T2_02", "T2", UV, "accept", "letter", [], ["T2.R8"],
     "StorageEncrypted taken from a parameter whose default is 'true' (encrypted by default).",
     base=T2, edits=[(T2_PARAMS, T2_PARAMS + "  EncryptStorage:\n    Type: String\n    Default: 'true'\n    AllowedValues: ['true']\n"),
                     ("StorageEncrypted: true", "StorageEncrypted: !Ref EncryptStorage")])
case("ADV_T2_03", "T2", SW, "reject", "letter", ["T2.R2", "T2.R3"], ["T2.R2", "T2.R3"],
     "PublicSubnet2 and its route-table association carry a Condition that is false by default, so a default deployment has only one public subnet.",
     base=T2, edits=[(T2_PARAMS, T2_PARAMS + "  CreateSecondPublic:\n    Type: String\n    Default: 'false'\n    AllowedValues: ['true', 'false']\n"),
                     ("Resources:\n", "Conditions:\n  SecondPublic: !Equals [!Ref CreateSecondPublic, 'true']\nResources:\n"),
                     ("  PublicSubnet2:\n    Type: AWS::EC2::Subnet\n", "  PublicSubnet2:\n    Type: AWS::EC2::Subnet\n    Condition: SecondPublic\n"),
                     ("  PublicSubnet2Assoc:\n    Type: AWS::EC2::SubnetRouteTableAssociation\n",
                      "  PublicSubnet2Assoc:\n    Type: AWS::EC2::SubnetRouteTableAssociation\n    Condition: SecondPublic\n")])
case("ADV_T2_04", "T2", SW, "reject", "letter", ["T2.R9"], ["T2.R9"],
     "Master password is a NoEcho parameter, but the parameter has a literal Default, so the password is in plain text in the template.",
     base=T2, edits=[(T2_PARAMS, T2_PARAMS + "  DBPassword:\n    Type: String\n    NoEcho: true\n    Default: 'Photo-Admin-2026'\n"),
                     ("ManageMasterUserPassword: true", "MasterUserPassword: !Ref DBPassword")])
SEL0 = "AvailabilityZone: !Select [0, !GetAZs '']"
SEL1 = "AvailabilityZone: !Select [1, !GetAZs '']"
case("ADV_T2_05", "T2", SW, "reject", "letter", ["T2.R2"], ["T2.R2"],
     "Availability Zones chosen with Fn::Select over a literal list [us-east-1a, us-east-1b]: hard-coded AZ names that fail outside us-east-1.",
     base=T2, edits=[(SEL0, "AvailabilityZone: !Select [0, [us-east-1a, us-east-1b]]", 2),
                     (SEL1, "AvailabilityZone: !Select [1, [us-east-1a, us-east-1b]]", 2)])
case("ADV_T2_06", "T2", SW, "reject", "intent", ["T2.R7"], ["T2.R7"],
     "Web SG allows 80/443 only from ::/0. The VPC has no IPv6 CIDR, so the site is unreachable from anywhere over IPv4.",
     base=T2, edits=[("          ToPort: 80\n          CidrIp: 0.0.0.0/0\n", "          ToPort: 80\n          CidrIpv6: ::/0\n"),
                     ("          ToPort: 443\n          CidrIp: 0.0.0.0/0\n", "          ToPort: 443\n          CidrIpv6: ::/0\n")])
case("ADV_T2_07", "T2", UV, "ambiguous", "letter", [], ["T2.R9"],
     "Master password from an SSM SecureString dynamic reference ({{resolve:ssm-secure:...}}). It is not plain text, but it is not one of the three mechanisms the brief lists.",
     base=T2, edits=[("ManageMasterUserPassword: true", "MasterUserPassword: '{{resolve:ssm-secure:/photo/db/master:1}}'")])
case("ADV_T2_08", "T2", DF, "reject", "letter", ["T2.R2", "T2.R4", "T2.R8"], ["T2.R2", "T2.R4", "T2.R6", "T2.R8"],
     "Double fault: PrivateSubnet1 maps public IPs and is routed through the public route table, and the web server is launched into it. The 'private' subnet is effectively public, so only one private subnet remains (R2, R4) and the DB subnet group contains a public subnet (R8). R6 is met because the instance is now in a genuinely public subnet.",
     base=T2, edits=[("      CidrBlock: 10.0.11.0/24\n", "      CidrBlock: 10.0.11.0/24\n      MapPublicIpOnLaunch: true\n"),
                     ("SubnetId: !Ref PrivateSubnet1\n      RouteTableId: !Ref PrivateRouteTable", "SubnetId: !Ref PrivateSubnet1\n      RouteTableId: !Ref PublicRouteTable"),
                     ("      SubnetId: !Ref PublicSubnet1\n  WebEIP:", "      SubnetId: !Ref PrivateSubnet1\n  WebEIP:")])
case("ADV_T2_09", "T2", SW, "reject", "letter", ["T2.R10"], ["T2.R10"],
     "Database SG allows all protocols and ports (IpProtocol -1) from the web SG rather than only TCP 3306.",
     base=T2, edits=[("        - IpProtocol: tcp\n          FromPort: 3306\n          ToPort: 3306\n          SourceSecurityGroupId: !Ref WebSecurityGroup",
                      "        - IpProtocol: '-1'\n          SourceSecurityGroupId: !Ref WebSecurityGroup")])

# ------------------------------------------------------------------------------------------ T3
T3 = "T3.yaml"
T3_PARAMS = "Parameters:\n  CustomAmiId:\n    Type: AWS::EC2::Image::Id\n"
RES_ARN = "                Resource: !Sub '${PhotoBucket.Arn}/*'\n"
ACTIONS = "                Action:\n                  - s3:PutObject\n                  - s3:GetObject\n                  - s3:DeleteObject\n"
TT_BLOCK = ("  CpuTargetTracking:\n    Type: AWS::AutoScaling::ScalingPolicy\n    Properties:\n      AutoScalingGroupName: !Ref WebASG\n"
            "      PolicyType: TargetTrackingScaling\n      TargetTrackingConfiguration:\n        PredefinedMetricSpecification:\n"
            "          PredefinedMetricType: ASGAverageCPUUtilization\n        TargetValue: 60\n")
ASG_PRIV = "      VPCZoneIdentifier:\n        - !Ref PrivateSubnet1\n        - !Ref PrivateSubnet2"
ASG_PUB = "      VPCZoneIdentifier:\n        - !Ref PublicSubnet1\n        - !Ref PublicSubnet2"
LT_SGS = "        SecurityGroupIds:\n          - !Ref WebSecurityGroup\n        UserData:"
case("ADV_T3_01", "T3", SW, "reject", "letter", ["T3.R11"], ["T3.R11"],
     "Adds an Allow statement with NotAction iam:* on Resource '*', which grants s3:* and every other non-IAM action.",
     base=T3, edits=[(RES_ARN, RES_ARN + "              - Effect: Allow\n                NotAction: iam:*\n                Resource: '*'\n")])
case("ADV_T3_02", "T3", SW, "reject", "letter", ["T3.R11"], ["T3.R11"],
     "Object resource written as !Sub 'arn:${AWS::Partition}:s3:::*', i.e. every bucket, through Fn::Sub.",
     base=T3, edits=[(RES_ARN, "                Resource: !Sub 'arn:${AWS::Partition}:s3:::*'\n")])
case("ADV_T3_03", "T3", SW, "reject", "letter", ["T3.R11"], ["T3.R11"],
     "Resource !Sub '${PhotoBucket.Arn}*/*': the inserted wildcard covers objects in every bucket whose name starts with the photo bucket's name.",
     base=T3, edits=[(RES_ARN, "                Resource: !Sub '${PhotoBucket.Arn}*/*'\n")])
case("ADV_T3_04", "T3", SW, "reject", "letter", ["T3.R11"], ["T3.R11"],
     "s3:Put* wildcard (PutObject plus PutObjectAcl, PutBucketPolicy, ...).",
     base=T3, edits=[("                  - s3:PutObject\n", "                  - s3:Put*\n")])
case("ADV_T3_05", "T3", UV, "accept", "letter", [], ["T3.R15"],
     "BucketName !Sub '${AWS::StackName}-photos'. Stack names are unique within an account and Region, so a second deployment does not collide. Caveat: a stack name with upper-case letters would fail S3 naming rules.",
     base=T3, edits=[("  PhotoBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n",
                      "  PhotoBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      BucketName: !Sub '${AWS::StackName}-photos'\n")])
case("ADV_T3_06", "T3", SW, "reject", "letter", ["T3.R15"], ["T3.R15"],
     "BucketName !Sub '${AWS::AccountId}-${AWS::Region}-photos' looks dynamic but is fixed per account and Region, so a second deployment collides.",
     base=T3, edits=[("  PhotoBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n",
                      "  PhotoBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      BucketName: !Sub '${AWS::AccountId}-${AWS::Region}-photos'\n")])
case("ADV_T3_07", "T3", SW, "reject", "letter", ["T3.R12"], ["T3.R12"],
     "PubliclyAccessible from a parameter whose default is 'true'.",
     base=T3, edits=[(T3_PARAMS, T3_PARAMS + "  DBPublic:\n    Type: String\n    Default: 'true'\n    AllowedValues: ['true', 'false']\n"),
                     ("PubliclyAccessible: false", "PubliclyAccessible: !Ref DBPublic")])
case("ADV_T3_08", "T3", UV, "accept", "letter", [], ["T3.R12"],
     "MultiAZ from a parameter whose only allowed value and default is 'true'.",
     base=T3, edits=[(T3_PARAMS, T3_PARAMS + "  DBMultiAZ:\n    Type: String\n    Default: 'true'\n    AllowedValues: ['true']\n"),
                     ("MultiAZ: true", "MultiAZ: !Ref DBMultiAZ")])
case("ADV_T3_09", "T3", SW, "reject", "letter", ["T3.R1", "T3.R4", "T3.R8", "T3.R12", "T3.R15"], ["T3.R1", "T3.R15"],
     "AZs chosen with Fn::Select over a literal list of us-east-1 AZ names (subnets, ALB, ASG and DB subnet group all inherit the hard-coding).",
     base=T3, edits=[(SEL0, "AvailabilityZone: !Select [0, [us-east-1a, us-east-1b]]", 2),
                     (SEL1, "AvailabilityZone: !Select [1, [us-east-1a, us-east-1b]]", 2)])
case("ADV_T3_10", "T3", SW, "reject", "intent", ["T3.R11"], ["T3.R11"],
     "The role's identity policy is compliant, but a bucket policy grants the role s3:* on the bucket and its objects, so its effective S3 permissions exceed Put/Get/Delete.",
     base=T3, edits=[("  WebInstanceProfile:\n", "  PhotoBucketPolicy:\n    Type: AWS::S3::BucketPolicy\n    Properties:\n      Bucket: !Ref PhotoBucket\n"
                      "      PolicyDocument:\n        Version: '2012-10-17'\n        Statement:\n          - Effect: Allow\n"
                      "            Principal:\n              AWS: !GetAtt WebRole.Arn\n            Action: s3:*\n"
                      "            Resource:\n              - !GetAtt PhotoBucket.Arn\n              - !Sub '${PhotoBucket.Arn}/*'\n  WebInstanceProfile:\n")])
SHADOW = ("  OpenWebSG:\n    Type: AWS::EC2::SecurityGroup\n    Properties:\n      GroupDescription: shadow web tier\n      VpcId: !Ref VPC\n"
          "      SecurityGroupIngress:\n        - IpProtocol: tcp\n          FromPort: 80\n          ToPort: 80\n          CidrIp: 0.0.0.0/0\n"
          "  ShadowLaunchTemplate:\n    Type: AWS::EC2::LaunchTemplate\n    Properties:\n      LaunchTemplateData:\n        ImageId: !Ref CustomAmiId\n"
          "        InstanceType: t3.large\n        NetworkInterfaces:\n          - DeviceIndex: 0\n            AssociatePublicIpAddress: true\n"
          "            Groups:\n              - !Ref OpenWebSG\n  ShadowASG:\n    Type: AWS::AutoScaling::AutoScalingGroup\n    Properties:\n"
          "      MinSize: '1'\n      MaxSize: '2'\n      VPCZoneIdentifier:\n        - !Ref PublicSubnet1\n        - !Ref PublicSubnet2\n"
          "      LaunchTemplate:\n        LaunchTemplateId: !Ref ShadowLaunchTemplate\n        Version: !GetAtt ShadowLaunchTemplate.LatestVersionNumber\n")
case("ADV_T3_11", "T3", DF, "reject", "intent", ["T3.R6", "T3.R7", "T3.R8"], ["T3.R6", "T3.R7", "T3.R8"],
     "Masking double fault: the compliant ASG is left in place and a second 'shadow' ASG launches t3.large instances with public IPs, in the public subnets, behind an SG open to the world. The web tier becomes publicly reachable without the load balancer.",
     base=T3, edits=[("  CpuTargetTracking:\n", SHADOW + "  CpuTargetTracking:\n")])
case("ADV_T3_12", "T3", DF, "reject", "intent", ["T3.R12"], ["T3.R12"],
     "Masking double fault: a second RDS instance (listed after the compliant one) is publicly accessible, unencrypted and has a literal password.",
     base=T3, edits=[("  Distribution:\n", "  ReportingDatabase:\n    Type: AWS::RDS::DBInstance\n    DeletionPolicy: Delete\n    Properties:\n"
                      "      Engine: mysql\n      DBInstanceClass: db.t3.micro\n      AllocatedStorage: '20'\n      MasterUsername: report\n"
                      "      MasterUserPassword: 'Report-Pass-2026'\n      PubliclyAccessible: true\n      StorageEncrypted: false\n  Distribution:\n")])
case("ADV_T3_13", "T3", DF, "reject", "letter", ["T3.R10"], ["T3.R10"],
     "Masking double fault: a decoy bucket with all four Block Public Access settings is declared first, while the photo bucket the role and user data use has RestrictPublicBuckets off.",
     base=T3, edits=[("  PhotoBucket:\n", "  LogBucket:\n    Type: AWS::S3::Bucket\n    Properties:\n      PublicAccessBlockConfiguration:\n"
                      "        BlockPublicAcls: true\n        BlockPublicPolicy: true\n        IgnorePublicAcls: true\n        RestrictPublicBuckets: true\n  PhotoBucket:\n"),
                     ("RestrictPublicBuckets: true\n  WebRole:", "RestrictPublicBuckets: false\n  WebRole:")])
case("ADV_T3_14", "T3", SW, "reject", "intent", ["T3.R9"], ["T3.R9"],
     "Step-scaling policy driven by a CloudWatch alarm on the DATABASE's CPUUtilization (AWS/RDS), not the web tier's CPU.",
     base=T3, edits=[(TT_BLOCK, "  ScaleOutPolicy:\n    Type: AWS::AutoScaling::ScalingPolicy\n    Properties:\n      AutoScalingGroupName: !Ref WebASG\n"
                      "      PolicyType: StepScaling\n      AdjustmentType: ChangeInCapacity\n      StepAdjustments:\n        - MetricIntervalLowerBound: 0\n"
                      "          ScalingAdjustment: 1\n  CpuAlarm:\n    Type: AWS::CloudWatch::Alarm\n    Properties:\n      Namespace: AWS/RDS\n"
                      "      MetricName: CPUUtilization\n      Dimensions:\n        - Name: DBInstanceIdentifier\n          Value: !Ref Database\n"
                      "      Statistic: Average\n      Period: 60\n      EvaluationPeriods: 2\n      Threshold: 70\n"
                      "      ComparisonOperator: GreaterThanThreshold\n      AlarmActions:\n        - !Ref ScaleOutPolicy\n")])
case("ADV_T3_15", "T3", SW, "reject", "letter", ["T3.R7"], ["T3.R7", "T3.R8"],
     "The ASG uses a MixedInstancesPolicy whose Overrides launch t3.large, although the launch template says t3.micro.",
     base=T3, edits=[("      LaunchTemplate:\n        LaunchTemplateId: !Ref WebLaunchTemplate\n        Version: !GetAtt WebLaunchTemplate.LatestVersionNumber\n",
                      "      MixedInstancesPolicy:\n        LaunchTemplate:\n          LaunchTemplateSpecification:\n            LaunchTemplateId: !Ref WebLaunchTemplate\n"
                      "            Version: !GetAtt WebLaunchTemplate.LatestVersionNumber\n          Overrides:\n            - InstanceType: t3.large\n")])
case("ADV_T3_16", "T3", DF, "reject", "letter", ["T3.R8"], ["T3.R1", "T3.R3", "T3.R7", "T3.R8"],
     "Collateral probe: ASG in the public subnets, but the launch template explicitly sets AssociatePublicIpAddress false. Only R8 (ASG across the private subnets) is violated: the VPC, subnets and NAT routing (R1, R3) are unchanged and instances get no public IP (R7).",
     base=T3, edits=[(ASG_PRIV, ASG_PUB),
                     (LT_SGS, "        NetworkInterfaces:\n          - DeviceIndex: 0\n            AssociatePublicIpAddress: false\n"
                      "            Groups:\n              - !Ref WebSecurityGroup\n        UserData:")])
case("ADV_T3_17", "T3", SW, "reject", "intent", ["T3.R14"], ["T3.R14"],
     "The default cache behaviour redirects to HTTPS, but an ordered cache behaviour for path /* uses allow-all, so viewers can use plain HTTP for every non-root path.",
     base=T3, edits=[("          OriginRequestPolicyId: 216adef6-5c7f-47e4-b989-5492eafa07d3\n",
                      "          OriginRequestPolicyId: 216adef6-5c7f-47e4-b989-5492eafa07d3\n        CacheBehaviors:\n          - PathPattern: /*\n"
                      "            TargetOriginId: alb-origin\n            ViewerProtocolPolicy: allow-all\n"
                      "            CachePolicyId: 4135ea2d-6df8-44a3-9df3-4b5a84be39ad\n")])
case("ADV_T3_18", "T3", UV, "ambiguous", "letter", [], ["T3.R6"],
     "Web SG additionally allows SSH (22) from the VPC CIDR. R6 restricts TCP 80 and forbids 0.0.0.0/0 but says nothing about other ports from inside the VPC.",
     base=T3, edits=[("          SourceSecurityGroupId: !Ref ALBSecurityGroup\n",
                      "          SourceSecurityGroupId: !Ref ALBSecurityGroup\n        - IpProtocol: tcp\n          FromPort: 22\n          ToPort: 22\n          CidrIp: 10.0.0.0/16\n")])
case("ADV_T3_19", "T3", DF, "reject", "letter", ["T3.R3", "T3.R8", "T3.R12"], ["T3.R3", "T3.R8", "T3.R12"],
     "Double fault: NAT gateway placed in a private subnet and the private default route sent to the IGW.",
     base=T3, edits=[("AllocationId: !GetAtt NatEIP.AllocationId\n      SubnetId: !Ref PublicSubnet1", "AllocationId: !GetAtt NatEIP.AllocationId\n      SubnetId: !Ref PrivateSubnet1"),
                     ("      NatGatewayId: !Ref NatGateway", "      GatewayId: !Ref InternetGateway")])
case("ADV_T3_20", "T3", SW, "reject", "letter", ["T3.R1", "T3.R4", "T3.R8", "T3.R12", "T3.R15"], ["T3.R1", "T3.R15"],
     "Subnets pinned with literal AvailabilityZoneId values (use1-az1/use1-az2): hard-coded AZ identifiers that exist only in us-east-1.",
     base=T3, edits=[(SEL0, "AvailabilityZoneId: use1-az1", 2), (SEL1, "AvailabilityZoneId: use1-az2", 2)])
case("ADV_T3_21", "T3", SW, "reject", "intent", ["T3.R15"], ["T3.R7", "T3.R15"],
     "The AMI parameter (type AWS::EC2::Image::Id) has a literal default ami-0abcdef1234567890: a hard-coded, Region-specific AMI ID in a template meant for any Region.",
     base=T3, edits=[(T3_PARAMS, T3_PARAMS + "    Default: ami-0abcdef1234567890\n")])
case("ADV_T3_22", "T3", SW, "reject", "intent", ["T3.R6"], ["T3.R6"],
     "Web SG allows TCP 80 from ::/0 in addition to the ALB SG reference (IPv6 anywhere).",
     base=T3, edits=[("          SourceSecurityGroupId: !Ref ALBSecurityGroup\n",
                      "          SourceSecurityGroupId: !Ref ALBSecurityGroup\n        - IpProtocol: tcp\n          FromPort: 80\n          ToPort: 80\n          CidrIpv6: ::/0\n")])

# ------------------------------------------------------------------------------------------ APP
APP = "photoapp.py"
SEARCH_GOLD = ('    cur = conn.execute(\n        "SELECT id, title, description, s3_key, uploaded_at FROM photos "\n'
               '        "WHERE lower(title) LIKE ? OR lower(coalesce(description, \'\')) LIKE ? ORDER BY id ASC",\n        (like, like),\n    )\n')
case("ADV_APP_01", "APP", SW, "reject", "letter", ["A06"], ["A05", "A06"],
     "search_photos builds SQL with an f-string using {like!r}. Python repr quoting looks like parameterisation and defeats the three A06 probe terms, but a term containing both quote types escapes the literal.",
     base=APP, edits=[(SEARCH_GOLD, '    cur = conn.execute(\n        f"SELECT id, title, description, s3_key, uploaded_at FROM photos "\n'
                       '        f"WHERE lower(title) LIKE {like!r} OR lower(coalesce(description, \'\')) LIKE {like!r} ORDER BY id ASC"\n    )\n')])
case("ADV_APP_02", "APP", UV, "ambiguous", "intent", [], ["A05", "A06"],
     "search_photos interpolates the term after doubling single quotes (correct SQLite string escaping). It is safe for SQLite but not parameterised; the brief only says the term is untrusted.",
     base=APP, edits=[('    like = "%" + term.lower() + "%"\n' + SEARCH_GOLD,
                       '    like = "%" + term.lower().replace("\'", "\'\'") + "%"\n    cur = conn.execute(\n'
                       '        "SELECT id, title, description, s3_key, uploaded_at FROM photos "\n'
                       '        "WHERE lower(title) LIKE \'%s\' OR lower(coalesce(description, \'\')) LIKE \'%s\' ORDER BY id ASC" % (like, like)\n    )\n')])
case("ADV_APP_03", "APP", SW, "reject", "intent", ["A09"], ["A09"],
     "Sanitiser uses os.path.basename, which strips backslash directories only on Windows. On the Linux EC2 target, 'C:\\Users\\me\\my photo (1).png' keeps its directory components.",
     base=APP, edits=[('    base = re.split(r"[\\\\/]", filename)[-1]\n', "    base = os.path.basename(filename)\n")])
case("ADV_APP_04", "APP", SW, "reject", "letter", ["A08"], ["A08"],
     "Key uses uuid1().hex: 32 lowercase hex characters, but not from uuid4 (time and host based).",
     base=APP, edits=[("uuid.uuid4().hex", "uuid.uuid1().hex")])
case("ADV_APP_05", "APP", SW, "reject", "letter", ["A03"], ["A03"],
     "search_photos sets conn.row_factory = sqlite3.Row on the caller's connection and returns sqlite3.Row objects, not dicts.",
     base=APP, edits=[("import os\n", "import os\nimport sqlite3\n"),
                      ('    like = "%" + term.lower() + "%"\n', '    like = "%" + term.lower() + "%"\n    conn.row_factory = sqlite3.Row\n'),
                      ('    cols = ["id", "title", "description", "s3_key", "uploaded_at"]\n    return [dict(zip(cols, row)) for row in cur.fetchall()]\n',
                       "    return cur.fetchall()\n")])
case("ADV_APP_06", "APP", SW, "reject", "letter", ["A16"], ["A16"],
     "A fallback helper creates an AWS client with importlib.import_module('boto3').client('s3') when s3 is None (client construction in the module, obfuscated).",
     base=APP, edits=[("def upload_photo(s3, bucket, filename, data, content_type):\n",
                       "def _client(s3):\n    if s3 is None:\n        import importlib\n        return importlib.import_module(\"boto3\").client(\"s3\", region_name=\"us-east-1\")\n"
                       "    return s3\n\n\ndef upload_photo(s3, bucket, filename, data, content_type):\n    s3 = _client(s3)\n")])
case("ADV_APP_07", "APP", SW, "reject", "letter", ["A16"], ["A16"],
     "Module embeds temporary-credential constants (ASIA... key id and a secret) under neutral names.",
     base=APP, edits=[("MAX_BYTES = 5 * 1024 * 1024\n",
                       "MAX_BYTES = 5 * 1024 * 1024\n_FALLBACK_ID = \"ASIA\" \"Q3EXAMPLE7XYZ12345\"\n_FALLBACK_SECRET = \"wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\"\n")])
case("ADV_APP_08", "APP", UV, "accept", "letter", [], ["A12", "A13"],
     "Presigned expiry taken from a module constant and passed through a local variable (ExpiresIn=ttl).",
     base=APP, edits=[("def photo_url(s3, bucket, key, expires=3600):\n    if not isinstance(expires, int) or expires < 1 or expires > 3600:\n",
                       "DEFAULT_TTL = 3600\n\n\ndef photo_url(s3, bucket, key, expires=DEFAULT_TTL):\n    ttl = expires\n    if not isinstance(ttl, int) or ttl < 1 or ttl > DEFAULT_TTL:\n"),
                      ("ExpiresIn=expires)", "ExpiresIn=ttl)")])
case("ADV_APP_09", "APP", SW, "reject", "letter", ["A13"], ["A13"],
     "photo_url applies 'expires = expires or 3600' before validating, so expires=0 silently becomes 3600 instead of raising ValueError.",
     base=APP, edits=[("def photo_url(s3, bucket, key, expires=3600):\n", "def photo_url(s3, bucket, key, expires=3600):\n    expires = expires or 3600\n")])
case("ADV_APP_10", "APP", SW, "reject", "letter", ["A03"], ["A03", "A04"],
     "The gold reference itself, unchanged: LIKE without ESCAPE treats '%' and '_' in the term as wildcards, so search_photos(conn, '_') returns every row rather than rows containing '_'.",
     text=gold(APP))
case("ADV_APP_11", "APP", SW, "reject", "letter", ["A14"], ["A14"],
     "handle_upload deletes the object but raises a new RuntimeError instead of re-raising the original exception.",
     base=APP, edits=[("        s3.delete_object(Bucket=bucket, Key=key)\n        raise\n",
                       "        s3.delete_object(Bucket=bucket, Key=key)\n        raise RuntimeError(\"metadata save failed\")\n")])

# ------------------------------------------------------------------------------------------ DES
GD = json.load(open(os.path.join(GOLD, "DES.json"), encoding="utf-8"))


def restate(d):
    d["stated_proposed_monthly_cost_usd"] = round(sum(CD.item_cost(i) for i in d["proposed_bom"]), 2)
    return d


def item(d, name):
    return [i for i in d["proposed_bom"] if i["item"] == name][0]


def des(cid, category, expected, basis, expect_fail, probes, rationale, fn):
    d = fn(copy.deepcopy(GD))
    case(cid, "DES", category, expected, basis, expect_fail, probes, rationale, text=json.dumps(d, indent=1))


def _neg(d):
    item(d, "rds_mysql_db.t3.medium_singleaz_hour")["item"] = "rds_mysql_db.r6g.large_singleaz_hour"
    d["database"]["instance_class"] = "db.r6g.large"
    d["proposed_bom"].append({"item": "nat_gateway_hour", "quantity": -1460, "purpose": "savings-plan credit"})
    return restate(d)


def _zero(d):
    item(d, "rds_mysql_db.t3.medium_singleaz_hour")["quantity"] = 0
    return restate(d)


def _replicas(d):
    d["database"]["read_replicas"] = 2
    return d


def _pillars(d):
    d["justification"] = ("We scale the web tier to t3.medium instances (2 to 6) and keep a Multi-AZ database. "
                          "The pillars considered are operational excellence, security, reliability, performance efficiency, cost optimisation and sustainability.")
    return d


def _long(d):
    filler = (" In addition, the team will review the configuration every quarter, document each change in the runbook, and confirm that "
              "monitoring dashboards, alarms and backup reports remain accurate and are understood by everyone on call.")
    while len(d["justification"].split()) <= 820:
        d["justification"] += filler
    return d


def _split(d):
    d["proposed_bom"] = [i for i in d["proposed_bom"] if i["item"] != "cloudfront_gb_out"] + [
        {"item": "cloudfront_gb_out", "quantity": 1500, "purpose": "images"}, {"item": "cloudfront_gb_out", "quantity": 500, "purpose": "pages"}]
    return restate(d)


def _inconsistent(d):
    for i in d["proposed_bom"]:
        if i["item"].startswith("rds_"):
            i["multi_az"] = False
    return restate(d)


def _strings(d):
    for i in d["proposed_bom"]:
        i["quantity"] = str(i["quantity"])
    return d


def _pitr0(d):
    d["database"]["backup_retention_days"] = 0
    return d


des("ADV_DES_01", SW, "reject", "letter", ["D01", "D04"], ["D01", "D02", "D04"],
    "Over-budget design (db.r6g.large Multi-AZ) brought under US$750 by a negative-quantity 'credit' line (-1460 NAT gateway hours).", _neg)
des("ADV_DES_02", SW, "reject", "letter", ["D01", "D08"], ["D01", "D08"],
    "Database instance line has quantity 0 (flagged multi_az true), so the declared Multi-AZ database is not costed at all.", _zero)
des("ADV_DES_03", SW, "reject", "letter", ["D08"], ["D08"],
    "Declares read_replicas = 2 but costs no replica (the price sheet prices a replica as an extra single-AZ instance).", _replicas)
des("ADV_DES_04", SW, "reject", "intent", ["D10"], ["D10"],
    "Justification is two sentences that only list the six pillar names; it does not justify the design against them.", _pillars)
des("ADV_DES_05", SW, "reject", "letter", ["D10"], ["D10"],
    "Justification exceeds the 800-word limit of the output format.", _long)
des("ADV_DES_06", UV, "accept", "letter", [], ["D09"],
    "CloudFront transfer split across two BoM lines (1500 + 500 GB).", _split)
des("ADV_DES_07", SW, "reject", "letter", ["D08"], ["D06", "D08"],
    "Database declared multi_az true but costed single-AZ (BoM inconsistent with the declared design).", _inconsistent)
des("ADV_DES_08", SW, "reject", "letter", ["D01"], ["D01"],
    "All BoM quantities are JSON strings ('1640'), not numbers as the output format requires.", _strings)
des("ADV_DES_09", SW, "reject", "letter", ["D07"], ["D07"],
    "point_in_time_recovery true but backup_retention_days 0 (which disables automated backups and PITR on RDS).", _pitr0)

# ------------------------------------------------------------------------------------------ positives
POSITIVE = [
    ("POS_T1_01", "T1", "separate AWS::EC2::SecurityGroupIngress resources (GroupId GetAtt), {{resolve:ssm:...}} AMI, Fn::Sub user data with heredoc, enable --now, Fn::Join https URL"),
    ("POS_T1_02", "T1", "numeric IpProtocol '6', SecurityGroups by name (default VPC), AllowedValues instance-type parameter, Fn::Join user data, yum, restart, Fn::Sub variable map URL"),
    ("POS_T2_01", "T2", "generated AWS::SecretsManager::Secret with dynamic references, EIPAssociation, separate ingress resources, one private route table per private subnet, Fn::GetAZs !Ref AWS::Region, string booleans, EnableDnsSupport omitted (default true)"),
    ("POS_T3_01", "T3", "two NAT gateways and two private route tables, StepScaling policies with CloudWatch CPU alarms, Fn::Sub partition ARNs, separate AWS::IAM::Policy, NoEcho password, ForwardConfig listener, NetworkInterfaces without public IP, profile by Name"),
    ("POS_T3_02", "T3", "Block Public Access left at the post-2023 default, AWS::IAM::RolePolicy with upper-case S3: actions and Fn::Join ARN, MixedInstancesPolicy without overrides, SubnetMappings, inline flow-style SG rules, ManageMasterUserPassword, target tracking at exactly 70"),
    ("POS_APP_01", "APP", "strict DB-API cursor use, instr()-based search (literal containment), character-loop sanitiser with rpartition basename, strftime Z timestamp, cursor.description dicts"),
    ("POS_APP_02", "APP", "repository class, LIKE with ESCAPE (literal containment), ntpath.basename + regex sanitiser, isoformat timestamp, type() expiry check"),
    ("POS_DES_01", "DES", "m6g.large fleet (2-4) across 2 AZs, two NAT gateways, no ElastiCache, S3 request lines costed"),
    ("POS_DES_02", "DES", "t3.small fleet (3-12) across 3 AZs, db.r6g.large Multi-AZ instead of a cache, single NAT, CloudFront transfer split over two lines"),
]


def main():
    import shutil
    if os.path.isdir(OUTD):
        shutil.rmtree(OUTD)
    os.makedirs(OUTD)
    man = []
    for c in CASES:
        open(os.path.join(HERE, c["path"]), "w", encoding="utf-8", newline="\n").write(c["_text"])
        man.append({k: v for k, v in c.items() if k != "_text"})
    for cid, task, constructs in POSITIVE:
        ext = {"APP": ".py", "DES": ".json"}.get(task, ".yaml")
        p = "cases/positive/%s%s" % (cid, ext)
        assert os.path.exists(os.path.join(HERE, p)), p
        man.append({"id": cid, "set": "positive", "task": task, "category": "alternative valid", "expected": "accept",
                    "basis": "letter", "expect_fail": [], "probes": [], "rationale": constructs, "path": p})
    json.dump(man, open(os.path.join(HERE, "cases", "cases.json"), "w", encoding="utf-8"), indent=1)
    print("adversarial %d, positive %d" % (len(CASES), len(POSITIVE)))


if __name__ == "__main__":
    main()
