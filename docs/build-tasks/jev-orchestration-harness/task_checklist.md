<!-- doc-governance: essential; canonical: self; checked: 2026-10-04 -->
# Jev Orchestration Harness task checklist

## Scope and marker legend

The [requirements pointer](PRD.md), [implementation plan](implementation_plan.md), [execution brief](agent_prompt.md), and [partial walkthrough](walkthrough.md) govern this checklist. `[ ]` means not evidenced, `[/]` means in progress, and `[x]` means the exact check ran with retained output. The current CLI is a bounded experiment, not a completed Release 1. (JOH-1–JOH-8)

## Phase 1: fixture and controller

- [x] JOH-1, JOH-4, JOH-6: NEW `orchestrate.py` `init` creates the simple or complex fixture, tiny Git base, protected evaluator, strict config, and model fixtures from an empty directory. The [interval task manifest](../../../evidence/orchestration-interval-demo/task.json) and [controller tests](../../../tests/test_orchestrate.py) are retained.
- [x] JOH-2, JOH-3, JOH-7: The controller admits strict task/config input, derives a finite baseline route, projects a small Jev packet, and reuses `jev_harness.run_one`. A rules-only `--jev-mode off` run has [recorded zero Jev calls](../../../evidence/orchestration-interval-demo/runs/aacedc07-0a8b-4d25-938e-ca1eb261e320/events.jsonl).
- [x] JOH-1, JOH-4–JOH-6: `demo`, `run`, `inspect`, and `replay` create one isolated checkout, apply strict JSON full-file replacement only to declared existing paths, run one Docker evaluator, and preserve a terminal event record. The current [fixture interval run](../../../evidence/orchestration-proof-interval/runs/01e95f48-8520-4faf-a3e6-46903d58b46a/events.jsonl) has a six-test trusted verdict and passed current artifact-aware replay.
- [x] JOH-5: The same Docker negative test [failed before](evidence/early-exit-before.txt) with `OrchestrationError not raised` and [passed after](evidence/early-exit-after.txt) child-process isolation plus trusted nonzero-test verdict. Post-repair watched 30B and 7B runs retain verdicts.
- [x] JOH-5, JOH-6: Current-format fixture, watched 30B, and watched 7B runs include evaluator/model/patch/checkout/restore artifacts; all three passed replay. The [final 96-test suite](evidence/tests-final.txt) passed. Earlier completed records are historical and current replay rejects them.
- [ ] JOH-4, JOH-6: Ship direct broker/verifier CLI access under the same enforcement contract and a reconstruction command for later replacement of a modified derived checkout. The current pre-write scratch base-tree proof does not cover that later case.

## Phase 2: pinned local coding models

