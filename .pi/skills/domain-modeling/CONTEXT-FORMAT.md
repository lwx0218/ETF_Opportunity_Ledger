# CONTEXT.md Format

Adapted from the upstream format identified in `SOURCE.md`.

## Structure

```md
# {Context Name}

{One or two sentences describing what this context is and why it exists.}

## Language

**Order**:
{A one or two sentence definition of the term.}
_Avoid_: Purchase, transaction
```

## Rules

- Pick one canonical term; put rejected synonyms under `_Avoid_`.
- Keep definitions to one or two sentences and define what the thing is.
- Include only project-specific domain concepts, not general implementation/programming terms.
- Group terms only when natural clusters emerge.
- Keep all implementation details, requirements, decisions, and scratch notes out.

## Single And Multiple Contexts

- Single context: use one root `CONTEXT.md`.
- Multiple contexts: use an approved root `CONTEXT-MAP.md` that links each context's `CONTEXT.md` and states relationships.
- Create either lazily and only in record mode after Owner Plan approval.
- If context ownership is unclear, keep the candidate model in chat and ask a blocking decision within the shared question budget.
