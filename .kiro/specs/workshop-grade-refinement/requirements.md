# Requirements Document

## Introduction

Kilimo Desk is a complete, committed Amazon Bedrock Guardrails demo that teaches guardrails as an
independent policy engine through a three-stage pipeline (Screen with `ApplyGuardrail(INPUT)`,
Answer with `Converse` + `guardrailConfig`, Verify with `ApplyGuardrail(OUTPUT)` and an inline
grounding source). This feature raises that demo to the depth and polish of an official AWS
self-paced workshop.

The refinement serves three audiences and one cross-cutting theme:

1. **Presenter** — one person driving a 60-minute live session over Google Meet. Needs legibility
   over compressed video, no dead air, and a defined fallback when AWS misbehaves.
2. **Attendees, afterwards** — cloning the repository and practising on their own AWS accounts.
   This is the largest gap today: the only documented path stands up Lambda, API Gateway, Amplify
   and the guardrail together. Pipeline stages 1 and 3 invoke no foundation model and need no
   deployed infrastructure, so a lightweight local lab path is already architecturally possible and
   simply unexploited.
3. **AWS Community Builder reviewers** — assessing technical depth, originality and educational
   quality.
4. **Correctness and validation** — nothing in the repository has been run against AWS. Every
   deployment claim, the `tier_config` syntax, the tier-swap segment and the declared-but-unexecuted
   expectation set in `backend/tests/suite.json` are currently unverified assertions.

"Workshop level" is treated throughout as a concrete bar: stated learning objectives, declared
prerequisites, verifiable checkpoints, a stated cost figure, a guaranteed teardown, and
troubleshooting that matches the code as committed.

**The member-facing restructure.** The frontend as committed is an engineer's console: a pipeline
lane of three stage cards and a grounding tab, with no end-user framing at all. It teaches the
mechanism and hides the consequence. Part E restructures it into two views over one request. The
Member_View is a landing page for Highland Growers Co-operative with a chat window embedded in it —
what a co-operative member would actually visit and actually see: a conversational answer, a plain
refusal, or an answer where their personal data was quietly handled. The guardrail machinery is
invisible there, and that invisibility is the teaching point. The Background_View then reveals, for
the same request, what the policy engine did. The strongest cases get considerably stronger: the
member reads a non-technical refusal directing them to a licensed agrovet and never sees
`topicPolicy · Agrochemical Dosing · BLOCKED`, nor that no model was ever invoked; the member asks
about a payment, gets an answer, and nothing looks unusual, while the Background_View shows their
name, phone number and member number were replaced before the model saw the text — the difference
between blocking and masking, visible only to the engineer; a grounding failure reaches the member
as the safe fallback rather than as a confident invention. Part E is cross-cutting: it serves the
presenter of Part B most directly, but it is also what an attendee runs locally and what a reviewer
in Part D looks at first.

**Scope note.** This document specifies requirements only. Existing project code, infrastructure and
documentation remain unmodified until the design and task phases.

## Glossary

- **ApplyGuardrail**: The Bedrock Runtime operation that evaluates content against a guardrail
  without invoking a foundation model. Used by pipeline stages 1 and 3.
- **Converse**: The Bedrock Runtime operation that invokes a foundation model, optionally with
  `guardrailConfig` attached. Used by pipeline stage 2 and the only model call in the pipeline.
- **guardContent**: The `Converse` message-content wrapper that marks which span a guardrail
  evaluates, leaving unwrapped content (such as the system prompt) unevaluated.
- **grounding_source qualifier**: The `ApplyGuardrail` content qualifier that designates a text
  block as the reference document for contextual grounding, alongside the `query` and
  `guard_content` qualifiers.
- **ANONYMIZE**: The API action name for the Bedrock console's *Mask* behaviour on sensitive
  information. With `input_action = ANONYMIZE`, matched values are replaced before the model
  receives the text; the request continues rather than being blocked.
- **CLASSIC tier**: The default evaluation tier for content filters and denied topics. Covers
  English, French and Spanish.
- **STANDARD tier**: The evaluation tier covering approximately 60 languages with improved recall on
  manipulated input and detection of harmful content inside code elements. Requires cross-Region
  inference.
- **Cross-Region inference profile**: A model or guardrail identifier prefixed with a geography
  (`eu.anthropic.claude-haiku-4-5-...`, `eu.guardrail.v1:0`) that fans a request out across Regions
  within that geography.
- **DRAFT version**: The mutable working version of a guardrail, which reflects the latest
  configuration immediately after an update.
- **Numbered version**: An immutable published snapshot of a guardrail configuration, which is what
  production callers pin.
- **outputScope=FULL**: The `ApplyGuardrail` parameter that returns every policy assessment,
  including policies that evaluated the content and allowed it, rather than only interventions.
- **Trace**: The per-policy detail returned by `Converse` when `guardrailConfig.trace` is
  `"enabled"`. Without it, a caller learns that a request was blocked but not which policy blocked
  it.
- **Assessment_Parser**: The functions in `backend/app/guardrails.py` that normalise assessments
  from both response shapes (`apply_guardrail` returns a flat `assessments` list; `Converse` returns
  a trace whose `inputAssessment` maps guardrail id to one assessment and whose `outputAssessments`
  maps guardrail id to a list) into `PolicyHit` records.
- **Pipeline_Service**: The `GuardrailService` class exposing `screen()`, `answer()` and `verify()`.
- **Lab_Path**: The lightweight, attendee-runnable practice path introduced by this feature, using
  only `ApplyGuardrail` and a single guardrail resource.
- **Lab_Guide**: The self-paced written module set that drives the Lab_Path.
- **Lab_CLI**: The command-line entry point attendees run for Lab_Path exercises.
- **Checkpoint_Verifier**: The component that confirms an attendee's exercise outcome matches the
  documented expectation.
- **Conformance_Runner**: The component that executes the case set currently held in
  `backend/tests/suite.json` against a live guardrail and reports observed versus expected outcomes.
- **Tuning_Module**: The Lab_Guide module teaching the false-positive tuning loop — define a topic,
  observe over-triggering, narrow the definition, re-measure.
- **Replay_Mode**: The fixture-backed mode that serves previously recorded Bedrock responses so the
  UI is demonstrable when AWS calls fail.
- **Demo_UI**: The Next.js frontend in `frontend/`, comprising the Member_View, the Background_View
  and the Grounding_Tool. Built as a static export (`output: "export"`) and served as CDN assets, so
  every API call is made from the browser by `frontend/src/lib/api.ts`.
- **Landing_Page**: The public page of the Demo_UI presenting Highland Growers Co-operative as a
  member would encounter it, and the entry route of the Demo_UI.
- **Chat_Window**: The conversational component embedded in the Landing_Page through which a member
  asks Kilimo Desk a question and reads the answer.
- **Member_View**: The Landing_Page together with its embedded Chat_Window — the whole of what a
  co-operative member sees, carrying no policy names, stage names, scores or AWS identifiers.
- **Background_View**: The engineer-facing view of what the system did for the request the member
  just sent, presenting the three pipeline stages with their policy findings, model-invoked
  indicators and latencies.
- **Grounding_Tool**: The engineer-facing instrument that calls `POST /api/verify` directly with an
  operator-supplied question and candidate answer, currently implemented as
  `frontend/src/components/GroundingLane.tsx` and driven by `GROUNDING_CASES`. Distinct from the
  verify stage of a member request, which appears in the Background_View.
- **Sample_Prompts**: The grouped demonstration prompts exported as `PROMPT_GROUPS` from
  `frontend/src/lib/samples.ts`, each group labelled by the policy its prompts exercise.
- **Demo_Disclosure**: The persistent notice stating that the Demo_UI is a demonstration, that
  Highland Growers Co-operative and everything named in the scenario are fictional, and that no real
  personal information should be entered.
- **Runbook**: `docs/demo-runbook.md`, the presenter's timeline and live-failure reference.
- **Documentation_Set**: `README.md`, `RUNNING.md`, `ADR.md`, and all files under `docs/`.
- **Infrastructure**: The Terraform configuration under `infrastructure/`.
- **Validation_Log**: The committed record of what was executed against AWS, when, in which Region,
  and with which observed result.
- **Teardown_Script**: The scripted removal of every resource an attendee creates while following
  the Lab_Guide.
- **Cost_Statement**: The documented monetary cost of the Lab_Path and of the deployed stack, with
  the date its pricing inputs were read.

## Requirements

---

### Part A — Attendees running the project locally

### Requirement 1: Lightweight local lab path

**User Story:** As a meetup attendee with my own AWS account, I want to practise the interesting
parts of the demo without deploying Lambda, API Gateway or Amplify, so that I can start learning
within minutes and at negligible cost.

#### Acceptance Criteria

1. THE Lab_Path SHALL create exactly one billable AWS resource, an `aws_bedrock_guardrail`, to
   complete every Lab_Guide module, and SHALL require no Lambda function, API Gateway or Amplify
   application to be created.
