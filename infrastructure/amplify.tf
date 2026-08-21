# Amplify Hosting for the Next.js frontend.
#
# The app is a static export (see ADR.md decision 4), so Amplify acts as a CDN
# with no SSR compute. Two ways in:
#
#   default        no repository — deploy the built bundle with
#                  scripts/deploy-frontend.sh (no Git token needed)
#   repo connected set amplify_repository_url + amplify_access_token for CI builds

resource "aws_amplify_app" "frontend" {
  name        = "${local.name}-frontend"
  description = "Kilimo Desk — Bedrock Guardrails demo frontend"
  platform    = "WEB"

  repository   = var.amplify_repository_url != "" ? var.amplify_repository_url : null
  access_token = var.amplify_access_token != "" ? var.amplify_access_token : null

  # Only meaningful for repo-connected builds; harmless otherwise.
  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: frontend
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: out
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
  YAML

  # NEXT_PUBLIC_API_BASE_URL is set on the branch, not here. The API's CORS list
  # needs this app's id to build the Amplify origin, so referencing the API stage
  # from the app itself would be a dependency cycle. The branch is downstream of
  # both and can safely see the stage URL.

  # A static export has no server-side router, so unknown paths must fall back to
  # the shell rather than returning Amplify's 404.
  custom_rule {
    source = "/<*>"
    target = "/index.html"
    status = "404-200"
  }
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.frontend.id
  branch_name = local.amplify_branch
  stage       = "PRODUCTION"

  enable_auto_build = var.amplify_repository_url != ""

  # Consumed by repo-connected CI builds. scripts/deploy-frontend.sh passes the
  # same value on the command line for manual deploys, since a static export
  # bakes the URL in at build time.
  environment_variables = {
    NEXT_PUBLIC_API_BASE_URL = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
  }
}
