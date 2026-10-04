<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev Orchestration Harness partial implementation walkthrough

## Outcome

The one-task CLI, two pinned local-model registrations, Windows OVMS setup, bounded local client, and Docker verifier now exist. A negative test reproduced an evaluator false green from candidate `os._exit(0)`; the same test passed after candidate calls moved to subprocesses and a trusted nonzero-test verdict became mandatory. Current-format fixture, watched 30B rules-only, and watched experimental Jev-routed 7B runs each passed protected tests and artifact-aware replay. The full suite passed 96 tests. A direct OpenVINO query maps the fast server's targeted `GPU.1` to Arc Pro B70, with a local 7B coding response through that server. Release 1 remains partial: no paired same-task routing study, controller-side server/device/artifact receipt, general task import or broker CLI, and no Jev promotion gate. [Canonical PRD](../../PRD-Jev-Orchestration-Harness.md), [canonical PRS](../../PRS-Jev-Orchestration-Harness.md), [plan](implementation_plan.md), [checklist](task_checklist.md), [execution brief](agent_prompt.md). (JOH-1–JOH-8)

## Actual design and changed files

| File and action | Current purpose |
| --- | --- |
| NEW `orchestrate.py` | `init`, `dry-run`, `demo`, `run`, `inspect`, `replay`; strict task/config, one baseline or experimental Jev route, isolated Git archive checkout, strict JSON full-file replacement of declared existing paths, pinned Docker verifier, event ledger and replay. `--jev-mode off` makes a clean rules-only arm. |
| NEW `model-pins.json` | Canonical fast/strong model IDs, HF commits, artifact sizes/counts, weight hashes, and parser metadata. Controller `init` and OVMS setup derive from it; `load_state` rejects identity/revision drift. |
| NEW `local_model.py` | Direct `probe` CLI and importable bounded OVMS chat completion with loopback/model/usage checks. |
| NEW `tools/setup_ovms.ps1` | Direct `dry-run`, `install`, `serve`, `verify` actions for pinned OVMS v2026.4.0 and model artifacts from `model-pins.json`; new-root and two-loopback-port checks; file hashes. |
| NEW `tools/prepare_verifier.ps1` | Direct `dry-run`, `install`, and `verify` for the pinned Linux/amd64 Docker image. Tested dry-run and verify on an already prepared host. |
| NEW `test_orchestrate.py` | Controller unit and Docker integration tests, including the reproduced early-zero-exit false green. |
| NEW `test_local_model.py` | Local client transport and response contract tests. |
| MODIFY `README.md` | Copyable observed commands, evidence links, and operational limits. |
| MODIFY `docs/PRD-Jev-Orchestration-Harness.md`, `docs/PRS-Jev-Orchestration-Harness.md` | Canonical intended requirements and observed limits. |
| NEW `docs/build-tasks/jev-orchestration-harness/{PRD.md,implementation_plan.md,task_checklist.md,agent_prompt.md,walkthrough.md}` | Requirements pointer, file-level plan, live checklist, handoff, and this evidence record. |

`jev_harness.py` remains the sole TypeSafe Choice adapter and deterministic acceptance-policy owner. The controller calls it directly after projecting the approved summary; no model connects components. `model-pins.json` owns model identity values, generated task config owns endpoints/limits, and code validates ranges. The coding model's only effect proposal is full file content for an allowed existing path. The verifier executes protected evaluator code in pinned `docker.io/library/python@sha256:b921fe7e7522f828d45197a47656ec465a9b15689b27fa8e1fba2864fca5b967` with network off, read-only root and checkout, capabilities dropped, unprivileged user, and bounded resources. The current evaluator runs candidate calls in child processes and reports a separate test verdict; replay additionally checks saved evaluator, model, patch, checkout, and restore artifacts. (JOH-1–JOH-7)

## Plan deviations