2. THE Lab_Path SHALL exercise `ApplyGuardrail` with `source=INPUT` and `source=OUTPUT` only, and
   SHALL make no `Converse` or `InvokeModel` call, so that no foundation model invocation is
   required.
3. WHERE an attendee completes only the Lab_Path, THE Lab_Guide SHALL state that Bedrock model
   access is not a prerequisite.
4. THE Lab_Guide SHALL declare its prerequisites as an explicit list naming each required tool with
   a minimum version, each required AWS IAM action, and the AWS Region the Lab_Path targets.
5. WHEN an attendee follows the documented Lab_Path setup steps on a machine meeting the declared
   prerequisites, THE Lab_Path SHALL reach its first verifiable checkpoint within 10 minutes of
   elapsed wall-clock time, measured from the first command in the Lab_Guide setup section to the
   first checkpoint being reported as met, and excluding installation of the declared prerequisites.
6. THE Lab_CLI SHALL print, for each evaluated prompt, the guardrail action, each policy finding
   with its policy type and detail, and whether a foundation model was invoked, and SHALL print an
   explicit no-policy-intervened statement when the evaluation returns no finding.
7. IF the guardrail identifier required by the Lab_CLI is absent from the environment, THEN THE
   Lab_CLI SHALL exit with a non-zero status before making any AWS call and print a message naming
   the environment variable and the command that populates it.
8. THE Documentation_Set SHALL present the Lab_Path as the default entry point for a reader who
   arrives at the repository without having attended the session, linking to the Lab_Guide ahead of
   any instruction that deploys Lambda, API Gateway or Amplify.
9. IF an AWS call made by the Lab_CLI fails, THEN THE Lab_CLI SHALL exit with a non-zero status,
   print a message naming the AWS operation that failed and the returned AWS error code, and leave
   the guardrail configuration unchanged.
10. IF a prompt supplied to the Lab_CLI is empty or exceeds the maximum prompt length declared in
    the Lab_Guide, THEN THE Lab_CLI SHALL reject the prompt before making any AWS call and print a
    message naming the violated limit.

### Requirement 2: Self-paced modules with verifiable checkpoints

**User Story:** As an attendee working alone after the meetup, I want each module to tell me what I
am about to learn and how to confirm I got it right, so that I can make progress without a
presenter.

#### Acceptance Criteria

1. THE Lab_Guide SHALL divide the Lab_Path into between 6 and 12 consecutively numbered modules,
   each module covering exactly one guardrail policy type or exactly one pipeline concept, and the
   module set collectively covering all five policy types (denied topics, content filters, word
   filters, sensitive information, contextual grounding) and all three pipeline stages (screen,
   answer, verify).
2. THE Lab_Guide SHALL state, for each module, between 1 and 3 learning objectives each phrased as
   an action the attendee performs and observes, an expected duration as a whole number of minutes
   between 5 and 20, and its prerequisite modules by module number or the explicit statement that it
   has none.
3. THE Lab_Guide SHALL state, for each module, between 1 and 5 checkpoints, each checkpoint giving
   the prompt text verbatim in at most 500 characters, the command the attendee runs, the expected
   guardrail action (intervened or not intervened), the expected policy type, the expected policy
   name as it appears in `shared/scenario.json` where that policy is named, and a label of either
   deterministic or probabilistic.
4. WHEN an attendee runs the Checkpoint_Verifier for a module, THE Checkpoint_Verifier SHALL report,
   for each checkpoint of that module, the checkpoint number, a verdict of met or unmet, the
   observed guardrail action, and each observed policy finding with its policy type and policy name.
5. IF an observed outcome differs from a documented checkpoint expectation, THEN THE
   Checkpoint_Verifier SHALL report the expected and the observed guardrail action, the expected and
   the observed policy names, SHALL name exactly one Lab_Guide troubleshooting entry by its
   identifier, and SHALL leave the guardrail configuration unchanged.
6. WHERE a checkpoint outcome depends on denied-topic or content-filter classification, THE
   Lab_Guide SHALL label that checkpoint as probabilistic, SHALL state the number of repetitions run
   during validation as at least 5 and the count of those repetitions in which the expected outcome
   was observed, and SHALL state that the checkpoint counts as met when the expected outcome is
   observed in at least 3 of 5 repetitions.
7. THE Lab_Guide SHALL include at least one exercise that names the policy field the attendee edits
   in `shared/scenario.json`, the command that re-applies the edited policy, the prompt used, the
   guardrail action observed before the edit, the guardrail action expected after the edit, and the
   command that restores the original policy.
8. WHEN the Checkpoint_Verifier finishes evaluating a module, THE Checkpoint_Verifier SHALL print a
   summary giving the module number, the count of checkpoints evaluated, and the counts met, unmet
   and not evaluated.
9. IF the Checkpoint_Verifier cannot evaluate a checkpoint because the guardrail identifier, AWS
   credentials or network access is unavailable, THEN THE Checkpoint_Verifier SHALL report that
   checkpoint as not evaluated rather than unmet, SHALL state which of those prerequisites was
   missing, and SHALL exit with a non-zero status.
10. THE Lab_Guide SHALL provide, for each documented checkpoint, a troubleshooting entry carrying
    the identifier the Checkpoint_Verifier names, covering at minimum the case where no guardrail
    intervention occurred and the case where a policy other than the expected one intervened.
11. THE Lab_Guide SHALL state that no numbered module covers the Demo_UI, the Landing_Page, the
    Chat_Window or the Background_View, and that every checkpoint of every numbered module is
    reachable through the Lab_CLI alone, so that the Lab_Path scope stays honest about what an
    attendee builds.
12. WHERE an attendee chooses to run the Demo_UI locally, THE Lab_Guide SHALL provide exactly one
    appendix, excluded from the module count of criterion 1 and evaluated by no Checkpoint_Verifier
    checkpoint, that names the command starting the backend, the command `npm run dev` starting the
    frontend, and the environment variable `NEXT_PUBLIC_API_BASE_URL` that points the Chat_Window at
    the local backend.
13. THE Lab_Guide appendix required by criterion 12 SHALL state that running the Demo_UI locally
    creates no AWS resource beyond the single guardrail of Requirement 1 and requires no Lambda, API
    Gateway or Amplify deployment, and SHALL state that the answer stage requires Bedrock model
    access while the screen stage, the verify stage and Replay_Mode do not.

### Requirement 3: Cost transparency

**User Story:** As a cost-sensitive attendee, I want to know what this costs before I run it, so
that I can decide to proceed without reading a pricing page.

#### Acceptance Criteria

1. THE Cost_Statement SHALL state the cost of completing every Lab_Guide module once as a figure in
   United States dollars to two decimal places, together with the total number of `ApplyGuardrail`
   evaluations that figure assumes and the added cost of one further full pass through all modules.
2. THE Cost_Statement SHALL state the cost of standing up the deployed stack, running one rehearsal
   of at most 60 minutes and one 60-minute session, and destroying it, as a figure in United States
   dollars to two decimal places, itemised per billed component across the guardrail, the foundation
   model, Lambda, API Gateway, Amplify Hosting and CloudWatch Logs.
3. THE Cost_Statement SHALL show its derivation as a table of billable units in which each row gives
   the billed item, the unit of billing, the unit price, the quantity assumed and the line total,
   covering each enabled guardrail policy with its assumed text-unit count and the model's assumed
   input and output token counts, and whose line totals sum to the Lab_Path figure and the deployed
   stack figure within one United States cent.
4. THE Cost_Statement SHALL state the calendar date on which its pricing inputs were read, the
   Region `eu-west-1` to which they apply, and the AWS pricing source consulted for each unit price.
5. THE Cost_Statement SHALL state that guardrail charges accrue per 1,000 text units per enabled
   policy and SHALL give the count of policies enabled by the committed scenario configuration, so
   that a reader understands the cost effect of leaving a policy configured.
6. THE Cost_Statement SHALL state the idle cost of the deployed stack in United States dollars per
   24 hours and per 30-day month while no requests are served, including CloudWatch Logs storage
   under 14-day retention and Amplify Hosting, and SHALL name each component whose idle cost is zero.
7. THE Lab_Guide SHALL place a link to the Cost_Statement, together with the stated Lab_Path total in
   United States dollars, in its prerequisites section above the first command an attendee runs.
8. THE Cost_Statement SHALL state whether its figures assume any AWS Free Tier allowance and SHALL
   state the figures that apply to an account with no free-tier allowance remaining.
9. THE Cost_Statement SHALL state the cost in United States dollars of one `ApplyGuardrail`
   evaluation with the committed policy set enabled and the change in that cost from enabling one
   additional policy.
10. IF an attendee leaves the guardrail created by the Lab_Guide in place without running the
    Teardown_Script, THEN THE Cost_Statement SHALL state the recurring charge in United States
    dollars per 30-day month that accrues while that guardrail serves no requests.

### Requirement 4: Guaranteed teardown

**User Story:** As an attendee, I want one documented command that removes everything I created, so
that I do not discover a forgotten resource on next month's bill.

#### Acceptance Criteria

