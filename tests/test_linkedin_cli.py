"""Tests for the `socialbrain-li` CLI (`xbrain.linkedin.cli`)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from typer.testing import CliRunner

from xbrain.linkedin.cli import app
from xbrain.store import load_state, load_store

runner = CliRunner()

_ACTIVITY_URL = "https://www.linkedin.com/feed/update/urn:li:activity:{}"


def _setup_repo(tmp_path: Path, monkeypatch) -> Path:
    """A minimal LinkedIn-only repo — no `[x]` section needed."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "config.toml").write_text(
        f'[paths]\nvault = "{vault}"\noutput_subdir = "x-knowledge"\ndata_dir = "data"\n',
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("XBRAIN_REPO_ROOT", str(tmp_path))
    return vault


def _export_csv(tmp_path: Path, *ids: str) -> Path:
    rows = "\n".join(f"{_ACTIVITY_URL.format(i)},2026-08-19 01:25:29" for i in ids)
    path = tmp_path / "Saved_Items_123.csv"
    path.write_text(f"savedItem,CreatedTime\n{rows}\n", encoding="utf-8")
    return path


def test_import_saved_from_csv(tmp_path: Path, monkeypatch) -> None:
    _setup_repo(tmp_path, monkeypatch)
    export = _export_csv(tmp_path, "7495649402552913920", "7495649402552913921")
    result = runner.invoke(app, ["import-saved", str(export)])
    assert result.exit_code == 0, result.output
    assert "li_saved: 2 nuevos items" in result.output

    store = load_store(tmp_path / "data" / "items.json")
    assert set(store) == {"li-7495649402552913920", "li-7495649402552913921"}
    state = load_state(tmp_path / "data" / "state.json")
    assert state.li_saved_imported is not None
    assert state.li_saved_imported.file == "Saved_Items_123.csv"


def test_import_saved_from_zip(tmp_path: Path, monkeypatch) -> None:
    _setup_repo(tmp_path, monkeypatch)
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "Saved_Items_123.csv",
            f"savedItem,CreatedTime\n{_ACTIVITY_URL.format('7495649402552913920')},2026-08-19 01:25:29\n",
        )
        archive.writestr("messages.csv", "PRIVATE")
    result = runner.invoke(app, ["import-saved", str(zip_path)])
    assert result.exit_code == 0, result.output
    assert "li_saved: 1 nuevos items" in result.output


def test_limit_takes_first_n(tmp_path: Path, monkeypatch) -> None:
    _setup_repo(tmp_path, monkeypatch)
    export = _export_csv(
        tmp_path, "7495649402552913920", "7495649402552913921", "7495649402552913922"
    )
    result = runner.invoke(app, ["import-saved", str(export), "--limit", "2"])
    assert result.exit_code == 0, result.output
    assert "li_saved: 2 nuevos items" in result.output
    assert set(load_store(tmp_path / "data" / "items.json")) == {
        "li-7495649402552913920",
        "li-7495649402552913921",
    }


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    _setup_repo(tmp_path, monkeypatch)
    export = _export_csv(tmp_path, "7495649402552913920")
    result = runner.invoke(app, ["import-saved", str(export), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "dry-run" in result.output
    assert "1 nuevos items" in result.output
    assert not (tmp_path / "data" / "items.json").exists()
    assert not (tmp_path / "data" / "state.json").exists()


def test_import_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    _setup_repo(tmp_path, monkeypatch)
    export = _export_csv(tmp_path, "7495649402552913920", "7495649402552913921")
    first = runner.invoke(app, ["import-saved", str(export)])
    assert first.exit_code == 0, first.output
    assert "li_saved: 2 nuevos items" in first.output

    second = runner.invoke(app, ["import-saved", str(export)])
    assert second.exit_code == 0, second.output
    assert "li_saved: 0 nuevos items" in second.output
    assert len(load_store(tmp_path / "data" / "items.json")) == 2


def test_missing_file_reports_clean_error(tmp_path: Path, monkeypatch) -> None:
    _setup_repo(tmp_path, monkeypatch)
    result = runner.invoke(app, ["import-saved", str(tmp_path / "nope.csv")])
    assert result.exit_code == 1
    assert "Error:" in result.output
