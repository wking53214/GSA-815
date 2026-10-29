"""POST /process reports success False for a governance-blocked call.

The HTTP status stays 200 and the result body is passed through unchanged;
only the envelope's `success` flag follows the governance outcome.
"""

import pytest
from fastapi.testclient import TestClient

import api_server_resilient as api


class _StubHarness:
    def __init__(self, result):
        self.result = result

    def process_call(self, call):
        return self.result


@pytest.fixture
def client():
    saved = api.harness
    api.app.dependency_overrides[api.require_api_key] = lambda: {"name": "t"}
    # No `with`: the startup hook must not run.
    yield TestClient(api.app)
    api.app.dependency_overrides.pop(api.require_api_key, None)
    api.harness = saved


def _post(client, result):
    api.harness = _StubHarness(result)
    return client.post("/process", json={"sid": "X"}, headers={"x-api-key": "k"})


def test_a_blocked_call_reports_success_false(client):
    result = {"governance_required": True, "governance_approved": False,
              "governance_blocked": True, "ledger_write_failed": False}

    resp = _post(client, result)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["result"] == result


def test_an_approved_call_still_reports_success_true(client):
    result = {"governance_required": True, "governance_approved": True,
              "governance_blocked": False, "ledger_write_failed": False}

    resp = _post(client, result)

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["result"] == result


def test_an_ungoverned_call_still_reports_success_true(client):
    result = {"governance_required": False, "governance_approved": False,
              "governance_blocked": False}

    assert _post(client, result).json()["success"] is True


def test_a_duplicate_rejection_without_the_flag_is_unchanged(client):
    result = {"error": "duplicate_sid", "sid": "X"}

    assert _post(client, result).json()["success"] is True
