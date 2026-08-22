# Execution role for the API Lambda. Scoped to the one guardrail and the one model
# this demo uses, rather than AmazonBedrockFullAccess.
#
# Every ARN is derived from var.aws_region and var.bedrock_model_id (see
# regions.tf), so this file needs no editing to work in another Region or with a
# different model.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

data "aws_iam_policy_document" "bedrock" {
  # --- stages 1 and 3: ApplyGuardrail, no model ---------------------------
  #
  # Permitted on the guardrail itself and, when a guardrail profile is in use, on
  # the profile object in every destination Region it can route to. Missing a
  # destination produces an AccessDeniedException naming a Region the caller never
  # asked for. Documented under "Permissions for invoking guardrails with
  # cross-Region inference".
  statement {
    sid       = "ApplyGuardrail"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = concat([aws_bedrock_guardrail.main.guardrail_arn], local.guardrail_profile_arns)
  }

  # Reading the guardrail's own configuration. The SDK does this to resolve DRAFT
  # to the current policy set.
  statement {
    sid       = "ReadGuardrail"
    effect    = "Allow"
    actions   = ["bedrock:GetGuardrail"]
    resources = [aws_bedrock_guardrail.main.guardrail_arn]
  }

  # --- stage 2: InvokeModel ------------------------------------------------
  #
  # Three shapes, because the three kinds of model identifier need different IAM.
  # Only the statements matching the configured identifier are emitted.

  # A `global.` profile keeps inference in the requesting Region but routes the
  # foundation-model call through a Region-less ARN. AWS documents a three-part
  # policy for this and states that all three are required: remove one and the
  # call is denied. See "IAM policy requirements for global cross-Region inference".
  dynamic "statement" {
    for_each = local.is_global_profile ? [1] : []
    content {
      sid       = "GlobalProfileInferenceProfile"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel"]
      resources = ["arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.bedrock_model_id}"]

      condition {
        test     = "StringEquals"
        variable = "aws:RequestedRegion"
        values   = [var.aws_region]
      }
    }
  }

  dynamic "statement" {
    for_each = local.is_global_profile ? [1] : []
    content {
      sid       = "GlobalProfileRegionalModel"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel"]
      resources = ["arn:${local.partition}:bedrock:${var.aws_region}::foundation-model/${local.model_name}"]

      condition {
        test     = "StringEquals"
        variable = "aws:RequestedRegion"
        values   = [var.aws_region]
      }
      condition {
        test     = "StringEquals"
        variable = "bedrock:InferenceProfileArn"
        values   = ["arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.bedrock_model_id}"]
      }
    }
  }

  # The Region-less foundation-model ARN, which is what enables the cross-Region
  # routing. `aws:RequestedRegion` is literally "unspecified" for this call — not
  # the destination Region — which is why an SCP written against Region names does
  # not match it.
  dynamic "statement" {
    for_each = local.is_global_profile ? [1] : []
    content {
      sid       = "GlobalProfileGlobalModel"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel"]
      resources = ["arn:${local.partition}:bedrock:::foundation-model/${local.model_name}"]

      condition {
        test     = "StringEquals"
        variable = "aws:RequestedRegion"
        values   = ["unspecified"]
      }
      condition {
        test     = "StringEquals"
        variable = "bedrock:InferenceProfileArn"
        values   = ["arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.bedrock_model_id}"]
      }
    }
  }

  # A geographic profile (`us.`, `eu.`, `apac.`, …) fans out across the Regions of
  # its geography and chooses one per request. The foundation-model ARN therefore
  # carries a wildcard Region: pinning it to the source Region breaks on the first
  # request AWS routes elsewhere.
  dynamic "statement" {
    for_each = local.is_geo_profile ? [1] : []
    content {
      sid     = "GeographicProfileInvokeModel"
      effect  = "Allow"
      actions = ["bedrock:InvokeModel"]
      resources = [
        "arn:${local.partition}:bedrock:*::foundation-model/${local.model_name}",
        "arn:${local.partition}:bedrock:${var.aws_region}:${local.account_id}:inference-profile/${var.bedrock_model_id}",
      ]
    }
  }

  # A bare model id, for Regions and models that still serve on-demand without a
  # profile. Current Claude models do not; see ADR decision 10.
  dynamic "statement" {
    for_each = local.is_bare_model ? [1] : []
    content {
      sid       = "BareModelInvokeModel"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel"]
      resources = ["arn:${local.partition}:bedrock:${var.aws_region}::foundation-model/${local.model_name}"]
    }
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "${local.name}-bedrock"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.bedrock.json
}
