# Test-gap risk-ranking rubric

Expands the P0/P1/P2 tiers in `SKILL.md` with ModelCompass-specific criteria and
concrete module examples, so the `testing-expert` agent ranks uncovered code
consistently across runs. The ranking question is always: *if this uncovered
branch is wrong, what is the blast radius?*

## P0 — must test (safety- or correctness-critical)

An untested defect here causes a missed escalation, a wrong decision acted on, or a
security exposure. Rank first.

- **Core decision logic** (e.g. `core/decision_engine.py`, `orchestrator._vote_node`,
  `_route_after_vote`): the primary convergence/voting rule, the max-attempts →
  fallback path, weight application per category. A bug here can silently ship a
  wrong outcome or loop forever.
- **Escalation / approval paths** (e.g. `orchestrator._approval_node`,
  `_build_result` escalation branch, `ApprovalRequest` construction): a genuinely
  inconclusive case must always produce an `ApprovalRequest`.
- **Untrusted-input parsing** (e.g. `input_adapter`, external-data backends,
  `error_codes` mapping): attacker- or user-influenced input; malformed input
  must fail safe, not crash or leak.
- **Security-relevant branches** (e.g. `SecretFilter`, secret redaction, auth on API
  routes, anything reading env/settings): a gap here is a disclosure risk.
- **De-duplication** (e.g. `similarity_check`, the `run` cache gate): both
  over-suppression (missed case) and under-suppression (alert fatigue).

## P1 — should test (behavioural correctness)

Wrong output but bounded blast radius; caught downstream or degrades gracefully.

- Backend strategy implementations (storage/log/notification/etc.) and their factories.
- Orchestrator node folding (e.g. `_fold_turn`, state accumulation, primary-result
  propagation).
- Schema validation & serialisation round-trips (e.g. `ResultReport`, `RequestBrief`,
  `WorkflowState`), including `Optional` fields and defaults.
- `DomainEvent` emission from node updates (e.g. `_events_from_update`).

## P2 — nice to have (low-risk / cosmetic)

- CLI/view formatting, Rich/TUI rendering.
- Logging output shape (beyond the redaction guarantee, which is P0).
- Help text, argument parsing niceties.

## Ranking procedure

1. Map each uncovered line/branch (from `--cov-report=term-missing`) to a
   behaviour, not just a line number.
2. Ask the blast-radius question; assign the highest tier that applies.
3. Within a tier, order by likelihood × reachability (a hot path beats a rare
   error branch).
4. For each P0, name a concrete suggested test (input → expected outcome), so the
   list is directly actionable by `testing-expert`.

## Anti-patterns

- Ranking by coverage-percentage delta instead of risk (a 2% gain over consensus
  logic beats a 20% gain over CLI formatting).
- Listing "add tests for module X" without the specific untested behaviour.
- Treating a security/redaction branch as P1 because it "looks simple".
