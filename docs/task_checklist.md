# Jev Harness task checklist

## Scope overview

Status follows the [PRD](PRD.md) and [implementation plan](implementation_plan.md). The [execution brief](agent_prompt.md) explains the update workflow.

## Implementation tasks

- [x] FR-01, FR-02, NFR-01: Create `jev_harness.py` with bootstrap, validated config/input, pinned model, and `.python-version`.
- [x] FR-03: Implement the direct TypeSafe adapter, explicit fixture mode, and recorded failures without secrets. Transport checked with mocks and the recorded authenticated synthetic probe.
- [x] FR-04, FR-05: Implement deterministic accept/review, append-only audit, and offline replay.
- [x] FR-06: Implement bounded evaluation and honest fixture provenance.
- [x] FR-01 through FR-06: Add `test_jev_harness.py` for useful boundaries and integration paths; 45 tests passed in the retained transcript.
- [x] FR-07: Add bounded dotenv probe, canonical synthetic cases, and offline analyzer; inspect one smoke before 12 further live calls; retain commands, raw results, and verified audits.

## Verification and completion tasks

- [x] NFR-02: Capture raw command outputs in `evidence/`; complete a fresh-directory manual CLI run and replay.
- [x] NFR-02: Reconcile broader Jev/Laya research, live results, usage guide, and packet; validate the updated packet. Live evidence and research are linked from the walkthrough.

Remaining adoption work: choose a real independently labeled domain dataset, evaluate quality and calibration, and decide whether a separate local Laya benchmark is worthwhile. The synthetic live probe is completed; production validation is not.

## File summary and marker legend

The canonical file-purpose table is in [implementation_plan.md](implementation_plan.md). `[ ]` pending; `[/]` executing; `[x]` verified by retained evidence. No checkbox represents unperformed live validation.
