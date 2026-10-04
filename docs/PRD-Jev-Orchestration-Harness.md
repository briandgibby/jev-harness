<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev Orchestration Harness — Product Requirements Document

> Status: DRAFT · Owner: TBD · Created: 2026-10-04
> No section has been ratified. This is a cross-project internal tool, not a SignSense production agent.

## 1. Purpose & vision

A developer now chooses models, scopes work, runs checks, and judges completion across separate tools. A coding model can make a plausible choice without leaving an inspectable reason or test result. The **Jev Orchestration Harness** will provide a command-line test surface that runs one bounded task through a code-owned sequence: admit the task, make one typed routing decision, invoke a registered local coding model, run required checks, and report the evidence. Its first live coding backend targets OpenVINO Model Server (OVMS) 2026.4.0 on Windows and must demonstrate inference on the operator's Intel Arc Pro B70. The Core Ultra CPU remains a separately reported device option, not evidence of GPU use.

Jev may handle a semantic decision only after that decision profile earns its place in a task-specific evaluation. Its finite output and the harness's policy make a branch inspectable and replayable. They do not prove that a fresh Jev answer is stable or correct. The product value is a measured improvement in verified work, cost, or review effort, with a small blast radius when a judgment is wrong. [TypeSafe coding-agent guidance](https://docs.typesafe.ai/introduction/coding-agents), [Coding Decision Study](coding-decision-study.md).

## 2. Users & personas

| Actor | Need and authority |
| --- | --- |
| Operator | Starts one task, sets scope and budgets, sees every provider destination, and inspects the final evidence. The operator authorizes live provider use and any later wider run. |
| Reviewer | Records a named resolution for an uncertain route or a non-test acceptance criterion. A route resolution starts a linked bounded run; a reviewer cannot turn a failed command into a pass. |
| Integrator | Registers a model, tool, or decision profile through a documented interface and supplies evaluation cases. The integrator cannot bypass the run policy through a model label. |

Release 1 is local, single-user internal tooling. It is an increment on the standalone Jev classification harness, not the separate Jev Brain knowledge system.

## 3. Value drivers → required capabilities

| Value driver | Capabilities | Observable value |
| --- | --- | --- |
| One task reaches a checkable end state | JOH-1, JOH-4, JOH-5 | A fresh setup produces a fixture result; a bounded live task produces exact check output or a named failure. |
| Work goes to a suitable registered engine | JOH-2, JOH-3 | The selected route, eligibility rule, model ID, and review path are visible for each run. |
| One bad judgment cannot take over the workflow | JOH-2, JOH-4, JOH-7 | A route cannot enlarge permissions, budget, workspace scope, or skip verification. |
| Decisions can be examined and improved | JOH-6, JOH-8 | A reviewer can replay policy from saved evidence and compare each profile with baselines. |

## 4. Capability catalog

| ID | Required capability and actor-visible outcome | Acceptance signal | Governing ADR |
| --- | --- | --- | --- |
| JOH-1 | The operator can initialize an empty workspace and run a full fixture task through routing, execution, verification, and report. Missing live credentials stop with the setting's name. | One shipped command creates required non-secret state; a second command completes the fixture path without manual inserts or source edits. | None yet. |
| JOH-2 | The integrator can register finite decision profiles. Exact checks stay in code; Jev receives only an approved semantic question and approved fields. An `unclear` answer goes to a declared review or escalation path. | A profile outside its allowed inputs, model, labels, or evaluation status cannot control a live route. | None yet. |
| JOH-3 | The operator can see a task route to one of at least two pinned, locally runnable coding-model registrations already eligible for that task. The route names its decision source, policy version, model artifact revision, serving version, and actual inference device. | A Jev label cannot select an unregistered or ineligible model; an uncertain label does not appear as a successful selection. Both registered models produce inspected local responses before a routing comparison is claimed. | None yet. |
| JOH-4 | The operator can run one task with displayed limits on paths, tools, provider calls, time, and spend. The run changes only its isolated checkout and stops at a cap. | The task command refuses wider effects or a second unattended task; exceeded limits leave a reportable partial run. | None yet. |
| JOH-5 | The operator receives `completed` only after trusted evaluator checks actually run and pass on the produced artifact. A failed or missing check remains visible. | The report links each exact command, exit code, and protected unedited output; evaluator tests outside model write scope and any declared non-test acceptance criterion determine the verdict. | None yet. |
| JOH-6 | The reviewer can inspect every transition, failure, model response, and policy decision without exposing credentials. Historical replay recomputes the saved policy decision without a fresh provider call. | Replaying the record yields the historical policy outcome or a visible integrity error; a missing audit prevents a success report. | None yet. |
| JOH-7 | The operator can inspect provider destinations and fields before a live call. Local admission rules block unapproved data and side effects before model inference. | A forbidden source or destination causes no provider or tool call and produces a safe error with a next action. | None yet. |
| JOH-8 | The operator can compare a Jev profile with rules and LLM baselines before enabling it for active routing. Profiles gain scope one at a time. | A profile with no held-out evidence stays in candidate or shadow mode; the report includes error, abstention, cost, and downstream outcome measures. | None yet. |

