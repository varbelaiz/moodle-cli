"""CLI tests, driven through the HTTP layer so the whole stack is exercised."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from moodle_cli.cli import app
from tests.conftest import BASE_URL, REST_URL, route_by_function

runner = CliRunner()

pytestmark = pytest.mark.usefixtures("configured_env")


@respx.mock
def test_courses_list_renders_a_table(courses_payload: dict[str, Any]) -> None:
    route_by_function(core_course_get_enrolled_courses_by_timeline_classification=courses_payload)

    result = runner.invoke(app, ["courses", "list"])

    assert result.exit_code == 0
    assert "IOS460 - 123246" in result.stdout
    assert "3 courses" in result.stdout


@respx.mock
def test_courses_list_json_is_machine_readable(courses_payload: dict[str, Any]) -> None:
    route_by_function(core_course_get_enrolled_courses_by_timeline_classification=courses_payload)

    result = runner.invoke(app, ["courses", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert [c["shortname"] for c in data] == ["IOS460 - 123246", "I312 - 106931", "I310 - 106934"]


@respx.mock
def test_courses_list_rejects_an_invalid_view() -> None:
    result = runner.invoke(app, ["courses", "list", "--view", "bogus"])
    assert result.exit_code != 0


@respx.mock
def test_participants_hide_emails_by_default(
    courses_payload: dict[str, Any], participants_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_enrol_get_enrolled_users=participants_payload,
    )

    result = runner.invoke(app, ["course", "participants", "IOS460"])

    assert result.exit_code == 0
    assert "Ada Docente" in result.stdout
    assert "@example.edu" not in result.stdout


@respx.mock
def test_participants_json_omits_the_email_key_by_default(
    courses_payload: dict[str, Any], participants_payload: list[dict[str, Any]]
) -> None:
    """The privacy default has to hold in the machine-readable path too."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_enrol_get_enrolled_users=participants_payload,
    )

    result = runner.invoke(app, ["course", "participants", "IOS460", "--json"])

    data = json.loads(result.stdout)
    assert all("email" not in person for person in data)


@respx.mock
def test_participants_include_emails_on_request(
    courses_payload: dict[str, Any], participants_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_enrol_get_enrolled_users=participants_payload,
    )

    result = runner.invoke(app, ["course", "participants", "IOS460", "--emails", "--json"])

    data = json.loads(result.stdout)
    assert data[0]["email"] == "ada.docente@example.edu"


@respx.mock
def test_participants_filter_by_role(
    courses_payload: dict[str, Any], participants_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_enrol_get_enrolled_users=participants_payload,
    )

    result = runner.invoke(app, ["course", "participants", "IOS460", "--role", "student", "--json"])

    data = json.loads(result.stdout)
    assert [p["fullname"] for p in data] == ["Grace Estudiante"]


@respx.mock
def test_download_dry_run_writes_nothing(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(app, ["course", "download", "IOS460", "--dry-run"])

    assert result.exit_code == 0
    assert "3 files" in result.stdout
    assert list(tmp_cwd.iterdir()) == []


@respx.mock
def test_download_writes_into_a_directory_named_after_the_course(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )
    respx.get(url__startswith=f"{BASE_URL}/webservice/pluginfile.php").mock(
        side_effect=lambda request: httpx.Response(200, content=b"x" * _expected_size(request))
    )

    result = runner.invoke(app, ["course", "download", "IOS460", "--type", "resource"])

    assert result.exit_code == 0
    written = list((tmp_cwd / "IOS460 - 123246").rglob("*.pdf"))
    assert [p.name for p in written] == ["Programa - Taller.pdf"]


def _expected_size(request: httpx.Request) -> int:
    """Serve the exact byte count the fixture declares, so validation passes."""
    return 171850 if "Programa" in str(request.url) else 2048


@respx.mock
def test_download_reports_failure_and_exits_nonzero(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    """A JSON error body served as 200 must surface as a failure, not a silent success."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )
    respx.get(url__startswith=f"{BASE_URL}/webservice/pluginfile.php").mock(
        return_value=httpx.Response(200, json={"errorcode": "missingparam", "error": "no token"})
    )

    result = runner.invoke(app, ["course", "download", "IOS460", "--type", "resource"])

    assert result.exit_code == 1
    assert "1 failed" in result.stdout
    assert list((tmp_cwd / "IOS460 - 123246").rglob("*.pdf")) == []


@respx.mock
def test_download_selects_an_exact_filename(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(
        app, ["course", "download", "IOS460", "--file", "Cap 1.pdf", "--dry-run"]
    )

    # Asserted on the count and size rather than the path: the dry-run table wraps long
    # destinations, so a filename can be split across lines.
    assert result.exit_code == 0
    assert "1 file," in result.stdout
    assert "2.0 KB" in result.stdout  # the size only "Cap 1.pdf" has


@respx.mock
def test_download_fails_loudly_on_an_unknown_filename(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    """A typo must be an error, not a silent zero-file success."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(app, ["course", "download", "IOS460", "--file", "Cap 9.pdf"])

    assert result.exit_code == 1
    assert "no such file in this course" in result.output
    assert list(tmp_cwd.iterdir()) == []


@respx.mock
def test_download_distinguishes_a_filtered_out_name_from_a_typo(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    """The two failures need different fixes, so they must not read the same."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(
        app, ["course", "download", "IOS460", "--file", "Cap 1.pdf", "--section", "1"]
    )

    assert result.exit_code == 1
    assert "excluded by --section/--type" in result.output


@respx.mock
def test_download_selects_by_glob(
    courses_payload: dict[str, Any],
    contents_payload: list[dict[str, Any]],
    tmp_cwd: Path,
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(app, ["course", "download", "IOS460", "--match", "_Car*", "--dry-run"])

    assert result.exit_code == 0
    assert "1 file," in result.stdout
    assert "Carátula" in result.stdout


@respx.mock
def test_api_error_is_reported_cleanly(courses_payload: dict[str, Any]) -> None:
    respx.post(REST_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "exception": "moodle_exception",
                "errorcode": "invalidtoken",
                "message": "Invalid token - token not found",
            },
        )
    )

    result = runner.invoke(app, ["courses", "list"])

    assert result.exit_code == 1
    assert "invalidtoken" in result.output


# -- links ---------------------------------------------------------------------------


@respx.mock
def test_contents_shows_a_url_modules_target_as_a_link(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(app, ["course", "contents", "IOS460"])

    assert result.exit_code == 0
    assert "1 link" in result.output
    assert "Slack de la Materia" in result.output
    assert "https://slack.example.com/join" in result.output


# -- search ---------------------------------------------------------------------------


@respx.mock
def test_courses_search_renders_a_table(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(app, ["courses", "search", "Material Bibliogr"])

    # Asserted on the short filename rather than the activity name or a URL: the table
    # ellipsizes the activity column and folds long links across lines.
    assert result.exit_code == 0
    assert "3 results" in result.stdout
    assert "module" in result.stdout
    assert "Cap 1.pdf" in result.stdout


@respx.mock
def test_courses_search_json_matches_the_mcp_payload(
    courses_payload: dict[str, Any], contents_payload: list[dict[str, Any]]
) -> None:
    """One search, one shape: the table and the tool must not diverge on what was found."""
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_course_get_contents=contents_payload,
    )

    result = runner.invoke(app, ["courses", "search", "Cap 1", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["truncated"] is False
    assert [r["match"] for r in data["results"]] == ["file"] * 3
    assert all(r["files"] == ["Cap 1.pdf"] for r in data["results"])
    assert all(r["section_number"] == 0 for r in data["results"])
