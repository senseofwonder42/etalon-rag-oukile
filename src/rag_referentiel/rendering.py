"""Composition des cartes rich text vues par le métier dans Kili.

Les couleurs sont portées par les styles CSS documentés pour le format
rich text. Le rendu réel dépend de la version **serveur** de l'instance
Kili : rien n'est garanti tant que ce n'est pas vu à l'écran (voir la
section « À vérifier au premier run » du README).
"""

from .markdown_to_richtext import markdown_vers_richtext
from .richtext import (
    GenerateurIds,
    document,
    noeud_element,
    noeud_texte,
)
from .schemas import Answer, CasRevue, EntreeReferentiel, Source

FOND_VALIDE = "#e8f5e9"
FOND_CANDIDATE = "#fff3e0"
FOND_ENTETE = "#eeeeee"
GRIS = "#616161"

LIBELLES_MOTIF = {
    "NOUVELLE_QUESTION": (
        "Question inédite : elle n'existe pas encore dans le référentiel."
    ),
    "DIVERGENCE": (
        "La réponse générée diverge des formulations déjà validées."
    ),
    "APPARIEMENT_INCERTAIN": (
        "La question ressemble à une entrée du référentiel sans certitude : "
        "commencer par répondre à « Même question ? »."
    ),
    "REVERIFICATION_DOC": (
        "Un document source a changé : l'entrée est à revérifier."
    ),
}


def _appliquer_styles(blocs: list[dict], styles: dict[str, str]) -> list[dict]:
    """Applique des styles CSS à une liste de nœuds de bloc.

    Args:
        blocs: Nœuds de bloc à styler.
        styles: Styles CSS à ajouter.

    Returns:
        Les mêmes nœuds, stylés (modifiés sur place).
    """
    for bloc in blocs:
        bloc.update(styles)
    return blocs


def _paragraphe(
    texte: str,
    generateur: GenerateurIds,
    marques: set[str] | None = None,
    styles: dict[str, str] | None = None,
) -> dict:
    """Construit un paragraphe d'une seule ligne.

    Args:
        texte: Contenu du paragraphe.
        generateur: Générateur d'identifiants du document.
        marques: Marques appliquées au texte.
        styles: Styles CSS appliqués au paragraphe.

    Returns:
        Le nœud paragraphe.
    """
    return noeud_element(
        "p",
        [noeud_texte(texte, generateur, marques)],
        generateur,
        styles,
    )


def _titre(niveau: str, texte: str, generateur: GenerateurIds) -> dict:
    """Construit un titre.

    Args:
        niveau: `h1` à `h4`.
        texte: Contenu du titre.
        generateur: Générateur d'identifiants du document.

    Returns:
        Le nœud titre.
    """
    return noeud_element(
        niveau, [noeud_texte(texte, generateur)], generateur
    )


def _table_sources(
    sources: list[Source], generateur: GenerateurIds
) -> list[dict]:
    """Rend les sources sous forme de tableau `doc_id` / `page`.

    Args:
        sources: Sources à afficher.
        generateur: Générateur d'identifiants du document.

    Returns:
        Le tableau, ou un paragraphe si la liste est vide.
    """
    if not sources:
        return [
            _paragraphe(
                "Aucune source citée.", generateur, styles={"color": GRIS}
            )
        ]

    def cellule(texte: str, entete: bool) -> dict:
        return noeud_element(
            "td",
            [
                noeud_texte(
                    texte, generateur, {"bold"} if entete else None
                )
            ],
            generateur,
            {"backgroundColor": FOND_ENTETE} if entete else None,
        )

    entete = noeud_element(
        "thead",
        [
            noeud_element(
                "tr",
                [cellule("Document", True), cellule("Page", True)],
                generateur,
            )
        ],
        generateur,
    )
    lignes = [
        noeud_element(
            "tr",
            [
                cellule(source.doc_id, False),
                cellule(
                    "—" if source.page is None else str(source.page), False
                ),
            ],
            generateur,
        )
        for source in sources
    ]
    corps = noeud_element("tbody", lignes, generateur)
    return [noeud_element("table", [entete, corps], generateur)]


