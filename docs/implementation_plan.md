# Jev Harness implementation plan

## Goal

Deliver an inspectable Choice classification pilot, a bounded authenticated synthetic probe, and a research-backed general scope including Laya. [PRD.md](PRD.md) owns requirements; [task_checklist.md](task_checklist.md) owns progress; [agent_prompt.md](agent_prompt.md) owns the execution handoff.

## Proposed changes and responsibilities

All paths below are relative to the deliverable root. All were new relative to the empty starting workspace. The continuation adds the probe/cases/analyzer/results and updates documentation; the original core and 45-test suite remain unchanged.

| File | Responsibility |
|---|---|
| `jev_harness.py` | Canonical local contract, `init`, `run`, `replay`, and `evaluate` CLI; JSON validation, TypeSafe transport, deterministic policy, hashing, append-only audit. |
| `test_jev_harness.py` | Policy, validation, provider-boundary, negative-path, and CLI integration tests. |
| `probe_live.py` | NEW bounded smoke/battery CLI, literal dotenv credential loading, exclusive phase evidence, explicit provider calls through the existing core. |
| `live_cases.json` | NEW canonical synthetic probe cases and predeclared labels; exact repeats reference earlier inputs. |
| `analyze_probe.py` | NEW offline audit validation/replay and derived probe summary. |
| `LIVE_RESULTS.md` | NEW interpretation of actual live observations, command evidence, and limits. |
| `.python-version` | Pin the observed and tested Python runtime. |
| `README.md` | Commands for bootstrap and use; config and data handling guidance; verification links. |
| `RESEARCH.md` | Primary-source findings, applicability, limits, architecture, and staged pilot decisions. |
| `docs/PRD.md` | Requirement ownership. |
| `docs/implementation_plan.md` | File responsibilities, integration, implementation order, verification strategy. |
| `docs/task_checklist.md` | Evidence-backed status of small implementation slices. |
| `docs/agent_prompt.md` | Self-contained execution instructions. |
| `docs/walkthrough.md` | Actual implementation outcome, evidence mapping, limitations. |
| `evidence/` | Generated command transcripts and observed results, retained for review. |

## Dependency order and integration traces

1. FR-01, FR-02, NFR-01: bootstrap generates config, input, fixtures, and labeled dataset; strict validation precedes every adapter.
2. FR-03: `run` -> validated request -> explicit transport mode -> `validate_response`; live credentials come only from the config-named environment variable. Dependency error stops the command. No response repair, retry, or substitute model.
3. FR-04, FR-05: `validate_response` -> `decide` -> append completed audit event -> JSON stdout. Replay validates saved hashes and applies the stored policy, not current config.
4. FR-06: `evaluate` -> prevalidate labeled dataset -> the same run path per record -> aggregate metrics. Failures are explicit, with partial evidence identified rather than a complete report.
5. NFR-02: root runs tests and a fresh-directory CLI workflow, captures unedited outputs, and reconciles walkthrough/status.
6. FR-07: `live_cases.json` -> `probe_live.py --dry-run` -> literal selected dotenv key into process environment -> unchanged `run_one` -> exclusive phase results/audits -> `analyze_probe.py` offline verification -> derived summary and `LIVE_RESULTS.md`. No repository source, credential file, or production data is changed.

## Compatibility and migration

No existing clients or data to migrate. Python 3.14.6, standard library only, one documented TypeSafe adapter. Model aliases are rejected. The local schema is version 1; unsupported versions stop. Files are created exclusively, and audit events append. No data is deleted and no existing repository is touched. New model versions or providers require explicit config/adapter updates followed by fresh evaluation.

## Verification and test plan

Working directory: deliverable root. Commands come from the implemented CLI and Python standard-library test runner. CLI registration was checked against actual help; full results and exact paths are recorded in [walkthrough.md](walkthrough.md).

| Command | Purpose | Planning status |
|---|---|---|
| `python --version` | Runtime evidence for NFR-01. | Run: Python 3.14.6. |
| `python -m unittest -v` | FR-01 through FR-06 boundaries and integration. | Implemented suite; final output linked from walkthrough. |
| `python jev_harness.py --help` | Verify command registration. | Run, exit 0. |
| `python jev_harness.py init --directory demo` | Bootstrap empty state, FR-01. | Run with a fresh temporary directory, exit 0. |
| `python jev_harness.py run --config demo/config.json --input demo/input.json --mode fixture` | End-to-end offline path, FR-02/FR-04/FR-05. | Run with the generated config/input, exit 0. |
| `python jev_harness.py evaluate --config demo/config.json --dataset demo/dataset.json --mode fixture` | FR-06 bounded evaluation. | Run with generated three-record data, exit 0. |

Replay used the actual audit path returned by run and reproduced the saved decision, exit 0. Reinitialization and a live-mode attempt with the credential deliberately removed both exited 1 as expected. [The original offline smoke transcript](../evidence/smoke-transcript.json) preserves each command and unedited streams. Subsequently, authenticated smoke and battery commands exited 0; their exact CLI arguments are in [live smoke](../evidence/live-smoke-command.txt) and [live battery](../evidence/live-battery-command.txt). `python analyze_probe.py --directory evidence/live-pilot` is the offline FR-07 verification command from the deliverable root; its [recorded output](../evidence/live-analysis-command.txt) validates all saved audits. The suite covers malformed responses, missing credentials, unavailable network, review thresholds, ties, altered replay, and invalid datasets. Preserve command outputs for NFR-02; never replace failures with invented passing output.

## Dependencies and decisions

No package installation. TypeSafe access is confirmed; the first real domain dataset remains an owner decision. The pilot supports one Choice question before broadening to Score/Noul or workflow integrations. Domain thresholds are illustrative until measured against labeled data. Laya was researched read-only, not installed or executed; its proposed adapter must add immutable artifacts and explicit truncation failure rather than reuse unsafe defaults.
