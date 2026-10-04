# Jev Brain — implementation plan

This is a proposed, unexecuted build plan. Read the [PRD](PRD.md) for the canonical scope and requirement IDs, [task checklist](task_checklist.md) for progress, and [execution brief](agent_prompt.md) for the handoff. All code paths below are relative to the existing `outputs/jev-harness` application root. Do not treat proposed files or CLI commands as present behavior.

## Goal and decision points

Deliver the Release 1 local CLI: capture and find real text without credentials; use the existing Jev harness for inspectable triage and passage judgments when explicitly allowed; preserve source, audit, and human review separately; rebuild every search projection from canonical files.

The default first scope is work/project notes and a local CLI. If the user selects personal knowledge or hosting instead, revise the trust, authentication, source connector, and deployment sections before coding. No other decision blocks the fixture/local slice. Do not choose an auto-accept probability from the synthetic harness results. A domain owner sets the acceptable error/review tradeoff after a labeled pilot.

## Proposed changes, in dependency order

| Action and file | Responsibility, symbols, consumers, and verification |
|---|---|
| EXISTING `jev_harness.py` | Remains the one Jev HTTP transport, Choice request/response validator, deterministic policy, per-call audit, and replay implementation. `brain/gate.py` imports `validate_config`, `run_one`, `replay`, and `canonical_hash`; no second copy of their logic. Modify only if a failing integration test establishes a missing public contract; preserve existing CLI and audit behavior. |
| EXISTING `probe_live.py` | `read_key(path, name)` remains the sole literal dotenv parser. `brain/credentials.py` uses it without sourcing the file. If extraction into a shared module becomes necessary, update the probe and its tests in the same change so one parser remains canonical. |
| NEW `brain/__init__.py`, `brain/__main__.py` | Make `python -m brain` the direct public CLI. `__main__` calls `brain.cli.main` and returns its exit status; no model-mediated component calls. |
| NEW `brain/cli.py` | Parse `init`, `demo`, `doctor`, `recover`, `config show/set`, `record add/show`, `index rebuild`, `find`, `classify`, `recall`, `review list/resolve`, `replay`, `live-smoke`, and `eval` commands. Emit one versioned JSON envelope per call. Coordinate records, search, gate, and review directly. Dry-run is a first-class option for provider operations. |
| NEW `brain/config.py` | Own immutable `vault/config/versions/<id>.json` and append-only `vault/config/activations/<id>.json`, including both operator settings and active profile definitions. `config set` validates unknown keys and code-owned bounds, then creates a new version/activation under the vault write lock; it never overwrites the prior settings. Construct the strict harness config in memory and detect absent FTS5 with a named remedy. |
| NEW `brain/profile_templates/triage-v1.json`, `brain/profile_templates/passage-evidence-v1.json` | Bootstrap templates for the two Choice rubrics. `triage` labels: `task`, `decision`, `reference`, `idea`, `unclear`. `passage_evidence` labels: `evidence`, `premise_conflict`, `context`, `irrelevant`, `unclear`; `premise_conflict` concerns an explicit query premise, not another record. The active immutable config version owns adjusted wording and thresholds; the harness audit owns its historical snapshot. Default all labels to review until domain evaluation. |
| NEW `brain/records.py` | Write immutable `vault/records/<id>.json` with exclusive creation and atomic publication. Validate UTF-8, byte cap, project, provenance, egress (`local_only` or `hosted_jev`), hash, and optional `supersedes_record_id`. Under the vault write lock, require a predecessor to be current and have no existing successor; reject a second successor, missing predecessor, cycle, or invalid ID. Provide `add`, `show`, `current_records`, and `doctor_records`. No update/delete API in Release 1. |
| NEW `brain/search.py` | Build `vault/index/search.sqlite` as a disposable FTS5 projection of current canonical records and verified review labels. `find` searches all current records. `recall` filters to `hosted_jev` within FTS5 before choosing `top_k` with a stable record-ID tie break, while separately counting all query-matching `local_only` records. Rebuild into a scratch index, verify record count/hash mapping, then atomically publish; document the regenerate command as its restore path. |
| NEW `brain/credentials.py` | Read only the configured key from an operator-selected dotenv through `probe_live.read_key`, or use the configured environment variable. Never print or persist the value; clear a temporary process environment assignment after `run_one` even on failure. Reject ambiguous/missing key names. |
| NEW `brain/gate.py` | Implement `classify`, `recall_candidates`, `live_smoke`, `dry_run`, and `replay_link`. One shared preflight enforces record egress, invocation consent, and a completed synthetic smoke for the same config version/profile before any ordinary live call. Build one bounded state for each Choice profile, derive harness config from the active version, reserve one idempotency key under the vault lock, and call `jev_harness.run_one`. Return the distribution and audit reference without persisting a second answer copy. Reject stale source hashes and unexpected model/profile versions. No hidden retry or fallback. |
| NEW `brain/reviews.py` | Write immutable human triage resolutions referencing exact record hash and completed inference audit. Read and validate those references; exclude stale resolutions from the current index while keeping them historically inspectable. Reject conflicting double resolutions unless the user explicitly records a new superseding resolution. |
| NEW `brain/eval.py` | Validate a bounded, versioned labeled corpus with full-split gold relevant IDs/spans and separately labeled fixed query–passage pairs. Compute FTS5 recall from the whole split, then Jev metrics on pairs; report eligible and local-only gold separately. Live evaluation uses the shared gate preflight, an inspected dry-run, sequential batches up to the configured hard maximum, and stop-on-error output with completed IDs. |
| NEW `brain/demo.py` | Generate only synthetic records and matching fixture responses, then call the same CLI services as real commands. The demo creates a fresh vault and proves a full path without credentials or pre-placed files. |
| NEW `tests/__init__.py`, `tests/test_brain.py` | Add tests for the primary flow, config bounds, source and egress checks, exact citation resolution, index rebuild, no-match states, audit/review references, failure semantics, and fixture/live separation. Use fake transport or local fixtures for ordinary tests. Existing `test_jev_harness.py` stays in the broad suite. |
| NEW `BRAIN_README.md` | Document user commands, egress meaning, vault ownership, and exact rebuild/replay steps after they actually work. It is derived operational guidance, not a second owner of rubrics or data. |

