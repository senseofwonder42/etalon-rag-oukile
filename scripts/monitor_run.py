"""De la production vers la revue : traite un JSONL d'occurrences.

Chaque occurrence est appariée au référentiel, éventuellement soumise au
LLM-as-judge, et envoyée en revue métier si nécessaire. **Aucune écriture
dans le projet A à cette étape.**
"""

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from _commun import ecrire_json, lire_jsonl, parametres
from loguru import logger

from rag_referentiel.client import creer_client
from rag_referentiel.config import Parametres
from rag_referentiel.embeddings import JinaEmbeddings
from rag_referentiel.judge import AnswerJudge, JugeClaude, JugeLexical
from rag_referentiel.matching import (
    HybridMatcher,
    LexicalMatcher,
    QuestionMatcher,
)
from rag_referentiel.normalisation import calculer_question_id
from rag_referentiel.referentiel import charger_entrees
from rag_referentiel.revue import calculer_identifiants, creer_cas
from rag_referentiel.schemas import (
    CasRevue,
    EntreeReferentiel,
    OccurrenceProd,
)


def construire_matcher(
    entrees: list[EntreeReferentiel],
    config: Parametres,
    hors_ligne: bool,
) -> QuestionMatcher:
    """Construit le matcher, hybride par défaut.

    Args:
        entrees: Entrées `ACTIF` du référentiel.
        config: Paramètres d'exécution.
        hors_ligne: Si vrai, se limite à BM25, sans appel réseau.

    Returns:
        Le matcher à utiliser.

    Raises:
        RuntimeError: Si la clé Jina manque en mode hybride.
    """
    if hors_ligne:
        return LexicalMatcher(
            entrees,
            config.seuil_appariement_haut,
            config.seuil_appariement_bas,
        )
    if not config.jina_api_key:
        raise RuntimeError(
            "JINA_API_KEY absente : utiliser --hors-ligne ou renseigner "
            "la clé."
        )
    backend = JinaEmbeddings(
        cle_api=config.jina_api_key,
        modele=config.modele_embeddings,
        url_base=config.url_jina,
    )
    backend.verifier_modele()
    return HybridMatcher(
        entrees,
        backend,
        config.seuil_appariement_haut,
        config.seuil_appariement_bas,
        config.poids_lexical,
        config.poids_semantique,
    )


def construire_juge(config: Parametres, hors_ligne: bool) -> AnswerJudge:
    """Construit le juge, adossé à Claude par défaut.

    Args:
        config: Paramètres d'exécution.
        hors_ligne: Si vrai, utilise le juge lexical déterministe.

    Returns:
        Le juge à utiliser.

    Raises:
        RuntimeError: Si la clé Anthropic manque en mode connecté.
    """
    if hors_ligne:
        return JugeLexical(config.seuil_juge_lexical)
    if not config.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY absente : utiliser --hors-ligne ou "
            "renseigner la clé."
        )
    import anthropic

    return JugeClaude(
        client=anthropic.Anthropic(api_key=config.anthropic_api_key),
        modele=config.modele_juge,
        max_references=config.max_references_juge,
    )


