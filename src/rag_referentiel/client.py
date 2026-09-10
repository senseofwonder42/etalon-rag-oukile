"""Instanciation du client Kili."""

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
        RuntimeError: Si aucune clé d'API n'est configurée.
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
    )
