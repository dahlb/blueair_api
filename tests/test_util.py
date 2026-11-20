"""Tests for the helpers in ``blueair_api.util``."""

from typing import Any

from multidict import CIMultiDict, CIMultiDictProxy
import pytest

from blueair_api.util import clean_dictionary_for_logging


@pytest.mark.parametrize(
    "value",
    ["home.blueair.io", 42, None, True],
)
def test_clean_dictionary_for_logging_returns_non_mapping_unchanged(value: Any) -> None:
    """Non-mapping JSON values (e.g. the bare home host string) pass through."""
    assert clean_dictionary_for_logging(value) == value


def test_clean_dictionary_for_logging_masks_nested_values() -> None:
    """Sensitive keys are masked in nested mappings and lists without mutating input."""
    original: dict[str, Any] = {
        "Password": "secret",
        "name": "device",
        "nested": {"username": "abc", "keep": 1},
        "items": [{"password": "x", "id": 2}, "plain"],
    }

    cleaned = clean_dictionary_for_logging(original)

    assert cleaned == {
        "Password": "***",
        "name": "device",
        "nested": {"username": "***", "keep": 1},
        "items": [{"password": "***", "id": 2}, "plain"],
    }
    assert original["Password"] == "secret"
    assert original["nested"]["username"] == "abc"


def test_clean_dictionary_for_logging_handles_top_level_list() -> None:
    """A top-level JSON list is cleaned item by item."""
    assert clean_dictionary_for_logging([{"password": "x"}, 1]) == [{"password": "***"}, 1]


def test_clean_dictionary_for_logging_handles_header_proxy() -> None:
    """Response headers from aiohttp (``CIMultiDictProxy``) are accepted."""
    headers = CIMultiDictProxy(CIMultiDict({"Username": "u", "Server": "s"}))
    cleaned = clean_dictionary_for_logging(headers)
    assert cleaned == {"Username": "***", "Server": "s"}


@pytest.mark.parametrize(
    "key",
    [
        "Authorization",
        "idtoken",
        "id_token",
        "access_token",
        "refresh_token",
        "oauth_token",
        "secret",
        "regToken",
        "sessionToken",
        "sessionSecret",
        "UIDSignature",
        "email",
        "loginID",
        "X-AUTH-TOKEN",
        "ba_X-Amz-CustomAuthorizer-Signature",
        "ba_X-Amz-CustomAuthorizer-Token",
    ],
)
def test_clean_dictionary_for_logging_masks_tokens_and_secrets(key: str) -> None:
    """Credentials, tokens, session secrets and signatures never reach the logs."""
    cleaned = clean_dictionary_for_logging({"outer": {key: "value-to-hide"}, "keep": 1})

    assert cleaned == {"outer": {key: "***"}, "keep": 1}


def test_clean_dictionary_for_logging_masks_gigya_login_response() -> None:
    """Mask the session secrets inside a Gigya ``accounts.login`` response."""
    cleaned = clean_dictionary_for_logging(
        {"sessionInfo": {"sessionToken": "st", "sessionSecret": "ss", "expires_in": "3600"}}
    )

    assert cleaned == {
        "sessionInfo": {"sessionToken": "***", "sessionSecret": "***", "expires_in": "3600"}
    }
