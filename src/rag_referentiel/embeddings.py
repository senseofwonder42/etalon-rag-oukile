"""Embedding backends used by the semantic part of the matching."""

import hashlib
import math
from typing import Protocol, runtime_checkable

import httpx
from loguru import logger


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Provides vectors for a list of texts."""

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts into vectors.

        Args:
            texts: Texts to encode.

        Returns:
            One vector per text, in the same order.
        """
        ...


class ModelUnavailableError(RuntimeError):
    """The requested embedding model is not exposed by the service."""


class FakeEmbeddings:
    """Deterministic, offline backend, for tests and the demonstration.

    Every token is projected onto a dimension by hashing: two texts
    sharing vocabulary get close vectors. This is not semantics, but it
    is reproducible and needs no network.
    """

    def __init__(self, dimension: int = 64) -> None:
        """Initialize the backend.

        Args:
            dimension: Size of the produced vectors.
        """
        self.dimension = dimension

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts into deterministic vectors.

        Args:
            texts: Texts to encode.

        Returns:
            One unit vector per text.
        """
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        from .normalisation import tokenize

        vector = [0.0] * self.dimension
        for token in tokenize(text):
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            vector[digest[0] % self.dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]


class JinaEmbeddings:
    """Embedding backend backed by the Jina API."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize the backend.

        Args:
            api_key: Jina API key.
            model: Identifier of the embedding model.
            base_url: Root of the API, without trailing slash.
            client: HTTP client to reuse (useful for tests).
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def check_model_available(self) -> None:
        """Check that the requested model is exposed by the service.

        Raises:
            ModelUnavailableError: If the service does not answer, or if
                the requested model is missing from the returned list.
        """
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url, headers=self._headers)
        except httpx.HTTPError as error:
            raise ModelUnavailableError(
                f"Impossible d'interroger {url} : {error}. Vérifier la clé "
                "JINA_API_KEY et l'URL du service."
            ) from error
        if response.status_code != httpx.codes.OK:
            raise ModelUnavailableError(
                f"{url} a répondu {response.status_code}. Impossible de "
                f"confirmer la disponibilité du modèle « {self.model} »."
            )
        available = [
            entry.get("id")
            for entry in response.json().get("data", [])
            if isinstance(entry, dict)
        ]
        if self.model not in available:
            listed = ", ".join(sorted(m for m in available if m))
            raise ModelUnavailableError(
                f"Le modèle « {self.model} » n'est pas disponible. "
                f"Modèles exposés : {listed}"
            )
        logger.info("Modèle d'embeddings disponible : {}", self.model)

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Encode texts through the Jina API.

        Args:
            texts: Texts to encode.

        Returns:
            One vector per text, in the same order.

        Raises:
            RuntimeError: If the API returns an error.
        """
        if not texts:
            return []
        response = self._client.post(
            f"{self.base_url}/embeddings",
            headers=self._headers,
            json={"model": self.model, "input": texts},
        )
        if response.status_code != httpx.codes.OK:
            raise RuntimeError(
                f"Appel d'embeddings en échec ({response.status_code}) : "
                f"{response.text[:200]}"
            )
        return [
            entry["embedding"]
            for entry in response.json().get("data", [])
        ]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Compute the cosine similarity of two vectors.

    Args:
        left: First vector.
        right: Second vector.

    Returns:
        The similarity, clamped into `[0, 1]`: negative values are cut to
        zero, opposite directions being no better than no relation at all
        for matching purposes.
    """
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return max(0.0, dot / (norm_left * norm_right))
