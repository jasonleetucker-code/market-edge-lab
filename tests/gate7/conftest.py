"""Fixtures for the Gate 7 adversarial suite. Disposable tmp_path stores only."""

from __future__ import annotations

import pytest

from edge_lab import exp001_stageb as stageb
from edge_lab.shadow_ledger import ShadowLedger
from edge_lab.storage import SnapshotStore


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path / "fwd.sqlite3")


@pytest.fixture
def ledger(tmp_path):
    return ShadowLedger(tmp_path / "ledger.sqlite3")


@pytest.fixture(scope="session")
def model():
    return stageb.load_model()


@pytest.fixture
def full_day(store, monkeypatch):
    """The captured fixture day D = 2026-09-23: complete pfm, decision and re-check captures."""
    from test_forward import _full_day
    _full_day(store, monkeypatch)
    return store
