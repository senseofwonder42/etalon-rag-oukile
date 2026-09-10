"""Kili client instantiation."""

from pathlib import Path

from kili.client import Kili
from loguru import logger

from .config import Settings


def create_client(settings: Settings) -> Kili:
    """Instantiate a Kili client from the settings.

    Args:
        settings: Runtime settings.

    Returns:
        The Kili client.

    Raises:
        RuntimeError: If no API key is configured, or if the designated
            certificate bundle cannot be found.
    """
    if not settings.kili_api_key:
        raise RuntimeError(
            "KILI_API_KEY absente : renseigner le fichier .env "
            "(voir .env.example)."
        )
    logger.debug("Connexion à {}", settings.kili_api_endpoint)
    return Kili(
        api_key=settings.kili_api_key,
        api_endpoint=settings.kili_api_endpoint,
        verify=tls_verification(settings.kili_ca_bundle),
    )


def tls_verification(ca_bundle: str | None) -> bool | str:
    """Determine the `verify` value handed to the Kili client.

    Args:
        ca_bundle: Path to the certificate bundle, or `None`.

    Returns:
        The bundle path when `KILI_CA_BUNDLE` is set, `True` otherwise —
        TLS verification is never turned off.

    Raises:
        RuntimeError: If the designated bundle does not exist. Failing is
            better than silently falling back on the system certificates.
    """
    if not ca_bundle:
        return True
    path = Path(ca_bundle).expanduser()
    if not path.is_file():
        raise RuntimeError(
            f"KILI_CA_BUNDLE désigne un fichier introuvable : {path}"
        )
    logger.debug("Vérification TLS via le bundle {}", path)
    return str(path)