No file is scheduled for deletion or move. The existing harness's research and probe files remain historical evidence. A future package extraction would be its own tested change, not a reason to copy the Jev adapter now.

## Data and interface contracts

**Record, proposed:** UTF-8 JSON with `schema_version: 1`, generated `record_id`, `created_utc`, `text`, `text_sha256`, `project`, `provenance`, `egress`, and nullable `supersedes_record_id`. The record filename equals its ID, and a validator recomputes the hash. The user can add literal text or one explicit file; there is no directory scan. A superseding record leaves the old file intact. Empty text and oversize text fail before a write.

**Configuration and profile, proposed:** `brain init` creates a validated immutable configuration version and an append-only activation event. The version contains operator settings plus both profiles, each with `profile_id`, `profile_version`, `question` (`id`, `instructions`, `criteria`), and `policy` (`min_probability`, `min_margin`, `review_labels`). `brain config set` creates another version/activation under the vault lock; no manual file placement or overwrite is needed to change provider mode, dotenv path/key name, bounds, or profile wording. A changed rubric must increment its `profile_version`; reusing the same version with different wording fails. Activation events form a verified predecessor chain so one version is current. The app constructs the existing harness's strict config in memory. Bootstrap review labels include every output label. Release 1 still requires human review even if the harness policy would recommend `accept`; no model suggestion becomes authoritative. Old config versions and audits remain readable.

**Audit profile mapping, proposed:** the harness config cannot accept extra `profile_id` or `profile_version` keys. Encode these in a stable, bounded `input.id` and in structured `state` metadata together with `config_version_id`, `source_id`, `source_hash`, and `profile_hash`. Define `profile_hash` over `{profile_id, profile_version, question, policy}`. The harness audit already stores `input_snapshot`, `config_snapshot`, and their hashes; `brain replay` recomputes the profile hash from the preserved config version and verifies the mapping before trusting the historical recommendation. No second response store is created. The state metadata is part of the recorded request, so its effect on Jev is included in evaluation rather than assumed irrelevant.

**Provider payload, proposed:** triage `state` contains profile metadata, record ID, content hash, project, and bounded text. Passage `state` contains profile metadata, query text, exact source ID/hash, source type, and one bounded passage. The app treats source text as data rather than executable instructions; Jev may still be influenced by adversarial text, so injection variants belong in evaluation. `recall` never sends `local_only` records. Live dry-run prints IDs, field names, per-record bytes, total call cap, destination, model, and hashes before any network call. It may offer an explicit local `--show-payload` option for exact text review, but must not print a key.

