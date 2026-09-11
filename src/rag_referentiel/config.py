"""Project configuration, read from the environment and the .env file."""

from pydantic import Field
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
    # Chemin d'un bundle de certificats, pour une instance derrière un
    # proxy d'entreprise. Transmis tel quel à `Kili(verify=...)`.
    kili_ca_bundle: str | None = None
    anthropic_api_key: str | None = None
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
    embedding_model: str = "jina-embeddings-v5-nano"
    jina_base_url: str = "https://api.jina.ai/v1"

    # --- Publication des documents sources -------------------------------
    # Gabarit d'URL des documents, par exemple
    # « https://contoso.sharepoint.com/sites/assurance/{doc_id}#page={page} ».
    # Laisser vide si les documents ne sont publiés nulle part.
    document_url_template: str | None = None

    # --- Stockage ---------------------------------------------------------
    max_metadata_size: int = Field(default=60_000, ge=1_000)


def load_settings() -> Settings:
    """Load settings from the environment.

    Returns:
        The validated settings.
    """
    return Settings()
