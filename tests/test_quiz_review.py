"""Quiz review parsing: one extractor per question type, run on synthetic fragments.

The fragments keep the markup and classes the real campus renders for each type, in the
graded variant and in the one whose review options hide correctness, with invented text.
"""

from __future__ import annotations

from pathlib import Path

from moodle_cli.models import ReviewAnswer, ReviewQuestion
from moodle_cli.quiz_review import parse_question


def _parse(
    fixture: str, question_type: str, state: str | None = None, mark: str | None = None
) -> ReviewQuestion:
    html = (Path(__file__).parent / "fixtures" / "quiz_review" / fixture).read_text(
        encoding="utf-8"
    )
    return parse_question(
        {
            "type": question_type,
            "html": html,
            "state": state,
            "mark": mark,
            "maxmark": 1,
            "questionnumber": "1",
        }
    )


# -- true/false and multiple choice ------------------------------------------------


def test_multichoice_strips_the_option_letter_so_options_read_like_the_right_answer() -> None:
    question = _parse("multichoice_single_graded.html", "multichoice", "gradedwrong", "0.00")

    assert question.choices == ["Canberra", "Sídney, la ciudad más poblada", "Melbourne"]
    assert question.right_answer == "La respuesta correcta es: Canberra"


def test_multichoice_keeps_the_chosen_option_feedback_on_its_answer_not_in_its_text() -> None:
    question = _parse("multichoice_single_graded.html", "multichoice", "gradedwrong", "0.00")

    assert question.answers == [
        ReviewAnswer(
            text="Sídney, la ciudad más poblada",
            correct=False,
            feedback="Es la más grande, pero no es la capital.",
        )
    ]
    assert question.prompt == "¿Cuál es la capital de Australia?"


def test_question_feedback_is_the_outcome_one_not_the_chosen_option_one() -> None:
    question = _parse("multichoice_single_graded.html", "multichoice", "gradedwrong", "0.00")

    assert question.feedback == "Respuesta incorrecta."


def test_multichoice_keeps_every_checked_option_of_a_multiple_answer_question() -> None:
    question = _parse("multichoice_multi_graded.html", "multichoice", "gradedpartial", "0.50")

    assert question.choices == ["7", "9", "11", "12"]
    assert question.answers == [
        ReviewAnswer(text="7", correct=True),
        ReviewAnswer(text="9", correct=False),
    ]


def test_multichoice_leaves_correctness_unknown_when_the_quiz_hides_it() -> None:
    question = _parse("multichoice_multi_hidden.html", "multichoice", None, "0.5")

    assert question.choices == ["El Paraná", "El Amazonas", "El Uruguay"]
    assert question.answers == [
        ReviewAnswer(text="El Paraná", correct=None),
        ReviewAnswer(text="El Uruguay", correct=None),
    ]
    assert question.right_answer is None
    assert question.feedback is None


def test_multichoice_reads_an_unanswered_question_as_no_answers() -> None:
    question = _parse("multichoice_single_unanswered.html", "multichoice", "gaveup", None)

    assert question.choices == ["42", "48"]
    assert question.answers == []
    assert question.right_answer == "La respuesta correcta es: 42"


# -- short answer and matching ----------------------------------------------------


def test_shortanswer_reads_the_typed_text_from_the_input_value() -> None:
    question = _parse("shortanswer_graded.html", "shortanswer", "gradedright", "1.00")

    assert question.prompt == "Escribir la capital de Uruguay:"
    assert question.choices == []
    assert question.answers == [ReviewAnswer(text="Montevideo", correct=True)]
    assert question.right_answer == "La respuesta correcta es: Montevideo"


def test_shortanswer_takes_its_verdict_from_the_input_class() -> None:
    question = _parse("shortanswer_wrong.html", "shortanswer", "gradedwrong", "0.00")

    assert question.answers == [ReviewAnswer(text="Punta del Este", correct=False)]


def test_shortanswer_left_blank_has_no_answers() -> None:
    question = _parse("shortanswer_blank.html", "shortanswer", "gradedwrong", "0.00")

    assert question.answers == []


def test_shortanswer_with_hidden_correctness_keeps_the_answer_unjudged() -> None:
    question = _parse("shortanswer_hidden.html", "shortanswer", None, None)

    assert question.answers == [ReviewAnswer(text="Montevideo", correct=None)]
    assert question.right_answer is None


def test_match_pairs_each_stem_with_its_selected_option() -> None:
    question = _parse("match_graded.html", "match", "gradedpartial", "0.67")

    assert question.prompt == "Relacionar cada país con su capital."
    assert question.answers == [
        ReviewAnswer(text="Perú -> Lima", correct=True),
        ReviewAnswer(text="Ecuador -> Quito", correct=True),
        ReviewAnswer(text="Paraguay -> La Paz", correct=False),
    ]
    assert question.feedback == "Respuesta parcialmente correcta."


