"""Projet A — Référentiel RAG : lecture, écriture et enrichissement.

Un asset = une question. C'est l'état de vérité : on n'y annote qu'à la
création d'une entrée et lors des campagnes de revérification. Toutes les
écritures issues de la production passent par `promouvoir_lot`.
"""

import json
import re

from loguru import logger
from pydantic import BaseModel, Field

from .config import Parametres
from .interfaces import INTERFACE_REFERENTIEL
from .labels import (
    auteur_de,
    categorie,
    categories,
    charger_metadata,
    labels_humains,
    transcription,
)
from .matching import similarite_lexicale
from .normalisation import calculer_question_id
from .rendering import rendu_asset_referentiel
from .revue import CasArbitre, lire_cas_arbitres, marquer_statut
from .schemas import (
    Answer,
    CasRevue,
    EntreeReferentiel,
    Origine,
    Source,
    Statut,
    aujourdhui,
)
from .storage import ChargeAsset, ecrire_avec_repli, preparer_charge

CHAMPS_ENTREE = [
    "externalId",
    "id",
    "jsonMetadata",
    "status",
    "labels.author.email",
    "labels.createdAt",
    "labels.jsonResponse",
    "labels.labelType",
]

_MOTIF_SOURCE = re.compile(r"^(?P<doc>[^:]+?)(?::p?(?P<page>\d+))?$", re.I)
_MOTIF_PAGE_SEULE = re.compile(r"^p\.?\s*(?P<page>\d+)$", re.I)
_SEPARATEURS_SOURCES = re.compile(r"[,\n;]")


class CibleIntrouvableError(ValueError):
    """Le repère de formulation désigné n'existe pas sur l'entrée."""


class RapportPromotion(BaseModel):
    """Compte rendu d'une exécution de la promotion."""

    cas_lus: int = 0
    promus: int = 0
    rejetes: int = 0
    ignores: int = 0
    nouvelles_entrees: int = 0
    variantes_ajoutees: int = 0
    entrees_mises_a_jour: int = 0
    entrees_revalidees: int = 0
    entrees_archivees: int = 0
    desaccords_juge_metier: int = 0
    labels_referentiel_consommes: int = 0
    formulations_remplacees: int = 0
    formulations_retirees: int = 0
    cibles_introuvables: list[str] = Field(default_factory=list)
    sources_illisibles: list[str] = Field(default_factory=list)
    sources_retirees: list[str] = Field(default_factory=list)
    details: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------- #
# Projet Kili
# --------------------------------------------------------------------- #
def creer_projet(kili: object, titre: str) -> str:
    """Crée le projet Kili du référentiel.

    Args:
        kili: Client Kili.
        titre: Titre du projet.

    Returns:
        L'identifiant du projet créé.
    """
    projet = kili.create_project(
        title=titre,
        input_type="TEXT",
        json_interface=INTERFACE_REFERENTIEL,
        description=(
            "Référentiel des questions et de leurs réponses validées."
        ),
    )
    logger.info("Projet de référentiel créé : {}", projet["id"])
    return projet["id"]


def importer_entrees(
    kili: object,
    project_id: str,
    entrees: list[EntreeReferentiel],
    taille_max_metadata: int,
) -> list[str]:
    """Importe des entrées neuves dans le référentiel.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet A.
        entrees: Entrées à créer.
        taille_max_metadata: Seuil de repli de la metadata, en octets.

    Returns:
        Les `external_id` des assets créés.
    """
    if not entrees:
        return []
    charges = [
        preparer_charge(
            entree.model_dump(),
            rendu_asset_referentiel(entree),
            taille_max_metadata,
        )
        for entree in entrees
    ]
    external_ids = [entree.question_id for entree in entrees]
    kili.append_many_to_dataset(
        project_id=project_id,
        external_id_array=external_ids,
        json_content_array=[charge.json_content for charge in charges],
        json_metadata_array=[charge.json_metadata for charge in charges],
    )
    logger.info("{} entrées importées au référentiel.", len(external_ids))
    return external_ids


