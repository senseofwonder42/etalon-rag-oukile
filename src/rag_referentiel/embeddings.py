"""Backends d'embeddings utilisés par l'appariement sémantique."""

import hashlib
import math
from typing import Protocol, runtime_checkable

import httpx
from loguru import logger


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Fournit des vecteurs pour une liste de textes."""

    def encoder(self, textes: list[str]) -> list[list[float]]:
        """Encode des textes en vecteurs.

        Args:
            textes: Textes à encoder.

        Returns:
            Un vecteur par texte, dans le même ordre.
        """
        ...


class ModeleIndisponibleError(RuntimeError):
    """Le modèle d'embeddings demandé n'est pas exposé par le service."""


class FakeEmbeddings:
    """Backend déterministe et hors ligne, pour les tests et la démo.

    Chaque jeton est projeté sur une dimension par hachage : deux textes
    partageant du vocabulaire obtiennent des vecteurs proches. Ce n'est pas
    de la sémantique, mais c'est reproductible et sans réseau.
    """

    def __init__(self, dimension: int = 64) -> None:
        """Initialise le backend.

        Args:
            dimension: Taille des vecteurs produits.
        """
        self.dimension = dimension

    def encoder(self, textes: list[str]) -> list[list[float]]:
        """Encode des textes en vecteurs déterministes.

        Args:
            textes: Textes à encoder.

        Returns:
            Un vecteur normé par texte.
        """
        return [self._encoder_un(texte) for texte in textes]

    def _encoder_un(self, texte: str) -> list[float]:
        from .normalisation import tokeniser

        vecteur = [0.0] * self.dimension
        for jeton in tokeniser(texte):
            empreinte = hashlib.sha1(jeton.encode("utf-8")).digest()
            indice = empreinte[0] % self.dimension
            vecteur[indice] += 1.0
        norme = math.sqrt(sum(x * x for x in vecteur))
        if norme == 0.0:
            return vecteur
        return [x / norme for x in vecteur]


class JinaEmbeddings:
    """Backend d'embeddings adossé à l'API Jina."""

    def __init__(
        self,
        cle_api: str,
        modele: str,
        url_base: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialise le backend.

        Args:
            cle_api: Clé d'API Jina.
            modele: Identifiant du modèle d'embeddings.
            url_base: Racine de l'API, sans barre oblique finale.
            client: Client HTTP à réutiliser (utile pour les tests).
        """
        self.modele = modele
        self.url_base = url_base.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        self._entetes = {
            "Authorization": f"Bearer {cle_api}",
            "Content-Type": "application/json",
        }

    def verifier_modele(self) -> None:
        """Vérifie que le modèle demandé est bien exposé par le service.

        Raises:
            ModeleIndisponibleError: Si le service ne répond pas ou si le
                modèle demandé n'est pas dans la liste renvoyée.
        """
        url = f"{self.url_base}/models"
        try:
            reponse = self._client.get(url, headers=self._entetes)
        except httpx.HTTPError as erreur:
            raise ModeleIndisponibleError(
                f"Impossible d'interroger {url} : {erreur}. Vérifier la clé "
                "JINA_API_KEY et l'URL du service."
            ) from erreur
        if reponse.status_code != httpx.codes.OK:
            raise ModeleIndisponibleError(
                f"{url} a répondu {reponse.status_code}. Impossible de "
                f"confirmer la disponibilité du modèle « {self.modele} »."
            )
        disponibles = [
            entree.get("id")
            for entree in reponse.json().get("data", [])
            if isinstance(entree, dict)
        ]
        if self.modele not in disponibles:
            liste = ", ".join(sorted(m for m in disponibles if m))
            raise ModeleIndisponibleError(
                f"Le modèle « {self.modele} » n'est pas disponible. "
                f"Modèles exposés : {liste}"
            )
        logger.info("Modèle d'embeddings disponible : {}", self.modele)

    def encoder(self, textes: list[str]) -> list[list[float]]:
        """Encode des textes via l'API Jina.

        Args:
            textes: Textes à encoder.

        Returns:
            Un vecteur par texte, dans le même ordre.

        Raises:
            RuntimeError: Si l'API renvoie une erreur.
        """
        if not textes:
            return []
        reponse = self._client.post(
            f"{self.url_base}/embeddings",
            headers=self._entetes,
            json={"model": self.modele, "input": textes},
        )
        if reponse.status_code != httpx.codes.OK:
            raise RuntimeError(
                f"Appel d'embeddings en échec ({reponse.status_code}) : "
                f"{reponse.text[:200]}"
            )
        donnees = reponse.json().get("data", [])
        return [entree["embedding"] for entree in donnees]


def similarite_cosinus(gauche: list[float], droite: list[float]) -> float:
    """Calcule la similarité cosinus de deux vecteurs.

    Args:
        gauche: Premier vecteur.
        droite: Second vecteur.

    Returns:
        La similarité, ramenée dans `[0, 1]` : les valeurs négatives sont
        écrêtées à zéro, une opposition de sens ne valant pas mieux qu'une
        absence de rapport pour l'appariement.
    """
    if not gauche or not droite or len(gauche) != len(droite):
        return 0.0
    produit = sum(a * b for a, b in zip(gauche, droite, strict=True))
    norme_g = math.sqrt(sum(a * a for a in gauche))
    norme_d = math.sqrt(sum(b * b for b in droite))
    if norme_g == 0.0 or norme_d == 0.0:
        return 0.0
    return max(0.0, produit / (norme_g * norme_d))
