"""Appariement d'une question de production au référentiel.

En production, deux questions ne sont presque jamais identiques :
l'appariement combine un score lexical (BM25) et un score sémantique
(embeddings). Le référentiel étant petit, l'index est reconstruit en
mémoire à chaque exécution ; il n'y a pas de base vectorielle.
"""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field
from rank_bm25 import BM25Okapi

from .embeddings import EmbeddingBackend, similarite_cosinus
from .normalisation import normaliser_question, tokeniser
from .schemas import EntreeReferentiel

Decision = Literal["MATCH", "INCERTAIN", "NOUVELLE"]


class MatchResult(BaseModel):
    """Résultat d'un appariement."""

    decision: Decision
    question_id: str | None = None
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    scores: dict[str, float] = Field(default_factory=dict)


@runtime_checkable
class QuestionMatcher(Protocol):
    """Apparie une question posée en production au référentiel."""

    def apparier(self, question: str) -> MatchResult:
        """Apparie une question.

        Args:
            question: Question brute posée à la RAG.

        Returns:
            Le résultat de l'appariement.
        """
        ...


def similarite_lexicale(gauche: str, droite: str) -> float:
    """Mesure le recouvrement de vocabulaire de deux textes.

    C'est l'indice de Jaccard sur les jetons normalisés. Cette mesure sert
    aussi bien à écarter les quasi-doublons de formulation qu'à choisir les
    variantes les plus diverses.

    Args:
        gauche: Premier texte.
        droite: Second texte.

    Returns:
        Un score dans `[0, 1]` ; `0` si l'un des textes est vide.
    """
    jetons_g = set(tokeniser(gauche))
    jetons_d = set(tokeniser(droite))
    if not jetons_g or not jetons_d:
        return 0.0
    return len(jetons_g & jetons_d) / len(jetons_g | jetons_d)


class _IndexBm25:
    """Index BM25 des questions normalisées du référentiel."""

    def __init__(self, questions: list[str]) -> None:
        self._corpus = [tokeniser(question) for question in questions]
        self._utilisable = any(self._corpus)
        if self._utilisable:
            self._bm25 = BM25Okapi(self._corpus)
            # Score maximal atteignable par chaque document : celui qu'il
            # obtient face à lui-même. Il sert à ramener les scores BM25,
            # non bornés, dans l'intervalle [0, 1].
            self._auto_scores = [
                float(self._bm25.get_scores(document)[indice])
                for indice, document in enumerate(self._corpus)
            ]

    def scores(self, question: str) -> list[float]:
        """Score chaque entrée du référentiel face à une question.

        Args:
            question: Question brute ou normalisée.

        Returns:
            Un score normalisé dans `[0, 1]` par entrée indexée.
        """
        if not self._utilisable:
            return [0.0] * len(self._corpus)
        jetons = tokeniser(question)
        if not jetons:
            return [0.0] * len(self._corpus)
        bruts = self._bm25.get_scores(jetons)
        resultat = []
        for brut, auto in zip(bruts, self._auto_scores, strict=True):
            if auto <= 0.0:
                resultat.append(0.0)
            else:
                resultat.append(min(1.0, max(0.0, float(brut) / auto)))
        return resultat


class LexicalMatcher:
    """Appariement BM25 seul, hors ligne."""

    def __init__(
        self,
        entrees: list[EntreeReferentiel],
        seuil_haut: float,
        seuil_bas: float,
    ) -> None:
        """Construit l'index lexical.

        Args:
            entrees: Entrées du référentiel à indexer (typiquement les
                entrées `ACTIF`).
            seuil_haut: Score au-dessus duquel la décision est `MATCH`.
            seuil_bas: Score au-dessus duquel la décision est `INCERTAIN`.
        """
        self.entrees = entrees
        self.seuil_haut = seuil_haut
        self.seuil_bas = seuil_bas
        self._index = _IndexBm25(
            [entree.question for entree in entrees]
        )

    def apparier(self, question: str) -> MatchResult:
        """Apparie une question par recouvrement lexical.

        Args:
            question: Question brute posée à la RAG.

        Returns:
            Le résultat de l'appariement.
        """
        scores = self._index.scores(question)
        return decider(
            self.entrees,
            scores,
            {"lexical": scores},
            self.seuil_haut,
            self.seuil_bas,
        )