def charger_entrees(
    kili: object,
    project_id: str,
    statuts: tuple[Statut, ...] | None = None,
) -> list[EntreeReferentiel]:
    """Charge les entrées du référentiel.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet A.
        statuts: Statuts à conserver ; tous si `None`.

    Returns:
        Les entrées lisibles du référentiel.
    """
    entrees: list[EntreeReferentiel] = []
    for asset in kili.assets(project_id=project_id, fields=CHAMPS_ENTREE):
        metadata = charger_metadata(asset.get("jsonMetadata"))
        if not metadata.get("question_id"):
            continue
        try:
            entree = EntreeReferentiel.model_validate(metadata)
        except ValueError as erreur:
            logger.warning(
                "Entrée illisible ({}) : {}", asset.get("externalId"), erreur
            )
            continue
        if statuts is None or entree.statut in statuts:
            entrees.append(entree)
    return entrees


def ecrire_entree(
    kili: object,
    project_id: str,
    entree: EntreeReferentiel,
    taille_max_metadata: int,
) -> None:
    """Rafraîchit la metadata et le rendu d'une entrée existante.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet A.
        entree: Entrée à écrire, version déjà incrémentée.
        taille_max_metadata: Seuil de repli de la metadata, en octets.
    """

    def ecriture(charge: ChargeAsset) -> None:
        kili.update_properties_in_assets(
            project_id=project_id,
            external_ids=[entree.question_id],
            json_metadatas=[charge.json_metadata],
            json_contents=[
                json.dumps(charge.json_content, ensure_ascii=False)
            ],
        )

    ecrire_avec_repli(
        ecriture,
        entree.model_dump(),
        rendu_asset_referentiel(entree),
        taille_max_metadata,
    )


def journaliser_variante(
    kili: object, project_id: str, question_id: str, texte: str
) -> None:
    """Écrit la piste d'audit d'une variante dans le projet A.

    La metadata porte l'état agrégé ; ce label porte l'ajout, horodaté par
    Kili. L'auteur du label est la clé d'API qui écrit ; le métier qui a
    réellement arbitré est conservé dans `answers[].auteur`.

    Le label est de type `INFERENCE` : il est écrit par un automate, et il
    ne doit pas être relu comme un arbitrage humain par la campagne de
    revérification — sans quoi chaque exécution de `promote.py` rejouerait
    les variantes déjà versées.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet A.
        question_id: Entrée concernée.
        texte: Formulation ajoutée.
    """
    kili.append_labels(
        project_id=project_id,
        asset_external_id_array=[question_id],
        json_response_array=[{"REPONSE_VALIDEE": {"text": texte}}],
        label_type="INFERENCE",
    )


# --------------------------------------------------------------------- #
# Règles pures : variantes et sources
# --------------------------------------------------------------------- #
def renumeroter(entree: EntreeReferentiel) -> None:
    """Renumérote les formulations en `a1`, `a2`, … dans l'ordre courant.

    Les repères servent de catégories au job `FORMULATION_CIBLE` du
    projet A : ils doivent rester dans la plage `a1`–`a5` fixée par le
    plafond de variantes, sans trou après un retrait.

    Args:
        entree: Entrée à renuméroter, modifiée sur place.
    """
    for numero, reponse in enumerate(entree.answers, start=1):
        reponse.id = f"a{numero}"


def selectionner_variantes(
    reponses: list[Answer], plafond: int
) -> list[Answer]:
    """Retient les formulations les plus diverses entre elles.

    La première formulation d'origine métier est toujours conservée : elle
    fait foi. Les suivantes sont choisies gloutonnement en maximisant la
    distance minimale aux formulations déjà retenues.

    Args:
        reponses: Formulations candidates.
        plafond: Nombre maximal de formulations à conserver.

    Returns:
        Les formulations retenues, dans l'ordre d'origine.
    """
    if len(reponses) <= plafond:
        return list(reponses)

    metier = next(
        (r for r in reponses if r.origine == "metier"), reponses[0]
    )
    retenues = [metier]
    restantes = [r for r in reponses if r.id != metier.id]
    while len(retenues) < plafond and restantes:
        suivante = max(
            restantes,
            key=lambda candidate: min(
                1.0 - similarite_lexicale(candidate.text, retenue.text)
                for retenue in retenues
            ),
        )
        retenues.append(suivante)
        restantes = [r for r in restantes if r.id != suivante.id]
    identifiants = {r.id for r in retenues}
    return [r for r in reponses if r.id in identifiants]


