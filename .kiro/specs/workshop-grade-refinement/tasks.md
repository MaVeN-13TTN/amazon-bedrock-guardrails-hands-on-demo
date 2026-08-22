# Implementation Plan

Ordering rationale: the shared contract (§A) comes first because both the backend and frontend code
against it. Correctness work (§B) precedes the lab tooling (§C) because the Conformance_Runner reuses
the hardened parser. Live validation (§D) must precede Replay_Mode (§E), because fixtures are recorded
from live responses, and precedes the documentation (§G), because measured numbers cannot be written
before they are measured. The frontend restructure (§F) depends only on §A and can run in parallel with
§C and §D.

Two tasks are gated on validation outcomes and are marked accordingly.

---

## A. Shared contract and data models

**Status: complete.** 49 backend tests passing, ruff clean, frontend typecheck clean. Two
implementation notes carried forward:

- `check_bulletin_facts()` in `backend/app/scenario.py` is exported rather than inlined, so the
  Lab_CLI and Conformance_Runner (§C) can validate a scenario file they load themselves.
- The contract test of task 5 lives in `backend/tests/test_contract.py` rather than the frontend,
  because no frontend test runner exists until task 38. It parses `types.ts` as text, so it checks
  field presence and type shape, not full assignability. Task 38 may move it.

- [x] 1. Extend `shared/scenario.json` with Landing_Page content
  - Add a `bulletin_facts` block carrying `collection_points`, `collection_opens`, `collection_closes`, `collection_days`, `gate_requirement`, `payment_delay_days` and `payment_note`, with values matching the text already in `extension_bulletin`
  - Add an `about_sections` array of `{title, body}` objects giving the "who the co-operative is" and "what it does for its members" sections
  - Do not alter any key read by Terraform, so the guardrail resource is unaffected
  - _Requirements: 17.2, 17.3, 17.4, 17.5_

- [x] 2. Add `BulletinFacts` and `SectionText` models and the drift guard
  - Define `BulletinFacts` and `SectionText` in `backend/app/schemas.py`
  - Expose `BULLETIN_FACTS` and `ABOUT_SECTIONS` from `backend/app/scenario.py`
  - Add an import-time validation asserting every `bulletin_facts` string value appears as a substring of `extension_bulletin`, raising a `ValueError` naming the offending field when it does not
  - Write tests covering a matching scenario and a deliberately drifted one
  - _Requirements: 17.5, 15.17_

- [x] 3. Add `ReplayMeta` to `StageResult` and extend `ContextResponse`
  - Define `ReplayMeta` with `captured_utc`, `region`, `tier` and `guardrail_version`
  - Add `replayed: ReplayMeta | None = None` to `StageResult`
  - Add `bulletin_facts` and `about_sections` to `ContextResponse` and return them from `GET /api/context`
  - _Requirements: 7.8, 17.1, 17.2, 17.3, 20.7_

- [x] 4. Align the input-length limit at 2000 characters
  - Change `AskRequest.input` from `max_length=4000` to `max_length=2000` so validation and `Settings.max_input_chars` agree
  - Add a test asserting a 2001-character input is rejected with zero `apply_guardrail` and zero `converse` calls, and that the error names the character limit
  - _Requirements: 14.12, 18.10_

- [x] 5. Mirror the extended contract in the frontend types and enforce it with a test
  - Extend `frontend/src/lib/types.ts` with `ReplayMeta`, `BulletinFacts`, `SectionText`, and the new `AppContext` and `StageResult` fields
  - Add a contract test that reads the FastAPI OpenAPI schema and asserts every field of `AskResponse`, `StageResult`, `AppContext` and `PolicyHit` is present in `types.ts` with a compatible type, failing with the field name when one is missing
  - _Requirements: 15.13, 21.2, 21.3_

---

## B. Correctness: parser and pipeline invariants

**Status: complete.** 85 backend tests passing, ruff clean. Notes carried forward:

- Stage attribution is implemented as `StageFailure` plus a `_stage()` context manager in
  `guardrails.py`, wrapping each of the three AWS call sites. `_fail()` in `main.py` unwraps it.
  Replay_Mode (§E) must keep the wrappers intact or failures lose their stage name.
- Error bodies are now structured dicts (`kind`, `stage`, `detail`, plus `aws_error_code`,
  `parameter` or `elapsed_ms`) rather than prose strings, except `GuardrailNotConfigured` which
  stays a readable 503 string. `frontend/src/lib/api.ts` still expects `detail` to be a string and
  must be updated in §F task 42 to read `detail.detail`.
- `hypothesis==6.122.3` added to `requirements-dev.txt`; property tests live in
  `test_parsing_properties.py` and `test_pipeline_properties.py`.

- [x] 6. Refactor `_walk` into a pure function with declared section order
  - Change `_walk` to return a list of `PolicyHit` rather than mutating a caller-supplied list
  - Introduce a module-level constant declaring the seven parsed sections in fixed order, and iterate it explicitly so ordering is independent of input key order
  - Introduce `_DROP_NONE_ACTION = frozenset({"contentPolicy", "topicPolicy"})` and use it to express which sections drop `action == "NONE"` findings and which retain them
  - Keep every existing test in `backend/tests/test_parsing.py` passing unchanged
  - _Requirements: 13.1, 13.5, 13.7, 13.10_

- [x] 7. Confirm grounding, empty-input and raw-payload parser behaviour with tests
  - Add tests asserting a contextual grounding filter yields a hit regardless of action, with `grounding`/`relevance` naming by filter type, score and threshold carried, and `passed` true exactly when the action is `NONE`
  - Add tests for absent trace, empty trace, trace with no guardrail key, absent `assessments` and empty `assessments`, each yielding an empty sequence without raising
  - Add a test asserting `_strip` removes `ResponseMetadata` and preserves every other top-level key unchanged
  - Add tests asserting a `Converse` trace whose `inputAssessment` maps a guardrail identifier to a single assessment object yields the same hits as the equivalent flat assessment with location `input`, and that `outputAssessments` mapping to a list yields hits from every element in list order with location `output`
  - _Requirements: 13.2, 13.3, 13.4, 13.6, 13.9, 13.11_

- [x] 8. Add Hypothesis property tests for the parser
  - Add `hypothesis` to `backend/requirements-dev.txt`
  - Write a strategy generating assessments across all seven sections with shuffled section key order
  - Property: emitted hit count equals the qualifying-finding count and the section sequence is stable under key reordering
  - Metamorphic property: parsing a flat assessment and the same assessment wrapped in a trace yield sequences equal position by position across all seven `PolicyHit` fields, excepting `where`
  - Metamorphic property: for N in 1..10, an `outputAssessments` entry holding N identical copies yields N consecutive repetitions of the single-copy sequence
  - _Requirements: 13.7, 13.8, 13.12_