**CLI result, proposed:** `schema_version: 1`, `operation`, `status`, and relevant `record_id`, `source_hash`, `scope`, `audit_path`, `candidate_count`, `excluded_local_only`, and `passages`. `record add/find` can be `completed`; `recall` returns `no_matches` when no current record matches, `no_eligible_matches` when only local-only records match, or `review_required` after Jev evaluates any eligible candidate. Every Release 1 passage classification remains provisional even if the harness policy reports `accept`: `candidate_evidence`, `premise_conflicts`, and `inspected_other` include literal source spans, full distributions, and `review_required: true`; `inspected_other` retains `context`, `irrelevant`, and `unclear` rather than silently hiding them. `candidate_evidence_count: 0` is explicit and never means the entire corpus lacks an answer. For each candidate, include its audit path, `disposition: fresh|reused`, and `network_called`; a recall with mixed dispositions still assembles the same complete passage envelope and reports aggregate new-call count. Code re-reads each source ID/hash/span before display. Errors are nonzero with `code`, `message`, `next_action`, and any completed IDs/audit paths. An incomplete provider batch is an error even when earlier calls finished.

**Credential configuration, proposed:** `api_key_env` defaults to the existing harness default; `dotenv_path` is null until the operator chooses a file. The user can point the configuration surface at the SignSense Reuse Agent root `.env` and key name `JEV_API_KEY` for a bounded test without copying the key into this project. That path is operator-supplied and is not shipped as a default. Missing credentials are named; no fixture is substituted in live mode.

**Failure and idempotency, proposed:** every record, configuration version, activation, and review write uses a new exclusive name. The idempotency key is a canonical hash of `mode`, endpoint, pinned model, complete request, profile/policy hashes, and config version. The gate atomically reserves it with a vault lock before scanning existing audits and calling the provider. By default, it reuses the **first completed** matching audit, ordered by its saved start time and audit filename as a tie break; this is an explicit `disposition: reused`, `network_called: false` in the normal classify/recall result, never a claim of fresh inference. `--fresh` runs a new observation and returns it for that invocation but does not silently replace the default historical selection; `brain replay --audit-path` can inspect any saved run. An incomplete matching audit or stale lock produces a nonzero diagnostic requiring `brain doctor`/`recover` or an explicit fresh attempt, never an implicit paid retry. Fixture and live runs have different keys. `doctor` and `recover` inspect the harness audit before releasing a stale, disposable lock; they never delete an audit or canonical record. If transport succeeds but result reporting fails, the audit remains discoverable and the command reports partial failure. An interrupted temporary record file is not exposed as canonical.

## Requirement trace

| Requirement | Planned implementation and evidence |
|---|---|
| FR-01 | `brain/cli.py` and `brain/demo.py`; fresh fixture demo and repeated-init refusal. |
| FR-02 | `brain/records.py` and `brain/search.py`; real-text capture/find and rebuild equivalence. |
| FR-03 | `brain/config.py`, profile templates, and `brain/gate.py`; Choice contract and model/hash tests. |
| FR-04 | `brain/credentials.py` and `brain/gate.py`; payload-inspecting egress and consent tests. |
| FR-05 | `brain/search.py` and `brain/gate.py`; eligible-scope, provisional candidate, query-premise-conflict, and no-match cases. |
| FR-06 | `brain/cli.py`, `brain/gate.py`, and `brain/records.py`; provider/storage/config failure cases. |
| FR-07 | `brain/reviews.py` and `brain/gate.py`; exact-hash review, supersession, and replay cases. |
| FR-08 | `brain/gate.py` and `brain/eval.py`; dry-run call list, per-profile same-config smoke, and batch cap. |
| FR-09 | `brain/eval.py`; full-split gold IDs/spans for lexical recall and separate labeled-pair Jev metrics with raw counts. |
| NFR-01 | `brain/config.py` and `brain/credentials.py`; bounds, unknown-key, and secret-redaction tests. |
| NFR-02 | Existing `.python-version`, `brain/config.py`, and harness audit; version checks and offline replay. |
| NFR-03 | `brain/demo.py`, `brain/cli.py`, and `BRAIN_README.md`; fresh-vault proof and egress inspection. |

## Integration traces