def ajouter_variante(
    entree: EntreeReferentiel,
    texte: str,
    origine: Origine,
    auteur: str,
    date: str,
    run_id: str | None,
    seuil_quasi_doublon: float,
    plafond: int,
) -> bool:
    """Ajoute une formulation à une entrée, si elle apporte quelque chose.

    Une variante trop proche d'une formulation existante est écartée. Au
    delà du plafond, on ne conserve que les formulations les plus diverses.

    Args:
        entree: Entrée à enrichir, modifiée sur place.
        texte: Formulation à ajouter.
        origine: Provenance de la formulation.
        auteur: Métier qui a arbitré la formulation.
        date: Date de l'arbitrage, au format ISO.
        run_id: Occurrence de production d'origine, le cas échéant.
        seuil_quasi_doublon: Similarité au-dessus de laquelle la variante
            est considérée comme un doublon.
        plafond: Nombre maximal de formulations conservées.

    Returns:
        `True` si la liste des formulations a changé.
    """
    texte = (texte or "").strip()
    if not texte:
        return False
    if entree.repli_texte:
        logger.error(
            "Entrée {} repliée (textes absents de la metadata) : ajout de "
            "variante refusé pour ne pas dédoublonner à l'aveugle.",
            entree.question_id,
        )
        return False
    for reponse in entree.answers:
        if similarite_lexicale(reponse.text, texte) >= seuil_quasi_doublon:
            logger.info(
                "Variante écartée (quasi-doublon de {}) sur {}.",
                reponse.id,
                entree.question_id,
            )
            return False

    avant = [reponse.text for reponse in entree.answers]
    entree.answers.append(
        Answer(
            id=f"a{len(entree.answers) + 1}",
            text=texte,
            origine=origine,
            auteur=auteur,
            date=date,
            run_id=run_id,
        )
    )
    entree.answers = selectionner_variantes(entree.answers, plafond)
    renumeroter(entree)
    return [reponse.text for reponse in entree.answers] != avant


def remplacer_formulation(
    entree: EntreeReferentiel,
    cible: str,
    texte: str,
    auteur: str,
    date: str,
    seuil_quasi_doublon: float,
) -> bool:
    """Remplace le texte d'une formulation désignée par son repère.

    Le repère et la place de la formulation sont conservés ; l'origine
    repasse à `metier` et le `run_id` est effacé, la formulation n'étant
    plus celle produite par la RAG.

    Args:
        entree: Entrée à corriger, modifiée sur place.
        cible: Repère de la formulation, `a1` à `a5`.
        texte: Texte corrigé.
        auteur: Métier qui a corrigé.
        date: Date de la correction, au format ISO.
        seuil_quasi_doublon: Similarité au-dessus de laquelle la
            correction est signalée comme redondante avec une autre
            formulation. Elle est appliquée quand même : c'est un
            arbitrage métier explicite.

    Returns:
        `True` si le texte a changé.

    Raises:
        CibleIntrouvableError: Si aucune formulation ne porte ce repère.
    """
    texte = (texte or "").strip()
    if not texte:
        return False
    if entree.repli_texte:
        logger.error(
            "Entrée {} repliée : remplacement refusé, les textes ne sont "
            "pas lisibles en metadata.",
            entree.question_id,
        )
        return False

    trouvee = next((r for r in entree.answers if r.id == cible), None)
    if trouvee is None:
        raise CibleIntrouvableError(
            f"L'entrée {entree.question_id} n'a pas de formulation "
            f"« {cible} » (repères existants : "
            f"{', '.join(r.id for r in entree.answers) or 'aucun'})."
        )
    if trouvee.text.strip() == texte:
        return False

    for autre in entree.answers:
        if autre.id == cible:
            continue
        if similarite_lexicale(autre.text, texte) >= seuil_quasi_doublon:
            logger.warning(
                "La correction de {} sur {} est très proche de {} : les "
                "deux formulations sont conservées.",
                cible,
                entree.question_id,
                autre.id,
            )

    trouvee.text = texte
    trouvee.origine = "metier"
    trouvee.auteur = auteur
    trouvee.date = date
    trouvee.run_id = None
    return True


