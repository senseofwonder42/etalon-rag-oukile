"""Matching of a production question against the reference repository.

In production, two questions are almost never identical: matching
combines a lexical score (BM25) with a semantic score (embeddings). The
repository being small, the index is rebuilt in memory on every run;
there is no vector database.
"""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from .embeddings import EmbeddingBackend, cosine_similarity
from .normalisation import normalize_question, tokenize
from .schemas import ReferenceEntry

Decision = Literal["MATCH", "INCERTAIN", "NOUVELLE"]


class MatchResult(BaseModel):
    """Outcome of a matching attempt."""

    decision: Decision
    question_id: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    scores: dict[str, float] = Field(default_factory=dict)


@runtime_checkable
class QuestionMatcher(Protocol):
    """Matches a production question against the repository."""

    def match(self, question: str) -> MatchResult:
        """Match a question.

        Args:
            question: Raw question asked to the RAG.

        Returns:
            The matching outcome.
        """
        ...


def lexical_similarity(left: str, right: str) -> float:
    """Measure the vocabulary overlap of two texts.

    This is the Jaccard index over normalized tokens. It serves both to
    discard near-duplicate wordings and to pick the most diverse
    variants.

    Args:
        left: First text.
        right: Second text.

    Returns:
        A score in `[0, 1]`; `0` when either text is empty.
    """
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


class _Bm25Index:
    """BM25 index over the normalized questions of the repository."""

    def __init__(self, questions: list[str]) -> None:
        self._corpus = [tokenize(question) for question in questions]
        self._usable = any(self._corpus)
        if self._usable:
            self._bm25 = BM25Okapi(self._corpus)
            # Score maximal atteignable par chaque document : celui qu'il
            # obtient face à lui-même. Il sert à ramener les scores BM25,
            # non bornés, dans l'intervalle [0, 1].
            self._self_scores = [
                float(self._bm25.get_scores(doc)[index])
                for index, doc in enumerate(self._corpus)
            ]

    def scores(self, question: str) -> list[float]:
        """Score every indexed entry against a question.

        Args:
            question: Raw or normalized question.

        Returns:
            One score in `[0, 1]` per indexed entry.
        """
        if not self._usable:
            return [0.0] * len(self._corpus)
        tokens = tokenize(question)
        if not tokens:
            return [0.0] * len(self._corpus)
        raw = self._bm25.get_scores(tokens)
        result = []
        for score, self_score in zip(raw, self._self_scores, strict=True):
            if self_score <= 0.0:
                result.append(0.0)
            else:
                result.append(min(1.0, max(0.0, float(score) / self_score)))
        return result


class LexicalMatcher:
    """BM25-only matching, offline."""

    def __init__(
        self,
        entries: list[ReferenceEntry],
        threshold_high: float,
        threshold_low: float,
    ) -> None:
        """Build the lexical index.

        Args:
            entries: Reference entries to index, typically the `ACTIF`
                ones.
            threshold_high: Score above which the decision is `MATCH`.
            threshold_low: Score above which the decision is `INCERTAIN`.
        """
        self.entries = entries
        self.threshold_high = threshold_high
        self.threshold_low = threshold_low
        self._index = _Bm25Index([entry.question for entry in entries])

    def match(self, question: str) -> MatchResult:
        """Match a question by vocabulary overlap.

        Args:
            question: Raw question asked to the RAG.

        Returns:
            The matching outcome.
        """
        scores = self._index.scores(question)
        return decide(
            self.entries,
            scores,
            {"lexical": scores},
            self.threshold_high,
            self.threshold_low,
        )


class HybridMatcher:
    """Hybrid matching: BM25 plus embedding similarity."""

    def __init__(
        self,
        entries: list[ReferenceEntry],
        backend: EmbeddingBackend,
        threshold_high: float,
        threshold_low: float,
        lexical_weight: float = 0.4,
        semantic_weight: float = 0.6,
    ) -> None:
        """Build the hybrid index.

        Repository embeddings are computed once, at construction time.

        Args:
            entries: Reference entries to index.
            backend: Embedding backend.
            threshold_high: Score above which the decision is `MATCH`.
            threshold_low: Score above which the decision is `INCERTAIN`.
            lexical_weight: Weight of the BM25 score in the weighted sum.
            semantic_weight: Weight of the embedding score.

        Raises:
            ValueError: If the weights do not sum to a positive number.
        """
        if lexical_weight + semantic_weight <= 0:
            raise ValueError("La somme des poids doit être positive.")
        self.entries = entries
        self.backend = backend
        self.threshold_high = threshold_high
        self.threshold_low = threshold_low
        self.lexical_weight = lexical_weight
        self.semantic_weight = semantic_weight
        self._index = _Bm25Index([entry.question for entry in entries])
        self._vectors = backend.encode(
            [normalize_question(entry.question) for entry in entries]
        )

    def match(self, question: str) -> MatchResult:
        """Match a question by weighted sum of both scores.

        Args:
            question: Raw question asked to the RAG.

        Returns:
            The matching outcome.
        """
        lexical = self._index.scores(question)
        if self.entries:
            vector = self.backend.encode([normalize_question(question)])[0]
            semantic = [
                cosine_similarity(vector, reference)
                for reference in self._vectors
            ]
        else:
            semantic = []

        total = self.lexical_weight + self.semantic_weight
        combined = [
            (self.lexical_weight * lex + self.semantic_weight * sem) / total
            for lex, sem in zip(lexical, semantic, strict=True)
        ]
        return decide(
            self.entries,
            combined,
            {"lexical": lexical, "semantique": semantic},
            self.threshold_high,
            self.threshold_low,
        )


def decide(
    entries: list[ReferenceEntry],
    scores: list[float],
    components: dict[str, list[float]],
    threshold_high: float,
    threshold_low: float,
) -> MatchResult:
    """Turn scores into a matching decision.

    Args:
        entries: Indexed entries, in the order of the scores.
        scores: Combined score per entry.
        components: Component scores, by name, in the same order.
        threshold_high: Score above which the decision is `MATCH`.
        threshold_low: Score above which the decision is `INCERTAIN`.

    Returns:
        The matching outcome; `NOUVELLE` when the repository is empty.
    """
    if not entries or not scores:
        return MatchResult(decision="NOUVELLE", score=0.0)

    best = max(range(len(scores)), key=lambda i: scores[i])
    score = scores[best]
    detail = {
        name: round(values[best], 4)
        for name, values in components.items()
        if values
    }
    if score >= threshold_high:
        decision: Decision = "MATCH"
    elif score >= threshold_low:
        decision = "INCERTAIN"
    else:
        return MatchResult(
            decision="NOUVELLE", score=round(score, 4), scores=detail
        )
    return MatchResult(
        decision=decision,
        question_id=entries[best].question_id,
        score=round(score, 4),
        scores=detail,
    )
