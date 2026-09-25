---
name: domain-modeling
description: Clarify ambiguous domain language, actors, entities, state transitions, ownership, and bounded contexts. Use only when domain ambiguity materially affects scope or architecture; before Plan approval operate read-only in chat, and record CONTEXT.md or sparse ADRs only after explicit approval.
license: MIT; see LICENSE
---

# Domain Modeling

Build and sharpen the project's domain model only when the words or ownership boundaries are materially blocking the design. This is an optional discovery lens, not an automatic first-session step.

## Trigger

Use when one or more are true:

- terminology is ambiguous, overloaded, or conflicts with repository language
- actors, entities, state transitions, invariants, or data ownership affect the design
- existing code and proposed domain language disagree
- bounded contexts or their relationships need clarification

Do not invoke merely to read an existing glossary, for a one-day/simple task, or after every first response.

## Mode Gate

### Discovery mode — before Owner Plan approval

Discovery mode is strictly no-write:

- read existing `CONTEXT.md`, `CONTEXT-MAP.md`, ADRs, contracts, and relevant code
- challenge conflicting terms and propose canonical language
- invent concrete edge-case scenarios to test boundaries
- keep the temporary glossary, scenarios, and candidate decisions in chat
- contribute resolved/assumed/blocking/deferred items to the Plan Preview

Do not create or modify `CONTEXT.md`, `CONTEXT-MAP.md`, ADRs, Plan, work log, code, or configuration before the Owner confirms the Plan.

### Record mode — after explicit Plan approval

Only after approval may you record approved language:

- create/update `CONTEXT.md` lazily when a real domain term has been resolved
- in a multi-context repository, follow an approved `CONTEXT-MAP.md` and write to the relevant context
- offer an ADR only when all three ADR tests pass
- keep records within the approved Plan and evidence boundary

## During Discovery

### Challenge the glossary

When a proposed term conflicts with committed language, quote the conflict and ask which meaning is authoritative.

### Sharpen fuzzy language

Propose one canonical term when a vague word is doing multiple jobs. Include a recommended default.

### Test concrete scenarios

Use scenarios that expose edge cases, lifecycle transitions, cardinality, and ownership. Ask only when the answer changes scope/acceptance, architecture/data ownership, or a hard-to-reverse choice.

### Cross-reference code and contracts

If code or existing evidence contradicts the proposed model, surface the contradiction rather than silently choosing one.

Follow the kickoff's shared question budget: at most 3 discovery rounds, 3–5 related blocking decisions per round, normally no more than 12–15 decisions. Exceed it only after explicit Owner opt-in to `deep-discovery`.

## CONTEXT.md Boundary

Use [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` is a glossary and nothing else:

- define what a domain-specific thing is in one or two sentences
- choose canonical terms and list rejected synonyms under `_Avoid_`
- exclude implementation details, specs, scratch notes, and general programming terms
- create files lazily, never speculatively

## ADR Boundary

Use [ADR-FORMAT.md](./ADR-FORMAT.md). Offer an ADR only when all three are true:

1. hard to reverse
2. surprising without context
3. the result of a real trade-off

If any test fails, do not create the ADR.

## Output

In discovery mode, return chat-only:

- candidate canonical terms
- scenarios examined
- ownership/context boundaries
- contradictions found
- Resolved / Assumed / Blocking / Deferred
- question budget remaining

In record mode, list each approved file write and the Plan decision authorizing it.

## Attribution

Adapted for Harness from Matt Pocock's MIT-licensed `domain-modeling` skill. See [SOURCE.md](./SOURCE.md) and [LICENSE](./LICENSE).