def retirer_formulations(
    entree: EntreeReferentiel, cibles: list[str]
) -> tuple[list[str], list[str]]:
    """Retire du référentiel les formulations désignées.

    Args:
        entree: Entrée à corriger, modifiée sur place.
        cibles: Repères des formulations à retirer.

    Returns:
        Le couple (textes retirés, repères introuvables). La dernière
        formulation d'une entrée n'est jamais retirée : une entrée sans
        réponse ne servirait plus à rien.
    """
    introuvables = [
        cible
        for cible in cibles
        if not any(r.id == cible for r in entree.answers)
    ]
    a_retirer = set(cibles) - set(introuvables)
    if not a_retirer:
        return [], introuvables

    restantes = [r for r in entree.answers if r.id not in a_retirer]
    if not restantes:
        logger.warning(
            "Retrait refusé sur {} : il ne resterait aucune formulation.",
            entree.question_id,
        )
        return [], introuvables

    retires = [r.text for r in entree.answers if r.id in a_retirer]
    entree.answers = restantes
    renumeroter(entree)
    return retires, introuvables


def parser_sources(texte: str) -> tuple[list[Source], list[str]]:
    """Analyse une liste de sources au format `doc.pdf:12, autre.pdf:3`.

    Plusieurs pages d'un même document s'écrivent en répétant la page
    seule après le document : `doc1.pdf:p12, p14` donne deux sources sur
    `doc1.pdf`. Le préfixe `p` est facultatif sur une page qui suit un
    document (`doc1.pdf:12`), mais **obligatoire** sur une page seule,
    sans quoi un fragment numérique serait indiscernable d'un nom de
    document.

    L'analyse est tolérante : un fragment illisible est signalé et
    ignoré, sans faire échouer le lot.

    Args:
        texte: Saisie de l'annotateur.

    Returns:
        Le couple (sources lues, fragments illisibles).
    """
    sources: list[Source] = []
    illisibles: list[str] = []
    dernier_doc: str | None = None
    for fragment in _SEPARATEURS_SOURCES.split(texte or ""):
        nettoye = fragment.strip()
        if not nettoye:
            continue

        page_seule = _MOTIF_PAGE_SEULE.match(nettoye)
        if page_seule:
            if dernier_doc is None:
                illisibles.append(nettoye)
                continue
            sources.append(
                Source(doc_id=dernier_doc, page=int(page_seule["page"]))
            )
            continue

        trouve = _MOTIF_SOURCE.match(nettoye)
        if not trouve:
            illisibles.append(nettoye)
            continue
        page = trouve.group("page")
        dernier_doc = trouve.group("doc").strip()
        sources.append(
            Source(
                doc_id=dernier_doc,
                page=int(page) if page else None,
            )
        )
    return sources, illisibles


def fusionner_sources(
    entree: EntreeReferentiel, nouvelles: list[Source]
) -> bool:
    """Ajoute des sources absentes de l'entrée.

    Args:
        entree: Entrée à compléter, modifiée sur place.
        nouvelles: Sources à ajouter.

    Returns:
        `True` si la liste des sources a changé.
    """
    connues = {
        (source.doc_id, source.page) for source in entree.sources
    }
    ajoutees = False
    for source in nouvelles:
        if (source.doc_id, source.page) in connues:
            continue
        entree.sources.append(source)
        connues.add((source.doc_id, source.page))
        ajoutees = True
    return ajoutees


def remplacer_sources(
    entree: EntreeReferentiel, nouvelles: list[Source]
) -> bool:
    """Remplace les sources d'une entrée par une liste corrigée.

    Les `doc_version` connues sont reportées sur les sources corrigées qui
    citent le même document : l'annotateur ne saisit que `doc.pdf:page`.

    Args:
        entree: Entrée à corriger, modifiée sur place.
        nouvelles: Sources corrigées.

    Returns:
        `True` si la liste des sources a changé.
    """
    versions = {
        source.doc_id: source.doc_version
        for source in entree.sources
        if source.doc_version
    }
    corrigees = [
        source.model_copy(
            update={"doc_version": versions.get(source.doc_id)}
        )
        for source in nouvelles
    ]
    if [s.model_dump() for s in corrigees] == [
        s.model_dump() for s in entree.sources
    ]:
        return False
    entree.sources = corrigees
    return True


def creer_entree(
    question: str,
    textes: list[str],
    sources: list[Source],
    auteur: str,
    date: str,
    origine: Origine = "metier",
    run_id: str | None = None,
) -> EntreeReferentiel:
    """Construit une entrée neuve du référentiel.

    Args:
        question: Question, telle que posée.
        textes: Formulations validées, dans l'ordre.
        sources: Sources citées.
        auteur: Métier à l'origine de l'entrée.
        date: Date de création, au format ISO.
        origine: Provenance des formulations.
        run_id: Occurrence de production d'origine, le cas échéant.

    Returns:
        L'entrée, prête à être importée.
    """
    reponses = [
        Answer(
            id=f"a{indice}",
            text=texte,
            origine=origine,
            auteur=auteur,
            date=date,
            run_id=run_id,
        )
        for indice, texte in enumerate(textes, start=1)
        if texte.strip()
    ]
    return EntreeReferentiel(
        question_id=calculer_question_id(question),
        question=question,
        answers=reponses,
        sources=sources,
        derniere_verification=date,
    )