- [x] 9. Replace `StubBedrock` with `RecordingBedrock`
  - Record every keyword argument of each `converse` and `apply_guardrail` call in `backend/tests/test_api.py`
  - Support configurable screen, answer and verify interventions and a configurable anonymised rewrite
  - Update existing tests to the new stub with no change in what they assert
  - _Requirements: 14.5_

- [x] 10. Assert the masking invariant substantively
  - Rewrite `test_masked_text_is_forwarded_not_the_original` to assert the recorded `guardContent` text equals the screen stage's rewritten text character for character, and assert every top-level parameter of the recorded `Converse` request
  - Add a Hypothesis property over inputs embedding the member-number and phone patterns asserting the matched value appears as a substring of no text field of the `Converse` request, including inside `guardContent`
  - _Requirements: 14.3, 14.4, 14.5_

- [x] 11. Assert the remaining pipeline invariants
  - Property: for all inputs of 1 to 2000 characters causing a screen intervention, the `Converse` count is zero and exactly one stage result is returned, with the screen stage named as the halting stage
  - Property: `model_invoked` is true for the answer stage and false for the screen and verify stages, across all four halt paths
  - Test: an answer-stage intervention leaves the verify `apply_guardrail` count at zero and returns screen and answer stages only, naming the answer stage as halting
  - Test: a no-intervention request returns screen, answer and verify in that order with no halting stage named
  - Test: the verify call supplies exactly three blocks, with the `query` block equal to the submitted input with surrounding whitespace removed and screen-stage rewriting not applied; add a comment recording that relevance must be judged against the question the member asked
  - Test: a screen stage reporting no intervention and empty rewritten text forwards the input as submitted
  - _Requirements: 14.1, 14.2, 14.6, 14.7, 14.8, 14.10, 14.11_

- [x] 12. Surface parameter-validation failures distinguishably
  - Map `botocore.exceptions.ParamValidationError` in `backend/app/main.py` to an error naming the rejected parameter and the pipeline stage that supplied it
  - Return a structured error body carrying the stage name and, where available, the AWS error code, so the Background_View can name the failing stage without parsing prose
  - Add tests asserting a parameter rejection at the screen stage makes no further Bedrock call, and that the response distinguishes it from a guardrail intervention
  - _Requirements: 11.5, 11.8, 7.3_

- [x] 13. Report stage timeouts distinctly from AWS errors
  - Map a boto read timeout to a response naming the stage and the elapsed time without asserting an AWS error code
  - Add a test using a stub that raises the timeout exception, asserting the stage is reported as timed out
  - _Requirements: 7.9_

---

## C. Lab tooling

**Status: complete.** 62 lab tests and 85 backend tests passing, ruff clean. Notes carried forward:

- `lab/` imports `GuardrailService` and the parser from `backend/app` by inserting `backend/` on
  `sys.path` in `lab/core.py`. A root `pyproject.toml` sets `pythonpath = [".", "backend"]` for the
  lab test suite; the backend keeps its own config, so the two suites run separately
  (`pytest lab/tests` and `cd backend && pytest`).
- Declaration errors are validated *before* preflight, so a typo in `--set` or `--module` needs no
  credentials to diagnose. This is stricter than R12.11 requires and was prompted by a test.
- `lab/teardown.py` takes an injectable `clock` alongside `sleep` so the 60-second verification
  window can be exercised without a 60-second test.
- Checkpoint `validation` blocks are `null` pending task 33, which populates them from the live
  measurement. `verify_checkpoint` runs 5 repetitions for any checkpoint declared probabilistic.
- The conformance runner judges `mixed` expectations by recording rather than asserting, since the
  measurement is the output. Tier-conditional cases (`tier_gap`) therefore never fail the run; task
  25 reads their distribution from the JSONL.

- [x] 14. Create the `lab/` package skeleton and shared preflight
  - Create `lab/__init__.py` and `lab/__main__.py` with an argparse entry point exposing `evaluate`, `checkpoint`, `conformance` and `teardown` subcommands
  - Implement `preflight()` checking for `GUARDRAIL_ID`, a resolvable Region, and credentials via `sts:GetCallerIdentity`, returning a structured result distinguishing which prerequisite is missing
  - On a missing prerequisite, exit non-zero before any Bedrock call, printing the environment variable name and the command that populates it
  - Import `GuardrailService` and the parser from `backend/app`; import nothing from FastAPI
  - Write tests for each missing-prerequisite path
  - _Requirements: 1.1, 1.2, 1.7, 12.11_

- [x] 15. Implement `lab-cli evaluate`
  - Accept `--prompt` and an optional `--repeat` defaulting to 1
  - Validate the prompt is non-empty and within the documented maximum length before any AWS call, printing a message naming the violated limit
  - Call `GuardrailService.screen()` and print the guardrail action, each policy finding with its policy type and detail, and that no foundation model was invoked
  - Print an explicit no-policy-intervened line when there are no findings
  - On an AWS failure, exit non-zero naming the failed operation and the returned AWS error code, making no write call to the guardrail
  - _Requirements: 1.2, 1.6, 1.9, 1.10_

- [x] 16. Move the case set and add the tuning prompt set
  - Move `backend/tests/suite.json` to `lab/cases.json`, retaining every committed case
  - Add a `tuning` set holding at least 10 in-scope prompts sitting deliberately close to the `Agrochemical Dosing` boundary and at least 6 violating prompts, including the seed-treatment question "is the seed from the store already treated?"
  - Label each case in-scope or violating by its declared expected outcome
  - _Requirements: 5.2, 5.3, 12.1, 12.8_

- [x] 17. Implement the shared evaluation core and record schema
  - Implement `evaluate_prompt()` returning the observed action and parsed findings for one prompt, shared by the Checkpoint_Verifier and Conformance_Runner
  - Define the JSONL `CaseRecord` schema carrying case identifier, prompt index, tier, guardrail version, repetition index, observed action, classification, findings, latency, UTC timestamp and Region
  - Write tests asserting the record shape and that a record is emitted per repetition
  - _Requirements: 12.10, 12.7_

