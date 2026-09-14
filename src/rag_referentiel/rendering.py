"""Composition of the rich text cards the business team sees in Kili.

Colours are carried by the CSS styles documented for the rich text
format. The actual rendering depends on the **server** version of the
Kili instance: nothing is guaranteed until it has been seen on screen
(see the « À vérifier au premier run » section of the README).

Every displayed string stays in French: this is the business interface.
"""

from .markdown_to_richtext import markdown_to_richtext
from .richtext import IdGenerator, document, element_node, text_node
from .schemas import Answer, ReferenceEntry, ReviewCase, Source
from .sources import document_url, format_sources, group_by_document

VALIDATED_BACKGROUND = "#e8f5e9"
CANDIDATE_BACKGROUND = "#fff3e0"
HEADER_BACKGROUND = "#eeeeee"
GREY = "#616161"

#: Les formulations validées tiennent la colonne de gauche, la réponse à
#: arbitrer celle de droite : la carte se lit comme deux colonnes, ce qui
#: sépare d'un coup d'œil ce qui fait foi de ce qui est à trancher. Le
#: texte reste aligné à gauche à l'intérieur de son bloc, bien plus
#: lisible qu'un texte ferré à droite.
#: Gabarit commun à tous les blocs encadrés de la carte : ils partagent
#: la même largeur et le même arrondi, de sorte que la question du
#: référentiel et les formulations qui en dépendent s'alignent.
BLOCK_STYLES = {
    "padding": "4px 8px",
    "borderRadius": "6px",
    "maxWidth": "65%",
}
#: Décalage de la colonne de droite, appliqué à tout ce qui décrit la
#: prédiction : la réponse à arbitrer comme les sources qu'elle cite.
RIGHT_COLUMN = {"maxWidth": "65%", "margin": "0 0 0 35%"}
#: Même décalage pour les titres de la colonne de droite, avec un espace
#: au-dessus et en dessous. Le raccourci `margin` de `RIGHT_COLUMN` met
#: les marges verticales à zéro, ce qui collait le titre à son contenu.
RIGHT_COLUMN_HEADING = {"maxWidth": "65%", "margin": "16px 0 8px 35%"}
#: Une URL est une longue chaîne sans espace : sans césure elle impose sa
#: largeur à toute la colonne. On l'autorise à se couper n'importe où,
#: pour qu'elle se replie dans sa cellule.
LINK_TEXT_STYLES = {
    "wordBreak": "break-all",
    "overflowWrap": "anywhere",
}
#: Tableau des sources : toute la largeur de sa colonne, des bordures, un
#: en-tête teinté et une ligne sur deux grisée. Aucune taille de police
#: n'y figure : Kili ignore `fontSize`, seuls les niveaux de titre
#: changent la taille du texte.
TABLE_CELL_STYLES = {"border": "1px solid #d9d9d9", "padding": "6px 10px"}
TABLE_HEADER_BACKGROUND = "#e3e8ec"
TABLE_STRIPE_BACKGROUND = "#fafafa"
#: Largeur relative et largeur minimale de chaque colonne. `width`
#: répartit la place ; `minWidth`, avec `whiteSpace: nowrap` sur
#: l'en-tête, empêche un en-tête de se couper sur deux lignes sur un écran
#: étroit — le tableau déborde alors plutôt que de se tasser. Ces deux
#: styles ne figurent pas dans la liste documentée : la sonde dit s'ils
#: sont respectés. Ignorés, ils ne cassent rien.
TABLE_COLUMNS = {
    "Document": {"width": "40%", "minWidth": "160px"},
    "Pages": {"width": "15%", "minWidth": "70px", "textAlign": "center"},
    "Lien": {"width": "45%", "minWidth": "160px"},
}
QUESTION_STYLES = {
    "backgroundColor": HEADER_BACKGROUND,
    **BLOCK_STYLES,
}
VALIDATED_STYLES = {
    "backgroundColor": VALIDATED_BACKGROUND,
    **BLOCK_STYLES,
}
CANDIDATE_STYLES = {
    "backgroundColor": CANDIDATE_BACKGROUND,
    **BLOCK_STYLES,
    **RIGHT_COLUMN,
}

