import pytest

from rag_referentiel.normalisation import (
    compute_question_id,
    compute_review_external_id,
    normalize_question,
    tokenize,
)


def test_normalization_strips_accents_case_and_punctuation():
    assert normalize_question("Quel DÉLAI, déjà ?") == "quel delai deja"


def test_normalization_collapses_whitespace():
    assert normalize_question("  a\t b\n\nc  ") == "a b c"


def test_normalization_of_an_empty_question():
    assert normalize_question("  ?? !! ") == ""


def test_question_id_is_stable_across_equivalent_wordings():
    left = compute_question_id("Quel est le délai ?")
    right = compute_question_id("quel est le delai")
    assert left == right
    assert left.startswith("q_")
    assert len(left) == len("q_") + 12


def test_question_id_differs_between_different_questions():
    assert compute_question_id("délai auto") != compute_question_id(
        "délai habitation"
    )


def test_question_id_rejects_an_empty_question():
    with pytest.raises(ValueError, match="vide"):
        compute_question_id("   ...   ")


def test_review_external_id():
    assert (
        compute_review_external_id("q_abc", "run_42") == "q_abc__run_42"
    )


def test_tokenize():
    assert tokenize("Délai, déjà !") == ["delai", "deja"]
    assert tokenize("  ") == []
