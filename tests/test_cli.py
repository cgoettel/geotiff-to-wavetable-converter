"""Smoke tests for cli.py.

Kept deliberately minimal: assert the module imports cleanly and argparse
wires up (a --help invocation exits with code 0). End-to-end CLI behavior lives
in test_integration.py.
"""

import pytest


def test_cli_module_imports() -> None:
    """The cli module loads without ImportError.

    Catches stale imports, missing dependencies, and bad re-exports —
    the common failure modes after a refactor.
    """
    from geotiff_to_wavetable import cli

    assert hasattr(cli, "main")


def test_cli_help_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """`geotiff_to_wavetable --help` exits with code 0.

    Proves argparse is wired correctly.
    """
    monkeypatch.setattr("sys.argv", ["geotiff_to_wavetable", "--help"])

    from geotiff_to_wavetable.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0
