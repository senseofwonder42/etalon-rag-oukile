"""Check the environment before a first real run. Writes nothing.

Every check prints one line, OK or ÉCHEC, with the reason. The script
exits with a non-zero status as soon as one check fails, so that it can
gate a deployment. Without `--projet-referentiel` and `--projet-revue`,
only the Kili connection is checked, not the projects.
"""

import argparse
import json
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from _commun import settings
from loguru import logger

from rag_referentiel.client import (
    create_anthropic_client,
    create_client,
    create_http_client,
    ssl_verification,
)
from rag_referentiel.config import Settings
from rag_referentiel.documents import DocumentStore
from rag_referentiel.embeddings import JinaEmbeddings
from rag_referentiel.interfaces import REFERENCE_INTERFACE, REVIEW_INTERFACE


def check_project(kili: object, project_id: str, expected: dict) -> str:
    """Check that a project exists and carries the expected jobs.

    Args:
        kili: Kili client.
        project_id: Identifier of the project.
        expected: Interface the project must carry.

    Returns:
        The title of the project.

    Raises:
        RuntimeError: If the project is missing or its jobs differ.
    """
    projects = list(
        kili.projects(project_id=project_id, fields=["title", "jsonInterface"])
    )
    if not projects:
        raise RuntimeError(f"projet {project_id} introuvable")
    interface = projects[0]["jsonInterface"]
    if isinstance(interface, str):
        interface = json.loads(interface)
    missing = set(expected["jobs"]) - set(interface.get("jobs", {}))
    if missing:
        raise RuntimeError(
            f"« {projects[0]['title']} » n'a pas les jobs "
            f"{', '.join(sorted(missing))} : projets A et B inversés ?"
        )
    return projects[0]["title"]


def check_embeddings(config: Settings) -> str:
    """Check that the embeddings server exposes the model and answers.

    Args:
        config: Runtime settings.

    Returns:
        A summary of the check.
    """
    backend = JinaEmbeddings(
        api_key=config.jina_api_key,
        model=config.embedding_model,
        base_url=config.jina_base_url,
        client=create_http_client(config),
        prefix=config.embedding_prefix,
    )
    backend.check_model_available()
    vector = backend.encode(["Quel est le délai de déclaration ?"])[0]
    return f"{config.embedding_model}, vecteurs de {len(vector)} dimensions"


def check_claude_model(config: Settings, model: str) -> str:
    """Check that a Claude model is reachable with the configured key.

    Args:
        config: Runtime settings.
        model: Identifier of the model.

    Returns:
        A summary of the check.

    Raises:
        RuntimeError: If no Anthropic key is configured.
    """
    if not config.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")
    create_anthropic_client(config).models.retrieve(model)
    return f"{model} accessible"


def check_documents(directory: Path | None) -> str:
    """Check that the source documents are present and readable.

    Args:
        directory: Directory of the source PDFs.

    Returns:
        A summary of the check.

    Raises:
        RuntimeError: If no directory is set, it holds no PDF, or some
            PDFs cannot be opened.
    """
    if directory is None:
        raise RuntimeError("DOCUMENTS_DIR non renseigné")
    store = DocumentStore(directory)
    total = sum(
        1 for path in directory.rglob("*") if path.suffix.lower() == ".pdf"
    )
    readable = len(store.page_counts())
    if total == 0:
        raise RuntimeError(f"aucun PDF dans {directory}")
    if readable < total:
        raise RuntimeError(f"{total - readable} PDF illisibles sur {total}")
    return f"{total} PDF lisibles dans {directory}"


def check_server() -> str:
    """Check the tools and folders the scheduled cycle relies on.

    Returns:
        A summary of the check.

    Raises:
        RuntimeError: If a tool is missing or a folder is not writable.
    """
    missing = [tool for tool in ("flock", "curl") if not shutil.which(tool)]
    if missing:
        raise RuntimeError(f"outils absents : {', '.join(missing)}")
    for folder in (Path("logs"), Path("reports")):
        folder.mkdir(exist_ok=True)
        probe = folder / ".ecriture"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    return "flock et curl présents, logs/ et reports/ accessibles"


def main() -> None:
    """Entry point of the environment check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--projet-referentiel",
        dest="reference_project",
        default=None,
        help="Projet A.",
    )
    parser.add_argument(
        "--projet-revue",
        dest="review_project",
        default=None,
        help="Projet B.",
    )
    parser.add_argument(
        "--documents",
        dest="documents",
        type=Path,
        default=None,
        help="Répertoire des PDF sources ; DOCUMENTS_DIR par défaut.",
    )
    parser.add_argument(
        "--hors-ligne",
        dest="offline",
        action="store_true",
        help="Ne vérifier ni le serveur d'embeddings, ni Claude.",
    )
    arguments = parser.parse_args()
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    failures = 0

    def run(label: str, check: Callable[[], str]) -> None:
        nonlocal failures
        try:
            result = check()
        except Exception as error:  # un diagnostic rapporte tout
            failures += 1
            print(f"[ÉCHEC] {label} : {error}")
            return
        print(f"[OK]    {label} : {result}")

    try:
        config = settings()
        ssl_verification(config.ca_bundle)
    except Exception as error:  # configuration illisible : rien à tester
        print(f"[ÉCHEC] Configuration : {error}")
        sys.exit(1)
    print(
        "[OK]    Configuration : "
        + (".env lu" if Path(".env").is_file() else "variables seules")
    )

    kili = None

    def connect() -> str:
        nonlocal kili
        kili = create_client(config)
        return config.kili_api_endpoint

    run("Kili", connect)
    if kili is not None:
        if arguments.reference_project:
            run(
                "Projet A",
                lambda: check_project(
                    kili, arguments.reference_project, REFERENCE_INTERFACE
                ),
            )
        if arguments.review_project:
            run(
                "Projet B",
                lambda: check_project(
                    kili, arguments.review_project, REVIEW_INTERFACE
                ),
            )
    if not arguments.offline:
        run("Embeddings", lambda: check_embeddings(config))
        run("Juge", lambda: check_claude_model(config, config.judge_model))
        run(
            "Régénération",
            lambda: check_claude_model(config, config.regeneration_model),
        )
    run(
        "Documents",
        lambda: check_documents(arguments.documents or config.documents_dir),
    )
    run("Serveur", check_server)

    if failures:
        print(f"\n{failures} vérification(s) en échec.")
        sys.exit(1)
    print("\nEnvironnement prêt.")


if __name__ == "__main__":
    main()
