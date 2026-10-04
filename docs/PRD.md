<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev Harness requirements

## Scope

Build a small, directly callable classification harness whose model observations and deterministic policy decisions can be inspected and replayed. This is a local pilot, with synthetic first-run data and an explicit live mode. The initial supported primitive is Choice. The research covers general profiles, the requested Receptron Laya repository, and Noul/Score as future extensions. The user's continuation authorizes testing with an existing dotenv credential; a bounded live probe now exercises that path.

The user requested research, planning, and implementation. The starting workspace has no repository or application files; `python --version` reported Python 3.14.6 and `git rev-parse --show-toplevel` reported that this is not a Git repository. No repository is being initialized or published.

Decisions: begin with incoming-data classification; use TypeSafe's direct API; produce recommendations only. Provider access is confirmed by the recorded live probe. A real labeled pilot dataset remains unresolved. Fixtures and the small synthetic live sample do not establish domain quality or universal repeatability.

Non-goals: production integration, a scheduler, automatic external actions, general reasoning, model training, a web service, or synthetic evidence presented as live evidence.

## Architecture

CLI input -> strict validation -> explicit fixture or TypeSafe HTTP adapter -> response validation -> deterministic policy -> local audit and JSON result.

Replay consumes a saved record directly, with no model call. Evaluation consumes at most 20 labeled records and reports recommendation quality separately from acceptance coverage. Code owns limits and type checks; configuration owns labels, rubric, thresholds, timeout, endpoint, model version, and paths. The model performs inference inside the adapter, never connects components.

## Requirements and acceptance

| ID | Requirement | Validation |
|---|---|---|
| FR-01 | `init` creates all non-secret state needed for one complete fixture run and refuses to overwrite existing state. | Bootstrap in a fresh temporary directory; run twice and inspect refusal. |
| FR-02 | Validate untrusted configuration, input, provider response, ranges, model pin, and probability distributions; failures are explicit and nonzero. | Boundary and malformed-input unit tests. |
| FR-03 | An explicit live mode calls the documented TypeSafe endpoint once per record, without fallback or hidden retries. Missing credentials name the environment setting without revealing it. | Mock transport tests, missing-key CLI test, and authenticated synthetic calls. |
| FR-04 | Code derives accept/review from configured probability, top-two margin, and review labels. Ties always require review. No tool or downstream business action executes. | Known distributions and threshold boundary tests. |
| FR-05 | Persist request, configuration, response, policy, model version, provenance, hashes, result, and failures in append-only audit events. Replay checks record integrity and reproduces the policy decision offline. | CLI run/replay and altered-record rejection tests. |
| FR-06 | Evaluate a fully validated, bounded labeled dataset; report overall accuracy, accepted accuracy, coverage, review count, and confusion counts with fixture/live provenance. | Fixture evaluation and invalid-dataset tests. |
| FR-07 | Ship a bounded live probe that reads only the configured dotenv credential, sends one smoke before at most 12 further synthetic calls, prevents accidental phase reruns, and derives an offline summary from validated audits. | Credential-free dry run, live command transcripts, and offline analysis/replay evidence. |
| NFR-01 | Use a pinned Python runtime and no external runtime packages; first-run code never resolves a moving dependency or model alias. | Runtime pin, source inspection, tests and fresh temporary-directory smoke check. |
| NFR-02 | Capture actual commands and unedited outputs; distinguish local tests, observed live results, and unperformed domain/Laya evaluation. | Evidence files and completion walkthrough. |

## Technical contracts

TypeSafe's [API reference](https://docs.typesafe.ai/api) owns the external contract. A request supplies `model`, `state`, and a map of typed `questions`. The adapter exposes one Choice question with a `criteria` map. The response's `model` must equal the requested version, the answer key must match, and probabilities must cover all configured labels. A probability sum may differ from one by at most 0.001 for rounding; values are never renormalized. Usage is retained when validating the documented response.

The local config is versioned (`schema_version: 1`) and contains a question and policy. Bootstrap emits the concrete configuration; `jev_harness.py` is the canonical owner of this application contract. The core reads credentials only from the configured environment variable. The probe can populate that variable in its own process from a user-selected dotenv key; it never sources the file or writes the value. Only the direct TypeSafe HTTPS host is supported in this slice; a different provider needs its own reviewed adapter.

Audit request/response material can contain input data. The local operator owns the audit directory and supplies only data approved for the provider. Error reports exclude credentials and upstream response bodies. An audit-write failure prevents a normal success response. Hashes detect accidental alteration, not malicious re-signing; these files are not signed evidence.

## File impact

See the canonical file responsibility table in [implementation_plan.md](implementation_plan.md). [task_checklist.md](task_checklist.md) owns execution status; [agent_prompt.md](agent_prompt.md) carries the handoff instructions.

## Success criteria

The offline pilot is acceptable when bootstrap, run, replay, evaluation, missing-key, and meaningful negative paths have command evidence. A live-capability claim additionally requires an authenticated provider smoke run. A useful business-quality claim additionally requires a representative held-out dataset and explicitly chosen error/review targets. Neither live quality nor production readiness follows from fixture tests.

## Risks and conditional gates

External contract: official documentation supplies API provenance; the recorded live probe verifies the exercised Choice contract. Untrusted input: reject ambiguous JSON, unknown settings, invalid bounds, aliases, malformed distributions, and unexpected model changes. Persistence: create and append records; never overwrite user state. Sensitive data: local audits contain synthetic state; secrets stay in the process environment. Capacity: evaluation is bounded to 20 items; the watched live probe to 13 total requests; no concurrent or scheduled execution. Domain correctness: deterministic facts and authorization remain code-owned. Jev classifications can be wrong even when well typed and confident.

## References

[Research and pilot design](RESEARCH.md), [TypeSafe models](https://docs.typesafe.ai/models), [confidence semantics](https://docs.typesafe.ai/confidence), and [known Jev limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