1. THE Teardown_Script SHALL remove, in a single invocation that requires no argument beyond the
   documented guardrail identifier environment variable, every AWS resource created by the Lab_Guide
   modules, comprising the `aws_bedrock_guardrail` resource and every published version of that
   guardrail.
2. WHEN the Teardown_Script completes with every resource it manages absent, THE Teardown_Script
   SHALL exit with status zero and print one confirmation line per resource, naming the resource
   type and the identifier removed.
3. WHEN the Teardown_Script has issued its removal calls, THE Teardown_Script SHALL query AWS for
   each resource it manages, retrying for up to 60 seconds at intervals of no more than 10 seconds,
   and report each resource as removed or still present.
4. IF a resource is still present when the 60-second verification window elapses, THEN THE
   Teardown_Script SHALL exit with a non-zero status and print, for each remaining resource, its
   resource type, its identifier and the documented manual removal command for it.
5. IF a removal call fails for one resource, THEN THE Teardown_Script SHALL continue attempting
   removal of the remaining resources and SHALL report the failing resource together with the AWS
   error code returned.
6. IF the Teardown_Script is run when every resource it manages is already absent, THEN THE
   Teardown_Script SHALL exit with status zero and report each resource as already absent, so that a
   repeated run is safe.
7. THE Lab_Guide SHALL state which account-level settings persist after teardown, naming Bedrock
   model access, and SHALL state for each that it carries no charge while unused.
8. THE Lab_Guide SHALL place the teardown instruction, as the single command named in criterion 1, in
   the closing section of every numbered module, so that an attendee stopping partway through finds
   it without reading ahead.
9. IF the local Terraform state file is absent or does not list the resources an attendee created,
   THEN THE Documentation_Set SHALL provide a state-independent removal procedure that names each
   resource type and the command that lists and then removes it.
10. WHERE an attendee also deployed the full stack, THE Documentation_Set SHALL state that
    `terraform destroy` removes it and SHALL name each resource type verified as removed during
    validation, namely the Lambda function, the API Gateway, the Amplify application, the IAM role
    and policies, the two CloudWatch log groups and the two metric alarms.

### Requirement 5: The false-positive tuning loop

**User Story:** As an attendee who will write my own guardrail policies, I want to see a legitimate
question wrongly blocked and then fix it, so that I learn the tuning loop rather than only the happy
path.

#### Acceptance Criteria

1. THE Tuning_Module SHALL identify at least one in-scope prompt, defined as a prompt whose answer is
   contained in the reference bulletin, that the guardrail blocked at the screen stage, and SHALL
   record for that prompt the observed guardrail action and the name of the denied topic that
   produced the block.
2. THE Tuning_Module SHALL use the seed-treatment question "is the seed from the store already
   treated?" as a candidate false positive against the `Agrochemical Dosing` topic definition,
   evaluate it for at least 10 repetitions, and state the count of those repetitions in which it was
   blocked together with the date and Region of the measurement.
3. THE Tuning_Module SHALL state the false-positive rate as the count of in-scope prompts blocked
   divided by the count of in-scope prompts evaluated, expressed as a percentage to one decimal
   place, measured over a named labelled prompt set holding at least 10 in-scope prompts and at
   least 6 violating prompts, each evaluated for the same repetition count of at least 10.
4. WHEN a topic definition is narrowed as instructed by the Tuning_Module, THE Conformance_Runner
   SHALL re-evaluate the same labelled prompt set at the same repetition count and report the
   recomputed false-positive rate, the count of violating prompts still blocked, and the block count
   observed for the seed-treatment question.
5. THE Tuning_Module SHALL state the trade-off that narrowing a topic definition to remove a false
   positive can also reduce recall on genuine violations, and SHALL support that statement with the
   measured counts of violating prompts blocked before and after narrowing.
6. THE Tuning_Module SHALL express the tuning loop as four ordered steps — define, measure, narrow,
   re-measure — stating for each step the command the attendee runs and the recorded outcome it
   produces, and SHALL quote both the original and the narrowed `Agrochemical Dosing` definition
   text verbatim.
7. THE Runbook SHALL allocate between 3 and 6 minutes to the false-positive segment, ordered so that
   the observed block is shown before the topic definition that caused it is read aloud.
8. IF the seed-treatment question is blocked in zero repetitions of the pre-narrowing measurement,
   THEN THE Tuning_Module SHALL substitute a blocked in-scope prompt from the same labelled prompt
   set, name the substituted prompt, and retain the seed-treatment result as a recorded
   non-reproduction rather than removing it.
9. IF the recomputed false-positive rate is not lower than the rate measured before narrowing, THEN
   THE Tuning_Module SHALL report that iteration as unsuccessful and instruct a further narrow and
   re-measure iteration, up to a stated maximum of 3 iterations.
10. IF the false positive does not reproduce within 2 live attempts during the session, THEN THE
    Runbook SHALL direct the presenter to the recorded result for that case and give the sentence to
    say while switching.

---

### Part B — The presenter driving the live session

### Requirement 6: Legibility over compressed video

**User Story:** As the presenter on a Google Meet screen share, I want the text carrying the lesson
to be readable for attendees on laptops and phones, so that the teaching-critical detail survives
video compression.

#### Acceptance Criteria

1. THE Background_View SHALL render the `ApplyGuardrail · no model` stage label at a computed font
   size of at least 16 CSS pixels, measured at 100 percent browser zoom with the default root font
   size.
2. THE Background_View SHALL render policy finding text, including policy type, detail and action, at
   a computed font size of at least 14 CSS pixels, measured at 100 percent browser zoom with the
   default root font size.
3. THE Background_View SHALL render the forwarded-text line that shows masked output at a computed
   font size of at least 14 CSS pixels, SHALL display at least the first 160 characters of that text,
   and SHALL display a truncation indicator when the text exceeds the displayed length.
4. THE Chat_Window SHALL render member turn text and assistant turn text at a computed font size of
   at least 16 CSS pixels, measured at 100 percent browser zoom with the default root font size, so
   that the sentence a member actually reads is legible over compressed video.
5. WHERE the Runbook enumerates a Demo_UI element as read aloud, THE Demo_UI SHALL render that
   element at a computed font size of at least 14 CSS pixels.
6. WHEN a request completes WHILE only the Member_View is displayed, THE Member_View SHALL present
   the most recent member turn in full, the assistant turn in full, the Demo_Disclosure and the
   control that opens the Background_View, within a viewport of 1280 by 720 CSS pixels without
   vertical or horizontal scrolling, for assistant turn lengths up to 120 words.
7. WHEN the Background_View is displayed for a completed request, THE Background_View SHALL present
   every stage entry of that response, each stage's model-invoked indicator and each stage's policy
   findings within a viewport of 1280 by 720 CSS pixels without vertical or horizontal scrolling, for
   the finding counts produced by the cases the Runbook demonstrates.
8. WHERE the presenter displays the Member_View and the Background_View at the same time within a
   viewport of 1280 by 720 CSS pixels, THE Demo_UI SHALL keep the assistant turn text, the member
   turn text, every stage name and every stage's model-invoked indicator visible without scrolling,
   and SHALL confine any scrolling the layout requires to policy finding detail text and raw payload
   panels.
9. THE Background_View SHALL distinguish an intervened stage from a passed stage by a text label
   rendered at a computed font size of at least 14 CSS pixels, such that the distinction remains
   determinable when colour is removed from the rendering.
10. WHERE a raw JSON panel is displayed, THE Background_View SHALL provide a keyboard-operable
    control that sets the panel text to a computed font size of at least 16 and at most 24 CSS
    pixels, and SHALL retain that size until the control is reversed.
11. THE Runbook SHALL enumerate, for each segment, every Demo_UI element the presenter is instructed
    to read aloud, together with the view that element belongs to, so that the element set governed
    by criterion 5 is decidable.
12. WHERE a policy finding, a forwarded-text line, a member turn or an assistant turn exceeds the
    width of its container, THE Demo_UI SHALL wrap that text onto additional lines without clipping
    it and without replacing it with an ellipsis.
13. THE Demo_UI SHALL render every text element governed by criteria 1 through 5 and criterion 9 at a
    contrast ratio of at least 4.5 to 1 against its background. Note that full accessibility conformance requires
    manual testing with assistive technologies and expert review beyond this measurable criterion.

### Requirement 7: Graceful degradation and a fallback path

**User Story:** As the presenter, I want the session to continue when a Bedrock call fails, so that
one AWS hiccup does not end the demo.

#### Acceptance Criteria

1. WHERE Replay_Mode is enabled, THE Pipeline_Service SHALL serve recorded fixture responses for
   every stage of every requested case.
2. THE Replay_Mode fixture set SHALL cover each of the eleven cases the Runbook instructs the
   presenter to demonstrate — the in-scope question, the dosing block, the land topic, the credit
   topic, the internal-leak word filter, the PII masking case, the prompt attack, the false-positive
   case, and the three grounding cases — and SHALL cover the tier-gap prompt under both CLASSIC and
   STANDARD.
