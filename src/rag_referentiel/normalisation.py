"""Normalisation des questions et calcul de leur identifiant stable.

La normalisation est volontairement une fonction pure, sans dépendance :
c'est elle qui garantit qu'une même question posée deux fois retombe sur
le même `question_id`, et donc sur le même asset Kili.
"""

import hashlib
import re
import unicodedata

_PONCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_ESPACES = re.compile(r"\s+")

LONGUEUR_HACHE = 12


def normaliser_question(question: str) -> str:
    """Normalise une question pour la comparaison et le hachage.

    Les traitements appliqués, dans l'ordre : suppression des accents,
    passage en minuscules, suppression de la ponctuation, réduction des
    espaces multiples et suppression des espaces de bord.

    Args:
        question: Question brute, telle que posée à la RAG.

    Returns:
        La question normalisée. Chaîne vide si la question ne contient
        aucun caractère significatif.
    """
    sans_accent = unicodedata.normalize("NFKD", question)
    sans_accent = "".join(
        c for c in sans_accent if not unicodedata.combining(c)
    )
    minuscules = sans_accent.lower()
    sans_ponctuation = _PONCTUATION.sub(" ", minuscules)
    return _ESPACES.sub(" ", sans_ponctuation).strip()


def calculer_question_id(question: str) -> str:
    """Calcule l'identifiant d'une question du référentiel.

    Args:
        question: Question brute ou déjà normalisée.

    Returns:
        Identifiant de la forme `q_<12 caractères hexadécimaux>`.

    Raises:
        ValueError: Si la question est vide une fois normalisée.
    """
    normalisee = normaliser_question(question)
    if not normalisee:
        raise ValueError("Question vide après normalisation.")
    empreinte = hashlib.sha1(normalisee.encode("utf-8")).hexdigest()
    return f"q_{empreinte[:LONGUEUR_HACHE]}"


def calculer_external_id_revue(question_id: str, run_id: str) -> str:
    """Calcule l'external_id d'un cas de revue du projet B.

    Args:
        question_id: Identifiant de la question (référentiel ou candidat).
        run_id: Identifiant de l'occurrence de production.

    Returns:
        Identifiant de la forme `<question_id>__<run_id>`.
    """
    return f"{question_id}__{run_id}"


def tokeniser(texte: str) -> list[str]:
    """Découpe un texte normalisé en jetons.

    Args:
        texte: Texte brut ou normalisé.

    Returns:
        La liste des jetons du texte normalisé.
    """
    normalise = normaliser_question(texte)
    return normalise.split() if normalise else []
