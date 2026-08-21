variable "aws_region" {
  description = "Region for every resource. Bedrock Guardrails, Lambda and Amplify must agree."
  type        = string
  default     = "eu-west-1"
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "kilimo-desk"
}

variable "bedrock_model_id" {
  description = <<-EOT
    Model the backend calls. In eu-west-1 current Claude models are not served on a
    bare model ID — an on-demand call must go through a cross-Region inference
    profile, hence the `eu.` prefix. A bare ID fails with
    "Invocation with on-demand throughput isn't supported".
  EOT
  type        = string
  default     = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "guardrail_tier" {
  description = <<-EOT
    STANDARD or CLASSIC. STANDARD adds ~60 languages, better recall on manipulated
    input, and detection inside code elements; it requires cross-Region inference.
    CLASSIC covers English, French and Spanish only — set it deliberately to
    demonstrate the tier gap.
  EOT
  type        = string
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "CLASSIC"], var.guardrail_tier)
    error_message = "guardrail_tier must be STANDARD or CLASSIC."
  }
}

variable "guardrail_profile_id" {
  description = <<-EOT
    Cross-Region guardrail profile, required by the STANDARD tier. Follows
    `<geo>.guardrail.v1:0`. Verify with:
      aws bedrock list-guardrail-profiles --region <region>
  EOT
  type        = string
  default     = "eu.guardrail.v1:0"
}

variable "publish_guardrail_version" {
  description = "Also cut an immutable numbered version alongside DRAFT."
  type        = bool
  default     = true
}

variable "lambda_memory_mb" {
  description = "Three sequential Bedrock calls are network-bound; more memory buys CPU for JSON handling and a faster cold start."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Must exceed the worst case of screen + answer + verify."
  type        = number
  default     = 60
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention."
  type        = number
  default     = 14
}

variable "api_throttling_rate_limit" {
  description = "Steady-state requests/second. The API is unauthenticated, so this is the cost guard — see ADR.md decision 6."
  type        = number
  default     = 10
}

variable "api_throttling_burst_limit" {
  description = "Burst capacity for the same stage."
  type        = number
  default     = 20
}

variable "extra_cors_origins" {
  description = "Additional origins allowed to call the API. The Amplify branch URL and localhost:3000 are added automatically."
  type        = list(string)
  default     = []
}

variable "amplify_repository_url" {
  description = "Optional Git repository to connect to Amplify for CI builds. Leave empty to use manual deployment via scripts/deploy-frontend.sh."
  type        = string
  default     = ""
}

variable "amplify_access_token" {
  description = "Personal access token, required only when amplify_repository_url is set."
  type        = string
  default     = ""
  sensitive   = true
}

variable "tags" {
  description = "Extra tags merged into every resource."
  type        = map(string)
  default     = {}
}
