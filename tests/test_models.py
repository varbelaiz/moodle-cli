"""Model behaviour that belongs to no single endpoint: HTML conversion, timestamps."""

from __future__ import annotations

from datetime import UTC, datetime

from moodle_cli.models import Announcement, Module, Section, epoch_to_datetime, html_to_text

# Two paragraphs, a line break, a list and two entities: everything a real forum post
# throws at the converter, in one string.
POST = (
    "<p>Estimados,</p>"
    "<p>La clase del jueves se dicta en el aula <strong>S004</strong>.<br>"
    "Traer la gu&iacute;a de ejercicios.</p>"
    "<ul><li>Cap&iacute;tulo 3</li><li>Ejercicios 1 &amp; 2</li></ul>"
)


def test_html_to_text_puts_every_block_on_its_own_line_and_decodes_entities() -> None:
    assert html_to_text(POST) == (
        "Estimados,\n"
        "La clase del jueves se dicta en el aula S004.\n"
        "Traer la guía de ejercicios.\n"
        "Capítulo 3\n"
        "Ejercicios 1 & 2"
    )


def test_html_to_text_never_runs_two_blocks_into_one_word() -> None:
    assert html_to_text("<p>Estimados,</p><p>Ya tienen el examen subido.</p>") == (
        "Estimados,\nYa tienen el examen subido."
    )


def test_html_to_text_treats_a_non_breaking_space_as_a_space() -> None:
    assert html_to_text("<p>Buenas&nbsp;tardes,&nbsp;&nbsp;desocult&eacute; el material.</p>") == (
        "Buenas tardes, desoculté el material."
    )


def test_announcement_message_text_is_plain_text() -> None:
    announcement = Announcement.model_validate({"id": 1, "message": POST})
    assert announcement.message_text == html_to_text(POST)


def test_epoch_to_datetime_resolves_to_local_wall_clock() -> None:
    """The single conversion point, so no two surfaces disagree on the day of an event."""
    moment = epoch_to_datetime(1783108601)

    assert moment == datetime.fromtimestamp(1783108601, tz=UTC)
    assert moment is not None
    assert moment.strftime("%Y-%m-%d %H:%M") == (
        datetime.fromtimestamp(1783108601).strftime("%Y-%m-%d %H:%M")
    )


def test_epoch_to_datetime_reads_zero_as_unset() -> None:
    assert epoch_to_datetime(0) is None


def test_module_description_text_is_plain_text() -> None:
    """A label module's whole body lives in ``description``; ``name`` is a Moodle-side
    preview truncated to about 50 characters and cut mid-word."""
    module = Module.model_validate(
        {
            "id": 1,
            "name": "ANTES DE LA PRÓXIMA CLASE Repasar el ap...",
            "modname": "label",
            "description": "<p><strong>ANTES DE LA PRÓXIMA CLASE</strong></p>"
            "<ul><li>Repasar el apunte de la unidad 2.</li></ul>",
        }
    )
    assert module.description_text == (
        "ANTES DE LA PRÓXIMA CLASE\nRepasar el apunte de la unidad 2."
    )


def test_section_summary_text_is_plain_text() -> None:
    section = Section.model_validate(
        {"id": 1, "name": "Semana 1", "summary": "<p>1 de marzo - 7 de marzo</p>"}
    )
    assert section.summary_text == "1 de marzo - 7 de marzo"
