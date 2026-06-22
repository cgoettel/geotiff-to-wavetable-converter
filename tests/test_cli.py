"""Smoke tests for cli.py.

Kept deliberately minimal: assert the module imports cleanly and argparse
wires up (a --help invocation exits with code 0). End-to-end CLI behavior is
covered transitively by the unit tests in test_converter.py / test_validators.py.
"""

from pathlib import Path

import pytest


def test_cli_module_imports() -> None:
    """The cli module loads without ImportError.

    Catches stale imports, missing dependencies, and bad re-exports —
    the common failure modes after a refactor.
    """
    from geotiff_to_wavetable import cli

    assert hasattr(cli, "main")


def test_cli_help_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`geotiff_to_wavetable --help` exits with code 0.

    Proves argparse is wired correctly and the module-level logging setup
    runs without error. chdir to tmp_path so the FileHandler's log file
    doesn't land in the repo root.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["geotiff_to_wavetable", "--help"])

    from geotiff_to_wavetable.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