These capabilities describe the complete intended behavior. An early one-task controller now has `init`, `dry-run`, `demo`, `run`, `inspect`, and `replay` commands, and a local OVMS client has a bounded `probe`. After a reproduced false-green bug was repaired and replay strengthened, a watched rules-only 30B interval-merge run produced a trusted verdict for six passing protected tests; a watched experimental Jev route selected the 7B model for a simple add task, whose three protected tests passed. Both current-format records replayed with saved evaluator, model, patch, checkout, and restore artifacts checked. The final [96-test suite](build-tasks/jev-orchestration-harness/evidence/tests-final.txt) passed. A direct [OpenVINO device query and running OVMS command](build-tasks/jev-orchestration-harness/evidence/ovms-device-map.md) identify the fast server's explicit `GPU.1` as Arc Pro B70; its endpoint answered the 7B coding call. A clean rules-only control is available through `--jev-mode off`. The different-task examples are not a paired coding-quality or routing comparison. Controller-side binding of each run to its installed artifact/device and a Jev promotion gate remain incomplete. The [PRS](PRS-Jev-Orchestration-Harness.md) separates observed behavior from remaining requirements.

## 5. Phased delivery

| Phase | User outcome | Boundary that phase proves |
| --- | --- | --- |
| Release 1: one-task orchestration | An operator runs a generated fixture, exercises at least two pinned local coding-model registrations, and then runs one watched, bounded coding task. A versioned baseline policy owns the route with Jev off or in shadow; a promoted Jev profile can later route among registered coding models. Code verifies the result. | End-to-end CLI path, explicit egress, caps, audit, replay, and a failure report. A recorded OVMS 2026.4.0 Windows inference call must identify the Arc Pro B70 as the target and show the selected model's response; CPU or fixture output does not satisfy that GPU acceptance check. Routine active Jev routing requires JOH-8 evidence. |
| Later: diagnostic profiles | A reviewer can inspect Jev failure-triage, plan-criteria, or test-gap classifications beside the baseline result. | Each profile has its own labels, gold cases, error costs, and held-out promotion gate. |
| Later: alternative inference backend | An operator can evaluate a local Laya adapter against the same decision cases. | Laya uses its own pinned artifacts and thresholds; wire similarity does not make it Jev. |

Release 1 has no automatic repair loop. After a failed implementation or check, the operator starts a new bounded run with the failure evidence. The system does not chain model decisions to conceal the failed step.

## 6. Success metrics

| Measure | Release 1 evidence or target |
| --- | --- |
| First-run completion | A fresh directory completes the generated fixture task with one command after `init`; the command and unedited output are retained. |
| Watched live completion | One real task runs inside an isolated checkout and reaches `completed`, `review_required`, or `failed` with an audit and exact evaluator output. No status is inferred from agent prose. |
| Local model availability | At least two distinct coding-model artifact revisions are registered, loaded locally, and each answers the same bounded coding prompt through the CLI. Record the resolved artifact hashes and serving/runtime version. |
| Intel GPU inference | A watched OVMS 2026.4.0 Windows run maps the Arc Pro B70 to an OpenVINO device ID and explicitly targets that `GPU.<index>`, returns a non-fixture response, and retains server/device and client request evidence. A CPU response or merely detecting a GPU does not pass. |
| False-green rate | Target zero in the release acceptance set: no `completed` report when a required check failed, did not run, or was weakened. |
| Unauthorized egress or effect | Target zero in negative acceptance cases: no forbidden payload or tool call reaches a provider or executor. |
| Jev route quality | Baseline, harm tolerance, abstention target, and study size are **TBD from pilot and owner risk preference**. No improvement claim follows from the existing 13 synthetic, non-coding calls. |
| All-in cost per verified completion | Measure on the held-out task set, including routing, coding, retries, checks, and priced reviewer time. The [Coding Decision Study](coding-decision-study.md) proposes a later joint success-and-cost comparison; its margins are not ratified product targets. |

