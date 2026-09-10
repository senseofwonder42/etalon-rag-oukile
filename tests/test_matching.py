import pytest

from rag_referentiel.embeddings import FakeEmbeddings, cosine_similarity
from rag_referentiel.matching import (
    HybridMatcher,
    LexicalMatcher,
    decide,
    lexical_similarity,
)
from rag_referentiel.schemas import ReferenceEntry

QUESTIONS = [
    "Quel est le délai de déclaration d'un sinistre auto ?",
    "Comment résilier mon contrat d'assurance habitation ?",
    "Quelle est la franchise en cas de bris de glace ?",
]


def entries():
    return [
        ReferenceEntry(question_id=f"q_{i}", question=question)
        for i, question in enumerate(QUESTIONS)
    ]


def test_match_on_an_identical_question():
    matcher = LexicalMatcher(entries(), 0.72, 0.45)
    result = matcher.match(QUESTIONS[0])
    assert result.decision == "MATCH"
    assert result.question_id == "q_0"
    assert result.score == pytest.approx(1.0)


def test_new_on_an_unseen_question():
    matcher = LexicalMatcher(entries(), 0.72, 0.45)
    result = matcher.match("Comment ajouter un conducteur ?")
    assert result.decision == "NOUVELLE"
    assert result.question_id is None


def test_uncertain_between_the_two_thresholds():
    matcher = LexicalMatcher(entries(), 0.72, 0.45)
    result = matcher.match("Comment résilier un contrat ?")
    assert result.decision == "INCERTAIN"
    assert 0.45 <= result.score < 0.72


def test_an_empty_repository_yields_new():
    matcher = LexicalMatcher([], 0.72, 0.45)
    result = matcher.match("Une question quelconque ?")
    assert result.decision == "NOUVELLE"
    assert result.score == 0.0


def test_an_empty_question_yields_new():
    matcher = LexicalMatcher(entries(), 0.72, 0.45)
    assert matcher.match("  ").decision == "NOUVELLE"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.9, "MATCH"),
        (0.7, "MATCH"),
        (0.6999, "INCERTAIN"),
        (0.4, "INCERTAIN"),
        (0.3999, "NOUVELLE"),
    ],
)
def test_threshold_boundaries(score, expected):
    result = decide(entries()[:1], [score], {"lexical": [score]}, 0.7, 0.4)
    assert result.decision == expected


def test_hybrid_combines_both_scores():
    matcher = HybridMatcher(
        entries(), FakeEmbeddings(), 0.72, 0.45, 0.4, 0.6
    )
    result = matcher.match(QUESTIONS[2])
    assert result.decision == "MATCH"
    assert set(result.scores) == {"lexical", "semantique"}
    expected = (
        0.4 * result.scores["lexical"] + 0.6 * result.scores["semantique"]
    )
    assert result.score == pytest.approx(expected, abs=1e-3)


def test_hybrid_rejects_null_weights():
    with pytest.raises(ValueError, match="poids"):
        HybridMatcher(entries(), FakeEmbeddings(), 0.7, 0.4, 0.0, 0.0)


def test_hybrid_on_an_empty_repository():
    matcher = HybridMatcher([], FakeEmbeddings(), 0.72, 0.45)
    assert matcher.match("Une question ?").decision == "NOUVELLE"


def test_fake_embeddings_are_deterministic():
    backend = FakeEmbeddings()
    assert backend.encode(["délai auto"]) == backend.encode(["délai auto"])
    close = cosine_similarity(
        backend.encode(["délai de déclaration sinistre"])[0],
        backend.encode(["délai de déclaration"])[0],
    )
    far = cosine_similarity(
        backend.encode(["délai de déclaration sinistre"])[0],
        backend.encode(["résiliation du contrat habitation"])[0],
    )
    assert close > far


def test_lexical_similarity():
    assert lexical_similarity("délai auto", "delai auto") == 1.0
    assert lexical_similarity("délai auto", "") == 0.0
    assert 0.0 < lexical_similarity("délai auto", "délai moto") < 1.0