```text
brain demo -> cli -> demo -> records.add -> search.rebuild/find
           -> gate.classify/recall -> jev_harness.run_one(fixture)
           -> harness audit -> gate.replay_link -> cli JSON

brain record add -> cli -> config validation -> records.add -> immutable record
brain config set -> cli -> config validation -> vault lock -> new version + activation
brain index rebuild -> cli -> records.current_records + reviews -> search.rebuild
brain find -> cli -> search.find -> records.show -> cli JSON

brain classify/live-smoke -> cli consent + config -> gate shared live preflight
                          -> vault reservation + credentials
                          -> jev_harness.run_one(live) -> harness audit
                          -> deterministic harness policy -> cli JSON

brain recall -> cli consent -> search.find(eligible scope, local-only count) -> records.show
             -> gate per query–passage pair -> harness audit + policy
             -> code checks source IDs/spans -> provisional candidate JSON

brain review resolve -> cli -> records + completed audit validation
                     -> reviews immutable resolution -> search.rebuild
brain replay -> cli -> audit path -> jev_harness.replay -> cli JSON
brain doctor/recover -> cli -> records/config/audits/locks inspection -> explicit repair status
brain eval -> cli -> labeled corpus -> search and gate/replay -> separate metrics
```

Every trace terminates at a direct CLI JSON result; there is no component-to-component language-model link. The existing harness audit is the sole owner of a model response, and the search index is never the owner of source text or a reviewed label.

## Compatibility, recovery, and rollout

The existing `jev_harness.py` supports only one Choice question per call and a direct TypeSafe endpoint. Release 1 keeps that contract; Noul, Score, combined questions, and Laya require separate validators/evaluations. The runtime pin is the existing `.python-version` value `3.14.6`. The new app uses Python standard library and available SQLite FTS5; startup checks actual availability and fails with an actionable message if absent. No package download or `latest` dependency is required for the fixture path.

The vault begins empty and is created by `brain init`; no schema migration applies to prior data. No canonical delete or overwrite command ships in Release 1. `index rebuild` proves the regenerate path in a scratch index before swapping derived files. Config/profile changes create immutable versions and append-only activations, so no active file is overwritten; activation-chain verification selects the latest version. If a later migration or delete is proposed, first add `brain backup`, restore the backup to a scratch vault, compare contents, and only then run the destructive operation. A valid model response for an old profile or superseded record remains historical, never silently current.

Initial rollout: fixture demo from empty state; local real-text capture/find; mock provider negative tests; dry-run one synthetic live request per profile; one watched synthetic `live-smoke` for each profile before its ordinary live use; then a small set of explicitly provider-eligible work notes in batches of at most 20 calls. The shared gate rejects absent, failed, or stale-config smoke evidence for `classify`, `recall`, and `eval`. No scheduler or recursive import. The first real pilot does not enable automatic decisions.

## Verification commands and evidence status

The following existing commands were verified from the current files or environment. Their planning outputs go in `docs/second-brain/evidence/`:

| Purpose | Working directory | Exact command | Planning status |
|---|---|---|---|
| Runtime | `outputs/jev-harness` | `python --version` | Ran; 3.14.6. |
| FTS5 | `outputs/jev-harness` | `python -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute('CREATE VIRTUAL TABLE docs USING fts5(body)'); print('SQLite', sqlite3.sqlite_version, 'FTS5 available')"` | Ran; SQLite 3.50.4 FTS5 available. |
| Existing harness regression | `outputs/jev-harness` | `python -m unittest discover -s . -p 'test_*.py' -v` | Must run after implementation; current test file was inspected, but this exact broad command has not yet been used as product evidence. |
| Packet validation | workspace root | `python (Join-Path $env:USERPROFILE '.codex\skills\prepare-and-run-build-task\scripts\validate_build_packet.py') outputs\jev-harness\docs\second-brain --strict` | Run after this packet is written and after any revision. |

The commands below are **proposed, unimplemented, and unrun**; implement their parser/contracts before treating them as verification evidence. Work from `outputs/jev-harness`:

```powershell
python -m brain demo --vault ..\..\work\brain-demo --mode fixture
python -m brain init --vault ..\..\work\brain-real
python -m brain record add --vault ..\..\work\brain-real --text "Decision: retain the source quote." --project pilot --egress local_only
python -m brain index rebuild --vault ..\..\work\brain-real
python -m brain find --vault ..\..\work\brain-real --query "source quote"
python -m brain config show --vault ..\..\work\brain-real
python -m brain live-smoke --vault ..\..\work\brain-real --profile triage --dry-run
python -m brain live-smoke --vault ..\..\work\brain-real --profile triage --allow-provider
python -m brain live-smoke --vault ..\..\work\brain-real --profile passage_evidence --dry-run
python -m brain live-smoke --vault ..\..\work\brain-real --profile passage_evidence --allow-provider
python -m brain recall --vault ..\..\work\brain-real --query "What was decided?" --allow-provider --dry-run
python -m brain doctor --vault ..\..\work\brain-real
```