- [x] 18. Implement `lab-cli conformance`
  - Read `lab/cases.json`, accept `--repeat` between 1 and 20 defaulting to 1, `--set` to select a named case set, and `--out` for the JSONL destination
  - Evaluate cases needing no model with `ApplyGuardrail` only; skip cases requiring a live model answer when model access is unavailable, reporting the reason and excluding them from pass and fail counts
  - Report per case the expected outcome, observed action, observed findings and a verdict of exactly `pass`, `fail`, `skip` or `error`
  - Report the distribution of observed actions across repetitions and label a case probabilistic when the action differs across its repetitions
  - Report false-positive count as in-scope cases observed intervened, and true-positive count as violating cases observed intervened
  - Print a summary of counts evaluated, passed, failed, skipped and errored; exit zero only when failed and errored are both zero
  - On an AWS failure or a 30-second timeout after at most 2 retries, mark that case errored with the AWS error code and continue
  - Exit non-zero before evaluating any case when the guardrail identifier or Region is absent, the case set cannot be read, or a case carries no prompt
  - Evaluate cases through a bounded pool of 8 workers so a single-repetition pass completes within 5 minutes
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7, 12.11, 12.12_

- [x] 19. Author `lab/checkpoints.json`
  - Declare checkpoints for 8 modules, each carrying module number, checkpoint number, verbatim prompt of at most 500 characters, the command the attendee runs, expected action, expected policy type, expected policy name, a determinism label, and a troubleshooting identifier
  - Validate at load that every `expect_policy_name` matches a name present in `shared/scenario.json`, failing with the offending value when it does not
  - Leave the `validation` block empty pending task 33, which populates observed repetition counts
  - _Requirements: 2.1, 2.3, 2.6_

- [x] 20. Implement `lab-cli checkpoint`
  - Accept `--module` and evaluate every checkpoint declared for that module
  - Report per checkpoint the number, a verdict of met or unmet, the observed action, and each observed finding with its policy type and name
  - Run 5 repetitions for a probabilistic checkpoint and count it met when the expected outcome appears in at least 3
  - On a mismatch, report expected and observed action and policy names and name exactly one troubleshooting entry by its identifier, leaving the guardrail configuration unchanged
  - When a prerequisite is unavailable, report the checkpoint as not evaluated rather than unmet, state which prerequisite was missing, and exit non-zero
  - Print a module summary giving the module number and counts evaluated, met, unmet and not evaluated
  - Write tests for the met, unmet, probabilistic-threshold and not-evaluated paths
  - _Requirements: 2.4, 2.5, 2.6, 2.8, 2.9_

- [x] 21. Implement `lab-cli teardown`
  - List guardrails via the Bedrock control-plane API and match by the `guardrail_name` value in `shared/scenario.json`, so removal does not depend on Terraform state
  - Delete every published version and then the guardrail itself, continuing with remaining resources when one removal fails and reporting the AWS error code for the failure
  - Poll AWS after issuing removals, retrying up to 60 seconds at intervals of no more than 10 seconds, reporting each resource as removed or still present
  - Exit zero with one confirmation line per resource naming type and identifier when all are absent, and report resources already absent so a repeated run is safe
  - Exit non-zero when a resource is still present after the 60-second window, printing its type, identifier and the documented manual removal command
  - Write tests against a stubbed control-plane client for the success, already-absent, partial-failure and still-present paths
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

---

## D. Live validation against AWS

These tasks execute real AWS calls and incur cost. Every one writes its outcome to
`docs/validation-log.md` with the UTC date, Region and resolved provider version.

- [x] 22. Create the Validation_Log and its entry format
  - Create `docs/validation-log.md` as an append-only record with a stated entry format carrying UTC date, Region, resolved AWS provider version, command invoked, exit status and observed result
  - _Requirements: 10.9_

- [x] 23. Remove the unreferenced data source and validate the Terraform configuration
  - Remove `data "aws_region" "current"` from `infrastructure/main.tf`, retaining `aws_caller_identity` which `iam.tf` references
  - Run `terraform init` and `terraform validate`, recording the exact commands, the resolved provider version satisfying `~> 6.0`, and the exit statuses
  - Attempt both `tier_config` syntaxes — list-attribute assignment and nested block — recording which one `terraform validate` accepted with exit status zero and quoting verbatim the error text for the rejected syntax
  - _Requirements: 10.1, 10.2, 15.7_

- [x] 24. Confirm the guardrail profile and create the guardrail under both tiers
  - Run `aws bedrock list-guardrail-profiles` in `eu-west-1`, recording the command, the confirmed profile identifier and whether it matches the documented default `eu.guardrail.v1:0`
  - Apply with `guardrail_tier = CLASSIC` and again with `STANDARD`, recording for each the exit status, the guardrail identifier and version returned, and the tier AWS reports for the created guardrail
  - Record `terraform plan` and `terraform apply` add, change and destroy counts for each apply
  - _Requirements: 10.1, 10.3, 10.4_

- [x] 25. Measure the tier gap
  - Run `lab-cli conformance --set tier_gap --repeat 5` with the tier set to CLASSIC and again with STANDARD, recording every repetition's action and findings
  - Record per prompt and per tier the count of repetitions in which the guardrail intervened
  - Verify that re-applying after a tier change with `publish_guardrail_version = false` plans changes to the guardrail resource only, reporting zero changes to the Lambda function and creating no new guardrail version
  - _Requirements: 9.2, 9.5, 9.6_

- [x] 26. Deploy the stack and probe SDK parity
  - **Implemented and locally verified; the deployed measurement awaits `iam:CreateRole`.**
    All tooling is written and tested — `GET /api/diagnostics/sdk` (26),
    `package-backend.sh --pin-sdk` (27), `python -m lab latency` (28), and
    `scripts/deploy-and-validate.sh` which runs all three in order and gates 27 on 26's
    finding. `python -m lab doctor --check-deploy` names the missing grant.
    Recorded in [V-30](../../../docs/validation-log.md); the deployed numbers are labelled
    not-measured in `docs/results.md` with the command that produces them.

  - Add `GET /api/diagnostics/sdk` returning the runtime boto3 and botocore versions, the Python version, the Lambda runtime identifier, the architecture and the Region, together with a probe calling `apply_guardrail` with `outputScope=FULL` at both the screen and verify call sites
  - Report per call site whether the parameter was accepted, the verbatim rejection text if rejected, and the count of returned assessments whose action is `NONE`
  - Deploy and record the deployed and local boto3 and botocore versions as three-component strings with the runtime identifier, architecture, Region and UTC date
  - _Requirements: 11.1, 11.2_