The planned `git apply` patch contract became strict JSON full-content replacement of declared existing files. The planned `doctor`, `prepare`, `start`, `smoke`, and `generate` commands in `local_model.py` were not implemented; pinned setup is through direct PowerShell CLIs, and `local_model.py` exposes only `probe`. The controller has no `--task` import option or direct broker/verifier command. A clean rules-only `--jev-mode off` arm was added after discovering that the baseline otherwise always called Jev. `model-pins.json` now removes duplicate model pin ownership across controller and setup. The false-green evaluator bug forced a trusted-verdict contract; replay now snapshots and validates evaluator/model/patch/checkouts. Earlier completed run records do not satisfy these later checks. These changes are reflected in the [plan](implementation_plan.md). (JOH-1–JOH-8)

## Verification evidence

The recorded commands below ran from the original `outputs/jev-harness` working directory. Links to `events.jsonl` and verifier files retain the unedited run evidence. Copied historical run records are static archival proof here: their nested fixture Git histories and absolute original paths were intentionally not migrated. Create a fresh run in this project folder for `inspect` and `replay`; replay is historical integrity inspection, not fresh inference.

`python -B orchestrate.py --help` listed `init,dry-run,run,demo,inspect,replay`; `python -B local_model.py --help` listed only `probe`. Both command outputs were inspected before documenting the CLI. The historical command `python -B orchestrate.py init --directory evidence/orchestration-interval-demo --fixture-complexity complex --local-endpoint http://127.0.0.1:8765/v1/chat/completions` created [task.json](../../../evidence/orchestration-interval-demo/task.json), which names `fixture-merge-intervals`, one allowed `solution.py`, and six protected cases in the evaluator. `--local-endpoint` was later replaced by separate `--fast-endpoint` and `--strong-endpoint` options; do not reuse the historical command on current code. A fixture `demo` created [run `5382142a-0d2e-499d-8bae-02450dc8e02a`](../../../evidence/orchestration-interval-demo/runs/5382142a-0d2e-499d-8bae-02450dc8e02a/events.jsonl). The clean rules-only control command `python -B orchestrate.py run --directory evidence/orchestration-interval-demo --mode fixture --jev-mode off --route-source baseline` created [run `aacedc07-0a8b-4d25-938e-ca1eb261e320`](../../../evidence/orchestration-interval-demo/runs/aacedc07-0a8b-4d25-938e-ca1eb261e320/events.jsonl) with `jev_audit_path: null` on replay. These runs precede the trusted-verdict fix and are exploratory. (JOH-1, JOH-2, JOH-4–JOH-6)

`pwsh -NoProfile -File tools/setup_ovms.ps1 -Action dry-run -Model fast` and the same with `-Model strong` both exited zero after migration to `model-pins.json`. Their [unedited fast output](evidence/ovms-fast-dry-run-post-pins.json) and [strong output](evidence/ovms-strong-dry-run-post-pins.json) report zero writes and 4,625,702,767 / 16,461,253,217 download bytes. A watched fast install on a separate root reported `status: installed`; fast serve reported `status: ready`, but original tool stdout was not saved. The installed manifest remains on the original host. Read-only `pwsh -NoProfile -File tools/setup_ovms.ps1 -Action verify -Model fast -Root <installed-fast-root>` returned [unedited `status: verified` output](evidence/ovms-fast-verify.json). The strong setup-script install/serve path has not run. Direct [OpenVINO device mapping and fast server startup evidence](evidence/ovms-device-map.md) identify explicit `GPU.1` as Arc Pro B70. (JOH-3, JOH-4, JOH-6)

The separately running 7B server answered one synthetic client probe. Exact command and unedited output:

```text
python -B local_model.py probe --endpoint http://127.0.0.1:8765/v1/chat/completions --model qwen25-coder-7b-int4 --max-tokens 64 --timeout-seconds 120
{"content": "LOCAL_MODEL_PROBE_OK", "model": "qwen25-coder-7b-int4", "status": "ok", "usage": {"completion_tokens": 6, "prompt_tokens": 38, "total_tokens": 44}}
```

The watched command `python -B orchestrate.py run --directory evidence/orchestration-interval-demo --mode live --jev-mode fixture --route-source baseline --watch` with typed `yes` created [run `f1e2560f-63ab-4e59-91a6-bf81b280e9a1`](../../../evidence/orchestration-interval-demo/runs/f1e2560f-63ab-4e59-91a6-bf81b280e9a1/events.jsonl). Its 30B response proposed one `solution.py` replacement; [unedited stderr](../../../evidence/orchestration-interval-demo/runs/f1e2560f-63ab-4e59-91a6-bf81b280e9a1/verifier.stderr) reads:

