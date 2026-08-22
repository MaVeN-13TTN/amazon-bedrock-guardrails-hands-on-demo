"""`lab-cli doctor` — check every AWS prerequisite before anything is created.

Written after a validation session lost several hours to a misdiagnosis worth
recording: **an absent IAM grant masks a service control policy deny.** While IAM
lacks a permission, authorisation stops at the identity-policy check and never
reaches the resource an SCP denies, so the failure reports `no identity-based
policy allows` and an SCP block stays invisible. Add the IAM grant and the SCP
deny appears — looking, misleadingly, like the new grant caused it.

So this tool never infers "no SCP" from the absence of an SCP message. It probes
in an order that separates the two, reports what it actually observed, and says
plainly when a conclusion cannot be drawn yet.

It works for a standalone account and for an account inside an organisation. In an
organisation, SCPs are usually unreadable from the member account, so the tool
detects them from denial messages rather than by reading policy documents.

    lab-cli doctor                 # check everything, create nothing
    lab-cli doctor --probe-write   # also create and delete a throwaway guardrail
"""
from __future__ import annotations

import contextlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum

GUARDRAIL_ACTIONS = [
    "bedrock:CreateGuardrail",
    "bedrock:CreateGuardrailVersion",
    "bedrock:UpdateGuardrail",
    "bedrock:DeleteGuardrail",
    "bedrock:GetGuardrail",
    "bedrock:ListGuardrails",
    "bedrock:ApplyGuardrail",
]

# Terraform tags every resource it manages, and reads tags back when refreshing
# state. Without these a guardrail can be created exactly once, with default_tags
# removed, and never re-planned. Observed as validation log V-13.
TAG_ACTIONS = [
    "bedrock:TagResource",
    "bedrock:UntagResource",
    "bedrock:ListTagsForResource",
]

HAIKU = "anthropic.claude-haiku-4-5-20251001-v1:0"

# Guardrail profile per source Region, and the geography prefix to use for a model
# inference profile there. From the Amazon Bedrock User Guide:
#   guardrails-cross-region-support.html  (guardrail profiles)
#   inference-profiles-support.html       (model inference profiles)
GEOGRAPHY = {
    "us-east-1": "us", "us-east-2": "us", "us-west-1": "us", "us-west-2": "us",
    "eu-central-1": "eu", "eu-west-1": "eu", "eu-west-3": "eu", "eu-north-1": "eu",
    "eu-south-1": "eu", "eu-south-2": "eu", "il-central-1": "eu",
    "eu-west-2": "uk",
    "ca-central-1": "ca",
    "ap-southeast-2": "au",
    "ap-south-1": "apac", "ap-northeast-1": "apac", "ap-northeast-2": "apac",
    "ap-southeast-1": "apac", "ap-southeast-3": "apac", "ap-southeast-4": "apac",
    "ap-southeast-5": "apac", "ap-southeast-7": "apac", "ap-east-2": "apac",
    "me-central-1": "apac",
    "us-gov-east-1": "us-gov", "us-gov-west-1": "us-gov",
}


class Status(str, Enum):
    OK = "ok"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"
    UNKNOWN = "unknown"


@dataclass
class Check:
    """One prerequisite, its outcome, and what to do when it fails."""

    name: str
    status: Status
    detail: str = ""
    fix: list[str] = field(default_factory=list)
    # True when this check's result cannot be trusted because an earlier gap
    # masks it — the V-12 lesson, made explicit rather than inferred.
    masked_by: str | None = None

    @property
    def blocking(self) -> bool:
        return self.status is Status.FAIL


class Denial(str, Enum):
    """Why an AWS call was refused. The distinction is the whole point."""

    SCP = "scp"  # explicit deny in a service control policy — a ceiling
    IAM = "iam"  # no identity-based policy allows it — a grant to add
    OTHER = "other"  # validation, not-found, throttle: authorised but wrong
    NONE = "none"  # the call succeeded


_SCP_PATTERN = re.compile(r"explicit deny in a service control policy:?\s*(\S+)?")
_IAM_PATTERN = re.compile(r"no identity-based policy allows")
_RESOURCE_PATTERN = re.compile(r"on resource:\s*(\S+)")