# --------------------------------------------------------------------- #
# Promotion : de la revue vers le référentiel
# --------------------------------------------------------------------- #
def _cible_promotion(arbitre: CasArbitre) -> str | None:
    """Détermine l'entrée du référentiel visée par un arbitrage.

    Args:
        arbitre: Cas de revue et son arbitrage.

    Returns:
        Le `question_id` visé, ou `None` si l'arbitrage ne permet pas de
        trancher — typiquement un cas incertain dont le job
        `MEME_QUESTION` n'a pas été rempli.
    """
    cas, label = arbitre.cas, arbitre.label
    if cas.motif != "APPARIEMENT_INCERTAIN":
        return cas.question_id
    if label.meme_question == "OUI":
        return cas.question_id_candidat or cas.question_id
    if label.meme_question == "NON":
        return cas.question_id
    logger.warning(
        "Cas incertain {} sans réponse à MEME_QUESTION : laissé en attente.",
        arbitre.external_id,
    )
    return None


def _texte_a_promouvoir(arbitre: CasArbitre) -> tuple[str | None, Origine]:
    """Détermine la formulation à verser au référentiel.

    Args:
        arbitre: Cas de revue et son arbitrage.

    Returns:
        Le couple (texte à verser ou `None`, origine à enregistrer).
    """
    label = arbitre.label
    if label.candidate_correcte == "OUI":
        return arbitre.cas.candidate_answer, "rag_valide"
    if label.candidate_correcte == "PRESQUE":
        if label.version_corrigee:
            return label.version_corrigee, "rag_corrige"
        logger.warning(
            "Cas {} arbitré « PRESQUE » sans version corrigée : rien n'est "
            "versé au référentiel.",
            arbitre.external_id,
        )
    return None, "rag_valide"


def _mettre_a_jour_sources(
    entree: EntreeReferentiel,
    arbitre: CasArbitre,
    rapport: RapportPromotion,
) -> bool:
    """Applique les corrections de sources d'un arbitrage.

    Args:
        entree: Entrée à mettre à jour, modifiée sur place.
        arbitre: Cas de revue et son arbitrage.
        rapport: Rapport à compléter des fragments illisibles.

    Returns:
        `True` si les sources ont changé.
    """
    label = arbitre.label
    if label.sources_corrigees:
        sources, illisibles = parser_sources(label.sources_corrigees)
        rapport.sources_illisibles.extend(
            f"{arbitre.external_id} : {fragment}"
            for fragment in illisibles
        )
        if sources:
            return remplacer_sources(entree, sources)
        return False
    if label.sources_pertinentes == "OUI":
        return fusionner_sources(entree, arbitre.cas.sources)
    return False


def _desaccord_juge_metier(arbitre: CasArbitre) -> bool:
    """Dit si le métier a contredit le LLM-as-judge.

    Args:
        arbitre: Cas de revue et son arbitrage.

    Returns:
        `True` si un verdict de juge existe et diverge de l'arbitrage
        métier (`OUI` vaut conforme, `NON` non conforme ; `PRESQUE` est
        traité comme un désaccord avec un juge qui disait « conforme »).
    """
    verdict = arbitre.cas.verdict_juge
    if verdict is None or arbitre.label.candidate_correcte is None:
        return False
    metier_conforme = arbitre.label.candidate_correcte == "OUI"
    return verdict.conforme != metier_conforme


