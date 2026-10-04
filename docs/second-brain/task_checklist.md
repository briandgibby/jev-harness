# Jev Brain — build checklist

## Scope and status

Plan-only status: no Release 1 implementation has started. [PRD](PRD.md) owns requirements and boundaries; [implementation plan](implementation_plan.md) owns proposed files and commands; [execution brief](agent_prompt.md) carries handoff instructions. Change this checklist as actual evidence arrives. `[ ]` means not started, `[/]` in progress, and `[x]` completed with post-change command output. Keep at most one item in progress per executing agent.

## Planning and setup

- [x] P-01 — Validate this four-file packet strictly; save the command and unedited output in [packet-validation.txt](evidence/packet-validation.txt). PRD, plan, checklist, and brief use the same names, paths, and requirement IDs.
- [ ] P-02 — Before coding, reconfirm the user's content/interface preference or retain the stated local work/project assumption; inspect the current harness files, `.python-version`, test command, and any new repository instructions. Record a baseline broad test result without changing code.
- [ ] P-03 — Define the proposed CLI JSON envelope, immutable config-version/activation schema, profile-to-harness audit mapping, and bounded settings in `brain/config.py` and tests. Reject unknown settings and invalid ranges (NFR-01, NFR-02).

## Small working path: vault and retrieval

- [ ] B-01 — Add `brain/__init__.py`, `brain/__main__.py`, `brain/cli.py`, and `brain/config.py` with `init`, `config show/set`, and error envelopes. Init must create immutable config versions/activations from empty state and refuse populated targets; config set must append a validated version, not overwrite (FR-01, NFR-01, NFR-03).
- [ ] B-02 — Add `brain/records.py` for bounded UTF-8 capture, immutable IDs/hashes/provenance/egress, explicit supersession, and safe atomic publication under a vault lock. Test invalid text/path/ID, duplicate and concurrent second-successor attempts, and interrupted writes (FR-02, FR-06, FR-07).
- [ ] B-03 — Add `brain/search.py` for FTS5 projection, stable tie breaks, `find`, and `index rebuild`. Prove that deleting a derived scratch index and regenerating it reproduces the same hits and source hashes before allowing index replacement (FR-02, FR-05).
- [ ] B-04 — Add `brain/demo.py` and synthetic fixture records. Run a credential-free capture → rebuild → find flow from an empty directory; extend the same demo through Jev and replay in J-03 (FR-01, FR-02).

## Jev decision center

- [ ] J-01 — Add versioned `brain/profile_templates/triage-v1.json` and `passage-evidence-v1.json` to bootstrap the active config version. Use `premise_conflict` only for an explicit query premise. Default every label to human review; verify profile IDs/versions/hashes in the harness audit input and reject malformed/unknown labels (FR-03, NFR-01).
- [ ] J-02 — Add `brain/credentials.py` reusing the single literal dotenv parser. Test missing/duplicate key, key redaction, and cleanup of temporary environment assignment (FR-04/06, NFR-01).
- [ ] J-03 — Add `brain/gate.py` triage using `jev_harness.run_one` and `replay`, exact record/profile/config hashes, explicit fixture/live mode, per-profile same-config smoke check, and `--dry-run`. Extend the fresh demo through fixture triage/recall/replay. Fake transport must prove local-only text and calls without consent/smoke never leave the process (FR-01, FR-03, FR-04, FR-08).
- [ ] J-04 — Exercise wrong-model, malformed answer, provider 401/429/timeout, stale record, audit-write failure, absent/failed/stale smoke, and idempotency cases. One vault reservation prevents concurrent duplicate calls; live/fixture keys differ; incomplete attempts require explicit recovery or fresh run. Default reuse selects the first completed audit, while `--fresh` returns only its new observation. Every failure is nonzero with a safe next action; no fallback (FR-06, FR-08, NFR-02).
- [ ] J-05 — Extend `brain/gate.py` and `brain/cli.py` with bounded `recall`: FTS5 filters eligible records before `top_k`, separately counts all matching local-only records, and makes one query–passage Choice call per eligible candidate when no prior completed audit exists. Show verified literal spans in **provisional** candidate-evidence, query-premise-conflict, and inspected-other groups with `review_required`; zero candidate evidence is explicit. A mixed reused/fresh recall must assemble the same complete envelope with per-passage provenance and aggregate new-call count. Compare with lexical-only baseline (FR-04, FR-05).
- [ ] J-06 — Add `brain/reviews.py`, `review list/resolve`, and index refresh. Confirm a resolution targets one completed audit and exact record hash and that a superseding record makes it historical (FR-07).
- [ ] J-07 — Add `doctor`, `recover`, and `replay` wiring: detect incomplete writes, stale/missing index, invalid references, config activation errors, and stale disposable locks; safely recover by shipped commands. Show offline replay with `network_called: false` (FR-06, FR-07).

