# ADR Format

Adapted from the upstream format identified in `SOURCE.md`.

ADRs normally live in `docs/adr/` and use sequential names such as `0001-slug.md`. Follow a project-local ADR contract when one already exists.

## Minimal Template

```md
# {Short title of the decision}

{One to three sentences: context, decision, and why.}
```

Optional status, considered options, or consequences sections are included only when they add genuine value.

## Creation Gate

Create no ADR before Owner Plan approval. In record mode, offer an ADR only when all three are true:

1. changing the decision later is meaningfully expensive
2. a future reader would find the decision surprising without context
3. genuine alternatives existed and a real trade-off selected one

If one test fails, keep the item in the Plan, assumptions, or implementation notes instead of creating an ADR.
