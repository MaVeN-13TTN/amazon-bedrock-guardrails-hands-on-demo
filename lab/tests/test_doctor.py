"""The prerequisite doctor.

The tests that matter most here are the ones about *classification*: telling an
organisation SCP deny apart from a missing IAM grant. Getting that wrong cost a
validation session several hours (see docs/validation-log.md V-09 to V-12), so the
distinction is pinned by example rather than left to inspection.
"""
from __future__ import annotations

from botocore.exceptions import ClientError

from lab.doctor import Denial, Doctor, Status, classify_denial

SCP_MESSAGE = (
    "An error occurred (AccessDeniedException) when calling the Converse operation: "
    "User: arn:aws:sts::111122223333:assumed-role/Dev/user is not authorized to perform: "
    "bedrock:InvokeModel on resource: "
    "arn:aws:bedrock:eu-north-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0 "
    "with an explicit deny in a service control policy: "
    "arn:aws:organizations::444455556666:policy/o-exampleorgid/service_control_policy/p-examplescpid"
)

IAM_MESSAGE = (
    "An error occurred (AccessDeniedException) when calling the CreateGuardrail operation: "
    "User: arn:aws:sts::111122223333:assumed-role/Dev/user is not authorized to perform: "
    "bedrock:TagResource on resource: arn:aws:bedrock:eu-west-1:111122223333:guardrail/* "
    "because no identity-based policy allows the bedrock:TagResource action"
)


def _error(message: str, code: str = "AccessDeniedException") -> ClientError:
    exc = ClientError({"Error": {"Code": code, "Message": message}}, "Probe")
    # botocore builds its own string; override so the fixture text is what is parsed.
    exc.args = (message,)
    return exc


# --- the distinction that matters ------------------------------------------

def test_an_scp_deny_is_classified_as_an_organisation_boundary():
    kind, resource, scp = classify_denial(_error(SCP_MESSAGE))
    assert kind is Denial.SCP
    assert scp.endswith("p-examplescpid")
    assert "eu-north-1" in resource


def test_a_missing_grant_is_classified_as_iam():
    kind, resource, scp = classify_denial(_error(IAM_MESSAGE))
    assert kind is Denial.IAM
    assert scp is None
    assert "guardrail/*" in resource


def test_a_validation_error_is_neither():
    """Authorised but malformed. Reporting this as a permission problem would send
    an attendee to their administrator for a bug in their own request."""
    kind, _, _ = classify_denial(
        _error("Guardrail must have at least one policy.", code="ValidationException")
    )
    assert kind is Denial.OTHER


def test_an_unexplained_denial_defaults_to_iam():
    kind, _, scp = classify_denial(_error("Access denied.", code="AccessDeniedException"))
    assert kind is Denial.IAM
    assert scp is None


def test_the_routed_region_is_extracted_from_the_resource_arn():
    """A fan-out profile picks its own Region, and the ARN is the only place it shows."""
    _, resource, _ = classify_denial(_error(SCP_MESSAGE))
    assert Doctor._region_of(resource) == "eu-north-1"


# --- account shape ---------------------------------------------------------

class _Session:
    def __init__(self, **clients):
        self._clients = clients

    def client(self, service, region_name=None):
        if service not in self._clients:
            raise AssertionError(f"unexpected client requested: {service}")
        return self._clients[service]


class _Sts:
    def __init__(self, account="111122223333"):
        self.account = account

    def get_caller_identity(self):
        return {"Account": self.account, "Arn": f"arn:aws:sts::{self.account}:assumed-role/Dev/u"}


def test_a_standalone_account_reports_no_scps():
    class _Orgs:
        def describe_organization(self):
            raise _error("not in use", code="AWSOrganizationsNotInUseException")

    doctor = Doctor("eu-west-1", session=_Session(sts=_Sts(), organizations=_Orgs()))
    doctor.check_credentials()
    check = doctor.check_account_type()

    assert check.status is Status.OK
    assert "standalone" in check.detail
    assert "no service control policies" in check.detail


def test_a_member_account_warns_that_scps_may_apply():
    class _Orgs:
        def describe_organization(self):
            return {"Organization": {"Id": "o-abc", "MasterAccountId": "999999999999"}}

    doctor = Doctor("eu-west-1", session=_Session(sts=_Sts(), organizations=_Orgs()))
    doctor.check_credentials()
    check = doctor.check_account_type()

    assert check.status is Status.WARN
    assert "member account" in check.detail
    assert "999999999999" in check.detail


