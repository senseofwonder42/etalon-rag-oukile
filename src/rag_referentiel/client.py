"""Instanciation du client Kili."""

from pathlib import Path

from kili.client import Kili
from loguru import logger

from .config import Parametres


def creer_client(parametres: Parametres) -> Kili:
    """Instancie un client Kili à partir des paramètres.

    Args:
        parametres: Paramètres d'exécution.

    Returns:
        Le client Kili.

    Raises:
        RuntimeError: Si aucune clé d'API n'est configurée, ou si le
            bundle de certificats désigné est introuvable.
    """
    if not parametres.kili_api_key:
        raise RuntimeError(
            "KILI_API_KEY absente : renseigner le fichier .env "
            "(voir .env.example)."
        )
    logger.debug("Connexion à {}", parametres.kili_api_endpoint)
    return Kili(
        api_key=parametres.kili_api_key,
        api_endpoint=parametres.kili_api_endpoint,
        verify=verification_tls(parametres.kili_ca_bundle),
    )


def verification_tls(ca_bundle: str | None) -> bool | str:
    """Détermine la valeur de `verify` à passer au client Kili.

    Args:
        ca_bundle: Chemin du bundle de certificats, ou `None`.

    Returns:
        Le chemin du bundle si `KILI_CA_BUNDLE` est renseignée, sinon
        `True` — la vérification TLS n'est jamais désactivée.

    Raises:
        RuntimeError: Si le bundle désigné n'existe pas. Mieux vaut
            échouer que de retomber silencieusement sur les certificats
            du système.
    """
    if not ca_bundle:
        return True
    chemin = Path(ca_bundle).expanduser()
    if not chemin.is_file():
        raise RuntimeError(
            f"KILI_CA_BUNDLE désigne un fichier introuvable : {chemin}"
        )
    logger.debug("Vérification TLS via le bundle {}", chemin)
    return str(chemin)
