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
from rag_referentiel.rendering import RIGHT_COLUMN_HEADING, sources_table
from rag_referentiel.richtext import (
    IdGenerator,
    document,
    element_node,
    text_node,
)
from rag_referentiel.schemas import Source

EXTERNAL_ID = "sonde_richtext"
#: Gabarit SharePoint réaliste : il produit des URL longues, qui éprouvent
#: la largeur de la colonne « Lien ».
PROBE_URL_TEMPLATE = (
    "https://contoso.sharepoint.com/sites/assurance/Documents/"
    "{doc_id}#page={page}"
)
#: Sources de la sonde : un document cité sur plusieurs pages, un autre
#: sur une seule, comme dans les cartes réelles.
PROBE_SOURCES = [
    Source(doc_id="DCON_ConditionsGénérales_MRH_202605.pdf", page=22),
    Source(doc_id="DCON_ConditionsGénérales_MRH_202605.pdf", page=23),
    Source(doc_id="DCON_ConditionsGénérales_MRH_202605.pdf", page=24),
    Source(doc_id="DCON_DIPA_MRH_202605.pdf", page=1),
]


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

    def heading_in_right_column() -> dict:
        return element_node(
            "h3",
            [text_node("Titre dans la colonne de droite", generator)],
            generator,
            RIGHT_COLUMN_HEADING,
        )

    def heading(level: str, text: str) -> dict:
        return element_node(
            level, [text_node(text, generator)], generator
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
        heading_in_right_column(),
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
        heading("h3", "Lien"),
        paragraph(
            [
                text_node("URL brute : ", generator),
                text_node(
                    "https://exemple.fr/docs/cg_auto_2024.pdf#page=12",
                    generator,
                ),
            ]
        ),
        paragraph(
            [
                text_node("URL en code : ", generator),
                text_node(
                    "https://exemple.fr/docs/cg_auto_2024.pdf#page=12",
                    generator,
                    {"code"},
                ),
            ]
        ),
        paragraph(
            [
                text_node("URL soulignée et colorée : ", generator),
                text_node(
                    "https://exemple.fr/docs/cg_auto_2024.pdf#page=12",
                    generator,
                    {"underline"},
                    {"color": "#1565c0"},
                ),
            ]
        ),
        heading("h3", "Citation"),
        element_node(
            "blockquote",
            [paragraph([text_node("Une citation encadrée.", generator)])],
            generator,
            {"borderLeft": "3px solid #9e9e9e", "padding": "4px 8px"},
        ),
        heading("h3", "Tableau pleine largeur"),
        *sources_table(
            PROBE_SOURCES, generator, url_template=PROBE_URL_TEMPLATE
        ),
        heading("h3", "Tableau étroit, écran réduit simulé"),
        *sources_table(
            PROBE_SOURCES,
            generator,
            {"maxWidth": "340px"},
            PROBE_URL_TEMPLATE,
        ),
    ]
    # Pas de largeur maximale sur la racine : elle fausserait l'essai du
    # tableau pleine largeur, que les cartes réelles n'ont pas.
    return document(blocks)


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
        json_metadata_array=[
            {
                "text": "Sonde du vocabulaire rich text.",
                # Clé documentée comme affichée à côté de l'asset : c'est
                # le seul endroit où un lien est censé être cliquable.
                "url": "https://exemple.fr/docs/cg_auto_2024.pdf",
            }
        ],
    )
    print(f"Asset « {EXTERNAL_ID} » importé dans le projet {project_id}.")
    print(
        "Ouvrir l'asset et vérifier, dans l'ordre : niveaux de titre,\n"
        "marques (gras, italique, code, souligné), fonds de couleur,\n"
        "alignements, décalage en colonne de droite, listes, citation,\n"
        "tableau.\n\n"
        "Tableau pleine largeur : occupe-t-il toute la largeur ? A-t-il\n"
        "des bordures, un en-tête teinté, une ligne sur deux grisée ?\n"
        "Tableau étroit : les en-têtes restent-ils sur une seule ligne ?\n"
        "Les colonnes gardent-elles leur largeur minimale, quitte à faire\n"
        "déborder le tableau ? Si les en-têtes se coupent encore,\n"
        "`minWidth` et `whiteSpace` sont ignorés par Kili.\n"
        "L'URL se replie-t-elle dans sa cellule ? Le « Titre dans la\n"
        "colonne de droite » est-il décalé, et séparé du bloc suivant ?\n\n"
        "Puis la question des liens : l'une des trois URL du paragraphe\n"
        "« Lien » est-elle cliquable ? Et la clé « url » de la metadata\n"
        "apparaît-elle à côté de l'asset, cliquable ?"
    )


if __name__ == "__main__":
    main()