## 7. Relationship to existing systems

The [standalone Jev harness](../README.md) owns one Choice call, TypeSafe transport, validation, acceptance policy, audit, and replay. The new `orchestrate.py` controller imports that interface and adds a generated two-model registry, isolated task copy, constrained full-file replacement, and protected Docker verifier for one task. It remains an experiment with incomplete strong-model setup-script, device-identity, paired-comparison, and promotion evidence. Jev's existing `accept` output is a recommendation, not execution authority.

The [Coding Decision Study](coding-decision-study.md) owns the empirical protocol. It does not supply an agent runner today. [Jev Brain](second-brain/PRD.md) is a separate, unbuilt knowledge-vault product; it is neither replaced nor included in Release 1. Receptron's [Laya runner](https://github.com/receptron/laya) is a later separately measured backend, not a silent fallback. These drafts are now in the `~/Git/jev-harness/docs` project folder, which is not yet a Git repository; no commit is claimed.

## 8. Risks & open questions

### Risks & mitigations

| Risk | Product response |
| --- | --- |
| A confident but wrong Jev route under-scopes a coding task. | Hard eligibility rules take precedence. Each route affects one bounded next step, and mandatory verification still runs. Track harmful under-routing by profile. |
| Long, adversarial, or irrelevant state moves Jev's answer. | Send only allowlisted state, include `unclear`, test option order and adversarial cases, and keep inactive profiles out of live control. [Known limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13). |
| Audits or provider calls disclose sensitive source. | Inspect fields and destinations before sending; exclude raw credentials. Protect unedited local evidence and quarantine suspected secret-bearing output. The current harness stores its complete input and request, so source admission occurs before it is called. |
| A passing suite misses a requirement. | Independent acceptance checks and reviewer disposition remain distinct from the coding model's own tests. |
| A provider or disk failure disappears behind a fallback. | Record the failed step and stop with a named next action. A later retry is a new explicit run. |

### Open questions

The first local provider interface is OVMS 2026.4.0 on Windows. Two OpenVINO INT4 coding-model registrations are [Qwen2.5-Coder-7B-Instruct](https://huggingface.co/OpenVINO/Qwen2.5-Coder-7B-Instruct-int4-ov) and [Qwen3-Coder-30B-A3B-Instruct](https://huggingface.co/OpenVINO/Qwen3-Coder-30B-A3B-Instruct-int4-ov); their artifact revisions and expected metadata are owned by [model-pins.json](../model-pins.json), read by the controller and setup script. The installed fast root passed read-only hash verification, while the controller has not bound artifact/device proof into individual run records. Both models have returned local coding responses on different generated tasks; direct B70 identity is proven for the fast server, but a paired model comparison remains open. The larger model's [published GPU guidance](https://docs.openvino.ai/2026/model-server/ovms_demos_code_completion_vsc.html) recommends at least 19 GB of VRAM. The owner still needs to settle the host repository, numeric task budgets, eligible source/egress classes, reviewer, and promotion targets. Carry unresolved choices to `docs/BACKLOG.md` in the chosen host repository before handoff. Decisions expensive to reverse need ADRs; none are ratified here.

## 9. Out of scope

Release 1 does not make Jev generate plans, code, prose, or tool calls. It does not ask Jev to certify green tests, calculate exact facts, grant access, or arbitrate secrets. It does not run batches, schedules, unattended repairs, arbitrary shell commands with ambient credentials, production deployments, or irreversible external actions. It does not implement Jev Brain, claim general coding superiority, infer GPU execution from host detection, or substitute Laya for Jev without a separate evaluation.
