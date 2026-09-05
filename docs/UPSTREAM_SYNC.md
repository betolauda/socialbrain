# UPSTREAM_SYNC.md — cherry-pick ledger

Every commit pulled from `upstream/develop` (or another upstream branch),
and every commit deliberately **not** pulled, gets one row here. See
[`docs/FORK.md`](FORK.md) for the sync playbook. Skipping a commit is
normal — silently skipping one is how a fork rots without anyone noticing.

Fork base: this fork branched from `VGonPa/xbrain@main` at commit
`546ed6b` (`Merge pull request #73 from VGonPa/develop`), 2026-09-05.

## Picked

| Date | Upstream SHA | Summary | Notes |
|---|---|---|---|
| — | — | — | (none yet) |

## Skipped

| Date | Upstream SHA | Summary | Reason |
|---|---|---|---|
| — | — | — | (none yet) |

## Watching

Branches not yet on `develop` that are likely to matter for this fork's
seams (`item.id`, `item.source`, `State`, `generate.py`, `ContentKind`):

| Branch | Why it matters |
|---|---|
| `upstream/VGonPa/knowledge-index-02-6a2a-item-fingerprints` | Almost certainly fingerprints `(item.id, item.source, ...)` — the two fields this fork's `SourceName`/id-namespacing widen. See `docs/FORK.md`. |
| `upstream/VGonPa/umbrella-knowledge-index-lexical` | Umbrella branch for the whole knowledge-index series; check its child branches as they merge. |