# Everything Terraform needs for the Lambda execution role. Printed as a ready
# policy when iam:CreateRole is denied, so the ask to an administrator is exact.
_DEPLOY_ACTIONS = [
    "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:PassRole", "iam:TagRole",
    "iam:AttachRolePolicy", "iam:DetachRolePolicy",
    "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy",
    "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:ListRoleTags",
]


def classify_denial(exc: Exception) -> tuple[Denial, str, str | None]:
    """Return (kind, resource ARN, SCP id) from an AWS error.

    The resource ARN matters: a cross-Region inference profile can route a request
    into a Region you never named, and the ARN is the only place that shows it.
    """
    message = str(exc)
    resource_match = _RESOURCE_PATTERN.search(message)
    resource = resource_match.group(1).rstrip(".,") if resource_match else ""

    scp_match = _SCP_PATTERN.search(message)
    if scp_match:
        return Denial.SCP, resource, (scp_match.group(1) or "").rstrip(".,") or None
    if _IAM_PATTERN.search(message):
        return Denial.IAM, resource, None

    code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
    if code in {"AccessDeniedException", "UnauthorizedException"}:
        # Denied, but AWS did not say which layer. Treat as IAM and say so.
        return Denial.IAM, resource, None
    return Denial.OTHER, resource, None