3. WHEN a Bedrock call returns an error, THE Background_View SHALL display within 2 seconds, at a
   computed font size of at least 14 CSS pixels, the name of the failing stage and the AWS error code
   returned, and SHALL retain the results of any stage that already completed, while THE Chat_Window
   displays the member-readable failure message required by Requirement 18.
4. IF a Bedrock call fails and a Replay_Mode fixture exists for the requested case, THEN THE
   Background_View SHALL present a control that substitutes the recorded result within 2 seconds
   without the presenter re-entering the prompt, and THE Chat_Window SHALL replace the failure
   message with the fixture's `final` value.
5. THE Runbook SHALL state the single command that enables Replay_Mode and SHALL state 60 seconds as
   the maximum time the presenter spends diagnosing a live failure before switching.
6. THE Replay_Mode fixtures SHALL be generated from recorded live AWS responses and SHALL record, for
   each fixture, the UTC date of capture, the Region, the guardrail tier and the guardrail version in
   force at capture.
7. WHILE Replay_Mode is enabled, THE Pipeline_Service SHALL complete all three pipeline stages with
   no AWS credentials present and with Bedrock unreachable, so that the mode is demonstrably
   independent of AWS availability.
8. WHERE a stage result is served from a Replay_Mode fixture, THE Background_View SHALL label that
   stage as replayed in visible text and SHALL display the fixture's capture date and Region, so that
   the audience is not shown a recorded result presented as live.
9. IF a Bedrock call returns no response within 30 seconds, THEN THE Background_View SHALL report the
   stage as timed out, naming the stage and the elapsed time, without asserting an AWS error code.
10. IF a Bedrock call fails and no Replay_Mode fixture exists for the requested case, THEN THE
    Background_View SHALL state that no recorded result is available for that case and SHALL name the
    case so the presenter can select a covered one.
11. WHILE Replay_Mode is enabled, THE Demo_UI SHALL display the replay state in a persistent
    indicator rendered outside the Chat_Window at a computed font size of at least 14 CSS pixels
    alongside the Demo_Disclosure, and THE Chat_Window SHALL render the assistant turn as the `final`
    value alone under the rule of Requirement 18, so that the member experience is identical between
    a live and a replayed run while the audience is still told the run is recorded.
12. THE Runbook SHALL state that the replay indicator required by criterion 11 sits outside the
    Chat_Window because a replay label inside the assistant turn would show the audience something a
    real member would never see, and SHALL name the on-screen element the presenter points to when
    disclosing that a result is recorded.

### Requirement 8: A runbook timeline that fits the hour

**User Story:** As the presenter, I want a timeline with room for questions and evidence shown
before explanation, so that the session lands rather than runs out of time.

#### Acceptance Criteria

1. THE Runbook SHALL reserve at least 8 minutes total for questions across at least 2 labelled
   question segments each carrying a start time and an end time, the first of which starts no later
   than minute 25 of the session.
2. THE Runbook SHALL reserve at least 4 minutes of unallocated buffer across at least 3 intervals of
   at least 1 minute each, with at least one interval in each third of the session.
3. THE Runbook SHALL place a segment that shows one non-intervening and one intervening guardrail
   evaluation in the Member_View so that it ends at or before the start time of any segment that
   reads policy configuration aloud.
4. THE Runbook SHALL allocate at most 5 minutes in total, summed across every segment, to reading
   `shared/scenario.json` aloud.
5. THE Runbook SHALL demonstrate exactly one denied topic in full, meaning one live prompt whose
   blocked outcome is shown, and SHALL name the remaining denied topics within at most 1 minute
   without running a prompt for each.
6. THE Runbook SHALL mark each segment as essential or cuttable and SHALL state a numbered cut order
   in which each entry carries the minutes it reclaims, totalling at least 8 reclaimable minutes.
7. THE Runbook SHALL state, for each segment, exactly one declarative sentence of at most 30 words
   naming what the presenter is there to land.
8. THE Runbook timeline SHALL consist of contiguous non-overlapping segments whose durations sum to
   exactly 60 minutes.
9. THE Runbook SHALL allocate a segment to the false-positive tuning case and SHALL state where in
   the timeline the presenter switches to Replay_Mode if a live failure occurs.
10. IF the session passes a segment's stated end time by more than 2 minutes, THEN THE Runbook SHALL
    direct the presenter to the next entry in the cut order.
11. THE Runbook SHALL open with an opening segment of between 4 and 10 minutes in which only the
    Member_View is displayed, showing at least the in-scope collection-point question and the dosing
    refusal exactly as a member reads them, and SHALL end that segment at or before the start time of
    the first segment that displays the Background_View.
12. THE Runbook SHALL place the first display of the Background_View to start no earlier than minute
    5 and no later than minute 15 of the session, so that the member experience is established before
    the machinery is revealed and the reveal still lands inside the first third.
13. THE Runbook SHALL order the dosing segment, the PII segment and the grounding-failure segment so
    that, within each, the Member_View is shown before the Background_View for the same submitted
    prompt, and SHALL state for each the one sentence naming what the member could not see.
14. THE Runbook SHALL allocate at most 4 minutes in total, summed across every segment, to the
    Landing_Page content that is not the Chat_Window, so that presenting the co-operative does not
    consume time reserved for guardrail behaviour.
15. THE Runbook timeline SHALL satisfy criteria 11 through 14 while continuing to satisfy criterion 1,
    criterion 2 and criterion 8, so that the added member-first ordering leaves the 8-minute question
    floor, the 4-minute buffer floor and the exact 60-minute total intact.

**User Story:** As the presenter, I want the tier swap to change the behaviour attendees see, so that
the segment proves the CLASSIC-to-STANDARD gap instead of silently proving nothing.

#### Acceptance Criteria

1. WHILE the demo is configured for a presented session, with publishing of a numbered guardrail
   version disabled, THE Infrastructure SHALL supply the guardrail version value `DRAFT` to the
   application, so that a tier change takes effect without republishing a version.
2. WHEN `guardrail_tier` is changed and Terraform is re-applied with publishing of a numbered
   guardrail version disabled, THE Infrastructure SHALL plan and apply changes to the guardrail
   resource only, reporting zero changes to the Lambda function resource and creating no new
   guardrail version.
3. THE Documentation_Set SHALL state, for each of the guardrail version, the Lambda environment
   configuration and the frontend build, whether a tier change alters it under each of the two
   version-publishing settings, and SHALL remove the existing RUNNING.md claim that a tier change
   needs no redeploy of Lambda or frontend wherever that claim does not match the applied
   configuration.
4. THE Documentation_Set SHALL state that when a numbered guardrail version is pinned and is not
   recut after a tier change, the application continues to evaluate against the previous tier, so
   that the tier-gap segment shows no behavioural difference, and SHALL name the configuration
   setting that avoids this.
5. WHEN the Conformance_Runner is run with the tier set to CLASSIC and again with the tier set to
   STANDARD, THE Conformance_Runner SHALL evaluate each of the 2 tier-gap prompts, the Swahili
   prompt attack and the code-embedded prompt attack, at least 5 times per prompt per tier, and
   SHALL record for every repetition the guardrail action and the policy findings observed.
6. THE Documentation_Set SHALL state the count of tier-gap prompts measured, the count of repetitions
   per prompt per tier, and, per prompt and per tier, the count of repetitions in which the guardrail
   intervened, so that the sample size behind the claim is visible.
7. WHERE a tier-gap prompt did not produce the same guardrail action in every recorded repetition for
   a tier, THE Runbook SHALL present that prompt as an illustration rather than as a guaranteed
   result, and SHALL state the observed intervention count out of the total repetitions.
8. THE Runbook SHALL provide a spoken description of the tier gap, deliverable in at most 90 seconds,
   that states the observed outcome of each tier-gap prompt under CLASSIC and under STANDARD and the
   repetition count behind each outcome, for use when the live swap is cut for time.
9. THE Runbook SHALL state the pre-swap check that confirms the running application reports the
   guardrail version in use, and SHALL state that the reported value must be `DRAFT` before the live
   swap is performed.
10. IF the pre-session tier-gap check records the same guardrail action for a tier-gap prompt under
    both CLASSIC and STANDARD, THEN THE Runbook SHALL direct the presenter to cut the live swap and
    deliver the spoken description instead.

---

### Part C — Correctness and validation

### Requirement 10: Infrastructure validated against AWS

**User Story:** As the repository owner, I want every deployment claim to have been executed at
least once, so that attendees and reviewers are not following untested hypotheses.

#### Acceptance Criteria

1. THE Validation_Log SHALL record, for each of `terraform init`, `terraform validate`,
   `terraform plan` and `terraform apply`, the exact command invoked, the target Region `eu-west-1`,
   the resolved AWS provider version satisfying the pinned `~> 6.0` constraint, the process exit
   status, and for `terraform plan` and `terraform apply` the counts of resources to add, change and
   destroy.
2. THE Validation_Log SHALL record, for the `tier_config` argument on the resolved provider version,
   both syntaxes attempted — list-attribute assignment and nested block — naming which syntax
   `terraform validate` accepted with exit status zero and quoting verbatim the error text emitted
   for the rejected syntax.
