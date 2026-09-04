# Packaging and the API Lambda.
#
# The build step runs from Terraform so `terraform apply` is self-contained. The
# archive_file data source has depends_on, which defers it to apply time — that
# is what lets Terraform zip a directory the same apply just created.

locals {
  build_dir = "${path.module}/../backend/build"

  # Any change to source, dependencies or the scenario triggers a rebuild.
  # fileset() has no brace expansion, so the patterns are listed separately.
  backend_files = sort(concat(
    tolist(fileset("${path.module}/../backend", "app/**/*.py")),
    tolist(fileset("${path.module}/../backend", "lambda_handler.py")),
    tolist(fileset("${path.module}/../backend", "requirements.txt")),
  ))
  source_hash = sha256(join("", [
    for f in local.backend_files : filesha256("${path.module}/../backend/${f}")
  ]))
  scenario_hash = filesha256("${path.module}/../shared/scenario.json")
}

resource "null_resource" "build_backend" {
  triggers = {
    source   = local.source_hash
    scenario = local.scenario_hash
  }

  provisioner "local-exec" {
    command     = "bash ${path.module}/../scripts/package-backend.sh"
    working_dir = path.module
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = local.build_dir
  output_path = "${path.module}/../backend/dist/lambda.zip"

  depends_on = [null_resource.build_backend]
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name}-api"
  description   = "Kilimo Desk guardrail pipeline (FastAPI via Mangum)"
  role          = aws_iam_role.lambda.arn
  handler       = "lambda_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds

  environment {
    variables = {
      # AWS_REGION is reserved — Lambda sets it to the function's own Region, and
      # pydantic-settings picks it up as `aws_region`. Setting it here is rejected.
      BEDROCK_MODEL_ID = var.bedrock_model_id

      GUARDRAIL_ID = aws_bedrock_guardrail.main.guardrail_id
      # Pin the published version when there is one; DRAFT keeps moving.
      GUARDRAIL_VERSION = var.publish_guardrail_version ? aws_bedrock_guardrail_version.main[0].version : "DRAFT"
      GUARDRAIL_ENABLED = "true"

      # The tier the application reports and, under Replay_Mode, the tier whose
      # fixtures it prefers. config.py defaults this to CLASSIC and its comment
      # claimed Terraform set it — which nothing did, so a STANDARD deployment
      # (the default) described itself as CLASSIC. That is the V-24 mislabelling
      # from the other direction.
      GUARDRAIL_TIER = var.guardrail_tier

      CORS_ALLOW_ORIGINS = join(",", local.cors_origins)
      LOG_LEVEL          = "INFO"
      SCENARIO_PATH      = "/var/task/scenario.json"
    }
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic,
    aws_cloudwatch_log_group.lambda,
  ]
}
