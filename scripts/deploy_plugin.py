"""Build and deploy the Kili plugin that checks typed sources.

The plugin runs on Kili's servers, without access to the local PDF
files. This script therefore assembles a folder holding:

- `main.py`, the plugin itself (copied from `plugin/main.py`);
- `catalogue.py`, generated: the page count of every local document;
- `rag_referentiel/sources.py` and `schemas.py`, so that the plugin
  parses and checks sources exactly like `promote.py`;
- `requirements.txt`, their dependencies.

Then it uploads the plugin (or updates it) and activates it on the given
projects. To run again whenever a document is added or changed: a stale
catalogue would report a recent document as unknown.
"""

import argparse
import shutil
from pathlib import Path

from _commun import settings
from loguru import logger

from rag_referentiel.client import create_client
from rag_referentiel.documents import DocumentStore

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "rag_referentiel"
#: Modules du paquet embarqués dans le plugin, et rien d'autre : ils ne
#: dépendent que de la bibliothèque standard, de pydantic et de loguru.
SHIPPED_MODULES = ("__init__.py", "schemas.py", "sources.py")
REQUIREMENTS = "pydantic>=2\nloguru\n"
DEFAULT_NAME = "verification-sources"


def build(page_counts: dict[str, int], target: Path) -> Path:
    """Assemble the plugin folder.

    Args:
        page_counts: Page count of every document, by `doc_id`.
        target: Folder to (re)create.

    Returns:
        The assembled folder.
    """
    if target.exists():
        shutil.rmtree(target)
    (target / "rag_referentiel").mkdir(parents=True)
    shutil.copy(ROOT / "plugin" / "main.py", target / "main.py")
    for module in SHIPPED_MODULES:
        shutil.copy(PACKAGE / module, target / "rag_referentiel" / module)
    lines = [
        '"""Catalogue des documents sources, généré par deploy_plugin.py.',
        "",
        "Ne pas modifier à la main : relancer scripts/deploy_plugin.py.",
        '"""',
        "",
        "PAGES = {",
        *(
            f"    {name!r}: {count},"
            for name, count in sorted(page_counts.items())
        ),
        "}",
        "",
    ]
    (target / "catalogue.py").write_text("\n".join(lines), encoding="utf-8")
    (target / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    return target


def main() -> None:
    """Entry point of the deployment script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--documents",
        dest="documents_dir",
        type=Path,
        default=None,
        help="Répertoire des PDF sources (sinon DOCUMENTS_DIR).",
    )
    parser.add_argument(
        "--projet",
        dest="project_ids",
        action="append",
        default=[],
        help="Projet sur lequel activer le plugin (option répétable).",
    )
    parser.add_argument(
        "--nom",
        dest="name",
        default=DEFAULT_NAME,
        help="Nom du plugin dans Kili.",
    )
    parser.add_argument(
        "--dossier",
        dest="target",
        type=Path,
        default=ROOT / "build" / "plugin_verification_sources",
        help="Dossier où assembler le plugin.",
    )
    parser.add_argument(
        "--construire-seulement",
        dest="build_only",
        action="store_true",
        help="Assembler le dossier sans rien envoyer à Kili.",
    )
    arguments = parser.parse_args()

    config = settings()
    documents_dir = arguments.documents_dir or config.documents_dir
    if documents_dir is None:
        parser.error("renseigner --documents ou DOCUMENTS_DIR.")
    page_counts = DocumentStore(documents_dir).page_counts()
    if not page_counts:
        parser.error(f"aucun PDF lisible dans {documents_dir}.")
    folder = build(page_counts, arguments.target)
    logger.info(
        "Plugin assemblé dans {} ({} documents au catalogue).",
        folder,
        len(page_counts),
    )
    if arguments.build_only:
        return

    kili = create_client(config)
    known = {plugin["name"] for plugin in kili.list_plugins(fields=["name"])}
    if arguments.name in known:
        kili.update_plugin(plugin_path=str(folder), plugin_name=arguments.name)
    else:
        kili.upload_plugin(plugin_path=str(folder), plugin_name=arguments.name)
    for project_id in arguments.project_ids:
        kili.activate_plugin_on_project(
            plugin_name=arguments.name, project_id=project_id
        )
        logger.info("Plugin activé sur le projet {}.", project_id)


if __name__ == "__main__":
    main()
