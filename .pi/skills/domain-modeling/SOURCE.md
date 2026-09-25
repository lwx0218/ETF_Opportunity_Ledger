# Source And Adaptation Notice

This Harness skill is adapted from:

- Project: `mattpocock/skills`
- Skill: `skills/engineering/domain-modeling/`
- Upstream commit: `6654f6b60cd9d5be8b54c6fafe44346dabeb3b76`
- Upstream repository: <https://github.com/mattpocock/skills>
- License: MIT; retained in [`LICENSE`](./LICENSE)
- Copyright: Matt Pocock, 2026

Harness adaptations:

- add a strict no-write discovery mode before Owner Plan approval
- keep temporary glossary and scenarios in chat before approval
- activate record mode only after explicit Plan confirmation
- integrate the bounded kickoff question budget and `deep-discovery` opt-in
- make domain modeling optional and trigger-based
- retain implementation-free `CONTEXT.md` and sparse ADR rules

No upstream endorsement is implied.