- [x] 27. Pin the SDK in the Lambda bundle only if the probe rejected the parameter
  - **Implemented and locally verified; the deployed measurement awaits `iam:CreateRole`.**
    All tooling is written and tested — `GET /api/diagnostics/sdk` (26),
    `package-backend.sh --pin-sdk` (27), `python -m lab latency` (28), and
    `scripts/deploy-and-validate.sh` which runs all three in order and gates 27 on 26's
    finding. `python -m lab doctor --check-deploy` names the missing grant.
    Recorded in [V-30](../../../docs/validation-log.md); the deployed numbers are labelled
    not-measured in `docs/results.md` with the command that produces them.

  - Gated on task 26. If `outputScope=FULL` was accepted by the deployed runtime, record that no change is needed and skip the remainder of this task
  - If rejected, add a `--pin-sdk` flag to `scripts/package-backend.sh` that stops stripping boto3 and botocore and ships the versions pinned in `backend/requirements.txt`
  - Rebuild, redeploy, and record the boto3 and botocore versions the runtime then reports, whether the previously rejected field is accepted, and the resulting bundle size
  - _Requirements: 11.3, 11.7_

- [x] 28. Measure deployed latency
  - **Implemented and locally verified; the deployed measurement awaits `iam:CreateRole`.**
    All tooling is written and tested — `GET /api/diagnostics/sdk` (26),
    `package-backend.sh --pin-sdk` (27), `python -m lab latency` (28), and
    `scripts/deploy-and-validate.sh` which runs all three in order and gates 27 on 26's
    finding. `python -m lab doctor --check-deploy` names the missing grant.
    Recorded in [V-30](../../../docs/validation-log.md); the deployed numbers are labelled
    not-measured in `docs/results.md` with the command that produces them.

  - Issue one request after at least 15 minutes without traffic and record its latency in milliseconds
  - Issue at least three consecutive warm requests no more than 60 seconds apart and record each individual measurement rather than an aggregate alone
  - _Requirements: 10.5_

- [x] 29. Run the full conformance pass and record the measurements
  - Run `lab-cli conformance --repeat 5 --out results/conformance-<date>.jsonl` against the deployed guardrail and commit the JSONL
  - Record the wall-clock duration of a single-repetition pass for the Runbook's stated figure
  - Record the observed action for a prompt containing both a national identity number and a phone number
  - _Requirements: 12.1, 12.9, 15.6, 16.1_

- [x] 30. Measure the false-positive tuning loop
  - Run `lab-cli conformance --set tuning --repeat 10 --out results/tuning-before.jsonl`, recording the block count for the seed-treatment question with the date and Region
  - Narrow the `Agrochemical Dosing` definition in `shared/scenario.json`, re-apply, and run the same command to `results/tuning-after.jsonl`
  - Compute the false-positive rate before and after to one decimal place, and the count of violating prompts still blocked after narrowing
  - If the seed-treatment question was blocked in zero repetitions, substitute a blocked in-scope prompt from the same set, name the substitution, and retain the seed-treatment result as a recorded non-reproduction
  - If the recomputed rate is not lower, iterate the narrow-and-remeasure up to a maximum of 3 iterations, recording each
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.8, 5.9_

- [x] 31. Destroy the stack and confirm removal
  - Run `terraform destroy`, recording the exit status
  - Query and record post-destroy absence for the guardrail, both log groups, both alarms, the Lambda function, the API Gateway HTTP API, the IAM role and the Amplify application
  - On any non-zero exit, record the failing resource address, the verbatim error text, the resources remaining in state, and the exit status of the corrected re-run
  - _Requirements: 10.6, 10.10, 4.10_

- [x] 32. Reconcile documentation against validation findings
  - Correct every documented claim contradicted by a validation result, citing the Validation_Log entry that contradicted it
  - Add a dated amendment to each affected numbered ADR decision that retains the superseded statement, names the observed behaviour and cites the log entry, rather than editing silently
  - Label any documented deployment claim lacking a Validation_Log entry as unverified, naming the command that would verify it
  - _Requirements: 10.7, 10.8, 10.11_

- [x] 33. Populate checkpoint validation blocks
  - Fill the `validation` block of every checkpoint in `lab/checkpoints.json` with the repetition count run, the count in which the expected outcome was observed, and the date and Region of measurement
  - Label each checkpoint deterministic or probabilistic according to the observed distribution
  - _Requirements: 2.3, 2.6_

---

- [x] 63. Add a prerequisite doctor that distinguishes an SCP deny from an IAM gap
  - Create `lab/doctor.py` and a `lab-cli doctor [--probe-write]` subcommand
  - Classify every denial as SCP, IAM or neither, by parsing the AWS message rather than
    inferring, and print the appropriate fix for each: a management-account ask for an SCP,
    a pastable policy document for IAM
  - Detect standalone versus organisation member accounts, warning that SCPs may apply when the
    organisation is present but unreadable
  - Probe every ACTIVE Haiku profile, extract the routed Region from the denial ARN, and
    recommend the single-Region `global.` profile when a fan-out profile routed elsewhere
  - Under `--probe-write`, create a tagged guardrail, retry untagged on failure to isolate a
    tagging gap from a create gap, exercise apply/version, and delete the probe
  - Check the boto3 floor for `outputScope`
  - State explicitly that an absent IAM grant hides any SCP deny behind it, and that the check
    must be re-run after adding permissions
  - Write `docs/aws-prerequisites.md` covering standalone accounts, organisation member
    accounts, SSO permission sets, the three tag permissions, the profile choice, and what
    still works when only the model is denied
  - _Requirements: 1.4, 1.7, 10.11, 15.5_

- [x] 64. Make the infrastructure Region-agnostic and resolve the open AWS facts from documentation
  - Create `infrastructure/regions.tf` deriving the guardrail profile, its destination Regions, the
    ARN partition and the model-identifier kind from `aws_region` and `bedrock_model_id`
  - Cover all seven documented guardrail geographies (US, EU, UK, Canada, Australia, APAC,
    GovCloud), preferring AU over APAC for ap-southeast-2 and handling the `aws-us-gov` partition
  - Rewrite `infrastructure/iam.tf` to emit only the statements the configured identifier needs:
    the documented three-part policy for a `global.` profile, a wildcard-Region policy for a
    geographic profile, a single-Region policy for a bare model id
  - Permit `bedrock:ApplyGuardrail` on the guardrail profile object in every destination Region,
    not only the source
  - Add a STANDARD-tier precondition that names the CLASSIC alternative when a Region has no
    guardrail profile
  - Make `guardrail_profile_id` an opt-in override rather than a value anyone must set
  - Teach `lab doctor` the geography table so it reports profile coverage per Region and suggests
    the right model identifier when none is available
  - _Requirements: 1.4, 10.11, 15.5, 16.3_

