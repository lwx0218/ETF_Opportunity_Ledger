# archive/grok-raw

Append-only orphan branch for Grok Bot raw evidence batches.

- Each batch lives in a top-level directory named `grok-<topic>-<YYYYMMDD>/`.
- Contents per batch: `raw.zip`, `SHA256SUMS`, `README.md`.
- **Do not** rewrite, delete, or force-push history on this branch.
- New batches are added only as new commits with new paths (or identical path + identical content may be skipped).