def test_match_choices_leave_out_the_placeholder_option() -> None:
    question = _parse("match_graded.html", "match", "gradedpartial", "0.67")

    assert question.choices == ["Lima", "Quito", "Asunción", "La Paz"]


def test_match_with_hidden_correctness_skips_rows_left_on_the_placeholder() -> None:
    question = _parse("match_hidden.html", "match", None, "1.00")

    assert question.answers == [
        ReviewAnswer(text="Perú -> Lima", correct=None),
        ReviewAnswer(text="Paraguay -> Asunción", correct=None),
    ]
    assert question.right_answer is None


def test_match_left_blank_has_no_answers_but_keeps_its_choices() -> None:
    question = _parse("match_blank.html", "match", None, None)

    assert question.answers == []
    assert question.choices == ["Lima", "Quito", "Asunción", "La Paz"]


# -- fill the gaps: drop-down and drag and drop ------------------------------------


def test_gapselect_renders_each_gap_inline_with_the_selected_word() -> None:
    question = _parse("gapselect_graded.html", "gapselect", "gradedpartial")

    assert question.prompt == (
        "Completar con la opción correcta:\n"
        "El río más largo de Sudamérica es el [Amazonas], y desemboca en el océano [Pacífico]."
    )


def test_gapselect_offers_each_distinct_option_without_the_empty_placeholder() -> None:
    question = _parse("gapselect_graded.html", "gapselect", "gradedpartial")

    assert question.choices == ["Amazonas", "Atlántico", "Pacífico"]


def test_gapselect_reads_each_gaps_correctness_from_its_select() -> None:
    question = _parse("gapselect_graded.html", "gapselect", "gradedpartial")

    assert question.answers == [
        ReviewAnswer(text="Amazonas", correct=True),
        ReviewAnswer(text="Pacífico", correct=False),
    ]
    assert question.right_answer is not None and "[Atlántico]" in question.right_answer


def test_gapselect_leaves_correctness_unknown_when_the_quiz_hides_it() -> None:
    question = _parse("gapselect_hidden.html", "gapselect", None)

    assert [a.correct for a in question.answers] == [None, None, None]
    assert question.right_answer is None


def test_gapselect_renders_an_unanswered_gap_as_a_blank() -> None:
    question = _parse("gapselect_hidden.html", "gapselect", None)

    assert question.prompt == (
        "La capital de Bolivia es ( [LIMA la ciudad] ) y la de Ecuador es [Quito].\n"
        "Montevideo es la capital de\n"
        "- [___]"
    )
    assert [a.text for a in question.answers] == ["LIMA la ciudad", "Quito", ""]


def test_ddwtos_renders_each_gap_inline_with_the_placed_choice() -> None:
    question = _parse("ddwtos_graded.html", "ddwtos", "gradedpartial")

    assert question.prompt == (
        "La cordillera de [los Andes] recorre el oeste del continente, [mientras, que] "
        "la llanura pampeana ocupa el centro.\n"
        "Su pico más alto es el [___]."
    )


def test_ddwtos_maps_each_place_to_the_choice_numbered_within_its_group() -> None:
    question = _parse("ddwtos_graded.html", "ddwtos", "gradedpartial")

    assert [a.text for a in question.answers] == ["los Andes", "mientras, que", ""]


def test_ddwtos_offers_the_whole_draggable_pool() -> None:
    question = _parse("ddwtos_graded.html", "ddwtos", "gradedpartial")

    assert question.choices == ["los Andes", "Aconcagua", "mientras que", "mientras, que"]


def test_ddwtos_reads_each_gaps_correctness_from_the_icon_after_its_drop() -> None:
    question = _parse("ddwtos_graded.html", "ddwtos", "gradedpartial")

    assert [a.correct for a in question.answers] == [True, False, False]


def test_ddwtos_drops_the_space_moodle_renders_after_each_drop() -> None:
    question = _parse("ddwtos_hidden.html", "ddwtos", None)

    assert question.prompt == (
        "Clasificar cada país según su continente:\n"
        "Kenia es un país de ( [ÁFRICA] ).\n"
        "Chile es un país de [América del Sur].\n"
        "Perú es un país de [América del Sur].\n"
        "Egipto es un país de [___]."
    )


def test_ddwtos_reuses_an_infinite_choice_and_hides_unknown_correctness() -> None:
    question = _parse("ddwtos_hidden.html", "ddwtos", None)

    assert question.answers == [
        ReviewAnswer(text="ÁFRICA"),
        ReviewAnswer(text="América del Sur"),
        ReviewAnswer(text="América del Sur"),
        ReviewAnswer(text=""),
    ]
    assert question.choices == ["ÁFRICA", "América del Sur"]
