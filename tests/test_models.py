"""Model behaviour that belongs to no single endpoint: HTML conversion."""

from __future__ import annotations

from moodle_cli.models import html_to_text

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
