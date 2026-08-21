# Execution role for the API Lambda. Scoped to the one guardrail and the one
# model this demo uses, rather than AmazonBedrockFullAccess.

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
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

locals {
  # A cross-Region inference profile fans out to foundation models in sibling
  # Regions, so InvokeModel has to be permitted on the profile *and* on the
  # underlying foundation models. Foundation-model ARNs carry no account id.
  model_suffix = replace(var.bedrock_model_id, "/^(eu|us|apac|global)\\./", "")

  bedrock_invoke_resources = distinct([
    "arn:aws:bedrock:*::foundation-model/${local.model_suffix}",
    "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}",
  ])
}

data "aws_iam_policy_document" "bedrock" {
  # Invoking the model, including through the cross-Region inference profile.
  statement {
    sid       = "InvokeModel"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = local.bedrock_invoke_resources
  }

  # Stages 1 and 3 call ApplyGuardrail directly; stage 2 applies the guardrail
  # as part of Converse. Both need this on the guardrail resource.
  statement {
    sid    = "ApplyGuardrail"
    effect = "Allow"
    actions = [
      "bedrock:ApplyGuardrail",
    ]
    resources = [aws_bedrock_guardrail.main.guardrail_arn]
  }

  # Reading the guardrail's own configuration (the console and SDK do this to
  # resolve DRAFT to the current policy).
  statement {
    sid       = "ReadGuardrail"
    effect    = "Allow"
    actions   = ["bedrock:GetGuardrail"]
    resources = [aws_bedrock_guardrail.main.guardrail_arn]
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "${local.name}-bedrock"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.bedrock.json
}