class HybridMatcher:
    """Appariement hybride : BM25 et similarité d'embeddings."""

    def __init__(
        self,
        entrees: list[EntreeReferentiel],
        backend: EmbeddingBackend,
        seuil_haut: float,
        seuil_bas: float,
        poids_lexical: float = 0.4,
        poids_semantique: float = 0.6,
    ) -> None:
        """Construit l'index hybride.

        Les embeddings du référentiel sont calculés une fois à la
        construction.

        Args:
            entrees: Entrées du référentiel à indexer.
            backend: Backend d'embeddings.
            seuil_haut: Score au-dessus duquel la décision est `MATCH`.
            seuil_bas: Score au-dessus duquel la décision est `INCERTAIN`.
            poids_lexical: Poids du score BM25 dans la somme pondérée.
            poids_semantique: Poids du score d'embeddings.

        Raises:
            ValueError: Si la somme des poids n'est pas strictement
                positive.
        """
        if poids_lexical + poids_semantique <= 0:
            raise ValueError("La somme des poids doit être positive.")
        self.entrees = entrees
        self.backend = backend
        self.seuil_haut = seuil_haut
        self.seuil_bas = seuil_bas
        self.poids_lexical = poids_lexical
        self.poids_semantique = poids_semantique
        self._index = _IndexBm25([entree.question for entree in entrees])
        self._vecteurs = backend.encoder(
            [normaliser_question(entree.question) for entree in entrees]
        )

    def apparier(self, question: str) -> MatchResult:
        """Apparie une question par somme pondérée des deux scores.

        Args:
            question: Question brute posée à la RAG.

        Returns:
            Le résultat de l'appariement.
        """
        lexicaux = self._index.scores(question)
        if self.entrees:
            vecteur = self.backend.encoder(
                [normaliser_question(question)]
            )[0]
            semantiques = [
                similarite_cosinus(vecteur, reference)
                for reference in self._vecteurs
            ]
        else:
            semantiques = []

        total = self.poids_lexical + self.poids_semantique
        combines = [
            (self.poids_lexical * lex + self.poids_semantique * sem) / total
            for lex, sem in zip(lexicaux, semantiques, strict=True)
        ]
        return decider(
            self.entrees,
            combines,
            {"lexical": lexicaux, "semantique": semantiques},
            self.seuil_haut,
            self.seuil_bas,
        )


def decider(
    entrees: list[EntreeReferentiel],
    scores: list[float],
    composants: dict[str, list[float]],
    seuil_haut: float,
    seuil_bas: float,
) -> MatchResult:
    """Transforme des scores en décision d'appariement.

    Args:
        entrees: Entrées indexées, dans l'ordre des scores.
        scores: Score combiné par entrée.
        composants: Scores composants, par nom, dans le même ordre.
        seuil_haut: Score au-dessus duquel la décision est `MATCH`.
        seuil_bas: Score au-dessus duquel la décision est `INCERTAIN`.

    Returns:
        Le résultat de l'appariement ; `NOUVELLE` si le référentiel est
        vide.
    """
    if not entrees or not scores:
        return MatchResult(decision="NOUVELLE", score=0.0)

    meilleur = max(range(len(scores)), key=lambda i: scores[i])
    score = scores[meilleur]
    detail = {
        nom: round(valeurs[meilleur], 4)
        for nom, valeurs in composants.items()
        if valeurs
    }
    if score >= seuil_haut:
        decision: Decision = "MATCH"
    elif score >= seuil_bas:
        decision = "INCERTAIN"
    else:
        return MatchResult(
            decision="NOUVELLE", score=round(score, 4), scores=detail
        )
    return MatchResult(
        decision=decision,
        question_id=entrees[meilleur].question_id,
        score=round(score, 4),
        scores=detail,
    )
