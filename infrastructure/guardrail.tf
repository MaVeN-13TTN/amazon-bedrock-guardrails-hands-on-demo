# The guardrail itself — built from shared/scenario.json so the policy has exactly
# one definition. Editing that file and re-applying is the whole change process.

resource "aws_bedrock_guardrail" "main" {
  name                      = local.scenario.guardrail_name
  description               = "Member-support guardrail for ${local.scenario.org} (${local.scenario.assistant})"
  blocked_input_messaging   = local.scenario.blocked_input_message
  blocked_outputs_messaging = local.scenario.blocked_output_message

  # STANDARD tier is only valid alongside cross-Region inference. The provider
  # validates this argument as an ARN, not the bare profile id AWS also documents,
  # so regions.tf assembles the ARN from the Region and account.
  dynamic "cross_region_config" {
    for_each = var.guardrail_tier == "STANDARD" && local.guardrail_profile_arn != "" ? [1] : []
    content {
      guardrail_profile_identifier = local.guardrail_profile_arn
    }
  }

  # --- Policy 1: content filters ------------------------------------------
  content_policy_config {
    dynamic "filters_config" {
      for_each = local.scenario.content_filters
      content {
        type            = filters_config.value.type
        input_strength  = filters_config.value.input_strength
        output_strength = filters_config.value.output_strength
      }
    }

    # tier_config is a list attribute in the v6 provider, not a nested block.
    tier_config = [{ tier_name = var.guardrail_tier }]
  }

  # --- Policy 2: denied topics, as natural-language definitions ------------
  topic_policy_config {
    dynamic "topics_config" {
      for_each = local.scenario.denied_topics
      content {
        name       = topics_config.value.name
        definition = topics_config.value.definition
        examples   = topics_config.value.examples
        type       = "DENY"
      }
    }

    tier_config = [{ tier_name = var.guardrail_tier }]
  }

  # --- Policy 3: word filters ---------------------------------------------
  word_policy_config {
    dynamic "words_config" {
      for_each = local.scenario.blocked_words
      content {
        text = words_config.value
      }
    }

    managed_word_lists_config {
      type = "PROFANITY"
    }
  }

  # --- Policy 4: sensitive information ------------------------------------
  # ANONYMIZE is the API's name for the console's "Mask". Setting input_action
  # means the value is replaced before the model ever sees it.
  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = local.scenario.pii_entities
      content {
        type           = pii_entities_config.value.type
        action         = pii_entities_config.value.action
        input_action   = pii_entities_config.value.action
        output_action  = pii_entities_config.value.action
        input_enabled  = true
        output_enabled = true
      }
    }

    dynamic "regexes_config" {
      for_each = local.scenario.pii_regexes
      content {
        name           = regexes_config.value.name
        description    = regexes_config.value.description
        pattern        = regexes_config.value.pattern
        action         = regexes_config.value.action
        input_action   = regexes_config.value.action
        output_action  = regexes_config.value.action
        input_enabled  = true
        output_enabled = true
      }
    }
  }

  # --- Policy 5: contextual grounding -------------------------------------
  # No knowledge base needed: ApplyGuardrail takes the reference document inline
  # as a `grounding_source` qualifier at evaluation time.
  contextual_grounding_policy_config {
    filters_config {
      type      = "GROUNDING"
      threshold = local.scenario.grounding_threshold
    }
    filters_config {
      type      = "RELEVANCE"
      threshold = local.scenario.relevance_threshold
    }
  }

  # Policy 6, Automated Reasoning, is deliberately absent: it needs a formal
  # policy document, and is unavailable in several Regions. See ADR.md.
}

# An immutable snapshot. DRAFT keeps moving as you edit; a numbered version is
# what you would pin in production.
resource "aws_bedrock_guardrail_version" "main" {
  count = var.publish_guardrail_version ? 1 : 0

  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "${var.guardrail_tier} tier"

  lifecycle {
    create_before_destroy = true
  }
}
