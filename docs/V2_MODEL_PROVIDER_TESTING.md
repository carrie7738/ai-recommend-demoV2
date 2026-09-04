# V2 Model Provider and A/B Testing

## Active scope and current evidence (2026-09-04)

The user has paused model A/B testing. DeepSeek is the only active acceptance provider;
Gemini API checks and cross-provider comparisons are deferred. Existing adapters are retained.

- Baseline: local `aad1da2`; subsequent working-tree changes are not a new committed checkpoint.
- DeepSeek smoke passed with actual model `deepseek-v4-flash`, no fallback or retry.
  Intent: 7114.1 ms, 1645 input / 583 output tokens; Decision: 2088.4 ms,
  1004 input / 169 output tokens. Both API/JSON checks succeeded; local Intent schema and
  budget=1000 / traffic=HIGH semantics passed; Decision schema/semantic validation passed.
  This smoke ran before the current Intent prompt correction and does not pass a store profile.
- Initial sandbox execution failed with a connection error and correctly reported FAIL/fallback.
  The successful smoke was run with approved network access.
- The first real browser run for C001 returned HTTP 200 but Intent schema validation failed:
  the model echoed trusted profile keys into `store_context`, which only accepts `{}`.
  The UI exposed `Intent: fallback` and `Rules Fallback`; its V2 Decision/Validator succeeded
  with 12 discovery lines, NZD 242 total, NZD 758 remaining. This is **not** an all-live pass.
- The prompt now explicitly reserves `store_context: {}` for local trusted enrichment.
  Local Intent/UI tests pass. Real confirmation of that prompt correction is pending.
- Automatic approval review rejected the browser re-generation because it would send local
  store-profile fields to DeepSeek. Explicit authorization for those fields has been requested.
  Profile-bearing six-scenario and browser calls remain paused pending that answer.
- C051 harness scenarios and C001 browser requests use different trusted store identities.
  They must be reported separately; see `V2_REMAINING_TASKS.md`.

The historical statuses below are from earlier runs. They are not acceptance evidence for
`aad1da2` or the current working tree. Gemini quota availability has not been rechecked.

## Provider boundary

Business services call `AIClient`, which delegates to a configured provider adapter. New providers
must implement the same provider-neutral contract; procurement business logic must not call a vendor
SDK directly.

| Provider | Current role | Structured response mode | Real validation status |
| --- | --- | --- | --- |
| DeepSeek | Active comparison provider | JSON object plus local schema/semantic validation | Six V2 scenarios passed after Structured Output changes |
| Gemini | Active comparison provider | Strict JSON Schema plus local schema/semantic validation | Smoke and Case 1 passed; full regression pending quota |
| GLM | Future extension entry | JSON object plus local validation | No current real API validation |

Select a provider with `AI_PROVIDER` and its provider-specific `*_API_KEY`, `*_BASE_URL`, and
`*_MODEL` variables. `AI_STRUCTURED_MAX_TOKENS` defaults to 16384. Do not place real credentials in
`.env.example` or evaluation artifacts.

## Smoke and scenario commands

```powershell
.\.venv\Scripts\python.exe scripts\model_smoke_test.py --provider deepseek
.\.venv\Scripts\python.exe scripts\model_smoke_test.py --provider gemini
.\.venv\Scripts\python.exe scripts\v2_scenario_regression.py --provider deepseek --summary
.\.venv\Scripts\python.exe scripts\v2_scenario_regression.py --provider gemini --summary
```

The scenario command fails when a known Demo Intent is semantically wrong, Validator does not pass,
the final plan is empty, a budget is exceeded, V2 fails, or fallback is triggered. HTTP success and
JSON parsing alone are not acceptance.

## A/B evaluation

Run both providers against the same workbook, store, evaluation date, scenario text, and evaluation
parameters:

```powershell
.\.venv\Scripts\python.exe scripts\ab_evaluation.py --providers deepseek gemini --runs 3
```

Optional flags include repeatable `--case`, provider-specific model overrides, and `--output-dir`.
The harness writes:

- `ab_runs.json`: complete structured run records and per-call metrics.
- `ab_runs.csv`: scalar metrics for analysis.
- `ab_comparison.json`: per-scenario SKU overlap and cost difference.

Metrics include Provider, configured/actual Model, contract result, Validator, repair/retry/fallback,
latency, and input/output/reasoning tokens when supplied by the API. API keys and raw prompts are not
written.

Model recommendations are not required to be identical. Explicit Intent and hard constraints must
agree; priority, intensity, retained candidates, and final quantities may be compared as evaluation
outcomes.

## UI acceptance

The Streamlit page must show Model & Pipeline Status with Provider, Model, Structured Intent, V2
status, Intent source, and Fallback state. A failed Validator must not render a Final Purchase Plan.
If V2 fails and V1 fallback is shown, the UI must retain `V2 FAILED` and display the fallback reason.

## Historical external blocker (not rechecked)

The configured Gemini project returned `RESOURCE_EXHAUSTED` after reaching the
`gemini-3.6-flash` free-tier request limit of 20. Cases 4–6 and post-fix retests for Cases 2–3 remain
pending until quota is available. This is an external API limitation, not a V2 pass.