3. WHEN the guardrail resource is created with `guardrail_tier` set to CLASSIC and again with
   `guardrail_tier` set to STANDARD, THE Validation_Log SHALL record, for each creation, the exit
   status, the guardrail identifier returned, the guardrail version returned, and the tier reported
   by AWS for the created guardrail.
4. THE Validation_Log SHALL record the guardrail profile identifier confirmed available in
   `eu-west-1`, whether that identifier matches the documented default `eu.guardrail.v1:0`, and the
   exact command used to list the available profiles.
5. THE Validation_Log SHALL record the latency of the deployed API in milliseconds for one
   cold-start request issued after at least 15 minutes without traffic and for at least three
   consecutive warm requests issued no more than 60 seconds apart, reporting each individual
   measurement rather than an aggregate alone.
6. THE Validation_Log SHALL record the exit status of `terraform destroy` and, for each of the
   guardrail, the two log groups, the two alarms, the Lambda function, the API Gateway HTTP API, the
   IAM role and the Amplify application, the result of a post-destroy query confirming the resource
   is absent.
7. IF a documented claim is contradicted by a validation result, THEN THE Documentation_Set SHALL be
   corrected to state the observed behaviour and to cite the Validation_Log entry that contradicted
   the previous claim.
8. THE ADR SHALL record any decision changed by validation as a dated amendment to the affected
   numbered decision that retains the superseded statement, names the observed behaviour and cites
   the Validation_Log entry, rather than as a silent edit.
9. THE Validation_Log SHALL record, for every entry, the UTC date of execution, the Region the
   execution targeted, and the resolved AWS provider version in effect, so that each entry is
   attributable to one execution environment.
10. IF `terraform apply` or `terraform destroy` exits with a non-zero status, THEN THE
    Validation_Log SHALL record the address of the failing resource, the verbatim error text, the
    resources remaining in state at the point of failure, and the exit status of the re-run
    performed after the correction.
11. WHERE a documented deployment claim has no corresponding Validation_Log entry, THE
    Documentation_Set SHALL label that claim as unverified and name the command that would verify it.

### Requirement 11: Deployed-runtime API-shape parity

**User Story:** As the repository owner, I want the deployed Lambda to use the same Bedrock request
shapes that work locally, so that a field unsupported by the runtime's bundled SDK does not surface
first in front of an audience.

#### Acceptance Criteria

1. WHEN a deployment completes, THE Validation_Log SHALL record the boto3 and botocore versions
   present in the deployed Lambda runtime and the versions used locally, each as a three-component
   version string, together with the Lambda runtime identifier, the architecture, the Region and the
   UTC date of observation.
2. WHEN `apply_guardrail` is called with `outputScope=FULL` from the deployed Lambda at both call
   sites, the screen stage and the verify stage, THE Validation_Log SHALL record for each call site
   whether the parameter was accepted, the verbatim rejection text if it was rejected, and the count
   of returned assessments whose action is `NONE`.
3. IF the deployed runtime rejects a Bedrock parameter that the local environment accepts, THEN THE
   Infrastructure SHALL include in the Lambda bundle the boto3 and botocore versions pinned in
   `backend/requirements.txt`, replacing reliance on the runtime-supplied packages.
4. THE Documentation_Set SHALL state, separately for the local environment and the deployed Lambda,
   which SDK version governs the available Bedrock request fields, and SHALL state that the packaging
   step strips boto3 and botocore because the runtime supplies them.
5. THE Pipeline_Service SHALL surface a parameter-validation failure as an error naming the rejected
   parameter and the pipeline stage that supplied it.
6. WHERE the deployed and local SDK versions differ, THE Documentation_Set SHALL name the command
   that detects the difference, the version fields it compares, its pass condition, and its position
   in the pre-session checklist ahead of the first live demonstration.
7. WHEN the Lambda bundle is rebuilt to include the pinned SDK, THE Validation_Log SHALL record the
   boto3 and botocore versions the runtime then reports, whether the previously rejected field is
   accepted, and the resulting bundle size.
8. IF a Bedrock call fails parameter validation, THEN THE Demo_UI SHALL report that stage as failed
   distinguishably from a guardrail intervention, and THE Pipeline_Service SHALL make no further
   Bedrock call for that request.

### Requirement 12: An executable conformance runner

**User Story:** As the repository owner, I want the declared case expectations to actually run
against a live guardrail, so that the file is rehearsal evidence rather than an expectation set
masquerading as a test suite.

#### Acceptance Criteria

1. THE Conformance_Runner SHALL read the case set that currently resides in
   `backend/tests/suite.json`, evaluate every case against a guardrail identified by its guardrail
   identifier, version and tier, and complete a full single-repetition pass within 5 minutes.
2. THE Conformance_Runner SHALL report, per case, the expected outcome, the observed guardrail
   action, the observed policy findings, and a verdict that is exactly one of pass, fail, skip or
   error.
3. THE Conformance_Runner SHALL print a summary giving the counts of cases evaluated, passed, failed,
   skipped and errored, and SHALL exit with status zero only when the failed count and the errored
   count are both zero.
4. WHERE a case declares a stage that requires no foundation model, THE Conformance_Runner SHALL
   evaluate that case using `ApplyGuardrail` only.
5. WHERE a case declares a stage that requires a model answer, THE Conformance_Runner SHALL skip that
   case when model access is unavailable, SHALL report it as skipped with the reason, and SHALL
   exclude it from the passed and failed counts.
6. THE Conformance_Runner SHALL accept a repetition count between 1 and 20 with a default of 1, SHALL
   report the distribution of observed actions across repetitions, and SHALL label a case as
   probabilistic when the observed action differs across its repetitions.
7. THE Conformance_Runner SHALL classify each case as in-scope or violating by reference to its
   declared expected outcome, and SHALL report a false-positive count as the number of in-scope cases
   observed as intervened and a true-positive count as the number of violating cases observed as
   intervened.
8. IF the case set is collected by the test runner while containing no executable assertions, THEN
   THE Documentation_Set SHALL rename it so that its name describes a declarative case set rather
   than an executable test suite.
9. THE Runbook SHALL name the Conformance_Runner as the pre-session verification step, SHALL state
   its validated wall-clock duration in minutes, and SHALL state its position in the pre-session
   timeline.
10. THE Conformance_Runner SHALL emit a machine-readable result record per case carrying the case
    identifier, the guardrail tier in force, the repetition index, the observed action and the
    observed policy findings, so that the measurements required by Requirement 5 and Requirement 9
    are computable without parsing printed text.
11. IF the guardrail identifier or the Region is absent, the case set cannot be read, or a case
    carries no prompt, THEN THE Conformance_Runner SHALL exit with a non-zero status before
    evaluating any case and print a message naming the missing or invalid item.
12. IF an individual AWS call fails or returns no response within 30 seconds after at most 2 retries,
    THEN THE Conformance_Runner SHALL report that case as errored with the AWS error code and SHALL
    continue evaluating the remaining cases.

### Requirement 13: Assessment parsing correctness

**User Story:** As a developer reading this repository as a reference, I want assessment parsing to
be provably correct across both response shapes, so that the UI panels reflect what Bedrock
actually reported.

#### Acceptance Criteria

1. WHEN an `apply_guardrail` response containing a flat `assessments` list of 0 to 50 assessments is
   parsed, THE Assessment_Parser SHALL emit one policy hit per qualifying finding, in section order,
   each carrying the location value stated by the caller.
2. WHEN a `Converse` trace is parsed in which `inputAssessment` maps a guardrail identifier to a
   single assessment object, THE Assessment_Parser SHALL emit the same policy hits it would emit for
   the equivalent flat assessment, each carrying the location value `input`.
3. WHEN a `Converse` trace is parsed in which `outputAssessments` maps a guardrail identifier to a
   list of assessment objects, THE Assessment_Parser SHALL emit the policy hits from every element of
   that list in list order, each carrying the location value `output`.
4. WHEN an assessment contains a contextual grounding filter, THE Assessment_Parser SHALL emit a hit
   for that filter regardless of its action, SHALL set the policy name to `grounding` where the
   filter type is `GROUNDING` and to `relevance` otherwise, SHALL carry the reported score and
   threshold, and SHALL set the passed indicator to true exactly when the reported action is `NONE`.
5. WHEN an assessment contains a finding whose action is `NONE` within `contentPolicy.filters` or
   `topicPolicy.topics`, THE Assessment_Parser SHALL omit that finding from the emitted hits.
6. WHEN an assessment omits a policy section entirely, THE Assessment_Parser SHALL emit the hits for
   the remaining sections without raising an error.
7. FOR ALL assessments, the count of emitted policy hits SHALL equal the count of qualifying findings
   across the seven parsed sections — `contentPolicy.filters`, `topicPolicy.topics`,
   `wordPolicy.customWords`, `wordPolicy.managedWordLists`,
   `sensitiveInformationPolicy.piiEntities`, `sensitiveInformationPolicy.regexes` and
   `contextualGroundingPolicy.filters` — where qualifying is determined by criteria 4, 5 and 10, and
   the emitted hits SHALL appear in a fixed section order independent of the key order in which the
   sections appear in the input (invariant property).
