# tests/test_config.py
from pathlib import Path

import pytest

from xbrain.config import load_config, require_x_handle


def _write_repo(root: Path, handle: str = "vgonpa") -> None:
    (root / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        f'handle = "{handle}"\n',
        encoding="utf-8",
    )


def test_load_config_resolves_paths(tmp_path: Path):
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.x_handle == "vgonpa"
    assert cfg.output_dir == Path("/tmp/vault/learnings/x-knowledge")
    assert cfg.items_path == tmp_path / "data" / "items.json"


def test_load_config_defaults_transcribe_command_to_parakeet(tmp_path: Path):
    """No [transcribe] section → the external transcriber defaults to
    `parakeet-mlx`, model unset (the transcriber's own default)."""
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.transcribe_command == "parakeet-mlx"
    assert cfg.transcribe_model is None


def test_load_config_round_trips_transcribe_command_and_model(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[transcribe]\n"
        'command = "my-asr --quiet"\n'
        'model = "parakeet-tdt-0.6b-v2"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.transcribe_command == "my-asr --quiet"
    assert cfg.transcribe_model == "parakeet-tdt-0.6b-v2"


def test_load_config_defaults_vision_command_to_unset(tmp_path: Path):
    """No [vision] section → the external vision command is unset (`""`) and the
    model is None. `digest-video --frames` errors clearly until it is configured —
    there is NO bundled default vision model (#44 PR4)."""
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.vision_command == ""
    assert cfg.vision_model is None


def test_load_config_round_trips_vision_command_and_model(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[vision]\n"
        'command = "vlm-describe --fast"\n'
        'model = "qwen2-vl-7b"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.vision_command == "vlm-describe --fast"
    assert cfg.vision_model == "qwen2-vl-7b"


def test_load_config_defaults_output_language_to_english(tmp_path: Path):
    """No [output] section → English default."""
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.output_language == "English"


def test_load_config_round_trips_spanish_language(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[output]\n"
        'language = "Spanish"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.output_language == "Spanish"


def test_load_config_rejects_unknown_language(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[output]\n"
        'language = "Klingon"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Klingon"):
        load_config(tmp_path)


def test_load_config_rejects_empty_handle(tmp_path: Path):
    _write_repo(tmp_path, handle="")
    with pytest.raises(ValueError, match="handle"):
        load_config(tmp_path)


def test_load_config_reads_pipeline_settings(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[enrich]\n"
        'executor = "api"\n'
        'model = "claude-haiku-4-5-20251001"\n'
        "[vocab]\n"
        "target_count = 25\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.enrich_executor == "api"
    assert cfg.enrich_model == "claude-haiku-4-5-20251001"
    assert cfg.vocab_target_count == 25


def test_load_config_pipeline_settings_have_defaults(tmp_path: Path):
    _write_repo(tmp_path)  # config.toml WITHOUT [enrich]/[vocab]
    cfg = load_config(tmp_path)
    assert cfg.enrich_executor == "claude-code"  # subscription is the default
    assert cfg.enrich_model == "claude-haiku-4-5-20251001"
    assert cfg.vocab_target_count == 30


def test_load_config_rejects_unknown_executor(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[enrich]\n"
        'executor = "gpt"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="executor must be"):
        load_config(tmp_path)


def test_load_config_rejects_zero_target_count(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[vocab]\n"
        "target_count = 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="target_count must be >= 1"):
        load_config(tmp_path)


def test_config_topics_threshold_defaults_to_25(tmp_path):
    from xbrain.config import load_config

    (tmp_path / "config.toml").write_text(
        '[paths]\nvault = "/v"\noutput_subdir = "o"\ndata_dir = "data"\n[x]\nhandle = "h"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.topics_resynth_threshold == 25
    assert cfg.topics_path == tmp_path / "data" / "topics.json"


def test_config_topics_threshold_is_configurable(tmp_path):
    from xbrain.config import load_config

    (tmp_path / "config.toml").write_text(
        '[paths]\nvault = "/v"\noutput_subdir = "o"\ndata_dir = "data"\n'
        '[x]\nhandle = "h"\n'
        "[topics]\nresynth_threshold = 50\n",
        encoding="utf-8",
    )
    assert load_config(tmp_path).topics_resynth_threshold == 50


def test_load_config_defaults_topic_style_to_wikilink(tmp_path: Path):
    """No `[output] topic_style` key → wikilink default (backwards-compat)."""
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.topic_style == "wikilink"


def test_load_config_round_trips_hashtag_topic_style(tmp_path: Path):
    """Explicit `topic_style = "hashtag"` round-trips."""
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[output]\n"
        'topic_style = "hashtag"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.topic_style == "hashtag"


def test_load_config_rejects_unknown_topic_style(tmp_path: Path):
    """Unknown topic_style fails fast with the supported list in the message."""
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[output]\n"
        'topic_style = "bogus"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="topic_style"):
        load_config(tmp_path)


def test_load_config_describe_settings_have_defaults(tmp_path: Path):
    """No [describe] section → Sonnet 4.6 + version v1 (the spec defaults)."""
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.describe_model == "claude-sonnet-4-6"
    assert cfg.describe_version == "v1"


def test_load_config_round_trips_describe_overrides(tmp_path: Path):
    """[describe] section overrides — operators can pin a different model + version."""
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n'
        "[describe]\n"
        'model = "claude-opus-4-1"\n'
        'version = "v3"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.describe_model == "claude-opus-4-1"
    assert cfg.describe_version == "v3"


# ------------------------------------------------------- fork: [x] optional


def test_load_config_without_an_x_section_at_all(tmp_path: Path):
    """Fork addition: a LinkedIn-only config need not set an X handle."""
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.x_handle == ""


def test_require_x_handle_raises_for_an_empty_handle(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    with pytest.raises(ValueError, match="required for X commands"):
        require_x_handle(cfg)


def test_require_x_handle_returns_the_handle_when_set(tmp_path: Path):
    _write_repo(tmp_path, handle="vgonpa")
    cfg = load_config(tmp_path)
    assert require_x_handle(cfg) == "vgonpa"


# ------------------------------------------------------------- fork: [linkedin]


def test_load_config_linkedin_defaults(tmp_path: Path):
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.linkedin_max_per_run == 25
    assert cfg.linkedin_min_delay_s == 45.0
    assert cfg.linkedin_max_delay_s == 120.0


def test_load_config_linkedin_overrides(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[linkedin]\n"
        "max_per_run = 10\n"
        "min_delay_s = 60.0\n"
        "max_delay_s = 90.0\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    assert cfg.linkedin_max_per_run == 10
    assert cfg.linkedin_min_delay_s == 60.0
    assert cfg.linkedin_max_delay_s == 90.0


def test_load_config_rejects_linkedin_max_per_run_over_the_ceiling(tmp_path: Path):
    """The 100 ceiling is a guardrail, not a suggestion — see docs/FORK.md."""
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[linkedin]\n"
        "max_per_run = 500\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="max_per_run must be between 1 and 100"):
        load_config(tmp_path)


def test_load_config_rejects_linkedin_min_delay_below_the_floor(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[linkedin]\n"
        "min_delay_s = 5.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="20 <= min_delay_s <= max_delay_s"):
        load_config(tmp_path)


def test_load_config_rejects_linkedin_max_delay_below_min_delay(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        'vault = "/tmp/vault"\n'
        'output_subdir = "learnings/x-knowledge"\n'
        'data_dir = "data"\n'
        "[linkedin]\n"
        "min_delay_s = 100.0\n"
        "max_delay_s = 50.0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="20 <= min_delay_s <= max_delay_s"):
        load_config(tmp_path)


# --------------------------------------------------- fork: per-platform auth


def test_storage_state_for_x_matches_the_original_property(tmp_path: Path):
    """Pins the invariant: `storage_state_path` must keep resolving to
    exactly the pre-fork path, byte-identical, for every X call site."""
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.storage_state_for("x") == cfg.storage_state_path
    assert cfg.storage_state_path == tmp_path / "auth" / "storage_state.json"


def test_storage_state_for_linkedin_uses_a_separate_file(tmp_path: Path):
    _write_repo(tmp_path)
    cfg = load_config(tmp_path)
    assert cfg.storage_state_for("linkedin") == tmp_path / "auth" / "linkedin_storage_state.json"
    assert cfg.storage_state_for("linkedin") != cfg.storage_state_path
