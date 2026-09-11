"""Probe the rich text rendering of the Kili server with one asset.

Imports a single asset exercising the whole rich text vocabulary: `h1`
to `h4` headings, bold, italic, code, underline, lists, blockquote,
table, background colours and alignments. It is there to check, in five
minutes, what the instance actually renders before building on it.
"""

import argparse

from _commun import settings
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.interfaces import REFERENCE_INTERFACE
from rag_referentiel.richtext import (
    IdGenerator,
    document,
    element_node,
    text_node,
)

EXTERNAL_ID = "sonde_richtext"


def build_probe_asset() -> list[dict]:
    """Compose the probe asset.

    Returns:
        The `json_content` of the asset.
    """
    generator = IdGenerator()

    def paragraph(
        children: list[dict], styles: dict[str, str] | None = None
    ) -> dict:
        return element_node("p", children, generator, styles)

    def heading(level: str, text: str) -> dict:
        return element_node(
            level, [text_node(text, generator)], generator
        )

    def cell(text: str, header: bool = False) -> dict:
        return element_node(
            "td",
            [text_node(text, generator, {"bold"} if header else None)],
            generator,
            {"backgroundColor": "#eeeeee"} if header else None,
        )

    blocks = [
        heading("h1", "Sonde rich text — h1"),
        heading("h2", "Sous-titre — h2"),
        heading("h3", "Sous-titre — h3"),
        heading("h4", "Sous-titre — h4"),
        paragraph(
            [
                text_node("Normal, ", generator),
                text_node("gras", generator, {"bold"}),
                text_node(", ", generator),
                text_node("italique", generator, {"italic"}),
                text_node(", ", generator),
                text_node("code", generator, {"code"}),
                text_node(", ", generator),
                text_node("souligné", generator, {"underline"}),
                text_node(", ", generator),
                text_node(
                    "gras + italique", generator, {"bold", "italic"}
                ),
                text_node(".", generator),
            ]
        ),
        paragraph(
            [text_node("Fond vert clair.", generator)],
            {"backgroundColor": "#e8f5e9", "padding": "4px 8px"},
        ),
        paragraph(
            [text_node("Fond ambre.", generator)],
            {"backgroundColor": "#fff3e0", "padding": "4px 8px"},
        ),
        paragraph(
            [text_node("Texte coloré et centré.", generator)],
            {"color": "#c62828", "textAlign": "center"},
        ),
        paragraph(
            [text_node("Texte aligné à droite.", generator)],
            {"textAlign": "right"},
        ),
        paragraph(
            [text_node("Bloc décalé en colonne de droite.", generator)],
            {
                "backgroundColor": "#fff3e0",
                "padding": "4px 8px",
                "borderRadius": "6px",
                "maxWidth": "65%",
                "margin": "0 0 0 35%",
            },
        ),
        heading("h3", "Liste à puces"),
        element_node(
            "ul",
            [
                element_node(
                    "li", [text_node("Premier point", generator)],
                    generator,
                ),
                element_node(
                    "li",
                    [
                        text_node("Deuxième point en ", generator),
                        text_node("gras", generator, {"bold"}),
                    ],
                    generator,
                ),
            ],
            generator,
        ),
        heading("h3", "Liste numérotée"),
        element_node(
            "ol",
            [
                element_node(
                    "li", [text_node("Étape un", generator)], generator
                ),
                element_node(
                    "li", [text_node("Étape deux", generator)], generator
                ),
            ],
            generator,
        ),
        heading("h3", "Citation"),
        element_node(
            "blockquote",
            [paragraph([text_node("Une citation encadrée.", generator)])],
            generator,
            {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
        ),
        heading("h3", "Tableau"),
        element_node(
            "table",
            [
                element_node(
                    "thead",
                    [
                        element_node(
                            "tr",
                            [
                                cell("Document", True),
                                cell("Page", True),
                            ],
                            generator,
                        )
                    ],
                    generator,
                ),
                element_node(
                    "tbody",
                    [
                        element_node(
                            "tr",
                            [
                                cell("cg_auto_2024.pdf"),
                                cell("12"),
                            ],
                            generator,
                        ),
                        element_node(
                            "tr",
                            [
                                cell("cg_habitation_2024.pdf"),
                                cell("22"),
                            ],
                            generator,
                        ),
                    ],
                    generator,
                ),
            ],
            generator,
        ),
    ]
    return document(blocks, {"maxWidth": "900px", "margin": "0 auto"})


def main() -> None:
    """Entry point of the probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Projet TEXT existant ; créé si absent.",
    )
    arguments = parser.parse_args()

    config = settings()
    kili = create_client(config)
    project_id = arguments.project_id
    if project_id is None:
        project_id = kili.create_project(
            title="Sonde rich text",
            input_type="TEXT",
            json_interface=REFERENCE_INTERFACE,
            description="Vérification du rendu rich text côté serveur.",
        )["id"]
        logger.info("Projet de sonde créé : {}", project_id)

    kili.append_many_to_dataset(
        project_id=project_id,
        external_id_array=[EXTERNAL_ID],
        json_content_array=[build_probe_asset()],
        json_metadata_array=[{"text": "Sonde du vocabulaire rich text."}],
    )
    print(f"Asset « {EXTERNAL_ID} » importé dans le projet {project_id}.")
    print(
        "Ouvrir l'asset et vérifier, dans l'ordre : niveaux de titre, "
        "marques\n(gras, italique, code, souligné), fonds de couleur, "
        "alignements, décalage\nen colonne de droite, listes, citation, "
        "tableau."
    )


if __name__ == "__main__":
    main()
