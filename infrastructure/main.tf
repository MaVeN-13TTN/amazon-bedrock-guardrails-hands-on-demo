locals {
  scenario = jsondecode(file("${path.module}/../shared/scenario.json"))
  name     = var.project

  tags = merge({
    Project   = var.project
    ManagedBy = "terraform"
    Demo      = "bedrock-guardrails"
  }, var.tags)

  # Amplify serves a branch at https://<branch>.<app-id>.amplifyapp.com
  amplify_branch = "main"
  amplify_url    = "https://${local.amplify_branch}.${aws_amplify_app.frontend.id}.amplifyapp.com"

  cors_origins = distinct(concat(
    ["http://localhost:3000", local.amplify_url],
    var.extra_cors_origins,
  ))
}

data "aws_caller_identity" "current" {}