class Doctor:
    """Runs the checks. Read-only unless `probe_write` is set."""

    def __init__(self, region: str, session=None, probe_write: bool = False):
        self.region = region
        self.probe_write = probe_write
        self.checks: list[Check] = []
        self._session = session
        self._identity: dict = {}
        self._org: dict | None = None
        self._scps_seen: set[str] = set()

    # --- plumbing ----------------------------------------------------------

    def _client(self, service: str, region: str | None = None):
        if self._session is None:
            import boto3

            self._session = boto3.Session()
        return self._session.client(service, region_name=region or self.region)

    def _add(self, check: Check) -> Check:
        self.checks.append(check)
        return check

    # --- identity and account shape ---------------------------------------

    def check_credentials(self) -> Check:
        try:
            self._identity = self._client("sts").get_caller_identity()
        except Exception as exc:  # noqa: BLE001
            return self._add(Check(
                "credentials", Status.FAIL,
                f"could not resolve AWS credentials: {type(exc).__name__}: {exc}",
                ["aws configure", "  or: aws sso login --profile <your-profile>",
                 "  or: export AWS_PROFILE=<your-profile>"],
            ))
        return self._add(Check(
            "credentials", Status.OK,
            f"account {self._identity['Account']} as {self._identity['Arn'].split('/')[-1]}",
        ))

    def check_account_type(self) -> Check:
        """Standalone or organisation member? This changes what can go wrong."""
        try:
            org = self._client("organizations", region="us-east-1").describe_organization()
            self._org = org["Organization"]
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            if code == "AWSOrganizationsNotInUseException":
                return self._add(Check(
                    "account type", Status.OK,
                    "standalone account — no service control policies apply",
                ))
            # Denied means we are almost certainly in an organisation but cannot
            # read it, which is the normal case for a member account.
            return self._add(Check(
                "account type", Status.WARN,
                "inside an AWS Organization (details not readable from this account). "
                "Service control policies may deny actions your IAM policy allows.",
            ))

        master = self._org.get("MasterAccountId", "")
        mine = self._identity.get("Account", "")
        role = "management account" if master == mine else "member account"
        return self._add(Check(
            "account type", Status.WARN if role == "member account" else Status.OK,
            f"organisation {self._org.get('Id', '?')}, this is the {role} "
            f"(management account {master}). SCPs may apply.",
        ))

    # --- guardrail control plane ------------------------------------------

    def check_guardrail_read(self) -> Check:
        try:
            self._client("bedrock").list_guardrails(maxResults=1)
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            if scp:
                self._scps_seen.add(scp)
            return self._add(Check(
                "bedrock:ListGuardrails", Status.FAIL,
                self._describe(kind, resource, scp, exc),
                self._fix_for(kind, ["bedrock:ListGuardrails"], scp),
            ))
        return self._add(Check("bedrock:ListGuardrails", Status.OK, "guardrails are listable"))

    def check_guardrail_write(self) -> list[Check]:
        """Create, tag, version, then delete a throwaway guardrail.

        Only runs with --probe-write. Everything it creates, it removes.
        """
        if not self.probe_write:
            return [self._add(Check(
                "guardrail lifecycle", Status.SKIP,
                "not probed — pass --probe-write to create and delete a test guardrail",
            ))]

        results: list[Check] = []
        client = self._client("bedrock")
        name = "kilimo-doctor-probe"
        identifier = None

        # A guardrail must carry at least one policy, so the probe uses a word
        # filter: the cheapest policy to configure and the easiest to assert on.
        try:
            created = client.create_guardrail(
                name=name,
                blockedInputMessaging="probe",
                blockedOutputsMessaging="probe",
                wordPolicyConfig={"wordsConfig": [{"text": "kilimodoctorprobe"}]},
                tags=[{"key": "Project", "value": "kilimo-doctor-probe"}],
            )
            identifier = created["guardrailId"]
            results.append(self._add(Check(
                "bedrock:CreateGuardrail (tagged)", Status.OK,
                f"created and tagged {identifier}",
            )))
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            if scp:
                self._scps_seen.add(scp)
            missing = self._missing_actions(exc) or ["bedrock:CreateGuardrail"]
            results.append(self._add(Check(
                "bedrock:CreateGuardrail (tagged)", Status.FAIL,
                self._describe(kind, resource, scp, exc),
                self._fix_for(kind, missing, scp),
            )))
            # Retry untagged: this separates a tagging gap from a create gap, which
            # a single probe cannot distinguish and which V-13 shows matters.
            try:
                created = client.create_guardrail(
                    name=name,
                    blockedInputMessaging="probe",
                    blockedOutputsMessaging="probe",
                    wordPolicyConfig={"wordsConfig": [{"text": "kilimodoctorprobe"}]},
                )
                identifier = created["guardrailId"]
                results.append(self._add(Check(
                    "bedrock:TagResource", Status.FAIL,
                    "creating an untagged guardrail succeeded, so the gap is tagging only. "
                    "Terraform tags every resource it manages, so `terraform apply` fails.",
                    self._fix_for(Denial.IAM, TAG_ACTIONS, None),
                )))
            except Exception:  # noqa: BLE001
                pass

        if identifier:
            results.extend(self._probe_with_guardrail(client, identifier))
            self._cleanup(client, identifier, results)
        return results

    def _probe_with_guardrail(self, client, identifier: str) -> list[Check]:
        results: list[Check] = []

        # Tag read: what Terraform needs to refresh existing state.
        try:
            client.list_tags_for_resource(
                resourceARN=f"arn:aws:bedrock:{self.region}:"
                f"{self._identity['Account']}:guardrail/{identifier}"
            )
            results.append(self._add(Check(
                "bedrock:ListTagsForResource", Status.OK, "tags are readable",
            )))
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            results.append(self._add(Check(
                "bedrock:ListTagsForResource", Status.FAIL,
                "Terraform reads tags when refreshing state, so without this a guardrail "
                "can be created once and never re-planned. "
                    + self._describe(kind, resource, scp, exc),
                self._fix_for(kind, TAG_ACTIONS, scp),
            )))

        # ApplyGuardrail: the only permission the Lab_Path actually needs.
        try:
            response = self._client("bedrock-runtime").apply_guardrail(
                guardrailIdentifier=identifier,
                guardrailVersion="DRAFT",
                source="INPUT",
                content=[{"text": {"text": "contains kilimodoctorprobe here",
                                   "qualifiers": ["guard_content"]}}],
                outputScope="FULL",
            )
            intervened = response.get("action") == "GUARDRAIL_INTERVENED"
            results.append(self._add(Check(
                "bedrock:ApplyGuardrail", Status.OK if intervened else Status.WARN,
                "word filter fired as configured" if intervened
                else "call succeeded but the policy did not fire "
                     f"(action={response.get('action')})",
            )))
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            if scp:
                self._scps_seen.add(scp)
            note = ""
            if "outputScope" in str(exc):
                note = ("This is an SDK version problem, not a permission one: outputScope "
                        "needs boto3 >= 1.37.0; the pinned floor is 1.38.0. ")
            results.append(self._add(Check(
                "bedrock:ApplyGuardrail", Status.FAIL,
                note + self._describe(kind, resource, scp, exc),
                ["pip install 'boto3==1.38.0'"] if note
                else self._fix_for(kind, ["bedrock:ApplyGuardrail"], scp),
            )))

        try:
            version = client.create_guardrail_version(guardrailIdentifier=identifier)
            results.append(self._add(Check(
                "bedrock:CreateGuardrailVersion", Status.OK,
                f"published version {version.get('version')}",
            )))
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            results.append(self._add(Check(
                "bedrock:CreateGuardrailVersion", Status.FAIL,
                self._describe(kind, resource, scp, exc),
                self._fix_for(kind, ["bedrock:CreateGuardrailVersion"], scp),
            )))
        return results

    def _cleanup(self, client, identifier: str, results: list[Check]) -> None:
        try:
            client.delete_guardrail(guardrailIdentifier=identifier)
            results.append(self._add(Check(
                "bedrock:DeleteGuardrail", Status.OK, f"probe {identifier} removed",
            )))
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            results.append(self._add(Check(
                "bedrock:DeleteGuardrail", Status.FAIL,
                f"probe guardrail {identifier} could NOT be removed and is still "
                f"billable. " + self._describe(kind, resource, scp, exc),
                [f"aws bedrock delete-guardrail --guardrail-identifier {identifier} "
                 f"--region {self.region}"] + self._fix_for(kind, ["bedrock:DeleteGuardrail"], scp),
            )))

    def check_guardrail_profile(self) -> Check:
        """Is a guardrail profile available here? The STANDARD tier needs one."""
        geography = GEOGRAPHY.get(self.region)
        if geography is None:
            return self._add(Check(
                "guardrail profile (STANDARD tier)", Status.WARN,
                f"no guardrail profile is documented for {self.region}, so the STANDARD "
                "tier is unavailable. CLASSIC works everywhere Guardrails does, and "
                "covers English, French and Spanish.",
                ["terraform apply -var guardrail_tier=CLASSIC",
                 "",
                 "Region coverage: https://docs.aws.amazon.com/bedrock/latest/"
                 "userguide/guardrails-cross-region-support.html"],
            ))
        return self._add(Check(
            "guardrail profile (STANDARD tier)", Status.OK,
            f"{geography}.guardrail.v1:0 — derived from the Region, no configuration needed",
        ))

    # --- model invocation --------------------------------------------------

    def check_model_access(self) -> list[Check]:
        """Probe every Haiku profile available, and report the Region each routes to.

        A cross-Region profile chooses its own Region, so a call made in eu-west-1
        can be served from eu-north-1 — and denied there. The profile that resolves
        to a single Region is what makes the outcome predictable.
        """
        results: list[Check] = []
        try:
            profiles = self._client("bedrock").list_inference_profiles()
            candidates = [
                p["inferenceProfileId"]
                for p in profiles.get("inferenceProfileSummaries", [])
                if "haiku-4-5" in p["inferenceProfileId"] and p.get("status") == "ACTIVE"
            ]
        except Exception:  # noqa: BLE001
            candidates = []

        if not candidates:
            geography = GEOGRAPHY.get(self.region, "global")
            results.append(self._add(Check(
                "model profiles", Status.WARN,
                f"no ACTIVE Haiku 4.5 inference profile found in {self.region}. The answer "
                "stage needs one; the screen and verify stages do not, so the lab still runs.",
                [f"enable the model: Bedrock console in {self.region} -> Model access",
                 "  -> Anthropic Claude Haiku 4.5",
                 "",
                 "then confirm what is available:",
                 f"  aws bedrock list-inference-profiles --region {self.region}",
                 "",
                 f"for {self.region} the identifier is likely one of:",
                 f"  global.{HAIKU}",
                 f"  {geography}.{HAIKU}"],
            )))
            return results

        single_region = [p for p in candidates if p.startswith("global.")]
        fanning_out = [p for p in candidates if not p.startswith("global.")]
        results.append(self._add(Check(
            "model profiles", Status.OK,
            f"{len(candidates)} ACTIVE: " + ", ".join(sorted(candidates)),
        )))

        # Prefer the single-Region profile: its failure is attributable.
        for profile in single_region + fanning_out:
            check = self._probe_invoke(profile)
            results.append(check)
            if check.status is Status.OK:
                break
        return results

    def _probe_invoke(self, profile: str) -> Check:
        label = f"bedrock:InvokeModel via {profile.split('.')[0]}."
        try:
            self._client("bedrock-runtime").converse(
                modelId=profile,
                messages=[{"role": "user", "content": [{"text": "hi"}]}],
                inferenceConfig={"maxTokens": 5},
            )
            return self._add(Check(label, Status.OK, f"{profile} answered"))
        except Exception as exc:  # noqa: BLE001
            kind, resource, scp = classify_denial(exc)
            if scp:
                self._scps_seen.add(scp)
            routed = self._region_of(resource)
            detail = self._describe(kind, resource, scp, exc)
            if routed and routed != self.region:
                detail += (f" NOTE: the request was routed to {routed}, not {self.region} — "
                           f"this profile fans out across Regions and chose one you did not name.")
            fix = self._fix_for(kind, ["bedrock:InvokeModel"], scp)
            if kind is Denial.SCP:
                fix = [
                    "This is an organisation boundary, not a permission you can grant.",
                    "Ask an administrator of the management account to amend "
                    f"SCP {scp or '(unnamed)'}",
                    "  to allow bedrock:InvokeModel on "
                    f"arn:aws:bedrock:*::foundation-model/{HAIKU}",
                    "",
                    "If that is a deliberate control on generative-model use, the lab still runs:",
                    "  the screen and verify stages need no model at all.",
                ]
            elif routed and routed != self.region:
                fix = [
                    f"Prefer the single-Region profile: global.{HAIKU}",
                    "  A profile that resolves to one Region cannot route into a denied Region.",
                ] + fix
            return self._add(Check(label, Status.FAIL, detail, fix))

    @staticmethod
    def _region_of(arn: str) -> str | None:
        parts = arn.split(":")
        return parts[3] if len(parts) > 4 and parts[3] else None

    # --- deployment prerequisites ------------------------------------------

    def check_deploy_permissions(self) -> Check:
        """Can this principal create the Lambda execution role?

        Only relevant if you intend to deploy the stack; the Lab_Path needs none
        of it. `iam:CreateRole` being denied is what blocked deployed SDK parity
        and deployed latency from ever being measured (validation log V-29), and
        it is a grant an administrator can add — unlike an SCP.

        **This one genuinely creates a role, then deletes it.** Two cheaper probes
        were tried and both fail to answer the question:

        - `CreateRole` with a deliberately invalid path returns `ValidationError`
          *whether or not* the caller is authorised — AWS validates parameters
          before evaluating permissions, so the two are indistinguishable. An
          earlier version of this check reported "authorised" in an account where
          `CreateRole` is denied.
        - `iam:SimulatePrincipalPolicy` rejects an `assumed-role` ARN and needs a
          permission of its own, so it fails for reasons unrelated to the answer.

        The role is trust-policy-only, has no attached policies, can therefore do
        nothing, and is deleted immediately. It is created only under
        `--check-deploy`, never by a default `lab doctor` run.
        """
        name = "kilimo-desk-doctor-probe"
        try:
            iam = self._client("iam")
        except Exception as exc:  # noqa: BLE001
            return self._add(Check("iam for deployment", Status.WARN, str(exc)))

        trust = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        })

        try:
            iam.create_role(
                RoleName=name,
                AssumeRolePolicyDocument=trust,
                Description="Temporary probe created by `lab doctor --check-deploy`.",
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            kind, _resource, scp = classify_denial(exc)

            if "EntityAlreadyExists" in message:
                # A previous probe did not clean up. Authorisation is proven.
                self._cleanup_probe_role(iam, name)
                return self._add(Check(
                    "iam:CreateRole (deployment only)", Status.OK,
                    "authorised — a leftover probe role was found and removed",
                ))

            # Only SCP and IAM are definite denials. Anything else — a
            # ValidationError, a throttle, a service fault — means the probe did
            # not answer the question, and saying so is the only honest option.
            # AWS validates parameters *before* evaluating permissions, so a
            # ValidationError is not evidence of authorisation either way.
            if kind not in (Denial.SCP, Denial.IAM):
                return self._add(Check(
                    "iam:CreateRole (deployment only)", Status.WARN,
                    f"could not determine: {message[:160]}",
                ))

            detail = (
                "cannot create the Lambda execution role, so the deployed stack cannot "
                "be stood up: no role means no Lambda, hence no endpoint, no deployed "
                "SDK-parity probe and no deployed latency (V-29). "
                "The Lab_Path is unaffected — it needs no deployed stack."
            )
            if kind is Denial.SCP:
                return self._add(Check(
                    "iam:CreateRole (deployment only)", Status.FAIL,
                    f"DENIED BY SERVICE CONTROL POLICY {scp or '(unnamed)'}. {detail}",
                    self._fix_for(Denial.SCP, [], scp),
                ))
            return self._add(Check(
                "iam:CreateRole (deployment only)", Status.FAIL, detail,
                self._fix_for(Denial.IAM, _DEPLOY_ACTIONS, None),
            ))

        removed = self._cleanup_probe_role(iam, name)
        note = "created and deleted a probe role" if removed else (
            f"created a probe role but could NOT delete it — remove {name} by hand"
        )
        return self._add(Check(
            "iam:CreateRole (deployment only)",
            Status.OK if removed else Status.WARN,
            f"authorised — {note}",
        ))

    @staticmethod
    def _cleanup_probe_role(iam, name: str) -> bool:
        """Remove the probe role, reporting whether it is actually gone."""
        with contextlib.suppress(Exception):
            iam.delete_role(RoleName=name)
        try:
            iam.get_role(RoleName=name)
        except Exception as exc:  # noqa: BLE001
            return "NoSuchEntity" in str(exc)
        return False



    def check_sdk(self) -> Check:
        """Both Bedrock fields this project reads, checked against the service model.

        One is a request field and fails loudly; the other is a response field and
        fails silently. The silent one is the reason this check exists at all — an
        SDK that drops `tier` reports a measurement under the wrong tier and
        nothing raises (V-24).
        """
        try:
            import boto3
            import botocore
            import botocore.session

            session = botocore.session.get_session()
            version = f"boto3 {boto3.__version__} / botocore {botocore.__version__}"

            runtime = session.get_service_model("bedrock-runtime")
            if "outputScope" not in runtime.operation_model("ApplyGuardrail").input_shape.members:
                return self._add(Check(
                    "boto3 carries the fields this project uses", Status.FAIL,
                    f"{version} does not carry `outputScope` on the ApplyGuardrail "
                    "request. Both pipeline stages pass it, so every call fails before "
                    "reaching AWS with a ParamValidationError (V-14).",
                    ["pip install 'boto3==1.38.0'"],
                ))

            control = session.get_service_model("bedrock")
            topic = control.operation_model("GetGuardrail").output_shape.members.get(
                "topicPolicy"
            )
            if topic is not None and "tier" not in topic.members:
                return self._add(Check(
                    "boto3 carries the fields this project uses", Status.WARN,
                    f"{version} does not carry `tier` on the GetGuardrail response. AWS "
                    "sends it; botocore drops unmodelled members silently, so the tier "
                    "reads as absent and a measurement can be filed under the wrong "
                    "tier with nothing raised (V-24).",
                    ["pip install 'boto3==1.38.0'"],
                ))

            return self._add(Check(
                "boto3 carries the fields this project uses", Status.OK,
                f"{version} — `outputScope` on the request, `tier` on the response",
            ))
        except ImportError as exc:
            return self._add(Check("boto3 installed", Status.FAIL, str(exc),
                                   ["pip install -r backend/requirements.txt"]))

    # --- reporting ---------------------------------------------------------

    def _describe(self, kind: Denial, resource: str, scp: str | None, exc: Exception) -> str:
        if kind is Denial.SCP:
            return (f"DENIED BY SERVICE CONTROL POLICY {scp or '(unnamed)'} "
                    f"on {resource or 'the resource'}. "
                    "An SCP is a ceiling no identity policy can raise.")
        if kind is Denial.IAM:
            return f"no identity-based policy allows it (resource: {resource or 'n/a'})"
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        return f"{code}: {str(exc)[:180]}"

    @staticmethod
    def _missing_actions(exc: Exception) -> list[str]:
        return re.findall(r"not authorized to perform:\s*(\S+)", str(exc))

    def _fix_for(self, kind: Denial, actions: list[str], scp: str | None) -> list[str]:
        if kind is Denial.SCP:
            return [
                f"SCP {scp or '(unnamed)'} denies this. Only an administrator of the",
                "organisation's management account can amend it. Adding IAM permissions",
                "will NOT help — an SCP is a boundary above identity policy.",
            ]
        statement = {
            "Version": "2012-10-17",
            "Statement": [{"Sid": "KilimoDeskGuardrail", "Effect": "Allow",
                           "Action": actions, "Resource": "*"}],
        }
        return ["attach this to your role, user, or SSO permission set:",
                *json.dumps(statement, indent=2).splitlines()]


def run(region: str, session=None, probe_write: bool = False,
        check_deploy: bool = False) -> int:
    doctor = Doctor(region, session=session, probe_write=probe_write)

    print(f"checking AWS prerequisites in {region}\n")

    credentials = doctor.check_credentials()
    if credentials.blocking:
        _report(doctor)
        return 1

    doctor.check_account_type()
    doctor.check_sdk()
    doctor.check_guardrail_profile()
    if not doctor.check_guardrail_read().blocking:
        doctor.check_guardrail_write()
    doctor.check_model_access()
    # Opt-in: the Lab_Path needs no deployed stack, so reporting a deployment
    # permission as a failure by default would tell a lab user something is
    # wrong when nothing is.
    if check_deploy:
        doctor.check_deploy_permissions()

    return _report(doctor)


_MARK = {
    Status.OK: "  ok  ",
    Status.FAIL: " FAIL ",
    Status.WARN: " warn ",
    Status.SKIP: " skip ",
    Status.UNKNOWN: "  ??  ",
}


def _report(doctor: Doctor) -> int:
    for check in doctor.checks:
        print(f"[{_MARK[check.status]}] {check.name}")
        if check.detail:
            print(f"           {check.detail}")
        if check.fix:
            print()
            for line in check.fix:
                print(f"           {line}")
            print()

    failed = [c for c in doctor.checks if c.status is Status.FAIL]
    scp_failures = [c for c in failed if "SERVICE CONTROL POLICY" in c.detail]

    print()
    print(f"{len(doctor.checks)} checks · "
          f"{sum(c.status is Status.OK for c in doctor.checks)} ok · "
          f"{len(failed)} failed · "
          f"{sum(c.status is Status.WARN for c in doctor.checks)} warnings · "
          f"{sum(c.status is Status.SKIP for c in doctor.checks)} skipped")

    if not failed:
        print("\nEverything the lab and the deployed demo need is in place.")
        return 0

    guardrail_ok = all(
        c.status is not Status.FAIL
        for c in doctor.checks
        if c.name.startswith("bedrock:") and "InvokeModel" not in c.name
    )
    model_failed = any("InvokeModel" in c.name for c in failed)

    if guardrail_ok and model_failed:
        print("\nThe guardrail permissions are in place; only model invocation is denied.")
        print("The Lab_Path is unaffected — it calls ApplyGuardrail and never invokes a model.")
        print("The deployed demo's answer stage will fall back to a canned response.")

    if scp_failures:
        print("\nAt least one failure is an organisation SCP, which no IAM change can fix.")
        print("The ask for your administrator is printed above.")

    # An unproven conclusion is worse than none: say what is still unknown.
    iam_gaps = [c for c in doctor.checks
                if c.status is Status.FAIL and "no identity-based policy" in c.detail]
    if iam_gaps:
        print("\nNOTE: an absent IAM grant hides any SCP deny behind it. Once the IAM")
        print("permissions above are added, run this again — a further SCP block may appear.")

    return 1
