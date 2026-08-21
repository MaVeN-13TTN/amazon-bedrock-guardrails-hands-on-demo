# Further reading

Prior art and reference material on Bedrock Guardrails. Collected while designing
this demo — useful as talk citations and as follow-ups for attendees.

## Official samples

[`aws-samples/amazon-bedrock-samples` → `responsible_ai/bedrock-guardrails/`](https://github.com/aws-samples/amazon-bedrock-samples/tree/main/responsible_ai/bedrock-guardrails)
is the most substantial collection, all Apache-2.0:

| Notebook | Covers |
|---|---|
| [`guardrails-api.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/guardrails-api.ipynb) | `create_guardrail` / `update_guardrail` / versioning, full config shape |
| [`bedrock_guardrails_apply_guardrail_api.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/bedrock_guardrails_apply_guardrail_api.ipynb) | `ApplyGuardrail` — evaluation with no model call |
| [`guardrails_iam_condition.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/guardrails_iam_condition.ipynb) | `bedrock:GuardrailIdentifier` — enforcing a guardrail via IAM |
| [`guardrails_for_code_modality.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/guardrails_for_code_modality.ipynb) | harmful content inside code — a Standard-tier capability |
| [`Apply_Guardrail_with_Streaming_and_Long_Context.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/Apply_Guardrail_with_Streaming_and_Long_Context.ipynb) | streaming responses, long context |
| [`bedrock_guardrails_apply_guardrail_strands_agents.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/bedrock_guardrails_apply_guardrail_strands_agents.ipynb) | guardrails with Strands Agents |
| [`guardrails_image_content_filters_api.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/guardrails_image_content_filters_api.ipynb) | image content filters |
| [`bedrock_guardrails_enforcements_tutorial.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/bedrock_guardrails_enforcements_tutorial.ipynb) | enforcement patterns end to end |
| [`guardrails_custom_model_import.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/responsible_ai/bedrock-guardrails/guardrails_custom_model_import.ipynb) | guardrails over imported custom models |

Also: [`contextual-grounding.ipynb`](https://github.com/aws-samples/amazon-bedrock-samples/blob/main/rag/knowledge-bases/features-examples/05-responsible-ai/contextual-grounding.ipynb)
— grounding with a real knowledge base, the path beyond this demo's inline
`grounding_source`.

## AWS Builder Center

Community articles. Note these pages are JavaScript-rendered, so they need a
browser rather than `curl`.

- [Implementing Responsible AI with Amazon Bedrock Guardrails](https://builder.aws.com/content/2tIpRMHO36OQkCnQXyao1LItJid/implementing-responsible-ai-with-amazon-bedrock-guardrails)
- [Building domain-constrained AI agents with Bedrock Guardrails](https://builder.aws.com/content/3DC2vwiljVkIt44ws05srcqsGMa/building-domain-constrained-ai-agents-with-bedrock-guardrails) — closest in spirit to this demo's denied-topic design
- [Amazon Bedrock Guardrails API: Part 1](https://builder.aws.com/content/2jMMl8bpX6u5z3MFG3qVYfUzOrr/amazon-bedrock-guardrails-api-part-1)
- [Amazon Bedrock Guardrails — Complete Setup Guide](https://builder.aws.com/content/3DZH9l4epfQiT5TZ5XMdDDS4XZG/amazon-bedrock-guardrails-complete-setup-guide)
- [Use Guardrails for safeguarding generative AI applications built using custom or third-party models](https://builder.aws.com/content/2j63w0yGI17kuL1TkUdI0GPddDL/use-guardrails-for-safeguarding-generative-ai-applications-built-using-custom-or-third-party-models) — the model-independence argument
- [Use Guardrails to prevent hallucinations in generative AI applications](https://builder.aws.com/content/2i12ntqFx3xAaDLfvrjH7278sEW/use-guardrails-to-prevent-hallucinations-in-generative-ai-applications) — contextual grounding
- [Centralized GenAI guardrails across multi-provider LLM gateways using the ApplyGuardrail API](https://builder.aws.com/content/3AQTdFoHJbYv430YAFl4tkOVyH2/centralized-genai-guardrails-across-multi-provider-llm-gateways-using-amazon-bedrock-applyguardrail-api) — the gateway pattern, a good "where next" slide

## Medium

- [Amazon Bedrock Guardrails: Building Safe and Responsible GenAI Applications](https://medium.com/@yashaswi.kakumanu/amazon-bedrock-guardrails-building-safe-and-responsible-genai-applications-e9f3a2fc1520) — code per guardrail type
- [Building Responsible AI: Implementing Bedrock Guardrails in Your Customer Support Chatbot](https://medium.com/@mccartni/building-responsible-ai-implementing-bedrock-guardrails-in-your-customer-support-chatbot-f8867088beeb)
- [How to create a Guardrail in Amazon Bedrock](https://medium.com/@vjraghavanv/how-to-create-a-guardrail-in-amazon-bedrock-e0de3305780f) — console walkthrough
- [AWS Bedrock Guardrails](https://medium.com/syntonize/aws-bedrock-guardrails-46d55cd98676) — guardrails with agents via boto3
- [Understanding Guardrails for RAG: Importance, Risks, and Implementation via AWS Bedrock](https://nipundavid.medium.com/understanding-guardrails-for-rag-importance-risks-and-implementation-via-aws-bedrock-d5a0e7aeb76a)
- [Building Safe and Responsible AI with Amazon Bedrock Guardrails](https://devopslearning.medium.com/%EF%B8%8F-building-safe-and-responsible-ai-with-amazon-bedrock-guardrails-%EF%B8%8F-762dd8f2ca2e)

Most of these follow the same shape: a customer-support chatbot, four policies,
a console walkthrough. The three-stage screen/answer/verify pipeline in this repo
is a deliberate departure — it puts `ApplyGuardrail` first so the
model-independence property is demonstrated rather than asserted, and it exercises
contextual grounding, which the chatbot-shaped demos generally skip.

## Documentation

- [Guardrails user guide](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [`ApplyGuardrail` API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ApplyGuardrail.html) — the `qualifiers` values
- [`create_guardrail` (boto3)](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock/client/create_guardrail.html) — `tierConfig`, `crossRegionConfig`
- [Contextual grounding checks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html)
- [Prompt attack detection](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html)
- [Automated Reasoning checks](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-automated-reasoning-checks.html) — region-limited, not used here
- [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)

## Background

- [Tailor responsible AI with new safeguard tiers in Amazon Bedrock Guardrails](https://aws.amazon.com/blogs/machine-learning/tailor-responsible-ai-with-new-safeguard-tiers-in-amazon-bedrock-guardrails/) — the Classic/Standard numbers quoted in the runbook
- [Guardrails can now detect hallucinations and safeguard apps built using custom or third-party FMs](https://aws.amazon.com/blogs/aws/guardrails-for-amazon-bedrock-can-now-detect-hallucinations-and-safeguard-apps-built-using-custom-or-third-party-fms/)
- [Minimize AI hallucinations with Automated Reasoning checks](https://aws.amazon.com/blogs/aws/minimize-ai-hallucinations-and-deliver-up-to-99-verification-accuracy-with-automated-reasoning-checks-now-available/)

## Related AWS workshop

AWS publishes [*Building secure and responsible generative AI applications with
Amazon Bedrock Guardrails*](https://catalog.workshops.aws/workshops/53c38a96-45e0-4019-967a-c73dcbe7a839/en-US),
a self-paced lab on the same product. Worth pointing attendees at as a follow-up.
It is AWS's own copyrighted material — this repo is an independent demo with its
own scenario, policies, architecture and code, not a copy of it.