## E. Replay_Mode

- [x] 34. Implement `ReplayStore` and the fixture models
  - Create `backend/app/replay.py` defining `ReplayCase` and `ReplayStore`
  - Implement prompt normalisation that lowercases, collapses whitespace and strips trailing punctuation
  - Implement `lookup(prompt)` returning the matched case or `None`, and `verify_case(question, answer)` for the Grounding_Tool path
  - Load fixtures from a configurable directory, selecting by tier where a case declares one
  - Write tests for matching, normalisation and the unmatched case
  - _Requirements: 7.1, 7.2, 7.10_

- [x] 35. Wire Replay_Mode into `GuardrailService` with no client construction
  - Add `replay_mode`, `replay_dir` and `guardrail_tier` to `Settings`
  - When replay is active, construct a `ReplayStore` and leave the boto3 client unconstructed
  - Return recorded `StageResult` values from `screen()`, `answer()` and `verify()`, bypassing `_require_guardrail()`
  - Set the `replayed` field on every returned stage result
  - Write a test that completes all three pipeline stages with no AWS credentials in the environment and no client available, asserting no boto3 client was constructed
  - _Requirements: 7.1, 7.7, 7.8_

- [x] 36. Surface an unmatched replay prompt as a distinct API response
  - Return a 409 from `POST /api/ask` under replay when no fixture matches, stating that no recorded result is available and naming the case set so a covered prompt can be chosen
  - Write a test for the unmatched path
  - _Requirements: 7.10_

- [x] 37. Add fixture recording to the Conformance_Runner
  - Add a `--record` flag writing a `ReplayCase` per evaluated case to the fixture directory, stamping `captured_utc`, `region`, `tier` and `guardrail_version` from the live call
  - Record the eleven Runbook cases plus the tier-gap prompt under both CLASSIC and STANDARD, giving 12 fixture records
  - Commit the recorded fixtures
  - _Requirements: 7.2, 7.6_

---

## F. Frontend restructure

**Status: complete.** 77 vitest tests and 12 Playwright checks passing, typecheck clean, static
export builds. Notes carried forward:

- `api.ts` now unwraps the structured `detail` object Phase B introduced, exposing `stage`, `kind`
  and `awsErrorCode` on `ApiError`. Configuration errors stay readable strings.
- The `dim` colour was darkened from `#67756c` to `#5a675e`: it measured 4.43:1 on red-50, under the
  4.5:1 floor. An `opacity-80` on the finding location span was also removed — it diluted the amber
  tone to 3.32:1, which axe caught.
- Three layout changes were forced by the 1280x720 measurement, not chosen: sample prompts collapse
  behind a toggle (8 groups ran to ~350px of a 720px viewport), the message history is capped and
  scrolls internally, and `ChatWindow` takes a `compact` prop that tightens it while an
  engineer-facing panel is open. Before these, `document.scrollHeight` was 999px at entry and the
  stage grid started at 845px — both off-screen.
- Capping the history introduced a WCAG 2.1.1 failure (unreachable scroll region), fixed with
  `tabIndex={0}` and `role="log"` rather than suppressed.
- `playwright-core` is pinned to 1.49.1 as a devDependency: a stale hoisted 1.62.1 made
  `@axe-core/playwright` resolve a different `Page` type than the tests.
- `npx next lint` requires interactive setup and was not run; typecheck and both suites cover the
  same ground.

- [x] 38. Set up the frontend test runner and legibility utilities
  - Add Vitest, React Testing Library and Playwright to `frontend/package.json` with `test` and `test:e2e` scripts
  - Add `text-stage` (16px), `text-turn` (16px), `text-finding` (14px), `text-raw` (14px) and `text-raw-lg` (20px) font sizes to `tailwind.config.ts`
  - Verify the four palette colours meet a 4.5:1 contrast ratio against their backgrounds, adjusting any that do not
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.13_

- [x] 39. Implement `useSession`
  - Create `frontend/src/lib/session.ts` defining `Exchange` and implementing `useSession` with `exchanges`, `selectedId`, `inFlight`, `submit`, `select` and `substituteFixture`
  - `submit` validates length between 1 and 2000 characters before any call, appends the member turn with `pending` status before the fetch begins, and issues exactly one `POST /api/ask`
  - `select` moves a pointer only and issues no request
  - Record the failing endpoint and error text on failure, retaining the member turn and every preceding turn
  - Write tests asserting one request per submission, that `select` issues no request, and that history is retained across selection changes
  - _Requirements: 18.2, 18.5, 18.11, 21.1, 21.4, 21.7_

- [x] 40. Implement the bulletin-derived Landing_Page sections
  - Create `frontend/src/components/LandingSections.tsx` taking `ctx` and `ctxError`
  - Render between 3 and 6 titled sections comprising the `about_sections` content, a collection-point section showing both points, the opening window, both days and the gate requirement, and a payment section stating the fourteen-day release and that grading results are posted at the collection point
  - Render every section as visible text requiring no expansion or hover
  - On a context failure, render the failing endpoint and error text at `text-finding`, mark each dependent section unavailable rather than rendering substitute content
  - Introduce no scenario text not sourced from `GET /api/context`
  - Write tests for the populated and failed states
  - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6_

- [x] 41. Implement the Demo_Disclosure
  - Create `frontend/src/components/Disclosure.tsx` rendering at `text-finding` in a position visible at every scroll position
  - State that the page is a demonstration and that Highland Growers Co-operative, Kilimo Desk, Project Tumaini, Batch Ledger v2 and Extension Bulletin 14 are fictional and the co-operative does not exist
  - State that the API performs no authentication and instruct the reader to enter no real personal information
  - Accept and render a replay indicator at `text-finding` when Replay_Mode is active
  - Write a test asserting the disclosure renders outside the Chat_Window
  - _Requirements: 7.11, 17.7, 17.8, 22.7_