def test_an_unreadable_organisation_still_warns():
    """A member account usually cannot read its own organisation. Absence of
    evidence is not evidence of absence."""
    class _Orgs:
        def describe_organization(self):
            raise _error("denied", code="AccessDeniedException")

    doctor = Doctor("eu-west-1", session=_Session(sts=_Sts(), organizations=_Orgs()))
    doctor.check_credentials()
    check = doctor.check_account_type()

    assert check.status is Status.WARN
    assert "may deny" in check.detail


def test_missing_credentials_block_everything_else():
    class _BadSts:
        def get_caller_identity(self):
            raise _error("expired", code="ExpiredToken")

    doctor = Doctor("eu-west-1", session=_Session(sts=_BadSts()))
    check = doctor.check_credentials()

    assert check.blocking
    assert any("sso login" in line for line in check.fix)


# --- guidance quality ------------------------------------------------------

def test_an_scp_failure_does_not_suggest_an_iam_policy():
    """The worst possible advice here is a policy document: it cannot work, and it
    sends the reader to the wrong administrator."""
    doctor = Doctor("eu-west-1")
    fix = doctor._fix_for(Denial.SCP, ["bedrock:InvokeModel"], "p-examplescpid")
    joined = "\n".join(fix)

    assert "management account" in joined
    assert "will NOT help" in joined
    assert '"Effect": "Allow"' not in joined


def test_an_iam_failure_suggests_a_pastable_policy():
    import json

    doctor = Doctor("eu-west-1")
    fix = doctor._fix_for(Denial.IAM, ["bedrock:TagResource"], None)
    document = json.loads("\n".join(line for line in fix if not line.startswith("attach")))

    assert document["Statement"][0]["Action"] == ["bedrock:TagResource"]
    assert document["Statement"][0]["Effect"] == "Allow"


def test_the_missing_actions_are_read_from_the_aws_message():
    """AWS names the action it refused; echoing it back beats guessing."""
    assert Doctor._missing_actions(_error(IAM_MESSAGE)) == ["bedrock:TagResource"]


# --- SDK -------------------------------------------------------------------

def test_the_sdk_check_catches_an_outputscope_gap():
    """boto3 < 1.37.0 rejects outputScope before reaching AWS, which reads like a
    permission problem but is not one."""
    doctor = Doctor("eu-west-1")
    check = doctor.check_sdk()

    assert check.status is Status.OK, "the pinned boto3 should support outputScope"
    assert "boto3" in check.detail


# --- Region portability ----------------------------------------------------

def test_every_documented_geography_is_known():
    """The lab must work wherever it is cloned, not only in eu-west-1."""
    from lab.doctor import GEOGRAPHY

    assert GEOGRAPHY["us-east-1"] == "us"
    assert GEOGRAPHY["eu-west-1"] == "eu"
    assert GEOGRAPHY["eu-west-2"] == "uk"          # UK is its own geography
    assert GEOGRAPHY["ap-southeast-2"] == "au"     # AU, not APAC
    assert GEOGRAPHY["ca-central-1"] == "ca"
    assert GEOGRAPHY["ap-south-1"] == "apac"
    assert GEOGRAPHY["us-gov-west-1"] == "us-gov"


def test_a_region_with_a_profile_reports_it_without_configuration():
    doctor = Doctor("ap-southeast-2")
    check = doctor.check_guardrail_profile()

    assert check.status is Status.OK
    assert "au.guardrail.v1:0" in check.detail
    assert "no configuration needed" in check.detail


def test_a_region_without_a_profile_recommends_the_classic_tier():
    """CLASSIC needs no profile, so an unsupported Region is a warning not a wall."""
    doctor = Doctor("sa-east-1")
    check = doctor.check_guardrail_profile()

    assert check.status is Status.WARN
    assert "CLASSIC" in check.detail
    assert any("guardrail_tier=CLASSIC" in line for line in check.fix)


# --- deployment permissions (opt-in) ----------------------------------------