REASON_LABELS = {
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


def _apply_styles(blocks: list[dict], styles: dict[str, str]) -> list[dict]:
    """Apply CSS styles to a list of block nodes.

    Args:
        blocks: Block nodes to style.
        styles: CSS styles to add.

    Returns:
        The same nodes, styled (modified in place).
    """
    for block in blocks:
        block.update(styles)
    return blocks


def _paragraph(
    text: str,
    generator: IdGenerator,
    marks: set[str] | None = None,
    styles: dict[str, str] | None = None,
) -> dict:
    """Build a single line paragraph.

    Args:
        text: Content of the paragraph.
        generator: Id generator of the document.
        marks: Marks applied to the text.
        styles: CSS styles applied to the paragraph.

    Returns:
        The paragraph node.
    """
    return element_node(
        "p", [text_node(text, generator, marks)], generator, styles
    )


def _heading(
    level: str,
    text: str,
    generator: IdGenerator,
    styles: dict[str, str] | None = None,
) -> dict:
    """Build a heading.

    Args:
        level: `h1` to `h4`.
        text: Content of the heading.
        generator: Id generator of the document.
        styles: CSS styles, to place the heading in a column.

    Returns:
        The heading node.
    """
    return element_node(
        level, [text_node(text, generator)], generator, styles
    )


def sources_table(
    sources: list[Source],
    generator: IdGenerator,
    styles: dict[str, str] | None = None,
    url_template: str | None = None,
) -> list[dict]:
    """Render sources as a `doc_id` / `pages` table.

    One row per document, however many pages it is cited for: three rows
    of `cg_auto.pdf` would only make the table harder to read. The table
    spans the width of its column — the whole card, or the column set by
    `styles` — with borders, a tinted header and striped rows;
    `TABLE_COLUMNS` sets the width of each column.

    Args:
        sources: Sources to display.
        generator: Id generator of the document.
        styles: CSS styles applied to every produced block, to place the
            whole section in a column.
        url_template: Template of the document URLs. When set, a third
            column carries the address of each document.

    Returns:
        The table followed by the copy-paste line, or a paragraph when
        there is no source.
    """
    if not sources:
        return _apply_styles(
            [
                _paragraph(
                    "Aucune source citée.",
                    generator,
                    styles={"color": GREY},
                )
            ],
            styles or {},
        )

    def cell(
        text: str,
        header: bool,
        cell_styles: dict[str, str],
        text_styles: dict[str, str] | None = None,
    ) -> dict:
        return element_node(
            "td",
            [
                text_node(
                    text,
                    generator,
                    {"bold"} if header else None,
                    text_styles,
                )
            ],
            generator,
            cell_styles,
        )

    documents = group_by_document(sources)
    urls = {
        doc_id: document_url(
            url_template, doc_id, pages[0] if pages else None
        )
        for doc_id, pages in documents
    }
    with_links = any(urls.values())

    columns = ["Document", "Pages"] + (["Lien"] if with_links else [])
    head = element_node(
        "thead",
        [
            element_node(
                "tr",
                [
                    cell(
                        name,
                        True,
                        {
                            **TABLE_CELL_STYLES,
                            **TABLE_COLUMNS[name],
                            "backgroundColor": TABLE_HEADER_BACKGROUND,
                            "whiteSpace": "nowrap",
                        },
                    )
                    for name in columns
                ],
                generator,
            )
        ],
        generator,
    )
    rows = []
    for index, (doc_id, pages) in enumerate(documents):
        row_styles = dict(TABLE_CELL_STYLES)
        if index % 2:
            row_styles["backgroundColor"] = TABLE_STRIPE_BACKGROUND
        cells = [
            cell(doc_id, False, row_styles),
            cell(
                ", ".join(str(page) for page in pages) or "—",
                False,
                {**row_styles, "textAlign": "center"},
            ),
        ]
        if with_links:
            cells.append(
                cell(
                    urls[doc_id] or "—", False, row_styles, LINK_TEXT_STYLES
                )
            )
        rows.append(element_node("tr", cells, generator))
    body = element_node("tbody", rows, generator)
    table = element_node("table", [head, body], generator)
    blocks = _apply_styles(
        [
            table,
            _paragraph(
                "À copier-coller dans « Sources corrigées », puis à "
                "modifier :",
                generator,
                styles={"color": GREY},
            ),
            _paragraph(
                format_sources(sources),
                generator,
                marks={"code"},
                styles={
                    "backgroundColor": HEADER_BACKGROUND,
                    "padding": "4px 8px",
                },
            ),
        ],
        styles or {},
    )
    # `maxWidth` ne contraint pas un tableau en CSS : un `width: 100%`
    # l'emporterait et ferait sortir le tableau de sa colonne. Il reçoit
    # donc une largeur explicite, celle de la colonne qui l'accueille, ou
    # toute la largeur quand il n'est placé dans aucune colonne.
    table["width"] = (styles or {}).get("maxWidth", "100%")
    return blocks


def answer_label(marker: str) -> str:
    """Turn an answer marker into the label shown to the annotator.

    The same label appears as the heading of the wording on the card and
    as the category of the `FORMULATION_CIBLE` and
    `FORMULATIONS_A_RETIRER` jobs, so the annotator picks what they read.

    Args:
        marker: Answer marker, `a1` to `a5`.

    Returns:
        A label such as `Réponse 2`; the marker itself if it is not
        shaped as expected.
    """
    if marker.startswith("a") and marker[1:].isdigit():
        return f"Réponse {marker[1:]}"
    return marker


def _answer_block(
    answer: Answer, generator: IdGenerator, styles: dict[str, str]
) -> list[dict]:
    """Render a validated wording, headed by its number.

    Args:
        answer: Validated wording.
        generator: Id generator of the document.
        styles: CSS styles applied to the wording itself.

    Returns:
        The block nodes of the answer.
    """
    blocks = [_heading("h3", answer_label(answer.id), generator)]
    blocks.extend(
        _apply_styles(
            markdown_to_richtext(answer.text, generator), styles
        )
    )
    provenance = (
        f"origine : {answer.origine} · auteur : {answer.auteur} · "
        f"date : {answer.date}"
    )
    if answer.run_id:
        provenance += f" · run : {answer.run_id}"
    blocks.append(_paragraph(provenance, generator, styles={"color": GREY}))
    return blocks


def render_reference_asset(
    entry: ReferenceEntry, url_template: str | None = None
) -> list[dict]:
    """Compose the rich text card of a reference entry (project A).

    Args:
        entry: Reference entry to render.
        url_template: Template of the document URLs, shown in the sources
            table when it is configured.

    Returns:
        The `json_content` of the asset.
    """
    generator = IdGenerator()
    blocks: list[dict] = [_heading("h1", entry.question, generator)]

    header = (
        f"statut : {entry.statut} · version : {entry.version} · "
        f"identifiant : {entry.question_id}"
    )
    if entry.derniere_verification:
        header += f" · vérifiée le {entry.derniere_verification}"
    blocks.append(_paragraph(header, generator, styles={"color": GREY}))

    blocks.append(_heading("h2", "Formulations validées", generator))
    if not entry.answers:
        blocks.append(
            _paragraph(
                "Aucune formulation validée pour le moment.",
                generator,
                styles={"color": GREY},
            )
        )
    for answer in entry.answers:
        blocks.extend(
            _answer_block(answer, generator, VALIDATED_STYLES)
        )

    blocks.append(_heading("h2", "Sources", generator))
    blocks.extend(
        sources_table(
            entry.sources, generator, url_template=url_template
        )
    )
    return document(blocks)


def render_review_asset(
    case: ReviewCase,
    validated_answers: list[Answer],
    candidate_question: str | None = None,
    url_template: str | None = None,
) -> list[dict]:
    """Compose the rich text card of a review case (project B).

    The LLM-as-judge verdict is **never** rendered: showing it would
    anchor the annotator on the very opinion the review audits.

    The reference question is shown right above the wordings, since those
    wordings belong to it — whether the match was certain or not, and
    even when it is word for word the question that was asked. On a brand
    new question the whole wordings section disappears.

    The validated wordings sit in the left column; the answer to
    arbitrate and the sources it cites sit in the right one — both
    describe the prediction — so that what stands as truth and what is up
    for judgement never blur together.

    Args:
        case: Review case to render.
        validated_answers: Wordings already validated for this question.
        candidate_question: Question of the matched reference entry, when
            there is one.
        url_template: Template of the document URLs, shown in the sources
            table when it is configured.

    Returns:
        The `json_content` of the asset.
    """
    generator = IdGenerator()
    blocks: list[dict] = [_heading("h1", case.question, generator)]

    blocks.append(
        element_node(
            "blockquote",
            [
                _paragraph(
                    REASON_LABELS.get(case.motif, case.motif), generator
                )
            ],
            generator,
            {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
        )
    )

    uncertain = case.motif == "APPARIEMENT_INCERTAIN"
    if candidate_question:
        blocks.append(
            _heading(
                "h2",
                "Question du référentiel proposée"
                if uncertain
                else "Question du référentiel appariée",
                generator,
            )
        )
        blocks.append(
            _paragraph(candidate_question, generator, styles=QUESTION_STYLES)
        )

    # Sur une question inédite il n'y a rien à montrer : la section
    # entière disparaît plutôt que d'afficher un « aucune ».
    if validated_answers:
        blocks.append(
            _heading(
                "h2",
                "Formulations validées pour cette question"
                if candidate_question
                else "Formulations déjà validées",
                generator,
            )
        )
        for answer in validated_answers:
            blocks.extend(
                _answer_block(answer, generator, VALIDATED_STYLES)
            )

    blocks.append(
        _heading(
            "h2",
            "Réponse générée à arbitrer",
            generator,
            RIGHT_COLUMN_HEADING,
        )
    )
    blocks.extend(
        _apply_styles(
            markdown_to_richtext(case.candidate_answer, generator),
            CANDIDATE_STYLES,
        )
    )

    blocks.append(
        _heading("h2", "Sources citées", generator, RIGHT_COLUMN_HEADING)
    )
    blocks.extend(
        sources_table(
            case.sources, generator, RIGHT_COLUMN, url_template
        )
    )
    return document(blocks)
