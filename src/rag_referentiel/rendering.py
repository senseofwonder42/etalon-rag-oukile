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
from .sources import format_sources

VALIDATED_BACKGROUND = "#e8f5e9"
CANDIDATE_BACKGROUND = "#fff3e0"
HEADER_BACKGROUND = "#eeeeee"
GREY = "#616161"

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


def _heading(level: str, text: str, generator: IdGenerator) -> dict:
    """Build a heading.

    Args:
        level: `h1` to `h4`.
        text: Content of the heading.
        generator: Id generator of the document.

    Returns:
        The heading node.
    """
    return element_node(level, [text_node(text, generator)], generator)


def _sources_table(
    sources: list[Source], generator: IdGenerator
) -> list[dict]:
    """Render sources as a `doc_id` / `page` table.

    Args:
        sources: Sources to display.
        generator: Id generator of the document.

    Returns:
        The table, or a paragraph when the list is empty.
    """
    if not sources:
        return [
            _paragraph(
                "Aucune source citée.", generator, styles={"color": GREY}
            )
        ]

    def cell(text: str, header: bool) -> dict:
        return element_node(
            "td",
            [text_node(text, generator, {"bold"} if header else None)],
            generator,
            {"backgroundColor": HEADER_BACKGROUND} if header else None,
        )

    head = element_node(
        "thead",
        [
            element_node(
                "tr",
                [cell("Document", True), cell("Page", True)],
                generator,
            )
        ],
        generator,
    )
    rows = [
        element_node(
            "tr",
            [
                cell(source.doc_id, False),
                cell("—" if source.page is None else str(source.page), False),
            ],
            generator,
        )
        for source in sources
    ]
    body = element_node("tbody", rows, generator)
    return [
        element_node("table", [head, body], generator),
        _paragraph(
            "À copier-coller dans « Sources corrigées », puis à modifier :",
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
    ]


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
    answer: Answer, generator: IdGenerator, background: str
) -> list[dict]:
    """Render a validated wording, headed by its number.

    Args:
        answer: Validated wording.
        generator: Id generator of the document.
        background: Background colour of the answer text.

    Returns:
        The block nodes of the answer.
    """
    blocks = [_heading("h3", answer_label(answer.id), generator)]
    blocks.extend(
        _apply_styles(
            markdown_to_richtext(answer.text, generator),
            {"backgroundColor": background, "padding": "4px 8px"},
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


def render_reference_asset(entry: ReferenceEntry) -> list[dict]:
    """Compose the rich text card of a reference entry (project A).

    Args:
        entry: Reference entry to render.

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
        blocks.extend(_answer_block(answer, generator, VALIDATED_BACKGROUND))

    blocks.append(_heading("h2", "Sources", generator))
    blocks.extend(_sources_table(entry.sources, generator))
    return document(blocks)


def render_review_asset(
    case: ReviewCase,
    validated_answers: list[Answer],
    candidate_question: str | None = None,
) -> list[dict]:
    """Compose the rich text card of a review case (project B).

    The LLM-as-judge verdict is **never** rendered: showing it would
    anchor the annotator on the very opinion the review audits.

    On an uncertain match the proposed reference question is shown right
    above the wordings, since those wordings belong to it. On a brand new
    question the whole wordings section disappears.

    Args:
        case: Review case to render.
        validated_answers: Wordings already validated for this question.
        candidate_question: Reference question proposed by the matching,
            to display when the reason is `APPARIEMENT_INCERTAIN`.

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

    if case.motif == "APPARIEMENT_INCERTAIN" and candidate_question:
        blocks.append(
            _heading("h2", "Question du référentiel proposée", generator)
        )
        blocks.append(
            _paragraph(
                candidate_question,
                generator,
                styles={
                    "backgroundColor": HEADER_BACKGROUND,
                    "padding": "4px 8px",
                },
            )
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
                _answer_block(answer, generator, VALIDATED_BACKGROUND)
            )

    blocks.append(_heading("h2", "Réponse générée à arbitrer", generator))
    blocks.extend(
        _apply_styles(
            markdown_to_richtext(case.candidate_answer, generator),
            {"backgroundColor": CANDIDATE_BACKGROUND, "padding": "4px 8px"},
        )
    )

    blocks.append(_heading("h2", "Sources citées", generator))
    blocks.extend(_sources_table(case.sources, generator))
    return document(blocks)
