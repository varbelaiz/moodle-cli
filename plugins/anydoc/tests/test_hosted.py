"""Tests for the Firecrawl Parse (hosted, OCR) conversion path.

`Firecrawl` is monkeypatched throughout: this is a paid third-party API, so nothing here
should ever reach the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from moodle_cli_anydoc import hosted as hosted_module
from moodle_cli_anydoc.hosted import HostedError, convert_hosted, resolve_firecrawl_key

# -- resolve_firecrawl_key -----------------------------------------------------------


def test_resolve_firecrawl_key_reads_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRECRAWL_KEY", "fc-test-key")

    assert resolve_firecrawl_key() == "fc-test-key"


def test_resolve_firecrawl_key_is_none_when_unset() -> None:
    assert resolve_firecrawl_key() is None


# -- convert_hosted --------------------------------------------------------------------


class _FakeDocument:
    def __init__(self, markdown: str | None) -> None:
        self.markdown = markdown


class _FakeFirecrawl:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def parse(self, source: Path, options: Any = None) -> _FakeDocument:
        return _FakeDocument("# Recovered by OCR")


def test_convert_hosted_returns_the_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted_module, "Firecrawl", _FakeFirecrawl)
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")

    assert convert_hosted(source, "fc-test-key") == "# Recovered by OCR"


def test_convert_hosted_wraps_a_failed_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class RaisingFirecrawl:
        def __init__(self, api_key: str) -> None:
            pass

        def parse(self, source: Path, options: Any = None) -> _FakeDocument:
            raise Exception("unauthorized")

    monkeypatch.setattr(hosted_module, "Firecrawl", RaisingFirecrawl)
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")

    with pytest.raises(HostedError, match="unauthorized"):
        convert_hosted(source, "bad-key")


def test_convert_hosted_raises_on_empty_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyFirecrawl:
        def __init__(self, api_key: str) -> None:
            pass

        def parse(self, source: Path, options: Any = None) -> _FakeDocument:
            return _FakeDocument(None)

    monkeypatch.setattr(hosted_module, "Firecrawl", EmptyFirecrawl)
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"%PDF-fake")

    with pytest.raises(HostedError, match="no markdown"):
        convert_hosted(source, "fc-test-key")
