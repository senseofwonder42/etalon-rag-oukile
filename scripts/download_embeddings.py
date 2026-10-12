"""Download the embedding weights and the server that exposes them.

To be run on a machine with internet access. The resulting folder is
then copied as is onto the server, where `serve_embeddings.sh` starts
it. Two downloads, both pinned and checked against their SHA-256:

- the GGUF weights of `jina-embeddings-v5-text-small-text-matching`,
  the text-matching variant, meant for comparing two questions;
- a llama.cpp build, whose `llama-server` exposes the weights through
  an OpenAI compatible API (`/v1/embeddings`, `/v1/models`).

A file already present with the right checksum is not downloaded again.
"""

import argparse
import hashlib
import tarfile
from pathlib import Path

import httpx
from _commun import settings
from loguru import logger

from rag_referentiel.client import create_http_client

MODEL_REPO = "jinaai/jina-embeddings-v5-text-small-text-matching"
# Commit du dépôt Hugging Face, figé pour que les poids ne changent pas
# d'un téléchargement à l'autre.
MODEL_REVISION = "69890c317b81d4e1f412e66ebe68b6ebf9534d24"
QUANTIZATIONS = ("F16", "Q8_0", "Q6_K", "Q4_K_M")

LLAMA_CPP_BUILD = "b11170"
# Empreintes publiées par GitHub pour chaque archive de cette version.
LLAMA_CPP_ARCHIVES = {
    "ubuntu-x64": (
        "ec5857f71de6cffff96090849c63127e7e51648393136a05405ca491fc97a439"
    ),
    "macos-arm64": (
        "253b2fbba4508115a71c20f76d769e5ee884b8cc3320f2ea66f928edfa87de0a"
    ),
}


def sha256_of(path: Path) -> str:
    """Compute the SHA-256 of a file.

    Args:
        path: File to hash.

    Returns:
        The hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(
    client: httpx.Client, url: str, destination: Path, expected: str
) -> None:
    """Download a file and check its SHA-256.

    The file is written next to its destination, then renamed once
    checked: an interrupted download never leaves a truncated file.

    Args:
        client: HTTP client.
        url: Address of the file.
        destination: Final path of the file.
        expected: Expected SHA-256, in hexadecimal.

    Raises:
        RuntimeError: If the checksum does not match.
    """
    if destination.exists() and sha256_of(destination) == expected:
        logger.info("Déjà présent et vérifié : {}", destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    logger.info("Téléchargement de {}", url)
    with (
        client.stream("GET", url, follow_redirects=True) as response,
        partial.open("wb") as stream,
    ):
        response.raise_for_status()
        for block in response.iter_bytes(1 << 20):
            digest.update(block)
            stream.write(block)
    if digest.hexdigest() != expected:
        partial.unlink()
        raise RuntimeError(
            f"Empreinte inattendue pour {url} : {digest.hexdigest()} "
            f"au lieu de {expected}."
        )
    partial.replace(destination)
    logger.info("Écrit et vérifié : {}", destination)


def gguf_checksum(client: httpx.Client, filename: str) -> str:
    """Read the SHA-256 that Hugging Face publishes for a weights file.

    Args:
        client: HTTP client.
        filename: Name of the file in the repository.

    Returns:
        The expected SHA-256.

    Raises:
        RuntimeError: If the file is not in the repository.
    """
    response = client.get(
        f"https://huggingface.co/api/models/{MODEL_REPO}/tree/{MODEL_REVISION}"
    )
    response.raise_for_status()
    for entry in response.json():
        if entry.get("path") == filename and entry.get("lfs"):
            return entry["lfs"]["oid"]
    raise RuntimeError(f"{filename} absent du dépôt {MODEL_REPO}.")


def main() -> None:
    """Entry point of the download script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dossier",
        dest="directory",
        type=Path,
        default=Path("models"),
        help="Dossier de destination, à copier ensuite sur le serveur.",
    )
    parser.add_argument(
        "--plateforme",
        dest="platform",
        choices=sorted(LLAMA_CPP_ARCHIVES),
        default="ubuntu-x64",
        help="Plateforme du serveur ; macos-arm64 pour essayer en local.",
    )
    parser.add_argument(
        "--quantification",
        dest="quantization",
        choices=QUANTIZATIONS,
        default="Q8_0",
        help="Q8_0 : moitié de la taille de F16, perte négligeable.",
    )
    arguments = parser.parse_args()

    client = create_http_client(settings(), timeout=60.0)

    filename = f"v5-small-text-matching-{arguments.quantization}.gguf"
    download(
        client,
        f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/"
        f"{filename}",
        arguments.directory / filename,
        gguf_checksum(client, filename),
    )

    archive_name = f"llama-{LLAMA_CPP_BUILD}-bin-{arguments.platform}.tar.gz"
    archive = arguments.directory / archive_name
    download(
        client,
        "https://github.com/ggml-org/llama.cpp/releases/download/"
        f"{LLAMA_CPP_BUILD}/{archive_name}",
        archive,
        LLAMA_CPP_ARCHIVES[arguments.platform],
    )
    target = arguments.directory / "llama.cpp"
    with tarfile.open(archive) as bundle:
        bundle.extractall(target, filter="data")
    logger.info("llama.cpp extrait dans {}", target)
    print(
        f"\nÀ copier sur le serveur : {arguments.directory}/ "
        "(par exemple avec rsync), puis y lancer "
        "scripts/serve_embeddings.sh start."
    )


if __name__ == "__main__":
    main()
