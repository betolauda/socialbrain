# tests/test_layering.py
"""Enforces the core/acquisition boundary as a checked property, not a claim.

Fork addition (see `docs/FORK.md`): "the source-agnostic core never imports
an acquisition layer" is the whole basis for adding a second source without
rewriting the pipeline. This test makes that a fact CI verifies on every PR,
not just a description in a docstring.

Acquisition-layer modules today: `xbrain.extract` (the X package),
`xbrain.fetch_x`, `xbrain.archive` (X's official-archive importer), and —
once the fork's LinkedIn support lands — `xbrain.linkedin`. `xbrain.cli` is
the one sanctioned exception: it is the seam where a CLI command wires an
acquisition layer to the core pipeline.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "xbrain"

ACQUISITION_PREFIXES = ("xbrain.extract", "xbrain.fetch_x", "xbrain.archive", "xbrain.linkedin")
ACQUISITION_MODULE_DIRS = {"extract", "linkedin"}
ACQUISITION_MODULE_FILES = {"fetch_x.py", "archive.py"}
SANCTIONED_IMPORTERS = {"cli.py"}


def _imported_module_names(py_file: Path) -> set[str]:
    """Every dotted module name a file imports, via `import` or `from ... import`."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def _core_python_files() -> list[Path]:
    """Every top-level core module — excludes acquisition packages/files
    themselves (which are allowed to import each other) and `__pycache__`."""
    files = [p for p in SRC.glob("*.py") if p.name not in ACQUISITION_MODULE_FILES]
    for sub in SRC.iterdir():
        if sub.is_dir() and sub.name not in ACQUISITION_MODULE_DIRS and sub.name != "__pycache__":
            files.extend(sub.rglob("*.py"))
    return files


def test_core_never_imports_an_acquisition_layer():
    violations: dict[str, set[str]] = {}
    for py_file in _core_python_files():
        if py_file.name in SANCTIONED_IMPORTERS:
            continue
        imported = _imported_module_names(py_file)
        hits = {
            name
            for name in imported
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in ACQUISITION_PREFIXES
            )
        }
        if hits:
            violations[str(py_file.relative_to(SRC))] = hits

    assert not violations, (
        "Core module(s) import an acquisition layer directly — this breaks the "
        "source-agnostic core property the fork's second source relies on. "
        f"Route the dependency through cli.py instead. Violations: {violations}"
    )


def test_acquisition_module_lists_are_accurate():
    """Guards the test itself against silent drift: every acquisition
    package/file this test excludes from the core scan must still exist."""
    for dirname in ACQUISITION_MODULE_DIRS:
        path = SRC / dirname
        assert path.exists() or dirname == "linkedin", f"expected {path} to exist"
    for filename in ACQUISITION_MODULE_FILES:
        assert (SRC / filename).exists(), f"expected {SRC / filename} to exist"