def _bloc_reponse(
    reponse: Answer, generateur: GenerateurIds, fond: str
) -> list[dict]:
    """Rend une formulation validée et sa provenance.

    Args:
        reponse: Formulation validée.
        generateur: Générateur d'identifiants du document.
        fond: Couleur de fond du texte de la réponse.

    Returns:
        Les nœuds de bloc de la réponse.
    """
    blocs = _appliquer_styles(
        markdown_vers_richtext(reponse.text, generateur),
        {"backgroundColor": fond, "padding": "4px 8px"},
    )
    provenance = (
        f"origine : {reponse.origine} · auteur : {reponse.auteur} · "
        f"date : {reponse.date}"
    )
    if reponse.run_id:
        provenance += f" · run : {reponse.run_id}"
    blocs.append(
        _paragraphe(provenance, generateur, styles={"color": GRIS})
    )
    return blocs


def rendu_asset_referentiel(entree: EntreeReferentiel) -> list[dict]:
    """Compose la carte rich text d'une entrée du référentiel (projet A).

    Args:
        entree: Entrée du référentiel à rendre.

    Returns:
        Le `json_content` de l'asset.
    """
    generateur = GenerateurIds()
    blocs: list[dict] = [_titre("h1", entree.question, generateur)]

    entete = (
        f"statut : {entree.statut} · version : {entree.version} · "
        f"identifiant : {entree.question_id}"
    )
    if entree.derniere_verification:
        entete += f" · vérifiée le {entree.derniere_verification}"
    blocs.append(_paragraphe(entete, generateur, styles={"color": GRIS}))

    blocs.append(_titre("h2", "Formulations validées", generateur))
    if not entree.answers:
        blocs.append(
            _paragraphe(
                "Aucune formulation validée pour le moment.",
                generateur,
                styles={"color": GRIS},
            )
        )
    for reponse in entree.answers:
        blocs.extend(_bloc_reponse(reponse, generateur, FOND_VALIDE))

    blocs.append(_titre("h2", "Sources", generateur))
    blocs.extend(_table_sources(entree.sources, generateur))
    return document(blocs)


def rendu_asset_revue(
    cas: CasRevue,
    reponses_validees: list[Answer],
    question_candidate: str | None = None,
) -> list[dict]:
    """Compose la carte rich text d'un cas de revue (projet B).

    Le verdict du LLM-as-judge n'est **jamais** rendu : l'afficher
    ancrerait l'annotateur sur l'avis que la revue cherche à auditer.

    Args:
        cas: Cas de revue à rendre.
        reponses_validees: Formulations déjà validées pour cette question.
        question_candidate: Question du référentiel proposée par
            l'appariement, à afficher quand le motif est
            `APPARIEMENT_INCERTAIN`.

    Returns:
        Le `json_content` de l'asset.
    """
    generateur = GenerateurIds()
    blocs: list[dict] = [_titre("h1", cas.question, generateur)]

    blocs.append(
        noeud_element(
            "blockquote",
            [
                _paragraphe(
                    LIBELLES_MOTIF.get(cas.motif, cas.motif), generateur
                )
            ],
            generateur,
            {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
        )
    )

    blocs.append(_titre("h2", "Formulations déjà validées", generateur))
    if not reponses_validees:
        blocs.append(
            _paragraphe(
                "Aucune : cette question n'est pas encore au référentiel.",
                generateur,
                styles={"color": GRIS},
            )
        )
    for reponse in reponses_validees:
        blocs.extend(_bloc_reponse(reponse, generateur, FOND_VALIDE))

    blocs.append(_titre("h2", "Réponse générée à arbitrer", generateur))
    blocs.extend(
        _appliquer_styles(
            markdown_vers_richtext(cas.candidate_answer, generateur),
            {"backgroundColor": FOND_CANDIDATE, "padding": "4px 8px"},
        )
    )

    blocs.append(_titre("h2", "Sources citées", generateur))
    blocs.extend(_table_sources(cas.sources, generateur))

    if cas.motif == "APPARIEMENT_INCERTAIN" and question_candidate:
        blocs.append(
            _titre("h2", "Question du référentiel proposée", generateur)
        )
        blocs.append(
            _paragraphe(
                question_candidate,
                generateur,
                styles={
                    "backgroundColor": FOND_ENTETE,
                    "padding": "4px 8px",
                },
            )
        )
    return document(blocs)