8. FOR ALL assessments, parsing a flat assessment and parsing the same assessment wrapped in a trace
   SHALL produce policy hit sequences that are equal position by position and field by field across
   all seven `PolicyHit` fields, excepting the location value that the shape determines
   (metamorphic property).
9. WHEN a response contains a `ResponseMetadata` key, THE Assessment_Parser SHALL exclude that key
   from the raw payload it exposes to the Demo_UI and SHALL preserve every other top-level key
   unchanged.
10. WHEN an assessment contains a finding within `wordPolicy.customWords`,
    `wordPolicy.managedWordLists`, `sensitiveInformationPolicy.piiEntities` or
    `sensitiveInformationPolicy.regexes`, THE Assessment_Parser SHALL emit a hit for that finding
    regardless of its action, including when the action is `NONE`.
11. WHEN the parsed input is an absent trace, an empty trace, a trace carrying no guardrail key, an
    absent `assessments` value or an empty `assessments` list, THE Assessment_Parser SHALL emit an
    empty policy hit sequence without raising an error.
12. FOR ALL assessments and for all repetition counts N between 1 and 10, an `outputAssessments`
    entry holding N identical copies of an assessment SHALL produce N consecutive repetitions of the
    policy hit sequence produced by a single copy (metamorphic property).

### Requirement 14: Pipeline invariants

**User Story:** As an attendee learning the central argument, I want the claims that a rejected
request costs no inference and that masked text is what the model receives to be enforced by tests,
so that the best moments of the demo are backed by more than a label in the UI.

#### Acceptance Criteria

1. WHEN the screen stage reports an intervention, THE Pipeline_Service SHALL complete the request
   with a `Converse` invocation count of zero, returning the screen stage result as the only stage
   result and naming the screen stage as the halting stage.
2. FOR ALL user inputs of 1 to 2000 characters that cause a screen-stage intervention, the count of
   foundation model invocations SHALL be zero and the count of reported stage results SHALL be one
   (invariant property).
3. WHEN the screen stage reports a sensitive-information finding with action `ANONYMIZE` and returns
   rewritten text, THE Pipeline_Service SHALL supply that rewritten text, character for character,
   as the text the answer stage sends to `Converse`.
4. FOR ALL user inputs containing a value matched by a sensitive-information rule configured with
   action `ANONYMIZE`, every text field of the `Converse` request, including the text carried inside
   `guardContent`, SHALL exclude that matched value as a substring (invariant property).
5. THE test suite SHALL assert every top-level parameter of the recorded `Converse` request for the
   masking case and SHALL compare the text inside `guardContent` against the expected rewritten
   text, so that a stub recording only the model identifier fails the assertion.
6. WHEN the screen stage reports no intervention and the answer stage reports no intervention, THE
   Pipeline_Service SHALL return stage results for the screen, answer and verify stages in that
   order, with no halting stage named.
7. WHEN the verify stage is called, THE Pipeline_Service SHALL supply exactly three text blocks: the
   reference document with the `grounding_source` qualifier, the user input as submitted with
   surrounding whitespace removed and screen-stage rewriting not applied with the `query` qualifier,
   and the answer stage's text with the `guard_content` qualifier, so that relevance is judged
   against the question the member actually asked.
8. FOR ALL stage results returned for any request, the reported model-invoked indicator SHALL be
   true for the answer stage result and false for the screen and verify stage results, regardless of
   which stage intervened (invariant property).
9. WHERE a request passes screening and both the screen stage and the answer stage report input
   findings, THE Background_View SHALL render a label alongside the answer stage's input findings as
   visible text within that stage's entry, without requiring hover or expansion, identifying those
   findings as a second evaluation of the same submitted text.
10. IF the screen stage reports no intervention and returns empty rewritten text, THEN THE
    Pipeline_Service SHALL supply the user input as submitted to the answer stage.
11. IF the answer stage reports an intervention, THEN THE Pipeline_Service SHALL complete the
    request with a verify-stage `ApplyGuardrail` invocation count of zero, returning stage results
    for the screen and answer stages only and naming the answer stage as the halting stage.
12. IF the submitted input exceeds the configured input-length limit of 2000 characters, THEN THE
    Pipeline_Service SHALL reject the request before the screen stage with zero `ApplyGuardrail`
    invocations and zero `Converse` invocations, and SHALL return an error naming the character
    limit.

### Requirement 15: Documentation accuracy

**User Story:** As a reader of this repository, I want every stated fact to match the committed code
and verified reality, so that the documentation is trustworthy when something breaks.

#### Acceptance Criteria

1. THE Runbook troubleshooting table SHALL reference only file paths that resolve in the committed
   tree, variables declared in the Infrastructure or the application configuration, and flags
   accepted by committed tooling, and SHALL state the Terraform `guardrail_tier` variable workflow
   and `shared/scenario.json` in place of the current references to `01_create_guardrail.py`,
   `scenario.py`, `--tier` and `--profile-id`.
2. WHERE the Runbook troubleshooting table and the RUNNING.md troubleshooting table describe the same
   symptom, identified by a matching AWS error name or a matching observable failure, THE Runbook
   SHALL report the same cause and the same fix as RUNNING.md, which is the reference table.
3. THE Documentation_Set SHALL describe the content filter configuration as six categories enabled on
   input and five on output, naming `PROMPT_ATTACK` as the single category whose output strength is
   `NONE`, and SHALL not state an unqualified category count.
4. THE Documentation_Set SHALL assert the originality of the scenario, policy set and code in exactly
   one named canonical location, and every other reference SHALL link to that location rather than
   restate the assertion.
5. WHERE the Documentation_Set asserts Bedrock availability in a Region, THE Documentation_Set SHALL
   cite the Validation_Log entry recording the source and the date of that confirmation.
6. THE Documentation_Set SHALL state that the national identity regex `\b[0-9]{8}\b` matches any
   eight-digit sequence delimited by non-digits, and SHALL state the observed guardrail action for a
   prompt containing both a national identity number and a phone number, citing the Validation_Log
   entry that recorded it.
7. THE Infrastructure SHALL declare only data sources referenced by at least one resource, local
   value or output, removing the currently unreferenced `aws_region` data source in
   `infrastructure/main.tf` and retaining `aws_caller_identity`, which `infrastructure/iam.tf`
   references.
8. WHERE a documented check depends on a live model answer clearing a grounding threshold, THE
   Documentation_Set SHALL state that the outcome is probabilistic and SHALL name the threshold
   value in force.
9. THE README opening paragraph SHALL state, within its first three sentences, that the repository
   contains both a presented demo and a self-paced lab, and SHALL distinguish observing the session
   from running the lab.
10. THE repository name SHALL match the description in the README opening paragraph, so that a reader
    arriving from a link is not told the repository is something other than what it provides.
11. THE smoke test SHALL report checks whose outcome depends on a probabilistic classification
    separately from checks whose outcome is deterministic.
12. IF a probabilistic check does not meet its expectation, THEN THE smoke test SHALL report it as
    inconclusive rather than failed, and SHALL exclude it from the exit status.
13. THE README repository-layout listing SHALL describe `frontend/` as the Landing_Page with its
    embedded Chat_Window, the Background_View and the Grounding_Tool, and SHALL replace any
    description of the frontend as a pipeline lane of stage cards, so that the description matches
    the committed structure.
14. THE README key-file table SHALL name, for each of the Landing_Page, the Chat_Window, the
    Background_View and the Grounding_Tool, the file that implements it, and SHALL state for each
    whether it is member-facing or engineer-facing.
15. THE Documentation_Set SHALL state that the Chat_Window calls the API directly from the browser
    because the frontend is a static export serving no server-side code, and SHALL cite the numbered
    ADR decision recording the static-export choice.
16. THE Documentation_Set SHALL state that the API performs no authentication, that the Landing_Page
    therefore presents no sign-in and implies none, and SHALL cite the numbered ADR decision
    recording the unauthenticated design.
17. THE Documentation_Set SHALL state that the PII Sample_Prompts entry carries invented values, and
    SHALL instruct readers to enter no real personal information into the Chat_Window.

---

### Part D — AWS Community Builder reviewers

### Requirement 16: Evidence of depth and measurement

**User Story:** As a Community Builder reviewer, I want to see measured results, honest limits and
original technical judgement, so that I can assess this as advanced work rather than a tutorial
retelling.

#### Acceptance Criteria

1. THE Documentation_Set SHALL present a results section containing one row for each of the five
   configured policy types (denied topics, content filters, word filters, sensitive information,
   contextual grounding), each row giving the count of prompts evaluated, the count of repetitions
   per prompt, and the observed count of outcomes per guardrail action, covering no intervention,
   blocked and anonymised.
