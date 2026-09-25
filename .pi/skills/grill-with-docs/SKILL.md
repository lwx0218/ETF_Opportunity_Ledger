---
name: grill-with-docs
description: Stress-test a plan or design against a substantive repository decision baseline or explicit contract conflict using a bounded interview. Use when approved plans/specs/architecture/domain evidence exists; do not use merely because bootstrap AGENTS/intake scaffold exists.
---

# Grill With Docs

Use only when the repository has a substantive decision baseline—such as an approved Plan, Spec, architecture/domain record, implementation evidence, or an explicit conflict with current contracts. Bootstrap-only `AGENTS.md`, README, intake, and empty operations directories do not qualify; for a fuzzy greenfield request with only scaffold, use `grill-me`.

Anchor the interview against that substantive baseline before asking the Owner.

## Read Order

1. `AGENTS.md`
2. `Harness_manual.md`
3. `docs/project-intake/`
4. `operations/planning/`
5. `operations/work_logs/`
6. `operations/reviews/`
7. `.pi/prompt-templates/`
8. relevant specs, architecture, `CONTEXT.md`, or ADRs

## Interview Contract

- default maximum 3 discovery rounds
- group 3–5 related blocking decisions per round
- target maximum 12–15 blocking decisions total
- every decision includes a recommended default grounded in repository evidence
- allow `accept recommended defaults`; this resolves discovery decisions but never approves a durable Plan
- do not ask what the repository already answers
- ask only if the answer changes scope/acceptance, architecture/data ownership, or a hard-to-reverse/high-risk choice
- put non-blocking uncertainty in assumptions/backlog
- require explicit Owner opt-in before `deep-discovery`

End every response with Resolved, Assumed, Blocking, Deferred, and Question budget remaining.

Stop when blocking scope, architecture, and acceptance decisions are resolved; non-blocking uncertainty is explicit; and validation/control gates are clear.

## During The Interview

- quote conflicts between the proposal and current contract/evidence
- sharpen vague language into terms the repository can use
- distinguish chat-only assumptions from Plan/Spec/domain records
- invoke optional `domain-modeling` only when terminology/ownership/state/context ambiguity is material

## Greenfield No-Write Boundary

Before Owner Plan approval, repository exploration and chat Plan Preview are allowed, but project writes are not. Keep temporary domain language and scenarios in chat. Do not create/update Plan, intake, `CONTEXT.md`, ADR, work log, code, or config.

## Output

1. clarified understanding
2. documented facts and conflicts
3. resolved/assumed/blocking/deferred summary
4. recommended route
5. evidence to refresh after the applicable approval gate
6. remaining question budget

## Boundaries

- no unbounded relentless questioning
- no implementation during grilling
- no durable writes before confirmation
- no heavyweight capability recommendation without evidence of a real gap
