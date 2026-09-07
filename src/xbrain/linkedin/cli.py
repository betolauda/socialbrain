"""``socialbrain-li`` — import LinkedIn saved posts into the shared store.

A small, separate `typer` app (console script ``socialbrain-li``) that
mirrors the idioms of `xbrain.cli` — same config/store/state helpers, same
clean-error handling, same summary-line style — without pulling in the X
extraction machinery.
"""

from __future__ import annotations

import functools
import logging
import os
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import typer

from xbrain.config import Config, load_config
from xbrain.linkedin.browser import login as run_login
from xbrain.linkedin.saved_items import parse_saved_items
from xbrain.models import ArchiveImport
from xbrain.store import load_state, load_store, merge_items, save_state, save_store

app = typer.Typer(help="socialbrain-li — importa tus publicaciones guardadas de LinkedIn")

_OPERATOR_ERRORS = (
    FileNotFoundError,
    ValueError,
    KeyError,
    zipfile.BadZipFile,
    # OSError covers PermissionError, IsADirectoryError, etc.
    OSError,
)


@app.callback()
def _configure_logging() -> None:
    """Route library `logging` warnings (skipped rows, bad timestamps) to stderr."""
    logging.basicConfig(level=logging.WARNING, format="%(message)s")


def _repo_root() -> Path:
    """Repo root — overridable via ``XBRAIN_REPO_ROOT`` for tests.

    Mirrors `xbrain.cli._repo_root`. This file is
    ``src/xbrain/linkedin/cli.py``, so the root is three parents up from the
    package dir.
    """
    override = os.environ.get("XBRAIN_REPO_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3]


def _config() -> Config:
    return load_config(_repo_root())


def _handle_cli_errors(func: Callable) -> Callable:
    """Surface expected operator errors as a clean message + exit code 1."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except _OPERATOR_ERRORS as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    return wrapper


@app.command()
@_handle_cli_errors
def login() -> None:
    """Abre un navegador para iniciar sesión en LinkedIn y guarda la sesión.

    La sesión se guarda en `auth/linkedin_storage_state.json` (gitignored),
    separada de la de X. Re-ejecuta esto cuando la sesión caduque.
    """
    run_login(_config().storage_state_for("linkedin"))


@app.command(name="import-saved")
@_handle_cli_errors
def import_saved(
    path: Path = typer.Argument(
        ..., help="El .zip del export oficial de LinkedIn, o un Saved_Items*.csv extraído."
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Importa solo los primeros N items (los más recientes en el archivo).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Muestra qué se importaría y no escribe nada.",
    ),
) -> None:
    """Importa las publicaciones guardadas de LinkedIn desde el export oficial.

    Lee ``Saved_Items*.csv`` directamente del ZIP (sin extraer nada más — el
    export contiene también mensajes y contactos privados) y crea un item
    ``li_saved`` vacío por fila. La importación es idempotente:
    `merge_items` nunca sobrescribe, así que repetirla no añade nada.
    """
    cfg = _config()
    store = load_store(cfg.items_path)
    state = load_state(cfg.state_path)

    items = parse_saved_items(path)
    if limit is not None:
        items = items[:limit]

    if dry_run:
        new = sum(1 for item in items if item.id not in store)
        typer.echo(f"li_saved (dry-run): {new} nuevos items de {len(items)} en el archivo")
        return

    added = merge_items(store, items)
    state.li_saved_imported = ArchiveImport(file=path.name, at=datetime.now(timezone.utc))
    save_store(store, cfg.items_path)
    save_state(state, cfg.state_path)
    typer.echo(f"li_saved: {added} nuevos items")
