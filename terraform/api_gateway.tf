resource "aws_apigatewayv2_api" "lab" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"
  description   = "Media job submission API"

  # CMP-SEC-020: CORS allows any origin with credentials-bearing headers and
  # every method. A real API would list its own front-end origin explicitly.
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["*"]
    allow_headers = ["*"]
    max_age       = 86400
  }
}

resource "aws_apigatewayv2_integration" "ingest" {
  api_id                 = aws_apigatewayv2_api.lab.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.ingest.invoke_arn
  payload_format_version = "2.0"

  # CMP-COST-040: a 29-second integration timeout (the maximum) means a stuck
  # backend holds the connection for the full window before the client can
  # retry, and the client usually retries — doubling Lambda invocations.
  timeout_milliseconds = 29000
}

# Authenticated route. This is the default path.
resource "aws_apigatewayv2_route" "submit" {
  api_id    = aws_apigatewayv2_api.lab.id
  route_key = "POST /jobs"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"

  authorization_type = "AWS_IAM"
}

# CMP-SEC-021: opt-in unauthenticated route. authorization_type NONE on a route
# that writes to S3 and DynamoDB. OFF by default — enabling it publishes an
# anonymous write endpoint to the internet.
resource "aws_apigatewayv2_route" "submit_public" {
  count = var.enable_public_api ? 1 : 0

  api_id    = aws_apigatewayv2_api.lab.id
  route_key = "POST /public/jobs"
  target    = "integrations/${aws_apigatewayv2_integration.ingest.id}"

  authorization_type = "NONE"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.lab.id
  name        = "$default"
  auto_deploy = true

  # CMP-COST-041: full request/response access logging in JSON on every call,
  # written to a log group with no expiry (CMP-COST-010). For a high-volume API
  # this is frequently larger than the API Gateway request charge itself.
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format = jsonencode({
      requestId        = "$context.requestId"
      ip               = "$context.identity.sourceIp"
      requestTime      = "$context.requestTime"
      httpMethod       = "$context.httpMethod"
      routeKey         = "$context.routeKey"
      status           = "$context.status"
      protocol         = "$context.protocol"
      responseLength   = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
      userAgent        = "$context.identity.userAgent"
    })
  }

  # CMP-COST-042: detailed CloudWatch metrics enabled per route, and no
  # throttling limits set at all. Without a rate limit a runaway client (or a
  # retry storm) can drive unbounded Lambda and API Gateway cost.
  default_route_settings {
    detailed_metrics_enabled = true
    # throttling_rate_limit  = <unset>
    # throttling_burst_limit = <unset>
  }

  # CMP-SEC-022: no WAF web ACL is associated with this API.
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/apigateway/${local.prefix}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.lab.execution_arn}/*/*"
}