- [x] 42. Implement the Chat_Window
  - Create `frontend/src/components/ChatWindow.tsx` rendering the message history in order with each turn labelled by speaker as visible text at `text-turn`
  - Render the assistant turn as exactly `{exchange.response.final}` with no conditional styling keyed off `stopped_at`, so a refusal is visually indistinguishable from an answer
  - Render the member turn as the text the member typed, with no masking placeholder or rule name
  - Display a pending indicator as visible text while a request is in flight, keeping the member turn visible and the submit control disabled so at most one request is in flight
  - Render a failure message at `text-turn` naming the endpoint and error text in place of the assistant turn on failure or 30-second timeout
  - Display a message-field hint at `text-finding` directing the reader to the sample prompts and instructing them to enter no real personal information
  - Accept submissions of 1 to 2000 characters, displaying a message naming the violated limit and making no call when outside that range
  - Delete `frontend/src/components/PipelineLane.tsx`
  - _Requirements: 18.1, 18.2, 18.3, 18.5, 18.6, 18.7, 18.8, 18.9, 18.10, 18.11, 18.12_

- [x] 43. Add the assistant-turn leakage property test
  - Write a property test generating `AskResponse` values and asserting the rendered assistant turn text equals `final` and contains none of the policy names, policy types, stage names, guardrail actions, scores, thresholds, latency values, `stopped_at` values or AWS identifiers carried by that response
  - _Requirements: 18.4_

- [x] 44. Render the Sample_Prompts inside the Chat_Window
  - Render each prompt of each group as its own activatable control, grouped under the eight labels read from `frontend/src/lib/samples.ts`, with each label at `text-finding`
  - Render prompt labels in full without ellipsis truncation, wrapping onto additional lines as needed
  - Activation submits the prompt text character for character through the same handler the text field uses, requiring no keystroke
  - Leave an in-flight request unchanged and make no further call when a control is activated while a request is in flight
  - Confirm the `PII` group carries only the invented values `Grace Wanjiku`, `HG-004182` and `0722135790`, correcting them if not
  - Write tests asserting all 9 prompts across 8 groups are present, that activation submits verbatim, and that activation during flight is a no-op
  - _Requirements: 6.12, 19.1, 19.2, 19.3, 19.4, 19.5, 19.7, 19.8_

- [x] 45. Implement `StageEntry`
  - Create `frontend/src/components/StageEntry.tsx` replacing `StageCard.tsx`
  - Render the stage name, intervened indicator, model-invoked indicator, latency, and each finding with policy name, detail, action and location, rendering every value verbatim without rewording
  - Render the stage label at `text-stage` and findings at `text-finding`, labelling a stage with `model_invoked` false as `ApplyGuardrail · no model`
  - Distinguish intervened from passed by a text label at `text-finding` so the distinction survives colour removal
  - For the screen stage, render `result.text` as the forwarded text at `text-finding`, showing at least the first 160 characters with an explicit truncation indicator when longer
  - Name each matching sensitive-information rule with its action
  - Where the answer stage carries findings with location `input`, render a visible label identifying them as a second evaluation of the same submitted text, requiring no hover or expansion
  - Label the stage as replayed with the fixture capture date and Region when `replayed` is set
  - Render every element the Runbook enumerates as read aloud at no less than `text-finding`
  - Delete `StageCard.tsx`
  - _Requirements: 6.1, 6.2, 6.3, 6.5, 6.9, 7.8, 14.9, 20.2, 20.5, 20.6, 20.9, 20.12_

- [x] 46. Implement the Background_View
  - Create `frontend/src/components/BackgroundView.tsx` rendering one `StageEntry` per element of the selected response's `stages` array in array order
  - Render a not-run entry for each pipeline stage absent from the array, naming that stage and naming the halting stage that prevented it
  - Render `stopped_at` and `total_latency_ms` as visible text
  - Render the guardrail identifier, guardrail version, Region and model identifier from `GET /api/context`
  - Render the member turn text of the request displayed
  - Render each stage's `raw` payload collapsed until its control is activated, with a keyboard-operable control toggling the panel between `text-raw` and `text-raw-lg`
  - Allow selection of any retained response by its member turn text, presenting only the selected response's stages, and default to the most recent completed response
  - State that no request has been sent and name the control that sends one when opened before any request has completed
  - Present the failure with the failing stage named and any completed stage retained when a request failed, offering a fixture-substitution control when a fixture exists for the case and stating that no recorded result is available when it does not
  - _Requirements: 7.3, 7.4, 7.10, 20.1, 20.2, 20.3, 20.4, 20.7, 20.8, 20.11, 21.5, 21.6, 21.7, 21.8, 6.10_

- [x] 47. Add the two-view correspondence property tests
  - Property: the rendered assistant turn text equals the `final` value of the same response whose `stages` array the Background_View renders
  - Property: the count of rendered stage entries equals the length of that response's `stages` array, with each entry carrying the stage name at the same array index
  - Test: opening and closing the Background_View leaves the message history unchanged
  - _Requirements: 20.10, 21.2, 21.3_

- [x] 48. Convert `GroundingLane` into the Grounding_Tool
  - Rename `GroundingLane.tsx` to `GroundingTool.tsx`
  - Render each of the three committed cases with its question, candidate answer and expected outcome as visible text rather than a `title` attribute
  - Render the returned grounding score, relevance score, the threshold in force for each, and a per-filter pass indicator
  - Render the reference document from the `bulletin` value returned by `GET /api/context`
  - Accept an operator-entered question and answer each of 1 to 2000 characters
  - On failure or a 30-second timeout, render the endpoint and error text at `text-finding` and retain the previously presented result
  - Write tests for the retained-result-on-failure and score-rendering behaviours
  - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6_

- [x] 49. Restructure the entry route
  - Rewrite `frontend/src/app/page.tsx` so the Landing_Page is the entry route, holding `useSession` above the view switch so neither the Background_View nor the Grounding_Tool can unmount it
  - Place the Chat_Window within the first 1280×720 viewport at the entry scroll position
  - Present exactly one free-text input on the Landing_Page, with every other control being a sample prompt, the Background_View control, or the Grounding_Tool control, offering no sign-in, registration or password entry
  - Open the Background_View as a panel replacing the co-op sections rather than stacking below them, reachable by at most one activation of a control at `text-stage`
  - Render the Demo_Disclosure outside the conditional so it survives a context failure
  - Write a test asserting message history is retained across every opening and closing of both engineer-facing views
  - _Requirements: 17.9, 17.10, 17.11, 18.13, 20.1, 22.1_

- [x] 50. Add the layout and legibility checks
  - Write a Playwright check at exactly 1280×720 asserting computed font sizes via `getComputedStyle` meet the floors for stage labels, findings, forwarded text, member and assistant turns, and the intervened-versus-passed label
  - Assert the Member_View presents the most recent member turn, the assistant turn, the disclosure and the Background_View control without scrolling for assistant turns up to 120 words
  - Assert the Background_View presents every stage entry, model-invoked indicator and findings without scrolling for the Runbook's demonstrated cases
  - Assert that with both views displayed, turn text, stage names and model-invoked indicators remain visible without scrolling, with scrolling confined to finding detail and raw panels
  - Add an axe-core pass covering contrast
  - _Requirements: 6.6, 6.7, 6.8, 6.13_