```text
test_contained (__main__.Acceptance.test_contained) ... ok
test_disjoint (__main__.Acceptance.test_disjoint) ... ok
test_empty (__main__.Acceptance.test_empty) ... ok
test_touching (__main__.Acceptance.test_touching) ... ok
test_unmodified (__main__.Acceptance.test_unmodified) ... ok
test_unsorted (__main__.Acceptance.test_unsorted) ... ok

----------------------------------------------------------------------
Ran 6 tests in 0.000s

OK
```

This is a genuine six-case coding demonstration but an old-verifier record, not post-repair JOH-5 evidence. An earlier 30B arithmetic [failure record](../../../evidence/orchestration-strong-demo/runs/1ec3972a-f2dd-454f-b774-195e831a594a/events.jsonl) shows `invalid_patch` after a Markdown fence; no verifier ran. The next arithmetic [run](../../../evidence/orchestration-strong-demo/runs/76ca6e5e-2223-4068-8aed-b71dc3a8582e/events.jsonl) passed three protected cases, also before the verdict repair. A paired 7B and 30B coding trial has not run. (JOH-3–JOH-6)

The false-green reproduction command `python -B -m unittest -v test_orchestrate.DockerDemoIntegrationTest.test_candidate_early_zero_exit_cannot_claim_green` initially exited 1 because `OrchestrationError` was not raised for candidate `os._exit(0)`. The [full unedited before output](evidence/early-exit-before.txt) is copied from the original failing tool result. After the evaluator/verdict change, the same command exited 0 with `Ran 1 test in 0.913s` and `OK`; [full unedited after output](evidence/early-exit-after.txt) was captured here. `python -B -m unittest -v` then exited 0 with [unedited `Ran 96 tests in 15.664s` and `OK`](evidence/tests-final.txt). Older runs fail current artifact-aware replay. (JOH-5, JOH-6)

Current-format commands and on-disk outputs (distinct fast port 8766 and strong port 8765):

```text
python -B orchestrate.py init --directory evidence/orchestration-proof-interval --fixture-complexity complex --fast-endpoint http://127.0.0.1:8766/v1/chat/completions --strong-endpoint http://127.0.0.1:8765/v1/chat/completions
python -B orchestrate.py demo --directory evidence/orchestration-proof-interval
python -B orchestrate.py run --directory evidence/orchestration-proof-interval --mode live --jev-mode off --route-source baseline --watch
python -B orchestrate.py init --directory evidence/orchestration-proof-add --fixture-complexity simple --fast-endpoint http://127.0.0.1:8766/v1/chat/completions --strong-endpoint http://127.0.0.1:8765/v1/chat/completions
python -B orchestrate.py run --directory evidence/orchestration-proof-add --mode live --jev-mode live --route-source jev --dotenv <authorized-dotenv-path> --watch --experimental-jev-route
```

The private dotenv path in the final command is redacted here; no key appears in run evidence. The [fixture interval run](../../../evidence/orchestration-proof-interval/runs/01e95f48-8520-4faf-a3e6-46903d58b46a/events.jsonl) and watched [rules-only strong run](../../../evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/events.jsonl) each have [unedited trusted stdout](../../../evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/verifier.stdout) with:

```json
{"errors": 0, "failures": 0, "schema_version": 1, "tests_run": 6}
```

The watched strong [unedited stderr](../../../evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/verifier.stderr) lists the six passing edge cases. Its routed event has `jev_audit_path: null` and its replay returned:

```json
{"jev_audit_path":null,"jev_network_called":false,"operation":"historical_replay","route":"strong","run_status":"completed","status":"completed"}
```

The watched experimental Jev Choice route selected `fast` for `fixture-add`; the [7B run event](../../../evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/events.jsonl) records `source: jev`, `label: fast`, and one local `qwen25-coder-7b-int4` response. [Unedited trusted stdout](../../../evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/verifier.stdout) is:

```json
{"errors": 0, "failures": 0, "schema_version": 1, "tests_run": 3}
```