2. THE Documentation_Set SHALL report the Tuning_Module false-positive measurement as four numbers
   over one labelled prompt set: the count of in-scope prompts evaluated, the count wrongly blocked
   before the topic definition was narrowed, the count wrongly blocked after it was narrowed, and
   the count of genuine violations still blocked after narrowing.
3. THE Documentation_Set SHALL label every claim in the results section with exactly one of
   measured, probabilistic or drawn from AWS documentation, and SHALL name, for each measured claim,
   the Conformance_Runner run that produced it, and for each documentation-derived claim, the AWS
   document it came from.
4. THE Documentation_Set SHALL state the limits of Bedrock Guardrails in a single section covering
   exactly four limits — identity, action enforcement, application-layer validation and
   probabilistic coverage — and SHALL state, for each limit, the control outside the guardrail that
   compensates for it.
5. THE Documentation_Set SHALL name the `bedrock:GuardrailIdentifier` IAM condition key as the
   mechanism that makes a guardrail an organisational control, and SHALL state that it constrains
   which guardrail identifier a caller may supply, so that a caller cannot invoke a model without
   the mandated guardrail.
6. THE README SHALL present, ahead of every other section, a single entry table with one row per
   reader purpose routing to the Lab_Guide, the Runbook, the ADR, the results section and the
   Demo_UI description, each row giving the reader purpose, exactly one destination link, and the
   expected reading or running time in minutes.
7. THE Documentation_Set SHALL state the relationship between this repository and the published AWS
   Bedrock Guardrails workshop in a single subsection that links to that workshop, states which
   material is derived from it, and names the four additions this repository makes: the three-stage
   screen, answer and verify pipeline that calls `ApplyGuardrail` before any model invocation,
   contextual grounding supplied inline without a knowledge base, the CLASSIC-to-STANDARD tier-gap
   demonstration, and the two-view Demo_UI in which one request is rendered both as the member sees
   it and as the policy engine executed it.
8. THE Documentation_Set SHALL state the reproduction steps for the reported measurements as an
   ordered numbered list giving, for each step, the command a reviewer runs and the expected
   observable output, and SHALL state the total expected duration in minutes and the total expected
   cost in United States dollars by reference to the Cost_Statement.
9. WHEN a measurement is reported in the results section, THE Documentation_Set SHALL state the date
   it was observed, the AWS Region, the guardrail tier in force and the guardrail version evaluated.
10. IF a configured policy type has no measured outcome at the time of publication, THEN THE
    Documentation_Set SHALL show that policy type in the results section marked as not measured,
    together with the reason, rather than omitting it.
11. THE ADR SHALL state, for each of its numbered decisions, the alternative that was rejected and
    the reason for rejecting it, so that a reviewer can distinguish original technical judgement
    from default choices.
12. THE README SHALL describe the Demo_UI in at most three sentences that name the Landing_Page, the
    Chat_Window, the Background_View and the Grounding_Tool, and SHALL state that the Chat_Window is
    member-facing while the Background_View and the Grounding_Tool are engineer-facing.
13. THE Documentation_Set SHALL state, for the two-view addition named in criterion 7, the case in
    which the gap between the two views is largest, namely the sensitive-information masking case in
    which the member observes nothing unusual while the Background_View shows the name, phone number
    and member number replaced before the model received the text.

---

### Part E — The member-facing experience

Part E specifies the restructured Demo_UI: a co-operative landing page with an embedded chat window
as the Member_View, the three-stage pipeline retained as the Background_View, and the grounding
check retained as a separate engineer-facing instrument. The pedagogical purpose is the gap between
the two views. A member reading a refusal cannot tell that a denied topic named
`Agrochemical Dosing` blocked the request and that no foundation model was ever invoked; a member
reading an answer about their payment cannot tell that their name, phone number and member number
were replaced before the model saw the text. Making the member's view honest is what makes the
engineer's view worth showing.

### Requirement 17: The co-operative landing page

**User Story:** As a co-operative member, I want a page that presents Highland Growers Co-operative
the way a real organisation would, so that I meet the assistant in the context a real member would
meet it rather than inside an engineering console.

#### Acceptance Criteria

1. THE Landing_Page SHALL present the organisation name, the assistant name and the county from the
   `org`, `assistant` and `county` values returned by `GET /api/context`, and the frontend source
   SHALL hold no second copy of those values.
2. THE Landing_Page SHALL present a collection-point section derived from the `bulletin` value
   returned by `GET /api/context`, showing the two collection points Kangema and Kiriaini, the
   opening window 06:00 to 10:00, the two collection days Tuesday and Friday, and the requirement to
   present a valid member number at the gate.
3. THE Landing_Page SHALL present a payment section derived from the same `bulletin` value, stating
   that payment for delivered produce is released fourteen days after grading is complete and that
   grading results are posted at the collection point.
4. THE Landing_Page SHALL present between 3 and 6 titled sections, comprising at minimum who the
   co-operative is, what it does for its members, collection points and payment cycles, each section
   rendered as visible text without requiring expansion or hover.
5. WHERE the Landing_Page presents any scenario content, THE Landing_Page SHALL take that content
   from `GET /api/context` or from a Sample_Prompts entry, so that `shared/scenario.json` remains the
   single source of truth and the frontend introduces no scenario text of its own.
6. IF `GET /api/context` fails, THEN THE Landing_Page SHALL display the failing endpoint and the
   returned error text at a computed font size of at least 14 CSS pixels, SHALL mark each section
   that depends on the unavailable context as unavailable rather than rendering substitute content,
   and SHALL keep the Demo_Disclosure visible.
7. THE Landing_Page SHALL display the Demo_Disclosure at a computed font size of at least 14 CSS
   pixels in a position that remains visible at every scroll position of the page, stating that the
   page is a demonstration and that Highland Growers Co-operative, Kilimo Desk, Project Tumaini,
   Batch Ledger v2 and Extension Bulletin 14 are fictional and that the co-operative does not exist.
8. THE Demo_Disclosure SHALL state that the API serving the page performs no authentication and
   SHALL instruct the reader to enter no real personal information into the Chat_Window.
9. THE Landing_Page SHALL present exactly one free-text input, the Chat_Window message field, and
   every other control on the page SHALL be one of a Sample_Prompts control, the control that opens
   the Background_View, or the control that opens the Grounding_Tool, so that the page offers no
   sign-in, no registration and no password entry that the API could not honour.
10. THE Landing_Page SHALL be the entry route of the Demo_UI, so that the first view a visitor
    reaches is the Member_View rather than the Background_View or the Grounding_Tool.
11. THE Landing_Page SHALL present the Chat_Window within a viewport of 1280 by 720 CSS pixels at the
    entry scroll position without scrolling, so that the assistant is reachable without hunting for
    it during a presented session.

### Requirement 18: The chat window as an ordinary member experience

**User Story:** As a co-operative member, I want to ask a question and get an answer, so that I
experience the assistant as any end user of a production system would, with none of the policy
machinery on display.

#### Acceptance Criteria

1. THE Chat_Window SHALL maintain a message history for the current session presenting each member
   turn and each assistant turn in the order they occurred, each turn labelled by its speaker as
   visible text.
2. WHEN a member submits a message, THE Chat_Window SHALL append the member turn to the history
   before the `POST /api/ask` call begins, so that the pending state is attached to a visible
   question.
3. WHEN `POST /api/ask` returns successfully, THE Chat_Window SHALL render the assistant turn as the
   response `final` value character for character, and SHALL render no other field of that response.
4. FOR ALL responses returned by `POST /api/ask`, the text rendered in the assistant turn SHALL equal
   the response `final` value and SHALL contain none of the policy names, policy types, stage names,
   guardrail actions, scores, thresholds, latency values, `stopped_at` values or AWS identifiers
   carried by that response (invariant property).
5. WHILE a `POST /api/ask` request is in flight, THE Chat_Window SHALL display a pending indicator as
   visible text, SHALL keep the submitted member turn visible, and SHALL hold the submit control in a
   disabled state so that at most one such request is in flight at a time.
6. WHERE the screen stage blocked the request, THE Chat_Window SHALL render the returned `final`
   value, which is the `blocked_input_message` text, in the same visual treatment as any other
   assistant turn, so that a refusal is indistinguishable in form from an answer.
7. WHERE the answer stage or the verify stage blocked the response, THE Chat_Window SHALL render the
   returned `final` value, which is the `blocked_output_message` text, in the same visual treatment as
   any other assistant turn, so that a grounding failure reaches the member as the safe fallback
   rather than as an invented answer.
8. WHERE the screen stage anonymised the submitted text, THE Chat_Window SHALL render the member turn
   as the text the member typed and the assistant turn as the `final` value, and the rendered turns
   SHALL contain no masking placeholder token and no sensitive-information rule name, so that nothing
   in the member's view indicates that masking occurred.
9. IF `POST /api/ask` fails or returns no response within 30 seconds, THEN THE Chat_Window SHALL
   render a failure message in place of the assistant turn at a computed font size of at least 16 CSS
   pixels, naming the endpoint called and the returned error text, and SHALL retain the member turn
   and every preceding turn.
