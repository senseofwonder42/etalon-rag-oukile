"""Project configuration, read from the environment and the .env file."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_KILI_ENDPOINT = (
    "https://cloud.kili-technology.com/api/label/v2/graphql"
)


class Settings(BaseSettings):
    """Runtime settings of the reference repository.

    Every value can be overridden through an environment variable (the
    attribute name in upper case) or through the `.env` file.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Accès aux services externes -------------------------------------
    kili_api_key: str | None = None
    kili_api_endpoint: str = DEFAULT_KILI_ENDPOINT
    # Chemin d'un bundle de certificats, pour un réseau derrière un proxy
    # d'entreprise. Utilisé par les trois clients : Kili, Anthropic et le
    # serveur d'embeddings. `KILI_CA_BUNDLE`, l'ancien nom, reste lu.
    ca_bundle: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ca_bundle", "kili_ca_bundle"),
    )
    anthropic_api_key: str | None = None
    # Facultative : un serveur d'embeddings local n'en demande pas.
    jina_api_key: str | None = None

    # --- Titres des deux projets Kili ------------------------------------
    reference_project_title: str = "Référentiel RAG"
    review_project_title: str = "Revue prod RAG"

    # --- Appariement des questions ---------------------------------------
    match_threshold_high: float = Field(default=0.72, ge=0.0, le=1.0)
    match_threshold_low: float = Field(default=0.45, ge=0.0, le=1.0)
    lexical_weight: float = Field(default=0.4, ge=0.0, le=1.0)
    semantic_weight: float = Field(default=0.6, ge=0.0, le=1.0)

    # --- Accumulation des formulations validées --------------------------
    near_duplicate_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    variant_cap: int = Field(default=5, ge=1)

    # --- Juge -------------------------------------------------------------
    judge_model: str = "claude-sonnet-5"
    lexical_judge_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    max_judge_references: int = Field(default=5, ge=1)

    # --- Embeddings -------------------------------------------------------
    # Serveur local compatible OpenAI, lancé par `serve_embeddings.sh`.
    # Le nom du modèle est l'alias sous lequel le serveur l'expose.
    embedding_model: str = "jina-embeddings-v5-text-small-text-matching"
    jina_base_url: str = "http://127.0.0.1:8080/v1"
    # Préfixe attendu par la variante text-matching de Jina v5 quand elle
    # est appelée par `/v1/embeddings`. Le vider pour l'API Jina, qui
    # l'ajoute elle-même.
    embedding_prefix: str = "Document: "

    # --- Publication des documents sources -------------------------------
    # Gabarit d'URL des documents, par exemple
    # « https://contoso.sharepoint.com/sites/assurance/{doc_id}#page={page} ».
    # Laisser vide si les documents ne sont publiés nulle part.
    document_url_template: str | None = None
    # Répertoire local des PDF sources. Le `doc_id` d'une source est le nom
    # du fichier. Renseigné, il active la vérification d'existence des
    # sources à la promotion et la régénération des réponses.
    documents_dir: Path | None = None

    # --- Régénération des réponses non conformes ------------------------
    regeneration_model: str = "claude-opus-5-5"
    regeneration_effort: Literal["low", "medium", "high", "xhigh", "max"] = (
        "high"
    )
    # Résolution du rendu des pages envoyées au VLM.
    regeneration_dpi: int = Field(default=150, ge=50, le=400)
    # Au-delà, le cas part en relecture sans brouillon plutôt que de
    # tronquer silencieusement les pages de vérité terrain.
    regeneration_max_pages: int = Field(default=20, ge=1)
    regeneration_max_attempts: int = Field(default=3, ge=1)
    # Repli côté serveur sur un autre modèle quand le modèle refuse une
    # requête (paramètre `fallbacks` de l'API). À couper si l'accès passe
    # par une passerelle qui ne le connaît pas.
    regeneration_fallbacks: bool = True
    # Fichier texte facultatif : consignes de forme du prompt de la RAG de
    # production, pour que le brouillon lui ressemble.
    regeneration_style_file: Path | None = None

    # --- Stockage ---------------------------------------------------------
    max_metadata_size: int = Field(default=60_000, ge=1_000)


def load_settings() -> Settings:
    """Load settings from the environment.

    Returns:
        The validated settings.
    """
    return Settings()