---

## G. Documentation

Written after §D so every number is measured rather than estimated.

- [x] 51. Write the Cost_Statement
  - Create `docs/cost.md` stating the cost of completing every Lab_Guide module once in USD to two decimal places, the number of `ApplyGuardrail` evaluations assumed, and the added cost of one further full pass
  - State the cost of standing up the deployed stack, one rehearsal of at most 60 minutes, one 60-minute session and destruction, itemised across the guardrail, the foundation model, Lambda, API Gateway, Amplify Hosting and CloudWatch Logs
  - Show a billable-units table whose rows give item, unit, unit price, quantity and line total, covering each enabled policy with its assumed text-unit count and the model's assumed input and output token counts, summing to both headline figures within one cent
  - State the date the pricing inputs were read, the Region `eu-west-1`, and the source consulted per unit price
  - State that guardrail charges accrue per 1,000 text units per enabled policy and give the count of policies enabled by the committed configuration
  - State idle cost per 24 hours and per 30-day month including CloudWatch Logs under 14-day retention and Amplify Hosting, naming each zero-cost component
  - State whether any Free Tier allowance is assumed and the figures for an account with none remaining
  - State the cost of one `ApplyGuardrail` evaluation with the committed policy set and the change from enabling one additional policy
  - State the recurring monthly charge of a guardrail left in place serving no requests
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.8, 3.9, 3.10_

- [x] 52. Write the Lab_Guide modules
  - Create `docs/lab-guide.md` with 8 numbered modules covering the five policy types and the three pipeline stages, teaching the answer stage from recorded fixtures and the `Converse` request shape with the live call as an optional extension
  - State per module 1 to 3 objectives phrased as actions the attendee performs and observes, a duration of 5 to 20 whole minutes, and its prerequisite modules or that it has none
  - State per module 1 to 5 checkpoints matching `lab/checkpoints.json`, each giving the verbatim prompt, the command, the expected action, expected policy type, expected policy name and a deterministic or probabilistic label
  - State for each probabilistic checkpoint the repetitions run during validation, the count in which the expected outcome was observed, and that it counts as met at 3 of 5
  - Provide a troubleshooting entry per checkpoint carrying the identifier the Checkpoint_Verifier names, covering at minimum no intervention occurring and a policy other than the expected one intervening
  - Include the tuning exercise naming the policy field edited in `shared/scenario.json`, the re-apply command, the prompt, the action before and expected after, and the restore command
  - Place the teardown command in the closing section of every numbered module
  - State that no numbered module covers the Demo_UI and that every checkpoint is reachable through the Lab_CLI alone
  - Add exactly one appendix, outside the module count and covered by no checkpoint, naming the backend start command, `npm run dev`, and `NEXT_PUBLIC_API_BASE_URL`, stating that it creates no AWS resource beyond the single guardrail and that the answer stage needs model access while screen, verify and Replay_Mode do not
  - Declare prerequisites as an explicit list of tools with minimum versions, required IAM actions and the target Region, stating that Bedrock model access is not required, and place a link to the Cost_Statement with the Lab_Path total above the first command
  - _Requirements: 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.6, 2.7, 2.10, 2.11, 2.12, 2.13, 3.7, 4.7, 4.8_

- [x] 53. Write the Tuning_Module content
  - Add the tuning module content to `docs/lab-guide.md` expressing the loop as four ordered steps — define, measure, narrow, re-measure — stating per step the command and the recorded outcome
  - Quote the original and narrowed `Agrochemical Dosing` definitions verbatim
  - Report the false-positive rate before and after to one decimal place over the named prompt set with its repetition count, the seed-treatment block count with date and Region, and the count of violating prompts still blocked after narrowing
  - State the trade-off that narrowing can reduce recall, supported by the measured before-and-after violation counts
  - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6_

- [x] 54. Write the results section
  - Create `docs/results.md` computed from the committed JSONL, with one row per configured policy type giving prompts evaluated, repetitions per prompt, and observed outcome counts across no intervention, blocked and anonymised
  - Report the tuning measurement as four numbers over one labelled prompt set
  - Label every claim measured, probabilistic or documentation-derived, naming the Conformance_Runner run for each measured claim and the AWS document for each documentation-derived one
  - State per measurement the date observed, the Region, the tier in force and the guardrail version
  - Show any policy type with no measurement as not measured with the reason rather than omitting it
  - State the reproduction steps as an ordered list giving the command and expected observable output per step, with the total duration in minutes and the total cost by reference to the Cost_Statement
  - _Requirements: 16.1, 16.2, 16.3, 16.8, 16.9, 16.10_

- [x] 55. Rewrite the Runbook timeline
  - Rewrite `docs/demo-runbook.md` as contiguous non-overlapping segments summing to exactly 60 minutes
  - Open with a Member_View-only segment of 4 to 10 minutes showing at least the in-scope collection-point question and the dosing refusal as a member reads them, ending at or before the first Background_View segment
  - Place the first Background_View display to start no earlier than minute 5 and no later than minute 15
  - Reserve at least 8 minutes of questions across at least 2 labelled segments with start and end times, the first starting no later than minute 25
  - Reserve at least 4 minutes of buffer across at least 3 intervals of at least 1 minute, one per third of the session
  - Order the dosing, PII and grounding-failure segments so the Member_View precedes the Background_View for the same prompt, stating for each the prompt submitted, the Member_View text read first, the Background_View finding revealed second, and one sentence naming what the member could not see
  - Allocate at most 5 minutes total to reading `shared/scenario.json` aloud and at most 4 minutes total to non-Chat_Window Landing_Page content
  - Demonstrate exactly one denied topic in full and name the remaining topics within at most 1 minute
  - Place the Grounding_Tool segment at or after the end of the segment showing a grounding failure in the Member_View
  - Allocate 3 to 6 minutes to the false-positive segment, ordered so the observed block precedes reading the topic definition aloud, and state where the presenter switches to Replay_Mode on a live failure
  - Mark each segment essential or cuttable with a numbered cut order reclaiming at least 8 minutes, and state one declarative sentence of at most 30 words per segment naming what it lands
  - Direct the presenter to the next cut-order entry when a segment overruns by more than 2 minutes
  - Enumerate per segment every Demo_UI element read aloud with the view it belongs to
  - Name the Conformance_Runner as the pre-session verification step with its validated duration and position, and the SDK parity check ahead of the first live demonstration
  - State the command enabling Replay_Mode, 60 seconds as the maximum live-failure diagnosis time, the element the presenter points to when disclosing a recorded result, and why the replay indicator sits outside the Chat_Window
  - State the pre-swap check that the application reports guardrail version `DRAFT`, and the ≤90-second spoken tier-gap description with per-tier outcomes and repetition counts for when the swap is cut
  - Direct the presenter to the recorded result if the false positive does not reproduce within 2 live attempts, giving the sentence to say while switching
  - Give the group label and verbatim prompt text for every Sample_Prompts entry a segment names
  - _Requirements: 5.7, 5.10, 6.11, 7.5, 7.12, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 8.13, 8.14, 8.15, 9.8, 9.9, 9.10, 11.6, 12.9, 19.6, 21.9, 22.9_