10. THE Chat_Window SHALL accept submissions of 1 to 2000 characters, matching the input-length limit
    the Pipeline_Service enforces under Requirement 14.
11. IF the entered text is empty after surrounding whitespace is removed or exceeds 2000 characters,
    THEN THE Chat_Window SHALL display a message naming the violated limit and SHALL make no call to
    `POST /api/ask`.
12. THE Chat_Window message field SHALL display a hint at a computed font size of at least 14 CSS
    pixels directing the reader to the Sample_Prompts or to invented values and instructing the
    reader to enter no real personal information.
13. THE Chat_Window SHALL retain the message history across every opening and closing of the
    Background_View and the Grounding_Tool within one session, so that a presenter can return to the
    member's view without re-sending the prompt.

### Requirement 19: Sample prompts reachable from the chat window

**User Story:** As the presenter, I want to fire any demonstration prompt from inside the chat
window without typing, so that I reach a specific policy in one action while the audience watches
the member's view.

#### Acceptance Criteria

1. THE Chat_Window SHALL present the Sample_Prompts as activatable controls grouped by the group
   labels held in `frontend/src/lib/samples.ts`, retaining the eight labels `in scope`, `dosing`,
   `land`, `credit`, `internal leak`, `PII`, `prompt attack` and `tier gap`, each label rendered as
   visible text at a computed font size of at least 14 CSS pixels.
2. THE Chat_Window SHALL present every prompt of every group, comprising the 9 prompts across 8
   groups held in `PROMPT_GROUPS` as committed, and SHALL make any one of them reachable within at
   most 2 activations from the Landing_Page entry route.
3. WHEN a Sample_Prompts control is activated, THE Chat_Window SHALL submit that prompt text
   character for character as a member turn without requiring a keystroke, and SHALL render the
   member turn as that prompt text so that the audience reads the question the assistant was asked.
4. THE Sample_Prompts SHALL reside in exactly one frontend module, and the Chat_Window together with
   every other consumer SHALL read both the group labels and the prompt text from that module.
5. IF a Sample_Prompts control is activated WHILE a `POST /api/ask` request is in flight, THEN THE
   Chat_Window SHALL leave the in-flight request unchanged and make no further call.
6. WHERE the Runbook names a Sample_Prompts entry for a segment, THE Runbook SHALL give the group
   label and the prompt text verbatim, so that the presenter locates the control without reading the
   frontend source.
7. THE `PII` Sample_Prompts entry SHALL carry only invented values, comprising the name
   `Grace Wanjiku`, the member number `HG-004182` and the phone number `0722135790`.
8. WHERE a Sample_Prompts group holds more than one prompt, THE Chat_Window SHALL present each prompt
   of that group as its own control, so that a presenter selects a specific prompt rather than a
   group.

### Requirement 20: The background view of what the system did

**User Story:** As an engineer in the audience, I want to see what the policy engine did for the
request the member just sent, so that I learn the mechanism behind the answer or refusal I have
already read.

#### Acceptance Criteria

1. WHEN `POST /api/ask` returns successfully, THE Background_View SHALL become reachable for that
   response from the Landing_Page by at most one activation of a control rendered at a computed font
   size of at least 16 CSS pixels.
2. THE Background_View SHALL present one entry per element of the response `stages` array in array
   order, each entry naming the stage, its intervened indicator, its model-invoked indicator, its
   latency in milliseconds, and each of its policy findings with the policy name, the detail, the
   action and the input-or-output location.
3. THE Background_View SHALL present the response `stopped_at` value and the `total_latency_ms` value
   as visible text.
4. WHERE the response `stages` array holds fewer than three entries, THE Background_View SHALL
   present each pipeline stage absent from the array as not run, naming that stage and naming the
   halting stage that prevented it, so that a halt reads as work that did not happen rather than as
   missing interface.
5. WHERE a stage entry reports a model-invoked indicator of false, THE Background_View SHALL label
   that stage `ApplyGuardrail · no model` under the sizing rule of Requirement 6 criterion 1, so that
   a request rejected before inference is visibly free of a model call.
6. WHERE the screen stage anonymised the submitted text, THE Background_View SHALL present the screen
   stage `text` value as the text forwarded to the answer stage and SHALL name each
   sensitive-information rule that matched together with its action, so that masking is visible to
   the engineer and to nobody in the Member_View.
7. THE Background_View SHALL present the guardrail identifier, the guardrail version, the Region and
   the model identifier returned by `GET /api/context`, so that the findings are attributable to one
   guardrail configuration.
8. THE Background_View SHALL present the raw payload of each stage from that stage's `raw` value and
   SHALL keep each raw payload collapsed until its control is activated.
9. WHERE Replay_Mode served the displayed response, THE Background_View SHALL apply the labelling
   required by Requirement 7 criterion 8.
10. WHEN the Background_View is closed, THE Chat_Window SHALL present the message history unchanged.
11. IF the Background_View is opened before any request has completed in the current session, THEN
    THE Background_View SHALL state that no request has been sent and SHALL name the control that
    sends one.
12. THE Background_View SHALL render every policy name, action and score as the value the response
    carried, without rewording, so that a reader can match the Background_View against the raw
    payload of the same stage.

### Requirement 21: One request, two views

**User Story:** As the presenter, I want the member's view and the background view to describe the
same single request, so that the contrast I am teaching cannot be an artefact of two different
evaluations of the same prompt.

#### Acceptance Criteria

1. WHEN a member submits one message, THE Demo_UI SHALL issue exactly one `POST /api/ask` request and
   SHALL derive both the assistant turn and every Background_View entry from that single response.
2. FOR ALL completed requests, the text rendered in the assistant turn SHALL equal the `final` value
   of the same response whose `stages` array the Background_View renders (invariant property).
3. FOR ALL completed requests, the count of stage entries the Background_View renders SHALL equal the
   length of the `stages` array of that response, and each rendered entry SHALL carry the stage name
   at the same array index (invariant property).
4. WHILE a response is displayed, THE Demo_UI SHALL make no further `POST /api/ask` call to populate
   or refresh the Background_View, so that the two views cannot disagree because a second evaluation
   returned a different probabilistic classification.
5. THE Background_View SHALL present the member turn text of the request it displays, so that the
   correspondence between the two views is readable in the Background_View alone.
6. WHEN a subsequent message completes, THE Background_View SHALL present the stages of the most
   recent completed response together with the member turn text it corresponds to.
7. WHERE the Demo_UI retains more than one completed response in the current session, THE
   Background_View SHALL allow selection of any retained response by its member turn text and SHALL
   present only the stages of the selected response.
8. IF a request fails before a response is returned, THEN THE Background_View SHALL present the
   failure with the failing stage named and present any stage that completed, and THE Chat_Window
   SHALL present the failure message required by Requirement 18 criterion 9.
9. THE Runbook SHALL state, for each of the dosing block, the sensitive-information masking case and
   a grounding failure, the prompt submitted, the Member_View text the audience reads first, the
   Background_View finding revealed second, and the one sentence naming what the member could not
   see.

### Requirement 22: The grounding check remains a separate engineer-facing instrument

**User Story:** As an attendee, I want the grounding check to stay a tool I drive directly with my
own question and answer, so that I can probe the thresholds without going through a member request.

#### Acceptance Criteria

1. THE Grounding_Tool SHALL be reachable from the Landing_Page by at most one activation of a control
   labelled as an engineer-facing tool, and SHALL be presented outside the Chat_Window.
2. THE Grounding_Tool SHALL retain the three committed cases held in `frontend/src/lib/samples.ts` —
   grounded and relevant, ungrounded with invented detail, and grounded but irrelevant — each
   presenting its question, its candidate answer and its expected outcome as visible text.
3. WHEN a Grounding_Tool case is submitted, THE Grounding_Tool SHALL call `POST /api/verify` with that
   case's question and answer and SHALL present the returned grounding score, the returned relevance
   score, the threshold in force for each, and the pass indicator per filter.
4. THE Grounding_Tool SHALL present the reference document used as the grounding source from the
   `bulletin` value returned by `GET /api/context`.
5. THE Grounding_Tool SHALL accept an operator-entered question of 1 to 2000 characters and an
   operator-entered answer of 1 to 2000 characters, so that a case beyond the three committed ones
   can be evaluated.
6. IF `POST /api/verify` fails or returns no response within 30 seconds, THEN THE Grounding_Tool SHALL
   present the endpoint called and the returned error text at a computed font size of at least 14 CSS
   pixels and SHALL retain the previously presented result.
7. WHILE the Grounding_Tool is presented, THE Demo_Disclosure SHALL remain visible.
8. THE Documentation_Set SHALL state that the Grounding_Tool exercises `POST /api/verify` directly,
   that it sits outside the member request path, and that the verify stage of a member request appears
   in the Background_View instead.
9. THE Runbook SHALL place the Grounding_Tool segment to start at or after the end time of the segment
   that shows a grounding failure in the Member_View, so that the member-facing fallback message is
   shown before the scores that produced it.