def promouvoir_lot(
    kili: object,
    id_referentiel: str,
    id_revue: str,
    parametres: Parametres,
) -> RapportPromotion:
    """Transfère les arbitrages du projet B vers le projet A.

    L'opération est idempotente : un cas déjà traité n'est plus
    `EN_ATTENTE`, une variante déjà présente est écartée comme
    quasi-doublon, et la `version` n'est incrémentée que si l'état change.

    Args:
        kili: Client Kili.
        id_referentiel: Identifiant du projet A.
        id_revue: Identifiant du projet B.
        parametres: Paramètres d'exécution.

    Returns:
        Le rapport de l'exécution.
    """
    rapport = RapportPromotion()
    entrees = {
        entree.question_id: entree
        for entree in charger_entrees(kili, id_referentiel)
    }
    appliquer_labels_referentiel(
        kili, id_referentiel, entrees, parametres, rapport
    )

    arbitres = lire_cas_arbitres(kili, id_revue)
    rapport.cas_lus = len(arbitres)
    promus: list[str] = []
    rejetes: list[str] = []
    cas_par_id: dict[str, CasRevue] = {}

    for arbitre in arbitres:
        cas_par_id[arbitre.external_id] = arbitre.cas
        question_id = _cible_promotion(arbitre)
        if question_id is None:
            rapport.ignores += 1
            continue

        texte, origine = _texte_a_promouvoir(arbitre)
        date = arbitre.label.date or aujourdhui()
        if _desaccord_juge_metier(arbitre):
            rapport.desaccords_juge_metier += 1

        if question_id not in entrees:
            if texte is None:
                rejetes.append(arbitre.external_id)
                rapport.rejetes += 1
                continue
            entree = creer_entree(
                question=arbitre.cas.question,
                textes=[texte],
                sources=list(arbitre.cas.sources),
                auteur=arbitre.label.auteur,
                date=date,
                origine=origine,
                run_id=arbitre.cas.run_id,
            )
            _mettre_a_jour_sources(entree, arbitre, rapport)
            importer_entrees(
                kili,
                id_referentiel,
                [entree],
                parametres.taille_max_metadata,
            )
            journaliser_variante(
                kili, id_referentiel, entree.question_id, texte
            )
            entrees[entree.question_id] = entree
            rapport.nouvelles_entrees += 1
            rapport.variantes_ajoutees += 1
            promus.append(arbitre.external_id)
            rapport.promus += 1
            rapport.details.append(
                {
                    "external_id": arbitre.external_id,
                    "action": "nouvelle_entree",
                    "question_id": entree.question_id,
                }
            )
            continue

        entree = entrees[question_id]
        variante_ajoutee = False
        if texte is not None:
            variante_ajoutee = ajouter_variante(
                entree,
                texte=texte,
                origine=origine,
                auteur=arbitre.label.auteur,
                date=date,
                run_id=arbitre.cas.run_id,
                seuil_quasi_doublon=parametres.seuil_quasi_doublon,
                plafond=parametres.plafond_variantes,
            )
        sources_changees = _mettre_a_jour_sources(entree, arbitre, rapport)

        if variante_ajoutee or sources_changees:
            entree.version += 1
            entree.derniere_verification = date
            ecrire_entree(
                kili,
                id_referentiel,
                entree,
                parametres.taille_max_metadata,
            )
            rapport.entrees_mises_a_jour += 1
            if variante_ajoutee:
                rapport.variantes_ajoutees += 1
                journaliser_variante(
                    kili, id_referentiel, entree.question_id, texte or ""
                )

        if texte is None:
            rejetes.append(arbitre.external_id)
            rapport.rejetes += 1
        else:
            promus.append(arbitre.external_id)
            rapport.promus += 1
        rapport.details.append(
            {
                "external_id": arbitre.external_id,
                "action": "variante" if variante_ajoutee else "sans_effet",
                "question_id": entree.question_id,
            }
        )

    marquer_statut(kili, id_revue, promus, "PROMU", cas_par_id)
    marquer_statut(kili, id_revue, rejetes, "REJETE", cas_par_id)
    return rapport


