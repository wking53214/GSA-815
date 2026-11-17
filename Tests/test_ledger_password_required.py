"""A configured ledger host without a password is refused.

governed_pipeline.py used to fall back to the password "iceberg" when the
config named a postgres_host but no postgres_password. A well-known default
lets a misconfigured deployment connect with a guessable credential, so the
pipeline now refuses at construction, before any connection is attempted,
whether or not cassette binding is required.

NO DATABASE, NO NETWORK. The ledger class is replaced with a stand-in that
records whether it was ever constructed.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import governed_pipeline  # noqa: E402
from production_harness import IcebergProductionHarness  # noqa: E402


class _NeverConnect:
    constructed = []

    def __init__(self, **kwargs):
        _NeverConnect.constructed.append(kwargs)


@pytest.fixture
def no_ledger(monkeypatch):
    _NeverConnect.constructed = []
    monkeypatch.setattr(governed_pipeline, "PostgreSQLLedger", _NeverConnect)
    return _NeverConnect


@pytest.mark.parametrize("require_binding", [True, False])
@pytest.mark.parametrize("password", [None, ""])
def test_ledger_host_without_password_is_refused(no_ledger, require_binding, password):
    config = {"postgres_host": "localhost", "claude_api_key": None,
              "twilio_account_sid": None}
    if password is not None:
        config["postgres_password"] = password
    with pytest.raises(RuntimeError, match="postgres_password is not set"):
        IcebergProductionHarness(config, require_cassette_binding=require_binding)
    assert no_ledger.constructed == []


def test_no_ledger_host_needs_no_password(no_ledger):
    harness = IcebergProductionHarness(
        {"postgres_host": None, "claude_api_key": None, "twilio_account_sid": None},
        require_cassette_binding=False,
    )
    assert harness.ledger is None
    assert no_ledger.constructed == []
