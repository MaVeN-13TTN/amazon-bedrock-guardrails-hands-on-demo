# HTTP API in front of the Lambda. Payload format 2.0, which is what Mangum expects.

resource "aws_apigatewayv2_api" "api" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
  description   = "Kilimo Desk guardrail pipeline API"

  # The browser calls this directly from the Amplify origin.
  cors_configuration {
    allow_origins  = local.cors_origins
    allow_methods  = ["GET", "POST", "OPTIONS"]
    allow_headers  = ["content-type"]
    max_age        = 300
    expose_headers = []
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = min(var.lambda_timeout_seconds * 1000, 30000)
}

# FastAPI owns routing, so the API forwards everything to it.
resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  # The endpoint is unauthenticated, so throttling is the cost guard that stops a
  # scraper turning into a Bedrock bill. See ADR.md decision 6.
  default_route_settings {
    throttling_rate_limit    = var.api_throttling_rate_limit
    throttling_burst_limit   = var.api_throttling_burst_limit
    detailed_metrics_enabled = true
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      httpMethod     = "$context.httpMethod"
      path           = "$context.path"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      latency        = "$context.responseLatency"
      integrationErr = "$context.integration.error"
    })
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
