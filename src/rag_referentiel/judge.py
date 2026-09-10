"""LLM-as-judge : la réponse générée est-elle conforme au référentiel ?

Le juge reçoit **toutes** les formulations validées d'une question, dans
la limite d'un plafond. La question qu'on lui pose exploite explicitement
cette pluralité : la réponse doit être équivalente à au moins une des
formulations et n'en contredire aucune.
"""

import json
import re
from typing import Protocol, runtime_checkable

from loguru import logger

from .matching import similarite_lexicale
from .schemas import Verdict

CONSIGNE_JUGE = """Tu arbitres la conformité d'une réponse produite par un
système de questions-réponses d'assurance.

On te donne une question, une réponse candidate, et une liste de
formulations déjà validées par le métier pour cette même question. Ces
formulations sont toutes correctes : elles disent la même chose de
manières différentes.

La réponse candidate est conforme si, et seulement si, elle est
équivalente sur le fond à **au moins une** des formulations validées et
qu'elle n'en contredit **aucune**. Une différence de style, de longueur ou
de mise en forme n'est pas une non-conformité. Un chiffre, un délai, une
condition ou une exclusion qui diffère en est une.

Réponds uniquement par un objet JSON :
{"conforme": true|false, "confiance": 0.0-1.0, "motif": "une phrase"}"""


@runtime_checkable
class AnswerJudge(Protocol):
    """Juge la conformité d'une réponse candidate."""

    def juger(
        self,
        question: str,
        reponse_candidate: str,
        reponses_validees: list[str],
    ) -> Verdict:
        """Rend un verdict.

        Args:
            question: Question posée.
            reponse_candidate: Réponse générée par la RAG.
            reponses_validees: Formulations validées par le métier.

        Returns:
            Le verdict.
        """
        ...


class JugeLexical:
    """Juge déterministe hors ligne, fondé sur le recouvrement lexical.

    Il n'a aucune prétention sémantique : il rend la démonstration et les
    tests exécutables sans clé d'API ni réseau.
    """

    def __init__(self, seuil: float = 0.6) -> None:
        """Initialise le juge.

        Args:
            seuil: Recouvrement lexical minimal avec l'une des
                formulations validées pour déclarer la conformité.
        """
        self.seuil = seuil

    def juger(
        self,
        question: str,
        reponse_candidate: str,
        reponses_validees: list[str],
    ) -> Verdict:
        """Rend un verdict par recouvrement lexical maximal.

        Args:
            question: Question posée (inutilisée, gardée pour l'interface).
            reponse_candidate: Réponse générée par la RAG.
            reponses_validees: Formulations validées par le métier.

        Returns:
            Le verdict.
        """
        del question
        if not reponses_validees:
            return Verdict(
                conforme=False,
                confiance=0.0,
                motif="Aucune formulation validée pour comparer.",
            )
        meilleur = max(
            similarite_lexicale(reponse_candidate, reference)
            for reference in reponses_validees
        )
        conforme = meilleur >= self.seuil
        return Verdict(
            conforme=conforme,
            confiance=round(min(1.0, meilleur), 4),
            motif=(
                f"Recouvrement lexical maximal de {meilleur:.2f} avec les "
                f"formulations validées (seuil {self.seuil:.2f})."
            ),
        )


class JugeClaude:
    """Juge adossé à l'API Claude."""

    def __init__(
        self,
        client: object,
        modele: str = "claude-sonnet-5",
        max_references: int = 5,
    ) -> None:
        """Initialise le juge.

        Args:
            client: Client `anthropic.Anthropic` déjà configuré.
            modele: Identifiant du modèle.
            max_references: Nombre maximal de formulations envoyées au
                juge, pour plafonner la taille du prompt.
        """
        self._client = client
        self.modele = modele
        self.max_references = max_references

    def juger(
        self,
        question: str,
        reponse_candidate: str,
        reponses_validees: list[str],
    ) -> Verdict:
        """Rend un verdict en interrogeant Claude.

        Args:
            question: Question posée.
            reponse_candidate: Réponse générée par la RAG.
            reponses_validees: Formulations validées par le métier.

        Returns:
            Le verdict. En cas de réponse illisible, un verdict non
            conforme de confiance nulle, qui enverra le cas en revue.
        """
        references = reponses_validees[: self.max_references]
        formulations = "\n".join(
            f"{indice}. {texte}"
            for indice, texte in enumerate(references, start=1)
        )
        message = (
            f"Question :\n{question}\n\n"
            f"Formulations validées :\n{formulations or '(aucune)'}\n\n"
            f"Réponse candidate :\n{reponse_candidate}"
        )
        reponse = self._client.messages.create(
            model=self.modele,
            max_tokens=1024,
            system=CONSIGNE_JUGE,
            messages=[{"role": "user", "content": message}],
        )
        texte = "".join(
            bloc.text for bloc in reponse.content if bloc.type == "text"
        )
        return _lire_verdict(texte)


def _lire_verdict(texte: str) -> Verdict:
    """Extrait un verdict d'une réponse de modèle.

    Args:
        texte: Réponse brute du modèle.

    Returns:
        Le verdict, ou un verdict non conforme de confiance nulle si la
        réponse n'est pas exploitable — le cas partira alors en revue.
    """
    trouve = re.search(r"\{.*\}", texte, flags=re.DOTALL)
    if trouve:
        try:
            charge = json.loads(trouve.group(0))
            return Verdict(
                conforme=bool(charge["conforme"]),
                confiance=float(charge.get("confiance", 0.5)),
                motif=str(charge.get("motif", "")),
            )
        except (ValueError, KeyError, TypeError) as erreur:
            logger.warning("Verdict illisible : {}", erreur)
    return Verdict(
        conforme=False,
        confiance=0.0,
        motif="Verdict du juge illisible : cas envoyé en revue.",
    )