The implementation must create or choose fresh scratch vault paths rather than overwrite the examples. Before any live command, create a new immutable config version with the operator's credential path/key name and provider mode through `brain config set`; no shipped default points to the SignSense dotenv. Inspect the per-profile dry-run, then confirm each same-config smoke result. Capture unedited command output after changes. Do not claim the proposed commands currently work.

## Test and review plan

1. **Contracts and storage (FR-01/02/06/07, NFR-01/03):** empty bootstrap, immutable config versions and activation chain, config-set without overwrite, explicit-file/literal-text capture, UTF-8/byte/path boundaries, duplicate IDs, predecessor-current check, concurrent second-successor rejection, failed atomic write, no-key local search, no-match status, FTS5 absence, rebuild equivalence, and scratch regeneration proof.
2. **Jev boundary (FR-03/04/06/08, NFR-01/02):** construct exact Choice requests, map profile ID/version/hash into audit input, compare model/profile/source hashes, validate distributions, force missing/duplicate dotenv keys, verify `local_only` text cannot reach fake transport, require invocation consent and same-config smoke for all ordinary live entry points, test absent/failed/stale smoke, inspect payload dry-run, and exercise 401/429/timeout/malformed response without fallback. Concurrent identical calls must reserve one key; fixture and live keys must differ; incomplete audits must not trigger hidden retries. Test that a deliberate `--fresh` experiment leaves the default first-completed selection unchanged.
3. **Recall and review (FR-05/07):** fixture passages for candidate evidence, explicit query-premise contradiction, related-only, irrelevant, unclear, superseded, and no eligible hit. A local-only result outranking eligible results must not consume `top_k`; `excluded_local_only` counts all matching local-only current records. Under unchanged bootstrap policy, every evaluated passage stays `review_required`, including suggested irrelevant passages in `inspected_other`. Mix one reused and one fresh candidate and verify the same complete envelope, per-passage audit/disposition, aggregate new-call count, and exact canonical quote resolution. Failure cannot display a success-shaped answer. Review resolution targets a precise audit/source hash; old review remains historical after supersession. Cross-record semantic conflicts are not inferred.
4. **Evaluation (FR-09):** build a diagnostic corpus of about 24 notes in 12 scenario families. For each of 12 queries, independently label all relevant source IDs and gold spans in the full corresponding split. Run real FTS5 over that entire split to measure candidate recall, distinguishing eligible from local-only gold. Separately label three fixed query–passage pairs per query to isolate Jev filtering from retrieval; add repeats/paraphrases/injection variants. The planned Jev diagnostic is 24 triage + 36 fixed-pair + 12 perturbation calls (72 total), issued only after per-profile smoke in sequential batches no wider than 20. Any additional live end-to-end pairs need a separate dry-run and cap; offline fixture/replay may cover them first. This sample diagnoses plumbing/rubrics, not production accuracy. Report triage confusion, selective error and coverage, useful-evidence retention, citation validity, query-premise conflicts, and per-label probability drift with raw counts.
5. **Manual acceptance:** observe the fresh fixture demo and one synthetic live smoke for each profile before that profile's real use. Inspect outbound field lists and exact user-approved payloads; confirm the key is absent from terminal/audit. Add one real provider-eligible work note only after triage smoke; run recall on real notes only after passage-evidence smoke. Record actual commands and unedited output. No scheduled or wide run.

## Dependencies, risks, and effort

The only runtime dependencies are the pinned Python interpreter, its SQLite build with FTS5, and TypeSafe's hosted API for live inference. The existing harness and dotenv parser are local code dependencies. Network, provider model availability, and account limits remain external and must fail visibly. A local Laya adapter could remove hosted egress later, but its weights/tokenizer/runtime must be pinned and its overflow/quality behavior tested independently; [Laya](https://github.com/receptron/laya) is not a Release 1 dependency.

Suggested delivery sequence: (1) vault, records, FTS5, fixture demo; (2) Jev Gate, consent, triage, and replay; (3) passage recall and review; (4) diagnostic evaluation and one watched live smoke per profile before its real use; (5) only after evidence, workbench/connectors/synthesis. Each slice retains a runnable end-to-end command. Effort depends primarily on real-data labeling and egress policy, not HTTP wiring.
