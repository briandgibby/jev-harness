<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev Harness completion walkthrough

## Outcome

The Choice pilot is implemented, verified offline, and exercised through a bounded authenticated TypeSafe probe. It bootstraps from an empty directory, produces classification recommendations, records evidence, replays a historical decision without a provider call, and evaluates bounded labeled data. The live continuation reused an authorized dotenv credential for synthetic inputs only. [LIVE_RESULTS.md](LIVE_RESULTS.md) owns the observed live results and limits.

The original manual fixture smoke used three synthetic examples and made no API requests. Subsequently, one authenticated smoke and 12 further synthetic calls completed. Neither experiment establishes domain quality. No existing repository source or credential file changed, and no schedule or downstream action was enabled.

## Actual design and decisions

`init` owns the generated configuration and examples. `run` validates configuration/input, creates an append-only audit, calls the explicitly selected adapter, validates the response, and applies `decide`. `replay` checks saved snapshots and hashes before reapplying the saved policy. `evaluate` prevalidates its dataset and uses the same run path per item.

The model is pinned to `jev-1.13.0` in generated configuration. Labels, rubric, thresholds, limits, and paths are operator settings with code-owned bounds. The first classifier uses maintenance/admin/unknown intent, and unknown is always reviewed. Confidence is preserved separately from selected-label probability. Decimal margin comparison makes the configured boundary inclusive. Ties always require review.

No silent retries, redirects, fallback models, or fixture fallback occur. Existing nonempty bootstrap directories are refused. Audit writes are flushed before inference and before reporting completion. Files contain source state and provider output, but no credential value. Hashes detect inconsistent edits; they are not signed tamper-proof records.

## Changed files and purpose

All source and documentation files are new. No existing application files were modified or deleted. The complete responsibility table is in [implementation_plan.md](implementation_plan.md).

| Files | Actual responsibility |
|---|---|
| `jev_harness.py` | CLI, strict validation, direct TypeSafe/fixture adapters, policy, audit, replay, evaluation. |
| `test_jev_harness.py` | 45 offline tests covering the externally meaningful behaviors and failures. |
| `probe_live.py`, `live_cases.json` | Bounded live smoke/battery runner with literal dotenv loading, and canonical synthetic scenarios with predeclared labels. |
| `analyze_probe.py`, `LIVE_RESULTS.md` | Offline audit/replay-based metric derivation, and interpretation of the live evidence. |
| `.python-version` | Pin Python 3.14.6, the runtime actually used. |
| `README.md`, `RESEARCH.md` | Operator commands and evidence-grounded research/adoption design respectively. |
| `docs/PRD.md`, `implementation_plan.md`, `task_checklist.md`, `agent_prompt.md`, this walkthrough | Requirements, file/integration plan, status, handoff, and observed outcome respectively. |
| `evidence/tests.txt`, `tests-initial-failure.txt` | Final test output with command/runtime source hashes, and initial failure output. |
| `evidence/core-*-reproduction.txt` | Four exact bug reproductions and their before/after outputs. |
| `evidence/smoke-transcript.json`, `smoke-success-audit.jsonl`, `smoke-missing-key-audit.jsonl` | Unedited manual smoke streams and copies of its inspectable audit records. |
| `evidence/packet-validation.txt` | Final packet validation command and unedited output. |
| `evidence/live-pilot/`, `live-*-command.txt`, `live-summary.json` | Generated probe config, per-call audits, phase records, exact commands/raw outputs, and rebuildable analysis export. |
| `evidence/packet-validation-live.txt` | Updated packet validation following live evidence and Laya research. |

Python may produce `__pycache__` during verification; those files are derived interpreter caches, not maintained source.

## Plan refinements and repair evidence

The initial example was changed to semantic request classification so it exercises a judgment worth modeling. Required-field presence remains a code concern. Five observed defects were repaired with failing evidence before changes:

- [Unknown-setting diagnostics](../evidence/tests-initial-failure.txt): the initial suite rejected a setting without naming it. The final test confirms the offending standard field name is included; arbitrary field contents remain sanitized.
- [Oversized integer](../evidence/core-numeric-reproduction.txt): avoid float conversion overflow and name the invalid setting.
- [Partial evaluation](../evidence/core-batch-reproduction.txt): preserve completed count and audit paths when a later item fails.
- [Invalid Unicode](../evidence/core-unicode-reproduction.txt): reject unpaired surrogates before creating an audit file.
- [Decimal margin](../evidence/core-margin-reproduction.txt): a 0.6/0.4 distribution meets an inclusive 0.2 margin threshold.

Source and planning-document backups were restored to scratch and hash-compared before overwriting them during development. No restore of user production data was necessary; this pilot created only new local files.

