"""The `hum` console script takes no subcommands; `hum shim` is a common slip
(the shim's entry point is `hum-shim`). Guard with a helpful message."""
from __future__ import annotations

import sys

import pytest


def test_hum_main_rejects_stray_args(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["hum", "shim"])
    from app.main import main

    with pytest.raises(SystemExit) as exc:
        main()
    # Exits before touching settings/uvicorn, and points at the real command.
    assert "hum-shim" in str(exc.value)
    assert "shim" in str(exc.value)
