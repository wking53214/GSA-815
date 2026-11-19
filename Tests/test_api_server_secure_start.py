"""The API server refuses to start on a made-up key or over plain HTTP, unless the one dev switch is on."""

import pytest

import api_server_resilient as api

KEY = {"ICEBERG_API_KEYS": "realkey:ops"}


def test_no_key_refuses_to_start():
    with pytest.raises(RuntimeError, match="ICEBERG_API_KEYS"):
        api.require_real_api_keys({})


def test_a_malformed_key_refuses_to_start():
    with pytest.raises(RuntimeError):
        api.require_real_api_keys({"ICEBERG_API_KEYS": "nocolon"})
    with pytest.raises(RuntimeError):
        api.require_real_api_keys({"ICEBERG_API_KEYS": ":name"})


def test_a_real_key_is_accepted():
    api.require_real_api_keys(KEY)


def test_the_dev_switch_allows_no_key():
    api.require_real_api_keys({api.DEV_SWITCH: "1"})


def test_plain_http_refuses_to_start():
    with pytest.raises(RuntimeError, match="plain HTTP"):
        api.require_tls(False, {})


def test_tls_is_accepted():
    api.require_tls(True, {})


def test_the_dev_switch_allows_plain_http():
    api.require_tls(False, {api.DEV_SWITCH: "true"})


@pytest.mark.parametrize("value", ["0", "", "no", "false", "2"])
def test_only_an_explicit_yes_turns_the_switch_on(value):
    assert api.insecure_dev_allowed({api.DEV_SWITCH: value}) is False
