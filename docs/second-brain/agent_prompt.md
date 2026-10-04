# Jev Brain — execution brief

## Mission and stopping point

The current user request is for a **plan**. This brief is a handoff for a later authorized implementation; it does not claim that the proposed `brain` package or commands exist. The application root is `outputs/jev-harness` in the current workspace. Build a local-first, single-user CLI that captures work/project notes, retrieves original text, and uses Jev for bounded triage and passage judgments. Stop the first release at cited evidence and human review; do not add autonomous external actions, generated answers, schedules, wide import, or an unbenchmarked Laya fallback.

## References and inputs

Read the [PRD](PRD.md) for the canonical requirements and boundaries, [implementation plan](implementation_plan.md) for the file-level design and commands, and [task checklist](task_checklist.md) for execution state. The current Jev integration lives in `jev_harness.py`; the safe literal dotenv reader is `probe_live.read_key`. Preserve their tested behavior and prior audit evidence. The documented model pin is `jev-1.13.0`, but record the actual returned model and reject a mismatch. TypeSafe's [API reference](https://docs.typesafe.ai/api) owns the external request/response contract.

The user's AGENTS rules apply: first run must be created by shipped commands; a model cannot connect components; configuration owns operator values and code validates bounds; failures are explicit; source facts have one canonical owner; changes stay small and describable; first live/side-effect run is bounded and watched; derived indexes must have a demonstrated regenerate path; destructive changes need a tested scratch restore; bug fixes start with a failing reproduction; builds and model versions are pinned; completion claims require the command and unedited post-change output. Configuration changes create immutable versions and append-only activations. The user's authorized dotenv path may be selected at runtime, but never print or copy its key.

## Workflow and phase instructions

Use this sequence, keeping one checklist item `[/]` at a time:

1. Reinspect the current application root and any instructions. Run the existing broad test command as a baseline. Reconcile the packet if repository facts, interface preference, or content scope differ from the plan.
2. Implement `init`, immutable configuration versions, immutable records, FTS5 rebuild, `find`, and a credential-free fixture `demo`; make this the first complete runnable path. Under the vault write lock, reject a second successor to the same record.
3. Add the two versioned Choice profiles, safe credential selection, explicit egress checks, triage, audit profile mapping, dry-run, and replay. Reuse the existing Jev harness rather than duplicating transport or probability validation. The shared gate requires a completed same-config synthetic smoke before ordinary live use and reserves paid calls against duplicates.
4. Add bounded candidate-evidence recall, exact source-span verification, review records, and `doctor`/`recover`. FTS5 filters eligible records before `top_k`; locally excluded matches are counted separately. Passage labels remain provisional with `review_required` under bootstrap policy. `premise_conflict` concerns the query, not disagreement between records. Keep no-match, review, provider failure, and partial batch results distinct.
5. Add a labeled diagnostic evaluator and relevant negative tests. Gold evidence IDs/spans cover the full corpus split before FTS5 selects candidates; fixed pairs test Jev separately. Inspect one synthetic live dry-run and watched call **per profile** before that profile sees a real note. Real pilot notes require explicit provider eligibility and invocation consent; batches stay sequential and at most 20 calls.
6. Run targeted and broad tests, fresh demo, regeneration proof, and manual evidence checks. Write `BRAIN_README.md` and a completion walkthrough from actual behavior. Update the four planning artifacts if the design changes; validate them again.

## Verification and deliverables

Existing commands to run from `outputs/jev-harness`:

```powershell
python --version
python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE docs USING fts5(body)'); print('SQLite', sqlite3.sqlite_version, 'FTS5 available')"
python -m unittest discover -s . -p 'test_*.py' -v
```

Packet validation from the workspace root:

```powershell
python (Join-Path $env:USERPROFILE '.codex\skills\prepare-and-run-build-task\scripts\validate_build_packet.py') outputs\jev-harness\docs\second-brain --strict
```

The first two preflight commands were run while planning; their unedited outputs belong in [planning-preflight.txt](evidence/planning-preflight.txt). The broad suite must be run after implementation; do not describe its future result as passing yet. Proposed `python -m brain ...` smoke commands appear in [implementation_plan.md](implementation_plan.md) and cannot be used as evidence until implemented.

For each changed file, state what it does and why. For each completed requirement, retain the exact command, exit code, and unedited output generated after the change. Build `walkthrough.md` only after implementation, with a requirement-to-evidence matrix and any unresolved limitations. Never commit, push, publish, schedule, or integrate with SignSense as an implicit part of this handoff.
