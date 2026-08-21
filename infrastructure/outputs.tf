output "api_base_url" {
  description = "Base URL of the FastAPI backend. Set NEXT_PUBLIC_API_BASE_URL to this for local frontend development."
  value       = trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")
}

output "frontend_url" {
  description = "The deployed demo. Populated once scripts/deploy-frontend.sh has run."
  value       = local.amplify_url
}

output "guardrail_id" {
  description = "Guardrail identifier. Put this in backend/.env as GUARDRAIL_ID for local development."
  value       = aws_bedrock_guardrail.main.guardrail_id
}

output "guardrail_arn" {
  value       = aws_bedrock_guardrail.main.guardrail_arn
  description = "Guardrail ARN — the resource to name in a bedrock:GuardrailIdentifier IAM condition."
}

output "guardrail_version" {
  description = "Immutable version in use, or DRAFT."
  value       = var.publish_guardrail_version ? aws_bedrock_guardrail_version.main[0].version : "DRAFT"
}

output "guardrail_tier" {
  description = "STANDARD or CLASSIC, as applied."
  value       = var.guardrail_tier
}

output "amplify_app_id" {
  description = "Needed by scripts/deploy-frontend.sh."
  value       = aws_amplify_app.frontend.id
}

output "amplify_branch" {
  value       = aws_amplify_branch.main.branch_name
  description = "Branch that scripts/deploy-frontend.sh deploys to."
}

output "lambda_function_name" {
  value       = aws_lambda_function.api.function_name
  description = "For `aws logs tail`."
}

output "lambda_log_group" {
  value       = aws_cloudwatch_log_group.lambda.name
  description = "CloudWatch Logs group for the API."
}

output "local_env_file" {
  description = "Paste into backend/.env to run the backend locally against this stack."
  value = join("\n", [
    "AWS_REGION=${var.aws_region}",
    "BEDROCK_MODEL_ID=${var.bedrock_model_id}",
    "GUARDRAIL_ID=${aws_bedrock_guardrail.main.guardrail_id}",
    "GUARDRAIL_VERSION=${var.publish_guardrail_version ? aws_bedrock_guardrail_version.main[0].version : "DRAFT"}",
    "GUARDRAIL_ENABLED=true",
    "CORS_ALLOW_ORIGINS=http://localhost:3000",
  ])
}