def _appliquer_un_label(
    entree: EntreeReferentiel,
    label: dict,
    parametres: Parametres,
    rapport: RapportPromotion,
) -> bool:
    """Applique un arbitrage du projet A à une entrée.

    Args:
        entree: Entrée à mettre à jour, modifiée sur place.
        label: Label humain renvoyé par Kili.
        parametres: Paramètres d'exécution.
        rapport: Rapport à compléter.

    Returns:
        `True` si l'entrée a changé.
    """
    reponse = label.get("jsonResponse") or {}
    auteur = auteur_de(label)
    date = (label.get("createdAt") or "")[:10] or aujourdhui()
    change = False

    toujours_valide = categorie(reponse, "ENTREE_TOUJOURS_VALIDE")
    if toujours_valide == "OUI" and (
        entree.statut != "ACTIF" or entree.derniere_verification != date
    ):
        entree.statut = "ACTIF"
        entree.derniere_verification = date
        rapport.entrees_revalidees += 1
        change = True
    elif toujours_valide == "NON" and entree.statut != "ARCHIVE":
        entree.statut = "ARCHIVE"
        entree.derniere_verification = date
        rapport.entrees_archivees += 1
        change = True

    texte = transcription(reponse, "REPONSE_VALIDEE")
    cible = categorie(reponse, "FORMULATION_CIBLE")
    if texte and cible:
        try:
            if remplacer_formulation(
                entree,
                cible=cible,
                texte=texte,
                auteur=auteur,
                date=date,
                seuil_quasi_doublon=parametres.seuil_quasi_doublon,
            ):
                rapport.formulations_remplacees += 1
                change = True
        except CibleIntrouvableError as erreur:
            logger.warning("{}", erreur)
            rapport.cibles_introuvables.append(str(erreur))
    elif texte and ajouter_variante(
        entree,
        texte=texte,
        origine="metier",
        auteur=auteur,
        date=date,
        run_id=None,
        seuil_quasi_doublon=parametres.seuil_quasi_doublon,
        plafond=parametres.plafond_variantes,
    ):
        rapport.variantes_ajoutees += 1
        change = True
    elif cible and not texte:
        logger.warning(
            "Repère {} désigné sur {} sans texte de remplacement : "
            "ignoré.",
            cible,
            entree.question_id,
        )

    a_retirer = categories(reponse, "FORMULATIONS_A_RETIRER")
    if a_retirer:
        retires, introuvables = retirer_formulations(entree, a_retirer)
        rapport.formulations_retirees += len(retires)
        rapport.cibles_introuvables.extend(
            f"{entree.question_id} : repère {repere} introuvable"
            for repere in introuvables
        )
        change = change or bool(retires)

    sources_texte = transcription(reponse, "SOURCES_CORRIGEES")
    if sources_texte:
        sources, illisibles = parser_sources(sources_texte)
        rapport.sources_illisibles.extend(
            f"{entree.question_id} : {fragment}" for fragment in illisibles
        )
        if sources:
            retirees = {
                (s.doc_id, s.page) for s in entree.sources
            } - {(s.doc_id, s.page) for s in sources}
            if remplacer_sources(entree, sources):
                change = True
            for doc_id, page in sorted(retirees):
                logger.info(
                    "Source retirée de {} par correction : {}:{}",
                    entree.question_id,
                    doc_id,
                    page,
                )
                rapport.sources_retirees.append(
                    f"{entree.question_id} : {doc_id}:{page}"
                )
    return change


def appliquer_labels_referentiel(
    kili: object,
    project_id: str,
    entrees: dict[str, EntreeReferentiel],
    parametres: Parametres,
    rapport: RapportPromotion,
) -> None:
    """Applique les arbitrages portés par les assets du projet A.

    Tous les labels humains créés **depuis le filigrane**
    `derniere_promotion` sont appliqués, du plus ancien au plus récent :
    un métier qui corrige deux formulations enregistre deux fois, et les
    deux corrections sont reprises. Le filigrane est ensuite avancé, ce
    qui rend l'opération idempotente sans dépendre de la comparaison des
    états.

    Args:
        kili: Client Kili.
        project_id: Identifiant du projet A.
        entrees: Entrées du référentiel, par `question_id`, modifiées sur
            place.
        parametres: Paramètres d'exécution.
        rapport: Rapport à compléter.
    """
    for asset in kili.assets(project_id=project_id, fields=CHAMPS_ENTREE):
        metadata = charger_metadata(asset.get("jsonMetadata"))
        entree = entrees.get(metadata.get("question_id", ""))
        if entree is None:
            continue

        filigrane = entree.derniere_promotion or ""
        nouveaux = [
            label
            for label in labels_humains(asset.get("labels") or [])
            if (label.get("createdAt") or "") > filigrane
        ]
        if not nouveaux:
            continue

        change = False
        for label in nouveaux:
            change = (
                _appliquer_un_label(entree, label, parametres, rapport)
                or change
            )
        rapport.labels_referentiel_consommes += len(nouveaux)

        if change:
            entree.version += 1
        entree.derniere_promotion = nouveaux[-1].get("createdAt") or ""
        ecrire_entree(
            kili, project_id, entree, parametres.taille_max_metadata
        )