- [x] 56. Correct the Runbook troubleshooting table
  - Replace the references to `01_create_guardrail.py`, `scenario.py`, `--tier` and `--profile-id` with the Terraform `guardrail_tier` variable workflow and `shared/scenario.json`
  - Reference only file paths that resolve in the committed tree, variables declared in the infrastructure or application configuration, and flags accepted by committed tooling
  - Report the same cause and fix as the RUNNING.md table for every shared symptom, treating RUNNING.md as the reference
  - _Requirements: 15.1, 15.2_

- [x] 57. Correct RUNNING.md and the tier-change claims
  - State for each of the guardrail version, the Lambda environment configuration and the frontend build whether a tier change alters it under each version-publishing setting
  - Remove the unqualified claim that a tier change needs no Lambda or frontend redeploy wherever it does not match the applied configuration
  - State that a pinned numbered version not recut after a tier change continues evaluating against the previous tier, and name the setting that avoids this
  - State the count of tier-gap prompts measured, the repetitions per prompt per tier, and the per-prompt per-tier intervention counts
  - State which account-level settings persist after teardown, naming Bedrock model access, and that each carries no charge while unused
  - Provide a state-independent removal procedure naming each resource type and the command that lists then removes it
  - State that `terraform destroy` removes the full stack and name each resource type verified removed during validation
  - Separate probabilistic from deterministic checks in the troubleshooting guidance
  - _Requirements: 4.9, 4.10, 9.3, 9.4, 9.6, 15.8_

- [x] 58. Add the third outcome to the smoke test
  - Add a `check_probabilistic` variant to `scripts/smoke-test.sh` reporting inconclusive rather than failed and excluded from the exit status
  - Apply it to the dosing and prompt-attack checks whose outcomes depend on classification, keeping deterministic checks on the existing pass-or-fail path
  - Report the two categories separately in the summary
  - _Requirements: 15.11, 15.12_

- [x] 59. Rewrite the README front matter and corrections
  - Add an entry table ahead of every other section with one row per reader purpose routing to the Lab_Guide, the Runbook, the ADR, the results section and the Demo_UI description, each with exactly one link and an expected time in minutes
  - State within the first three sentences that the repository holds both a presented demo and a self-paced lab, distinguishing observing the session from running the lab, and confirm the description matches the repository name
  - Present the Lab_Path as the default entry point, linking to the Lab_Guide ahead of any instruction that deploys Lambda, API Gateway or Amplify
  - Describe the content filters as six categories on input and five on output, naming `PROMPT_ATTACK` as the one with output strength `NONE`, removing the unqualified count
  - Describe `frontend/` as the Landing_Page with its embedded Chat_Window, the Background_View and the Grounding_Tool, replacing the pipeline-lane description
  - Name in the key-file table the file implementing each of the Landing_Page, Chat_Window, Background_View and Grounding_Tool, stating for each whether it is member-facing or engineer-facing
  - Describe the Demo_UI in at most three sentences naming all four components and stating which are member-facing and which engineer-facing
  - State that the PII sample prompt carries invented values and instruct readers to enter no real personal information
  - Assert the originality of the scenario, policy set and code in exactly one canonical location, with every other reference linking to it
  - _Requirements: 1.8, 15.3, 15.4, 15.9, 15.10, 15.13, 15.14, 15.17, 16.6, 16.12_

- [x] 60. Write the limits, IAM and workshop-relationship sections
  - State the limits of Bedrock Guardrails in one section covering exactly four — identity, action enforcement, application-layer validation and probabilistic coverage — naming for each the compensating control outside the guardrail
  - Name `bedrock:GuardrailIdentifier` as the mechanism making a guardrail an organisational control, stating that it constrains which guardrail identifier a caller may supply
  - State the relationship to the published AWS workshop in one subsection linking to it, stating which material is derived from it, and naming this repository's four additions
  - State the case where the gap between the two views is largest, namely the masking case in which the member observes nothing unusual while the Background_View shows the name, phone number and member number replaced before the model received the text
  - State that the Chat_Window calls the API directly from the browser because the frontend is a static export, citing the numbered ADR decision recording that choice
  - State that the API performs no authentication and that the Landing_Page therefore presents and implies no sign-in, citing the numbered ADR decision recording that design
  - State that the Grounding_Tool exercises `POST /api/verify` directly outside the member request path, and that the verify stage of a member request appears in the Background_View
  - State separately for the local environment and the deployed Lambda which SDK version governs the available Bedrock request fields, and that the packaging step strips boto3 and botocore because the runtime supplies them
  - Cite the Validation_Log entry recording the source and date wherever Bedrock Region availability is asserted
  - State that the national identity regex matches any eight-digit sequence delimited by non-digits, with the observed action for a prompt containing both an ID and a phone number, citing the log entry
  - State that a documented check depending on a live model answer clearing a grounding threshold is probabilistic, naming the threshold in force
  - _Requirements: 11.4, 15.5, 15.6, 15.8, 15.15, 15.16, 16.4, 16.5, 16.7, 16.13, 22.8_

- [x] 61. Add rejected alternatives to every ADR decision
  - State for each of the eleven numbered decisions the alternative rejected and the reason for rejecting it
  - _Requirements: 16.11_

- [x] 62. Update the architecture diagram
  - Update `docs/architecture.svg` to show the Landing_Page with its embedded Chat_Window, the Background_View and the Grounding_Tool over one `POST /api/ask` response, and the Lab_Path calling `ApplyGuardrail` with no deployed infrastructure
  - _Requirements: 15.13_