Its [unedited stderr](../../../evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/verifier.stderr) lists three passing arithmetic tests, and current artifact-aware replay returned `completed`, `fast`, `jev_network_called: false` (the latter means replay made no provider call; the original run used live Jev). The [rules-only fixture control](../../../evidence/orchestration-proof-interval/runs/43e8e0cb-629e-4d24-82ba-f36619e4e6da/events.jsonl) also completed with zero Jev calls and a six-test verdict. A single Jev success does not qualify routine routing; strong and fast models solved **different** generated tasks, so neither branch is a head-to-head model comparison. (JOH-1–JOH-8)

Verifier image preparation is shipped as `pwsh -NoProfile -File tools/prepare_verifier.ps1 -Action dry-run|install|verify`. On this host, [unedited dry-run output](evidence/verifier-image-dry-run.json) reported an existing pinned Linux/amd64 image, zero writes, and 43,416,556 registry artifact bytes if the cache were empty. [Unedited verify output](evidence/verifier-image-verify.json) returned `status: verified`; `install` was not run because the image was present. (JOH-1, JOH-5)

## Acceptance matrix

| PRD capability | Status and evidence |
| --- | --- |
| JOH-1 empty-state full fixture | Demonstrated: [current fixture run](../../../evidence/orchestration-proof-interval/runs/01e95f48-8520-4faf-a3e6-46903d58b46a/events.jsonl) has six-test verdict and passed replay. Verifier-image preparation command is shipped; its install action was not needed on this host. |
| JOH-2 bounded Jev decision | Partial: strict route packet and clean rules-only control exist; profile lifecycle/promotion is absent. |
| JOH-3 two pinned local models | Partial: two pinned registrations and separate 7B/30B watched coding runs. [Direct B70 mapping/explicit fast target](evidence/ovms-device-map.md) plus 7B response support bounded GPU inference. Paired same-task trial and controller-side installed artifact/device binding remain open. |
| JOH-4 bounded one-task effects | Partial: isolated checkout and Docker limits observed; general broker and later reconstruction command absent. |
| JOH-5 trustworthy completion | Demonstrated for generated tasks: false green reproduced and fixed; current fixture, 30B, and 7B runs have trusted verdicts and current replay; [96-test suite](evidence/tests-final.txt) passed. Non-test acceptance criteria and general task import remain open. |
| JOH-6 audit and replay | Demonstrated for current-format generated tasks: event/audit/replay check saved evaluator/model/patch/checkouts. Old records fail the newer contract; migration policy and general tasks remain open. |
| JOH-7 provider/secret admission | Partial: loopback local client and Jev summary projection exist; direct effect broker and broader source classes absent. |
| JOH-8 empirical route promotion | Open: no held-out paired routing study or promotion gate. |

## Operational steps, known issues, and reviewer quick check

Use `tools/prepare_verifier.ps1 -Action dry-run`, then `verify` or a watched `install` if absent, before `init` on a new empty directory, `dry-run`, and `demo`. Git and Python 3.14.6 must be present. For local inference, inspect both OVMS setup dry-runs before bounded watched install/serve; `-Action verify` checks an installed root. `local_model.py probe` tests one synthetic completion. For a live coding run, pass separate `--fast-endpoint` and `--strong-endpoint` loopback URLs at `init` if their ports differ from defaults 8000 and 8001, inspect `dry-run --mode live --jev-mode fixture`, then run with `--watch` and typed `yes`. Do not reuse a run directory or replace canonical task/config/audit files; failures remain inspectable. No shipped command reconstructs a previously modified checkout, and no schedule or unattended batch exists. (JOH-1, JOH-3, JOH-4, JOH-6)

A reviewer can run `python -B orchestrate.py --help`, `python -B local_model.py --help`, `python -B -m unittest discover -s tests -v`, then create a fresh `init`/`demo` directory and inspect its `verifier.stdout` trusted verdict, `verifier.stderr` test names, `events.jsonl` terminal state, and `replay` result. The reviewer should also run the early-zero-exit negative test and verify that it fails the run without `completed`. [B70 mapping evidence](evidence/ovms-device-map.md) supports the fast server claim; keep per-run binding, paired routing comparison, and JOH-8 superiority open. (JOH-1–JOH-8)
