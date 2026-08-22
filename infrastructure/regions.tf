# Region portability.
#
# The demo is written for eu-west-1 but must apply cleanly in any Region where
# Bedrock Guardrails is available, because it is cloned by people who are not in
# Ireland. Everything Region-specific is derived here from `var.aws_region` rather
# than hard-coded, so an attendee changes one variable and nothing else.
#
# Sources, all from the Amazon Bedrock User Guide:
#   guardrails-cross-region-support.html  guardrail profile ids and destinations
#   guardrail-profiles-permissions.html   IAM for cross-Region guardrail inference
#   global-cross-region-inference.html    the three-part policy global. profiles need

locals {
  # Guardrail profile per geography, keyed by source Region. Required by the
  # STANDARD tier, which is what enables ~60 languages and detection inside code.
  #
  # The value is the profile ID; the ARN is assembled below. AWS documents both as
  # acceptable, but the Terraform provider validates this argument as an ARN, so
  # the ARN form is what gets used (see ADR decision 9, amendment 2026-08-22).
  guardrail_profile_by_region = {
    # US
    "us-east-1" = "us.guardrail.v1:0"
    "us-east-2" = "us.guardrail.v1:0"
    "us-west-1" = "us.guardrail.v1:0"
    "us-west-2" = "us.guardrail.v1:0"
    # EU
    "eu-central-1" = "eu.guardrail.v1:0"
    "eu-west-1"    = "eu.guardrail.v1:0"
    "eu-west-3"    = "eu.guardrail.v1:0"
    "eu-north-1"   = "eu.guardrail.v1:0"
    "eu-south-1"   = "eu.guardrail.v1:0"
    "eu-south-2"   = "eu.guardrail.v1:0"
    "il-central-1" = "eu.guardrail.v1:0"
    # UK — a single-Region geography
    "eu-west-2" = "uk.guardrail.v1:0"
    # Canada
    "ca-central-1" = "ca.guardrail.v1:0"
    # APAC
    "ap-south-1"     = "apac.guardrail.v1:0"
    "ap-northeast-1" = "apac.guardrail.v1:0"
    "ap-northeast-2" = "apac.guardrail.v1:0"
    "ap-southeast-1" = "apac.guardrail.v1:0"
    "ap-southeast-3" = "apac.guardrail.v1:0"
    "ap-southeast-4" = "apac.guardrail.v1:0"
    "ap-southeast-5" = "apac.guardrail.v1:0"
    "ap-southeast-7" = "apac.guardrail.v1:0"
    "ap-east-2"      = "apac.guardrail.v1:0"
    "me-central-1"   = "apac.guardrail.v1:0"
    # Australia — a single-Region geography. ap-southeast-2 appears in both the
    # AU and APAC tables; AU is the narrower choice and is preferred.
    "ap-southeast-2" = "au.guardrail.v1:0"
  }

  # Every Region a guardrail profile may route to. `bedrock:ApplyGuardrail` has to
  # be permitted on the profile object in each destination, not only the source —
  # a detail that produces an AccessDeniedException naming a Region you never
  # asked for. Documented under "Permissions for invoking guardrails with
  # cross-Region inference".
  guardrail_destinations_by_profile = {
    "us.guardrail.v1:0" = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]
    "eu.guardrail.v1:0" = ["eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1",
    "eu-south-1", "eu-south-2", "il-central-1"]
    "uk.guardrail.v1:0" = ["eu-west-2"]
    "ca.guardrail.v1:0" = ["ca-central-1", "ca-west-1"]
    "au.guardrail.v1:0" = ["ap-southeast-2"]
    "apac.guardrail.v1:0" = ["ap-south-1", "ap-south-2", "ap-northeast-1", "ap-northeast-2",
      "ap-northeast-3", "ap-southeast-1", "ap-southeast-2", "ap-southeast-3",
    "ap-southeast-4", "ap-southeast-5", "ap-southeast-7", "ap-east-2", "me-central-1"]
  }

  # ARN partition. GovCloud and China use their own, and an ARN built with the
  # wrong partition is rejected rather than merely unauthorised.
  partition = (
    startswith(var.aws_region, "us-gov-") ? "aws-us-gov" :
    startswith(var.aws_region, "cn-") ? "aws-cn" : "aws"
  )

  account_id = data.aws_caller_identity.current.account_id

  # Resolved profile for the Region being applied to. Empty when the Region has no
  # guardrail profile, which the STANDARD-tier precondition below turns into a
  # readable error rather than an AWS rejection.
  guardrail_profile_id = (
    var.guardrail_profile_id != "" ? var.guardrail_profile_id
    : lookup(local.guardrail_profile_by_region, var.aws_region, "")
  )

  guardrail_profile_arn = (
    local.guardrail_profile_id == "" ? ""
    : "arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:guardrail-profile/${local.guardrail_profile_id}"
  )

  guardrail_profile_destinations = lookup(
    local.guardrail_destinations_by_profile, local.guardrail_profile_id, [var.aws_region]
  )

  # Every Region the guardrail profile can route to, as profile ARNs. ApplyGuardrail
  # must be allowed on all of them.
  guardrail_profile_arns = local.guardrail_profile_id == "" ? [] : [
    for region in local.guardrail_profile_destinations :
    "arn:${local.partition}:bedrock:${region}:${local.account_id}:guardrail-profile/${local.guardrail_profile_id}"
  ]

  # --- model identity ------------------------------------------------------

  # The model id with any inference-profile prefix removed, giving the bare
  # foundation-model name the ARNs need.
  model_name = replace(var.bedrock_model_id, "/^(us|eu|uk|ca|au|apac|us-gov|global)\\./", "")

  # Which kind of identifier was supplied? Each needs different IAM.
  is_global_profile = startswith(var.bedrock_model_id, "global.")
  is_geo_profile    = can(regex("^(us|eu|uk|ca|au|apac|us-gov)\\.", var.bedrock_model_id))
  is_bare_model     = !local.is_global_profile && !local.is_geo_profile
}

# A guardrail profile is only needed by the STANDARD tier. Failing here beats
# failing inside the provider with "Invalid ARN Value", which says nothing about
# what to do next.
resource "null_resource" "guardrail_profile_precondition" {
  count = var.guardrail_tier == "STANDARD" ? 1 : 0

  lifecycle {
    precondition {
      condition     = local.guardrail_profile_id != ""
      error_message = <<-EOT
        No guardrail profile is available for ${var.aws_region}, which the STANDARD
        tier requires.

        Either apply with the CLASSIC tier, which needs no profile:
            terraform apply -var guardrail_tier=CLASSIC

        or set the profile id explicitly if AWS has since added one:
            terraform apply -var guardrail_profile_id=<geo>.guardrail.v1:0

        Region-to-profile coverage is listed at
        https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html
      EOT
    }
  }
}