## Verification evidence

Command from the deliverable root: `python -m unittest -v`. The actual executable, working directory, SHA-256 hashes, exit status, and **unedited complete output** are in [tests.txt](../evidence/tests.txt). Result: exit 0, 45 tests in 2.716 seconds, `OK`.

The separate manual workflow ran `python --version`, CLI help, `init`, fixture `run`, `replay`, fixture `evaluate`, repeat `init`, and missing-key live-mode rejection. [smoke-transcript.json](../evidence/smoke-transcript.json) stores exact commands, working directories, exit codes, stdout, and stderr. Successful paths exited 0; overwrite refusal and missing credentials exited 1 as expected. The repeated init did not overwrite state. Replay returned the same decision and `network_called: false`.

Inspect the [successful run audit](../evidence/smoke-success-audit.jsonl) and [missing-key failure audit](../evidence/smoke-missing-key-audit.jsonl). The copied records contain no secret value. Paths within transcripts reflect the original scratch execution, while these linked evidence copies are retained with the deliverable.

The core source and its 45-test suite were unchanged during the live continuation. `probe_live.py` was exercised through dry-run, one authenticated smoke, and a 12-call battery. `analyze_probe.py` then checked all saved results against their audit records and replayed their decisions offline. Commands and unedited outputs: [live smoke](../evidence/live-smoke-command.txt), [live battery](../evidence/live-battery-command.txt), [offline analysis](../evidence/live-analysis-command.txt). All three commands exited 0. An independent review also checked all 13 audit records and the credential-loading path without reading the dotenv or making additional requests.

Packet validation uses the installed prepare-and-run-build-task validator with `--strict --require-walkthrough`; the initial command/output is in [packet-validation.txt](../evidence/packet-validation.txt), with the continuation in [packet-validation-live.txt](../evidence/packet-validation-live.txt). These checks validate packet structure and cross-references, not model quality.

## Acceptance matrix

| Requirement | Status and evidence |
|---|---|
| FR-01 | Verified offline: fresh bootstrap/run and overwrite-refusal tests plus manual smoke. |
| FR-02 | Verified offline: config/input/response boundaries, ambiguous JSON, Unicode, model identity, distributions. |
| FR-03 | Adapter verified with mocks, missing-key smoke, and authenticated synthetic Choice calls. |
| FR-04 | Verified offline: probability/margin boundaries, ties, forced review, confidence kept separate. |
| FR-05 | Verified offline: saved evidence, flush failures, no-call failure paths, corruption checks, offline replay. |
| FR-06 | Verified offline: three-record smoke, bounded prevalidation, confusion/coverage, all-review case, partial failures. |
| FR-07 | Live smoke/battery and offline analysis command evidence; phase bounds, synthetic-only inputs, selected dotenv key, and all audit replays inspected. |
| NFR-01 | Python 3.14.6 observed and pinned; standard library only; bootstrap rejects moving model aliases through validation. Clean-machine runtime installation itself was not exercised. |
| NFR-02 | Commands and unedited outputs retained in the linked evidence. |

## Operational steps and reviewer quick check

From the deliverable root:

```powershell
python -m unittest -v
python jev_harness.py init --directory reviewer-demo
$jevRun = python jev_harness.py run --config reviewer-demo/config.json --input reviewer-demo/input.json --mode fixture | ConvertFrom-Json
python jev_harness.py replay --record $jevRun.audit_path
python jev_harness.py evaluate --config reviewer-demo/config.json --dataset reviewer-demo/dataset.json --mode fixture
```

Use a fresh directory name if `reviewer-demo` already contains files. `init` supplies all non-secret state. To inspect the recorded live continuation without credentials, run `python analyze_probe.py --directory evidence/live-pilot`. For a deliberate new probe, use the dotenv commands and fresh output directory described in [README.md](../README.md). Provider access was confirmed only by the recorded calls; the credential value was never displayed or copied to output.

## Known limitations and follow-up

No domain benchmark, calibration study, deployment, production integration, or Laya inference was performed. A few repeated live requests matched in the recorded synthetic sample; this is not a general reproducibility guarantee. A pinned model does not freeze provider internals, and provider caching is unknown. Demo thresholds remain illustrative. Fixture IDs select canned responses; fixture agreement does not establish semantic correctness.

This slice supports one Choice question. The probe analyzer reports repeated-request observations, but a representative evaluation suite, Noul/Score adapters, Laya execution, calibration plots, human review UI, caching, and production connectors remain future work. The byte limit is not a token-budget guarantee. Local audit files require appropriate protection and operational retention decisions before real sensitive data is used. See [RESEARCH.md](RESEARCH.md) for general application scope, the source-reviewed Laya assessment, and the proposed rollout sequence.