## Verification and watched live validation

- [ ] E-01 — Add `brain/eval.py` and a bounded, versioned corpus with scenario-family dev/holdout separation. Label gold relevant IDs/spans across each full split for FTS5 recall, plus fixed query–passage pairs for Jev quality. Report eligible/local-only denominators, triage/evidence metrics, raw counts, coverage/review, repeats, paraphrases, and injection variants. Never infer production accuracy from fixtures (FR-09).
- [ ] E-02 — Run the full offline suite and fresh fixture demo. Capture exact commands, exit codes, and unedited output after the code changes; reconcile any failures before using live credentials (FR-01 through FR-09).
- [ ] E-03 — Use `brain config set` to create a new immutable version with the operator-selected dotenv path/key name without copying the secret. For each profile, inspect `live-smoke --dry-run` fields/count/destination, then run one watched synthetic call; preserve its audit and unedited output. Missing credentials fail by name without value (FR-03, FR-04, FR-06, FR-08).
- [ ] E-04 — Only after each profile's E-03 smoke, pilot a small explicitly provider-eligible set of real work notes in sequential batches of at most 20 calls. Freeze config/profile versions for the batch; stop and report partial progress on any failure. Do not enable schedules or automatic task/action execution (FR-08, FR-09).
- [ ] E-05 — Add `BRAIN_README.md` from commands that actually passed. Include vault ownership, egress, exact rebuild/replay, known limits, and no-evidence behavior; do not duplicate live rubrics or keys (NFR-03).
- [ ] E-06 — Re-run the broad suite, verify the fresh-vault CLI and index regeneration, then create a completion walkthrough from the actual diff and evidence. Revalidate the packet with `--strict --require-walkthrough`; close only evidenced checklist items.

## Conditional future phases, outside Release 1

- [ ] F-01 — Decision workbench: supplied options, exact constraints in code, atomic Jev judgments, cited evidence, and human final decision record. Define its own rubric and error budget before use.
- [ ] F-02 — One connector at a time: source-native authority and permissions, explicit sync scope, source revision/provenance, egress mapping, bounded watched import, and reproducible cache rebuild. Keep source systems canonical.
- [ ] F-03 — Optional cited prose synthesis: use a separate answer component only after evidence sufficiency and claim/citation evaluation. Jev stays the bounded decision center; the generator never links components or executes actions.
- [ ] F-04 — Optional Laya adapter: pin code, ONNX weights, tokenizer, and runtime; reject overflow instead of truncating silently; benchmark the same held-out corpus against hosted Jev before offering an explicit provider switch.

## File summary

Release 1 adds `brain/__init__.py`, `brain/__main__.py`, `brain/cli.py`, `brain/config.py`, two `brain/profile_templates/*.json`, `brain/records.py`, `brain/search.py`, `brain/credentials.py`, `brain/gate.py`, `brain/reviews.py`, `brain/eval.py`, `brain/demo.py`, `tests/__init__.py`, `tests/test_brain.py`, and `BRAIN_README.md`. It reuses `jev_harness.py`, `probe_live.py`, and `.python-version` without an assumed edit. The exact action and reason for each file are in [implementation_plan.md](implementation_plan.md). No deletion or move is planned.

Marker legend: `[ ]` not started; `[/]` in progress; `[x]` verified with a command and unedited output after the change.
