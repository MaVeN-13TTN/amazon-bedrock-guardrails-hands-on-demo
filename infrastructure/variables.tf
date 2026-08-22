variable "aws_region" {
  description = <<-EOT
    Region for every resource. Any Region where Bedrock Guardrails is available
    works: the guardrail profile, the model ARNs and the IAM policy are all derived
    from this one value, so changing it is the only edit required.

    Check your Region first:
      python -m lab doctor
  EOT
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
    Model the answer stage calls. Current Claude models are not served on a bare
    model ID in most Regions — an on-demand call must go through an inference
    profile, or it fails with "Invocation with on-demand throughput isn't
    supported" (ADR decision 10).

    Pick the prefix that matches your Region's geography:

      global.anthropic.claude-haiku-4-5-20251001-v1:0   inference stays in your Region
      us.anthropic.claude-haiku-4-5-20251001-v1:0       fans out across US Regions
      eu.anthropic.claude-haiku-4-5-20251001-v1:0       fans out across EU Regions
      apac.anthropic.claude-haiku-4-5-20251001-v1:0     fans out across APAC Regions

    `global.` is the default because a profile that resolves to one Region cannot
    route a request into a Region your organisation denies, and because the IAM it
    needs is fully derived here. A geographic profile chooses its own destination
    per request, which makes a denial name a Region you never asked for.

    Confirm what is available to you:
      aws bedrock list-inference-profiles --region <your-region>
  EOT
  type        = string
  default     = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
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
    Guardrail profile ID for the STANDARD tier, e.g. `eu.guardrail.v1:0`.

    Leave empty — the default — and it is derived from `aws_region`, so you should
    never need to set this. Override it only if AWS adds a profile for a Region
    this configuration does not yet know about.

    Coverage: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-cross-region-support.html
  EOT
  type        = string
  default     = ""
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
