"""Configuration loading for XBrain."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from xbrain.i18n import strings_for
from xbrain.models import ExecutorName
from xbrain.platforms import PLATFORMS, PlatformName

# In-body `**Topics:**` line styles. `wikilink` (default) keeps the current
# navigation-first behaviour; `hashtag` emits Obsidian tags so the line pivots
# into the tag pane. Frontmatter `tags:` are unaffected by this toggle.
SUPPORTED_TOPIC_STYLES: tuple[str, ...] = ("wikilink", "hashtag")


@dataclass(frozen=True)
class Config:
    repo_root: Path
    vault: Path
    output_dir: Path
    data_dir: Path
    x_handle: str
    enrich_executor: ExecutorName
    enrich_model: str
    vocab_target_count: int
    topics_resynth_threshold: int
    output_language: str  # one of xbrain.i18n.SUPPORTED_LANGUAGES
    topic_style: str  # one of xbrain.config.SUPPORTED_TOPIC_STYLES
    # `describe_model` defaults to Sonnet 4.6 — the spec settled on it as the
    # quality / cost sweet spot for vision (~$3-5 for a 2k-image corpus).
    # Override per run via `xbrain describe --model ...` when iterating on
    # prompt or budget; the CLI flag wins over the config value.
    describe_model: str
    # `describe_version` tags every produced description so a prompt
    # evolution can be rolled out incrementally: bumping the value here
    # makes the next `xbrain describe` run re-describe stale entries
    # automatically (no `--force` needed). The string is exact-match —
    # there is no ordering relation, only equality.
    describe_version: str
    # `transcribe_command` is the EXTERNAL transcriber `xbrain digest-video`
    # shells out to (#44) — the heavy ASR lives outside xbrain core, invoked as
    # a subprocess located via PATH/config. Defaults to `parakeet-mlx`; may be a
    # multi-token wrapper command (split with shlex, no shell). `transcribe_model`
    # is the optional model id passed through (`None` → the transcriber's own
    # default).
    transcribe_command: str
    transcribe_model: str | None
    # `vision_command` is the EXTERNAL vision model `xbrain digest-video --frames`
    # shells out to (#44 PR4) to describe key-frame slides — the heavy vision lives
    # outside xbrain core, invoked as a subprocess located via PATH/config. There
    # is NO bundled default: it defaults to `""` (unset), and `--frames` errors
    # clearly until it is configured. May be a multi-token wrapper (split with
    # shlex, no shell). `vision_model` is the optional model id passed through
    # (`None` → the vision tool's own default).
    vision_command: str
    vision_model: str | None
    # Fork additions (see docs/FORK.md) — defaulted so every pre-fork
    # `Config(...)` construction still compiles unchanged.
    linkedin_max_per_run: int = 25
    linkedin_min_delay_s: float = 45.0
    linkedin_max_delay_s: float = 120.0

    @property
    def items_path(self) -> Path:
        return self.data_dir / "items.json"

    @property
    def media_dir(self) -> Path:
        """Root directory for downloaded photo bytes.

        Photos are stored at ``<media_dir>/<item-id>/<index>.<ext>``. Lives
        under `data/` so it shares the gitignore with the rest of the
        artifact tree. The snapshot lifecycle in `xbrain.snapshot`
        currently covers only the JSON store (`items.json`, `state.json`,
        `vocab.yaml`, `topics.json`) — the binary photo bytes are NOT
        snapshotted today. A re-download via `xbrain media` is the
        recovery path if `data/media/` is lost.
        """
        return self.data_dir / "media"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    @property
    def topics_path(self) -> Path:
        return self.data_dir / "topics.json"

    def storage_state_for(self, platform: PlatformName) -> Path:
        """The Playwright session-state file for one platform.

        Each platform gets its own file (see `xbrain.platforms.PLATFORMS`)
        so an X session and a LinkedIn session never collide.
        """
        return self.repo_root / "auth" / PLATFORMS[platform].auth_filename

    @property
    def storage_state_path(self) -> Path:
        return self.storage_state_for("x")


def require_x_handle(cfg: Config) -> str:
    """The X handle, raised loudly if unset.

    Fork addition: `[x]` in config.toml is now optional (a LinkedIn-only
    config need not set an X handle at all), so the two X-only call sites
    that actually need it (`_run_extract`'s own-tweet URL, `import_archive`'s
    `Author`) must check explicitly rather than relying on `load_config`
    having already validated it.
    """
    if not cfg.x_handle:
        raise ValueError(
            "config.toml: [x].handle is required for X commands — set it, or use "
            "the LinkedIn CLI (`socialbrain-li`) if you only use LinkedIn."
        )
    return cfg.x_handle


def _load_linkedin_settings(settings: dict) -> tuple[int, float, float]:
    """Parse and validate `[linkedin]`, split out of `load_config` to keep
    that function's complexity down (radon). The three limits are
    guardrails, not suggestions — see docs/FORK.md and
    `xbrain.linkedin.hydrate`: LinkedIn's User Agreement prohibits browser
    automation outright, and low volume + heavy pacing is what keeps this
    fork's hydrator from being an obvious high-volume bot signature.
    """
    linkedin = settings.get("linkedin", {})
    max_per_run = int(linkedin.get("max_per_run", 25))
    if not 1 <= max_per_run <= 100:
        raise ValueError("config.toml: [linkedin].max_per_run must be between 1 and 100")
    min_delay_s = float(linkedin.get("min_delay_s", 45.0))
    max_delay_s = float(linkedin.get("max_delay_s", 120.0))
    if min_delay_s < 20.0 or max_delay_s < min_delay_s:
        raise ValueError(
            "config.toml: [linkedin] delays must satisfy 20 <= min_delay_s <= max_delay_s"
        )
    return max_per_run, min_delay_s, max_delay_s


def load_config(repo_root: Path) -> Config:
    """Load config.toml from a repo root into a Config."""
    settings = tomllib.loads((repo_root / "config.toml").read_text(encoding="utf-8"))
    paths = settings["paths"]
    # Fork addition: `[x]` is optional — a LinkedIn-only user need not set an
    # X handle. A PRESENT `[x]` section with an empty handle is still an
    # error (same message as before), so an existing config's validation
    # behaviour is unchanged; only a config that omits `[x]` entirely now
    # loads, where it previously could not.
    x_settings = settings.get("x")
    if x_settings is not None and not x_settings.get("handle"):
        raise ValueError("config.toml: [x].handle is empty — set your X handle")
    x_settings = x_settings or {}
    vault = Path(paths["vault"]).expanduser()
    enrich = settings.get("enrich", {})
    vocab = settings.get("vocab", {})
    executor = enrich.get("executor", "claude-code")
    valid_executors = get_args(ExecutorName)
    if executor not in valid_executors:
        raise ValueError(
            f"config.toml: [enrich].executor must be manual|api|claude-code, got {executor!r}"
        )
    target_count = int(vocab.get("target_count", 30))
    if target_count < 1:
        raise ValueError("config.toml: [vocab].target_count must be >= 1")
    topics = settings.get("topics", {})
    resynth_threshold = int(topics.get("resynth_threshold", 25))
    if resynth_threshold < 1:
        raise ValueError("config.toml: [topics].resynth_threshold must be >= 1")
    output = settings.get("output", {})
    output_language = output.get("language", "English")
    # Validate via strings_for: it already raises ValueError listing supported
    # languages on an unknown value. Single source of truth for the check.
    strings_for(output_language)
    topic_style = output.get("topic_style", "wikilink")
    if topic_style not in SUPPORTED_TOPIC_STYLES:
        raise ValueError(
            f"config.toml: [output].topic_style must be one of "
            f"{list(SUPPORTED_TOPIC_STYLES)}, got {topic_style!r}"
        )
    describe = settings.get("describe", {})
    transcribe = settings.get("transcribe", {})
    vision = settings.get("vision", {})
    linkedin_max_per_run, linkedin_min_delay_s, linkedin_max_delay_s = _load_linkedin_settings(
        settings
    )
    return Config(
        repo_root=repo_root,
        vault=vault,
        output_dir=vault / paths["output_subdir"],
        data_dir=repo_root / paths["data_dir"],
        x_handle=x_settings.get("handle", ""),
        enrich_executor=executor,
        enrich_model=enrich.get("model", "claude-haiku-4-5-20251001"),
        vocab_target_count=target_count,
        topics_resynth_threshold=resynth_threshold,
        output_language=output_language,
        topic_style=topic_style,
        describe_model=describe.get("model", "claude-sonnet-4-6"),
        describe_version=describe.get("version", "v1"),
        transcribe_command=transcribe.get("command", "parakeet-mlx"),
        transcribe_model=transcribe.get("model"),
        vision_command=vision.get("command", ""),
        vision_model=vision.get("model"),
        linkedin_max_per_run=linkedin_max_per_run,
        linkedin_min_delay_s=linkedin_min_delay_s,
        linkedin_max_delay_s=linkedin_max_delay_s,
    )