class _FakeIam:
    """An iam stand-in. `denial` is raised by create_role when given."""

    def __init__(self, denial: Exception | None = None, delete_fails: bool = False):
        self.denial = denial
        self.delete_fails = delete_fails
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.existing: set[str] = set()

    def create_role(self, **kw):
        if self.denial is not None:
            raise self.denial
        self.created.append(kw["RoleName"])
        self.existing.add(kw["RoleName"])
        return {"Role": {"Arn": f"arn:aws:iam::1:role/{kw['RoleName']}"}}

    def delete_role(self, RoleName):  # noqa: N803 — boto3's parameter name
        if self.delete_fails:
            raise ClientError(
                {"Error": {"Code": "DeleteConflict", "Message": "in use"}}, "DeleteRole"
            )
        self.deleted.append(RoleName)
        self.existing.discard(RoleName)

    def get_role(self, RoleName):  # noqa: N803
        if RoleName in self.existing:
            return {"Role": {"RoleName": RoleName}}
        raise ClientError(
            {"Error": {"Code": "NoSuchEntity", "Message": "not found"}}, "GetRole"
        )


def _doctor_with_iam(fake) -> Doctor:
    d = Doctor("eu-west-1")
    d._client = lambda service, region=None: fake  # noqa: SLF001 — test seam
    return d


def test_the_deploy_check_is_not_run_by_default():
    """The Lab_Path needs no deployment permission, so a default run must not
    report one as a failure — and must not create a role either."""
    import inspect

    from lab.doctor import run

    source = inspect.getsource(run)
    assert "if check_deploy:" in source
    assert inspect.signature(run).parameters["check_deploy"].default is False


def test_an_authorised_principal_passes_and_the_probe_role_is_deleted():
    fake = _FakeIam()
    check = _doctor_with_iam(fake).check_deploy_permissions()

    assert check.status is Status.OK
    assert fake.created == ["kilimo-desk-doctor-probe"]
    assert fake.deleted == ["kilimo-desk-doctor-probe"]
    assert fake.existing == set()


def test_a_probe_role_that_cannot_be_deleted_is_reported_as_a_warning():
    """Leaving a role behind silently would be worse than saying so."""
    fake = _FakeIam(delete_fails=True)
    check = _doctor_with_iam(fake).check_deploy_permissions()

    assert check.status is Status.WARN
    assert "could NOT delete" in check.detail
    assert "kilimo-desk-doctor-probe" in check.detail


def test_an_iam_denial_fails_and_prints_a_pastable_policy():
    denial = ClientError(
        {"Error": {"Code": "AccessDenied", "Message":
                   "User: arn:aws:sts::1:assumed-role/dev/me is not authorized to "
                   "perform: iam:CreateRole on resource: arn:aws:iam::1:role/x because "
                   "no identity-based policy allows the iam:CreateRole action"}},
        "CreateRole",
    )
    check = _doctor_with_iam(_FakeIam(denial=denial)).check_deploy_permissions()

    assert check.status is Status.FAIL
    assert "V-29" in check.detail
    assert "Lab_Path is unaffected" in check.detail
    joined = "\n".join(check.fix)
    assert "iam:CreateRole" in joined and "iam:PassRole" in joined


def test_an_scp_denial_says_iam_cannot_fix_it():
    denial = ClientError(
        {"Error": {"Code": "AccessDenied", "Message":
                   "User: arn:aws:sts::1:assumed-role/dev/me is not authorized to "
                   "perform: iam:CreateRole with an explicit deny in a service control "
                   "policy: p-abc123"}},
        "CreateRole",
    )
    check = _doctor_with_iam(_FakeIam(denial=denial)).check_deploy_permissions()

    assert check.status is Status.FAIL
    assert "SERVICE CONTROL POLICY" in check.detail
    assert "p-abc123" in check.detail
    assert any("will NOT help" in line for line in check.fix)


def test_a_leftover_probe_role_still_proves_authorisation():
    denial = ClientError(
        {"Error": {"Code": "EntityAlreadyExists", "Message": "already exists"}},
        "CreateRole",
    )
    fake = _FakeIam(denial=denial)
    fake.existing.add("kilimo-desk-doctor-probe")
    check = _doctor_with_iam(fake).check_deploy_permissions()

    assert check.status is Status.OK
    assert "leftover" in check.detail
    assert fake.existing == set()


def test_an_unrecognised_error_is_a_warning_not_a_false_pass():
    """A probe that cannot answer must say so rather than guess either way.

    An earlier version of this check matched "validation" in the error text and
    reported OK — in an account where iam:CreateRole is denied. AWS validates
    parameters before evaluating permissions, so a ValidationError proves nothing.
    """
    denial = ClientError(
        {"Error": {"Code": "ValidationError", "Message":
                   "The specified value for path is invalid."}},
        "CreateRole",
    )
    check = _doctor_with_iam(_FakeIam(denial=denial)).check_deploy_permissions()

    assert check.status is Status.WARN
    assert "could not determine" in check.detail
