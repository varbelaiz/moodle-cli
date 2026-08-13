"""Per-recording metadata and transcript retrieval, against a Panopto host directly.

Both endpoints answer HTTP 200 no matter what -- a bad ``language`` code returns 200
with an empty body rather than an error -- so every call here treats "200 but hollow"
as a failure explicitly, the same discipline ``moodle_cli.client.check_api_error``
applies to the campus's own REST surface.
"""

from __future__ import annotations

from typing import Any

import httpx

from moodle_cli_panopto.errors import PanoptoError

_DELIVERY_INFO_PATH = "/Panopto/Pages/Viewer/DeliveryInfo.aspx"
_GENERATE_SRT_PATH = "/Panopto/Pages/Transcription/GenerateSRT.ashx"


def get_delivery_info(panopto: httpx.Client, delivery_id: str) -> dict[str, Any]:
    """Fetch ``DeliveryInfo.aspx`` for one recording: metadata, including which caption
    languages are available."""
    response = panopto.post(
        _DELIVERY_INFO_PATH, data={"deliveryId": delivery_id, "responseType": "json"}
    )
    response.raise_for_status()
    try:
        body: Any = response.json()
    except ValueError as exc:
        raise PanoptoError(
            f"{delivery_id}: DeliveryInfo.aspx returned a non-JSON response"
        ) from exc
    if not isinstance(body, dict) or "Delivery" not in body:
        raise PanoptoError(f"{delivery_id}: DeliveryInfo.aspx returned an unexpected response")
    return body


def _available_languages(delivery_info: dict[str, Any]) -> list[int]:
    delivery = delivery_info.get("Delivery") or {}
    languages = delivery.get("AvailableLanguages")
    if languages:
        return [int(value) for value in languages]
    captions = delivery.get("AvailableCaptions") or []
    return [int(caption["Language"]) for caption in captions if "Language" in caption]


def resolve_language(delivery_info: dict[str, Any], language: int | None) -> int:
    """Pick the caption language to fetch. Never guesses among more than one option.

    ``language`` given and available: used as-is. Given but not available: ``ValueError``
    naming what is. Omitted with none available: ``PanoptoError`` -- there is no
    transcript at all. Omitted with exactly one available: that one. Omitted with 2+
    available: ``ValueError`` asking the caller to pick.
    """
    available = _available_languages(delivery_info)
    if language is not None:
        if language not in available:
            options = ", ".join(str(value) for value in available) or "none"
            raise ValueError(f"language {language} is not available; available: {options}")
        return language
    if not available:
        raise PanoptoError("this recording has no captions in any language")
    if len(available) > 1:
        options = ", ".join(str(value) for value in available)
        raise ValueError(
            f"{len(available)} caption languages available ({options}); pass --language"
        )
    return available[0]


def fetch_srt(panopto: httpx.Client, delivery_id: str, language: int) -> str:
    """Fetch the raw SRT for one recording in LANGUAGE.

    An unavailable/wrong language code answers HTTP 200 with an empty body rather than
    an error -- treated here as a failure, not as "no transcript".
    """
    response = panopto.get(_GENERATE_SRT_PATH, params={"id": delivery_id, "language": language})
    response.raise_for_status()
    text = response.text
    if not text.strip():
        raise PanoptoError(
            f"{delivery_id}: GenerateSRT.ashx returned an empty transcript for language {language}"
        )
    return text


__all__ = ["fetch_srt", "get_delivery_info", "resolve_language"]
