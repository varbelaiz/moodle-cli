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
from tests.conftest import BASE_URL, REST_URL

runner = CliRunner()


@pytest.fixture(autouse=True)
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token in the environment keeps the CLI off the keyring and off login/token.php."""
    monkeypatch.setenv("MOODLE_URL", BASE_URL)
    monkeypatch.setenv("MOODLE_TOKEN", "test-token")


def route_by_function(**payloads: Any) -> respx.Route:
    """Dispatch the single REST endpoint on the wsfunction being requested."""

    def responder(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        for function, payload in payloads.items():
            if f"wsfunction={function}" in body:
                return httpx.Response(200, json=payload)
        return httpx.Response(200, json={"errorcode": "unmocked", "message": body})

    return respx.post(REST_URL).mock(side_effect=responder)


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


# -- links, announcements, assignments and grades ---------------------------------


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


@respx.mock
def test_announcements_strip_html_and_show_the_newest_first(
    courses_payload: dict[str, Any],
    forums_payload: list[dict[str, Any]],
    discussions_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_forum_get_forums_by_courses=forums_payload,
        mod_forum_get_forum_discussions=discussions_payload,
    )

    result = runner.invoke(app, ["course", "announcements", "IOS460"])

    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0] == "Cambio de aula para la clase del jueves (pinned)"
    assert "<strong>" not in result.output
    assert "S004" in result.output


@respx.mock
def test_announcements_report_nothing_for_a_course_without_a_news_forum(
    courses_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_forum_get_forums_by_courses=[],
    )

    result = runner.invoke(app, ["course", "announcements", "IOS460"])

    assert result.exit_code == 0
    assert "No announcements" in result.output


@respx.mock
def test_assignments_lists_due_dates(
    courses_payload: dict[str, Any], assignments_payload: dict[str, Any]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_assign_get_assignments=assignments_payload,
    )

    result = runner.invoke(app, ["course", "assignments", "IOS460"])

    assert result.exit_code == 0
    assert "Actividad semana 1" in result.output
    assert "40393" in result.output
    assert "2026-03-11" in result.output


@respx.mock
def test_assignment_status_decodes_the_grade_and_lists_submitted_files(
    submission_status_payload: dict[str, Any],
) -> None:
    route_by_function(mod_assign_get_submission_status=submission_status_payload)

    result = runner.invoke(app, ["course", "assignment-status", "40393"])

    assert result.exit_code == 0
    assert "submitted: yes" in result.output
    assert "graded: yes" in result.output
    assert "90.00\xa0/\xa0100.00" in result.output  # &nbsp; decoded to U+00A0, not literal
    assert "Entrega - Semana 1.pdf" in result.output


@respx.mock
def test_quizzes_lists_close_dates_and_attempt_limits(
    courses_payload: dict[str, Any], quizzes_payload: dict[str, Any]
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        mod_quiz_get_quizzes_by_courses=quizzes_payload,
    )

    result = runner.invoke(app, ["course", "quizzes", "IOS460"])

    assert result.exit_code == 0
    assert "Actividad semana 2" in result.output
    assert "42628" in result.output
    assert "2026-03-19" in result.output


@respx.mock
def test_quiz_status_reports_attempts_and_grade(
    quiz_attempts_payload: dict[str, Any], quiz_best_grade_payload: dict[str, Any]
) -> None:
    route_by_function(
        mod_quiz_get_user_attempts=quiz_attempts_payload,
        mod_quiz_get_user_best_grade=quiz_best_grade_payload,
    )

    result = runner.invoke(app, ["course", "quiz-status", "42628"])

    assert result.exit_code == 0
    assert "attempts used: 1" in result.output
    assert "last attempt: finished" in result.output
    assert "grade: 6.925 (pass: 4.0)" in result.output


@respx.mock
def test_quiz_status_reports_not_graded_yet_without_a_grade() -> None:
    route_by_function(
        mod_quiz_get_user_attempts={"attempts": [], "warnings": []},
        mod_quiz_get_user_best_grade={"hasgrade": False, "gradetopass": 60, "warnings": []},
    )

    result = runner.invoke(app, ["course", "quiz-status", "42628"])

    assert result.exit_code == 0
    assert "attempts used: 0" in result.output
    assert "grade: not graded yet" in result.output


@respx.mock
def test_courses_grades_shows_the_summary_across_courses(
    courses_payload: dict[str, Any],
    grades_overview_payload: dict[str, Any],
    site_info_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_webservice_get_site_info=site_info_payload,
        gradereport_overview_get_course_grades=grades_overview_payload,
    )

    result = runner.invoke(app, ["courses", "grades"])

    assert result.exit_code == 0
    assert "IOS460 - 123246" in result.output
    assert "85.00" in result.output


@respx.mock
def test_course_grades_shows_the_per_item_breakdown(
    courses_payload: dict[str, Any],
    grade_items_payload: dict[str, Any],
    site_info_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_webservice_get_site_info=site_info_payload,
        gradereport_user_get_grade_items=grade_items_payload,
    )

    result = runner.invoke(app, ["course", "grades", "IOS460"])

    assert result.exit_code == 0
    assert "TP1" in result.output
    assert "10.00" in result.output


@respx.mock
def test_course_grades_fails_loudly_without_gradebook_permission(
    courses_payload: dict[str, Any],
    site_info_payload: dict[str, Any],
) -> None:
    route_by_function(
        core_course_get_enrolled_courses_by_timeline_classification=courses_payload,
        core_webservice_get_site_info=site_info_payload,
        gradereport_user_get_grade_items={
            "exception": "moodle_exception",
            "errorcode": "nopermissiontoviewgrades",
            "message": "No se pueden ver las calificaciones.",
        },
    )

    result = runner.invoke(app, ["course", "grades", "IOS460"])

    assert result.exit_code == 1
    assert "nopermissiontoviewgrades" in result.output
