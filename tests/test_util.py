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
    original = {
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
    """aiohttp response headers (``CIMultiDictProxy``) are accepted."""
    headers = CIMultiDictProxy(CIMultiDict({"Username": "u", "Server": "s"}))
    cleaned = clean_dictionary_for_logging(headers)
    assert cleaned == {"Username": "***", "Server": "s"}