- [x] JOH-3, JOH-4, JOH-7: NEW `tools/setup_ovms.ps1` pins OVMS 2026.4.0 and reads both model revisions/checksums from `model-pins.json`. Both post-migration [fast](evidence/ovms-fast-dry-run-post-pins.json) and [strong](evidence/ovms-strong-dry-run-post-pins.json) dry-runs returned exit 0 with byte bounds and no writes. [Script](../../../tools/setup_ovms.ps1).
- [x] JOH-3: NEW [model-pins.json](../../../model-pins.json) now owns both model identities and artifact metadata; `orchestrate.py init` derives its registrations, while `load_state` rejects identity/revision drift. A focused [controller test](../../../tests/test_orchestrate.py) exercises pin derivation.
- [x] JOH-3, JOH-4: Setup script reads the canonical model registry and its read-only [fast installed-root verification](evidence/ovms-fast-verify.json) returned `status: verified`; both post-pin dry-runs passed. Strong install/serve remains a separate open check.
- [x] JOH-1, JOH-5: NEW `tools/prepare_verifier.ps1` ships `dry-run|install|verify` for the pinned Linux/amd64 Docker image. [Dry-run](evidence/verifier-image-dry-run.json) reports 43,416,556 registry bytes and no writes; [verify](evidence/verifier-image-verify.json) confirms the local pinned image. Install through this script was not exercised because the image was already present.
- [x] JOH-3, JOH-4, JOH-6, JOH-7: NEW `local_model.py` provides bounded direct `probe` and importable `chat_completion`; it validates loopback, response identity and usage, and refuses proxy, redirect, and retry. The [7B probe](../../PRS-Jev-Orchestration-Harness.md#2-system-architecture-overview) returned `LOCAL_MODEL_PROBE_OK`. [Client tests](../../../tests/test_local_model.py) exercise transport negatives.
- [ ] JOH-3, JOH-4: Preserve unedited stdout for the fast setup script install/serve commands. They were watched on a separate empty root and reported `status: installed` and `status: ready` for `qwen25-coder-7b-int4` on `GPU.1`, but the original tool output is only in the active chat; manifest and server logs remain on disk. Readiness is not chat completion.
- [ ] JOH-3, JOH-4: Run the strong setup script install and serve actions under its own bounded dry-run/verified-root procedure. Manual 30B OVMS serving and task completion exist, but the shipped strong setup path has only passed dry-run.
- [ ] JOH-3, JOH-4, JOH-6: Execute a paired same-task coding prompt against 7B and 30B and retain server/version/artifact and response evidence. Watched 7B add and 30B interval-merge tasks prove separate branches but do not compare model routes.
- [x] JOH-3, JOH-6: [Read-only OpenVINO C API mapping](evidence/ovms-device-map.md) identifies `GPU.1` as Arc Pro B70; the running fast server command explicitly targets `GPU.1` on loopback 8766, and the current-format 7B coding response used that endpoint. The controller does not yet bind that server/device receipt to each run.
- [ ] JOH-3, JOH-4, JOH-6: Make the controller validate installed artifact hashes, server version, and selected device before recording a live route. It currently trusts the configured model registration and server response identity.

## Phase 3: verification, completion evidence, and handoff

- [x] JOH-1, JOH-3–JOH-6: A watched, bounded rules-only 30B live run on `fixture-merge-intervals` changed `solution.py`; the pinned Docker verifier ran with network disabled, read-only root/checkout, dropped capabilities, six protected tests, and a trusted verdict. [Events](../../../evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/events.jsonl), [stdout verdict](../../../evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/verifier.stdout), and [unedited test lines](../../../evidence/orchestration-proof-interval/runs/87f75c56-e81b-4e12-9676-6f9f9c541921/verifier.stderr) passed current replay. Strong runtime artifact/device proof remains open.
- [x] JOH-2, JOH-3, JOH-5, JOH-6: A watched experimental live Jev Choice selected `fast`, then local 7B solved generated `fixture-add` with a three-test trusted verdict. [Events](../../../evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/events.jsonl) and [verdict](../../../evidence/orchestration-proof-add/runs/54cf2c0e-dc53-417a-bf8f-bb51675d1472/verifier.stdout) passed current replay; one success is not held-out routing quality.
- [x] JOH-1–JOH-7: `python -B -m unittest -v` passed [96 tests](evidence/tests-final.txt), including Docker negative and integration checks, after the latest code changes.
- [x] JOH-1–JOH-8: Reconciled `README.md`, canonical PRD/PRS, and this packet to current code and setup evidence; strict packet validation and document guard passed after final edits.
- [x] JOH-1–JOH-8: [Walkthrough](walkthrough.md) records actual commands, a requirement-evidence matrix, and explicit incomplete items; strict validation with `--require-walkthrough` passed.
- [ ] JOH-8: Run a held-out Jev versus clean rules-only baseline and other routers with predeclared error/cost measures before activating Jev for routine live routing or claiming it is superior.

## File summary

NEW: `orchestrate.py`, `local_model.py`, `model-pins.json`, `test_orchestrate.py`, `test_local_model.py`, `tools/setup_ovms.ps1`, `tools/prepare_verifier.ps1`, and this packet's `walkthrough.md`. MODIFY: `README.md`, canonical `docs/PRD-Jev-Orchestration-Harness.md`, and `docs/PRS-Jev-Orchestration-Harness.md`. `jev_harness.py` remains the single Jev transport and policy owner. Nothing is scheduled for deletion. `[ ]` open; `[/]` in progress; `[x]` evidenced.
