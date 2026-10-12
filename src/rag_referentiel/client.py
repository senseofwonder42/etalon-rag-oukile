"""Instantiation of the clients that talk to external services."""

import ssl
from pathlib import Path

import anthropic
import httpx
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
        verify=tls_verification(settings.ca_bundle),
    )


def tls_verification(ca_bundle: str | None) -> bool | str:
    """Determine the `verify` value handed to the Kili client.

    Args:
        ca_bundle: Path to the certificate bundle, or `None`.

    Returns:
        The bundle path when `CA_BUNDLE` is set, `True` otherwise — TLS
        verification is never turned off.

    Raises:
        RuntimeError: If the designated bundle does not exist. Failing is
            better than silently falling back on the system certificates.
    """
    if not ca_bundle:
        return True
    path = Path(ca_bundle).expanduser()
    if not path.is_file():
        raise RuntimeError(
            f"CA_BUNDLE désigne un fichier introuvable : {path}"
        )
    logger.debug("Vérification TLS via le bundle {}", path)
    return str(path)


def ssl_verification(ca_bundle: str | None) -> bool | ssl.SSLContext:
    """Determine the `verify` value handed to the httpx based clients.

    httpx no longer accepts a bundle path: it expects an SSL context.

    Args:
        ca_bundle: Path to the certificate bundle, or `None`.

    Returns:
        An SSL context built on the bundle when one is set, `True`
        otherwise.

    Raises:
        RuntimeError: If the designated bundle does not exist.
    """
    verification = tls_verification(ca_bundle)
    if verification is True:
        return True
    return ssl.create_default_context(cafile=verification)


def create_http_client(
    settings: Settings, timeout: float = 30.0
) -> httpx.Client:
    """Instantiate an HTTP client that honours the certificate bundle.

    Args:
        settings: Runtime settings.
        timeout: Timeout of every request, in seconds.

    Returns:
        The HTTP client.
    """
    return httpx.Client(
        timeout=timeout, verify=ssl_verification(settings.ca_bundle)
    )


def create_anthropic_client(settings: Settings) -> anthropic.Anthropic:
    """Instantiate an Anthropic client that honours the certificate bundle.

    The SDK reads `ANTHROPIC_BASE_URL` from the environment, which allows
    going through an internal gateway.

    Args:
        settings: Runtime settings.

    Returns:
        The Anthropic client.
    """
    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        http_client=anthropic.DefaultHttpxClient(
            verify=ssl_verification(settings.ca_bundle)
        ),
    )
