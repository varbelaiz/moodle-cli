"""Tests for per-recording Panopto metadata and transcript retrieval."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from moodle_cli_panopto.errors import PanoptoError
from moodle_cli_panopto.panopto_api import fetch_srt, get_delivery_info, resolve_language

from conftest import PANOPTO_URL

DELIVERY_ID = "e7864c25-59dc-47c5-993a-b4a300033c23"


def _client() -> httpx.Client:
    return httpx.Client(base_url=PANOPTO_URL)


# -- get_delivery_info -----------------------------------------------------------------


def test_get_delivery_info_returns_the_parsed_body() -> None:
    body = {"Delivery": {"AvailableLanguages": [3]}}
    with respx.mock:
        respx.post(f"{PANOPTO_URL}/Panopto/Pages/Viewer/DeliveryInfo.aspx").mock(
            return_value=httpx.Response(200, json=body)
        )
        with _client() as client:
            assert get_delivery_info(client, DELIVERY_ID) == body


def test_get_delivery_info_raises_on_a_non_json_response() -> None:
    with respx.mock:
        respx.post(f"{PANOPTO_URL}/Panopto/Pages/Viewer/DeliveryInfo.aspx").mock(
            return_value=httpx.Response(200, text="not json")
        )
        with _client() as client, pytest.raises(PanoptoError):
            get_delivery_info(client, DELIVERY_ID)


def test_get_delivery_info_wraps_an_http_error_as_panopto_error() -> None:
    """A non-2xx must never escape as a raw httpx.HTTPStatusError."""
    with respx.mock:
        respx.post(f"{PANOPTO_URL}/Panopto/Pages/Viewer/DeliveryInfo.aspx").mock(
            return_value=httpx.Response(500)
        )
        with _client() as client, pytest.raises(PanoptoError):
            get_delivery_info(client, DELIVERY_ID)


def test_get_delivery_info_raises_when_the_shape_is_unexpected() -> None:
    with respx.mock:
        respx.post(f"{PANOPTO_URL}/Panopto/Pages/Viewer/DeliveryInfo.aspx").mock(
            return_value=httpx.Response(200, json={"nothing": "useful"})
        )
        with _client() as client, pytest.raises(PanoptoError):
            get_delivery_info(client, DELIVERY_ID)


# -- resolve_language --------------------------------------------------------------------


def test_resolve_language_auto_selects_the_only_option() -> None:
    info = {"Delivery": {"AvailableLanguages": [3]}}
    assert resolve_language(info, None) == 3


def test_resolve_language_raises_when_none_are_available() -> None:
    info: dict[str, Any] = {"Delivery": {"AvailableLanguages": []}}
    with pytest.raises(PanoptoError, match="no captions"):
        resolve_language(info, None)


def test_resolve_language_raises_when_omitted_and_several_are_available() -> None:
    info = {"Delivery": {"AvailableLanguages": [1, 3]}}
    with pytest.raises(ValueError, match="pass --language"):
        resolve_language(info, None)


def test_resolve_language_raises_when_the_explicit_choice_is_unavailable() -> None:
    info = {"Delivery": {"AvailableLanguages": [1, 3]}}
    with pytest.raises(ValueError, match="not available"):
        resolve_language(info, 9)


def test_resolve_language_accepts_an_explicit_available_choice() -> None:
    info = {"Delivery": {"AvailableLanguages": [1, 3]}}
    assert resolve_language(info, 1) == 1


def test_resolve_language_falls_back_to_available_captions() -> None:
    """`AvailableLanguages` absent: derive from `AvailableCaptions` instead."""
    info = {"Delivery": {"AvailableCaptions": [{"Language": 3, "ShowDisclaimer": True}]}}
    assert resolve_language(info, None) == 3


# -- fetch_srt -----------------------------------------------------------------------------


def test_fetch_srt_returns_the_raw_text() -> None:
    with respx.mock:
        respx.get(f"{PANOPTO_URL}/Panopto/Pages/Transcription/GenerateSRT.ashx").mock(
            return_value=httpx.Response(200, text="1\n00:00:00,000 --> 00:00:01,000\nHola\n")
        )
        with _client() as client:
            assert "Hola" in fetch_srt(client, DELIVERY_ID, 3)


def test_fetch_srt_raises_on_an_empty_body() -> None:
    """A wrong language code answers HTTP 200 with nothing -- the campus's usual failure mode."""
    with respx.mock:
        respx.get(f"{PANOPTO_URL}/Panopto/Pages/Transcription/GenerateSRT.ashx").mock(
            return_value=httpx.Response(200, text="")
        )
        with _client() as client, pytest.raises(PanoptoError, match="empty"):
            fetch_srt(client, DELIVERY_ID, 99)


def test_fetch_srt_wraps_an_http_error_as_panopto_error() -> None:
    with respx.mock:
        respx.get(f"{PANOPTO_URL}/Panopto/Pages/Transcription/GenerateSRT.ashx").mock(
            return_value=httpx.Response(403)
        )
        with _client() as client, pytest.raises(PanoptoError):
            fetch_srt(client, DELIVERY_ID, 3)