def traiter(
    occurrences: list[dict],
    entrees: list[EntreeReferentiel],
    matcher: QuestionMatcher,
    juge: AnswerJudge,
) -> tuple[list[CasRevue], dict]:
    """Apparie, juge et prépare les cas de revue.

    Args:
        occurrences: Lignes du JSONL de production.
        entrees: Entrées `ACTIF` du référentiel.
        matcher: Matcher de questions.
        juge: LLM-as-judge.

    Returns:
        Le couple (cas de revue à créer, éléments du rapport).
    """
    par_id = {entree.question_id: entree for entree in entrees}
    debut = time.perf_counter()
    decisions = {"MATCH": 0, "INCERTAIN": 0, "NOUVELLE": 0}
    juges = 0
    conformes = 0
    ignorees = 0
    cas: list[CasRevue] = []
    envoyes: list[dict] = []

    for ligne in occurrences:
        occurrence = OccurrenceProd.model_validate(ligne)
        try:
            question_id = calculer_question_id(occurrence.question)
        except ValueError:
            logger.warning(
                "Occurrence {} sans question exploitable : ignorée.",
                occurrence.run_id,
            )
            ignorees += 1
            continue

        resultat = matcher.apparier(occurrence.question)
        decisions[resultat.decision] += 1
        motif = None
        verdict = None
        cible = question_id
        candidat = None

        if resultat.decision == "MATCH":
            entree = par_id[resultat.question_id]
            juges += 1
            verdict = juge.juger(
                occurrence.question,
                occurrence.answer_markdown,
                [reponse.text for reponse in entree.answers],
            )
            if verdict.conforme:
                conformes += 1
                continue
            motif = "DIVERGENCE"
            cible = entree.question_id
        elif resultat.decision == "INCERTAIN":
            motif = "APPARIEMENT_INCERTAIN"
            candidat = resultat.question_id
        else:
            motif = "NOUVELLE_QUESTION"

        cas.append(
            CasRevue(
                question_id=cible,
                run_id=occurrence.run_id,
                motif=motif,
                question=occurrence.question,
                candidate_answer=occurrence.answer_markdown,
                sources=occurrence.sources,
                verdict_juge=verdict,
                score_appariement=resultat.score,
                question_id_candidat=candidat,
            )
        )
        envoyes.append(
            {
                "run_id": occurrence.run_id,
                "motif": motif,
                "question_id": cible,
                "question_id_candidat": candidat,
                "score_appariement": resultat.score,
            }
        )

    duree = time.perf_counter() - debut
    traitees = len(occurrences) - ignorees
    rapport = {
        "occurrences": len(occurrences),
        "ignorees": ignorees,
        "decisions": decisions,
        "conformite": {
            "cas_juges": juges,
            "conformes": conformes,
            "taux": round(conformes / juges, 4) if juges else None,
        },
        "latence_secondes": {
            "total": round(duree, 3),
            "moyenne_par_occurrence": (
                round(duree / traitees, 4) if traitees else None
            ),
        },
        "cas_envoyes_en_revue": envoyes,
    }
    return cas, rapport


def main() -> None:
    """Point d'entrée du script de monitoring."""
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument(
        "--entree",
        type=Path,
        default=Path("data/samples/run_prod.jsonl"),
        help="JSONL des occurrences de production.",
    )
    analyseur.add_argument(
        "--projet-referentiel", required=True, help="Projet A."
    )
    analyseur.add_argument("--projet-revue", required=True, help="Projet B.")
    analyseur.add_argument(
        "--rapport",
        type=Path,
        default=None,
        help="Fichier du rapport JSON.",
    )
    analyseur.add_argument(
        "--hors-ligne",
        action="store_true",
        help="Matcher BM25 et juge lexical : aucun appel de modèle.",
    )
    arguments = analyseur.parse_args()

    config = parametres()
    kili = creer_client(config)
    entrees = charger_entrees(
        kili, arguments.projet_referentiel, statuts=("ACTIF",)
    )
    logger.info("{} entrées ACTIF chargées.", len(entrees))

    cas, rapport = traiter(
        lire_jsonl(arguments.entree),
        entrees,
        construire_matcher(entrees, config, arguments.hors_ligne),
        construire_juge(config, arguments.hors_ligne),
    )

    external_ids = calculer_identifiants(cas)
    for envoye, external_id in zip(
        rapport["cas_envoyes_en_revue"], external_ids, strict=True
    ):
        envoye["external_id"] = external_id
    creer_cas(
        kili,
        arguments.projet_revue,
        cas,
        external_ids,
        {entree.question_id: entree.answers for entree in entrees},
        {entree.question_id: entree.question for entree in entrees},
        config.taille_max_metadata,
    )

    horodatage = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rapport = {
        "horodatage": horodatage,
        "projet_referentiel": arguments.projet_referentiel,
        "projet_revue": arguments.projet_revue,
        "hors_ligne": arguments.hors_ligne,
        **rapport,
    }
    ecrire_json(
        arguments.rapport or Path(f"reports/monitoring_{horodatage}.json"),
        rapport,
    )


if __name__ == "__main__":
    main()
