# NOTICE

**socialbrain** is a fork of [`xbrain`](https://github.com/VGonPa/xbrain) by
**Víctor González Pacheco**, extended to support a second source (LinkedIn
saved posts) alongside the original X/Twitter support.

This is a fork, not a contribution back upstream: `xbrain`'s own
`CONTRIBUTING.md` scopes contributions to "X, personal use, your own
account and your own data," which a second-platform source falls outside
of. See [`docs/FORK.md`](docs/FORK.md) for the fork rationale, the
cherry-pick policy toward upstream, and why the importable Python package
is still named `xbrain` internally while everything user-facing
(distribution name, console scripts, docs) is `socialbrain`.

- Upstream project: <https://github.com/VGonPa/xbrain>
- Upstream author: Víctor González Pacheco
- Fork maintained by: Alberto Laudadio ([@betolauda](https://github.com/betolauda))
- License: MIT for both the original work and the fork's additions — see
  [`LICENSE`](LICENSE), which carries both copyright lines.

All of xbrain's original "Responsible use" constraints (personal account,
personal data, respect the platform's Terms of Service) apply in full, and
LinkedIn's User Agreement §8.2 (no browser automation, no crawlers) is
materially stricter than X's — see the "Responsible use" section of
[`README.md`](README.md) for how this fork's LinkedIn support is designed
around that.
