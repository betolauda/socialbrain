# tests/test_import_note.py
import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from xbrain.cli import app
from xbrain.models import Author, Item
from xbrain.store import load_store, save_store

runner = CliRunner()


def _setup_repo(tmp_path: Path, monkeypatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "config.toml").write_text(
        "[paths]\n"
        f'vault = "{vault}"\n'
        'output_subdir = "x-knowledge"\n'
        'data_dir = "data"\n'
        "[x]\n"
        'handle = "vgonpa"\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("XBRAIN_REPO_ROOT", str(tmp_path))
    return tmp_path / "data" / "items.json"


def _item(item_id: str) -> Item:
    return Item(
        id=item_id,
        source="bookmark",
        url=f"https://x.com/a/status/{item_id}",
        author=Author(handle="alice", name="Alice"),
        text=f"Note {item_id}",
        created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        captured_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )


def _write_transcript(path: Path, **overrides) -> Path:
    data = {
        "text": "Hola mundo",
        "language": "es",
        "has_speech": True,
        "segments": [{"start": 0.0, "end": 2.5, "text": "Hola mundo"}],
        "title": "Charla",
        "source": "a.mp4",
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_import_note_attaches_x_video_source(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    source = load_store(items_path)["42"].content.sources[0]
    assert source.kind == "x_video"
    assert source.text == "Hola mundo"
    assert source.language == "es"
    assert source.title == "Charla"
    assert source.has_speech is True


def test_import_note_repeated_item_attaches_to_all(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1"), "2": _item("2")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "1", "--item", "2"])

    assert result.exit_code == 0, result.output
    store = load_store(items_path)
    assert store["1"].content.sources[0].kind == "x_video"
    assert store["2"].content.sources[0].kind == "x_video"


def test_import_note_unknown_item_fails_cleanly_and_writes_nothing(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"1": _item("1")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "1", "--item", "999"])

    assert result.exit_code == 1
    assert "999" in result.output
    assert load_store(items_path)["1"].content is None


def test_import_note_no_speech_is_attached_as_data(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(
        tmp_path / "transcript.json", text="", has_speech=False, segments=[]
    )

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    source = load_store(items_path)["42"].content.sources[0]
    assert source.kind == "x_video"
    assert source.has_speech is False
    assert source.text == ""


def test_import_note_skips_item_with_existing_transcript_unless_force(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    first = _write_transcript(tmp_path / "v1.json", text="v1")
    second = _write_transcript(tmp_path / "v2.json", text="v2")
    runner.invoke(app, ["import-note", str(first), "--item", "42"])

    skipped = runner.invoke(app, ["import-note", str(second), "--item", "42"])
    assert skipped.exit_code == 0, skipped.output
    assert load_store(items_path)["42"].content.sources[0].text == "v1"

    forced = runner.invoke(app, ["import-note", str(second), "--item", "42", "--force"])
    assert forced.exit_code == 0, forced.output
    sources = load_store(items_path)["42"].content.sources
    assert [s.kind for s in sources] == ["x_video"]
    assert sources[0].text == "v2"


def test_import_note_snapshots_before_writing(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    transcript = _write_transcript(tmp_path / "transcript.json")

    result = runner.invoke(app, ["import-note", str(transcript), "--item", "42"])

    assert result.exit_code == 0, result.output
    assert "Snapshot created" in result.output


def test_import_note_malformed_json_fails_cleanly(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    result = runner.invoke(app, ["import-note", str(bad), "--item", "42"])

    assert result.exit_code == 1
    assert load_store(items_path)["42"].content is None


def test_import_note_missing_file_fails_cleanly(tmp_path: Path, monkeypatch):
    items_path = _setup_repo(tmp_path, monkeypatch)
    save_store({"42": _item("42")}, items_path)

    result = runner.invoke(app, ["import-note", str(tmp_path / "nope.json"), "--item", "42"])

    assert result.exit_code == 1
