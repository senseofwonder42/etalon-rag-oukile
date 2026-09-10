"""Configuration du projet, lue depuis l'environnement et le fichier .env."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENDPOINT_KILI_PAR_DEFAUT = (
    "https://cloud.kili-technology.com/api/label/v2/graphql"
)


class Parametres(BaseSettings):
    """Paramètres d'exécution du référentiel.

    Toutes les valeurs sont surchargeables par variable d'environnement
    (nom de l'attribut en majuscules) ou par le fichier `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Accès aux services externes -------------------------------------
    kili_api_key: str | None = None
    kili_api_endpoint: str = ENDPOINT_KILI_PAR_DEFAUT
    # Chemin d'un bundle de certificats, pour une instance derrière un
    # proxy d'entreprise. Transmis tel quel à `Kili(verify=...)`.
    kili_ca_bundle: str | None = None
    anthropic_api_key: str | None = None
    jina_api_key: str | None = None

    # --- Titres des deux projets Kili ------------------------------------
    titre_projet_referentiel: str = "Référentiel RAG"
    titre_projet_revue: str = "Revue prod RAG"

    # --- Appariement des questions ---------------------------------------
    seuil_appariement_haut: float = Field(default=0.72, ge=0.0, le=1.0)
    seuil_appariement_bas: float = Field(default=0.45, ge=0.0, le=1.0)
    poids_lexical: float = Field(default=0.4, ge=0.0, le=1.0)
    poids_semantique: float = Field(default=0.6, ge=0.0, le=1.0)

    # --- Accumulation des formulations validées --------------------------
    seuil_quasi_doublon: float = Field(default=0.85, ge=0.0, le=1.0)
    plafond_variantes: int = Field(default=5, ge=1)

    # --- Juge -------------------------------------------------------------
    modele_juge: str = "claude-sonnet-5"
    seuil_juge_lexical: float = Field(default=0.6, ge=0.0, le=1.0)
    max_references_juge: int = Field(default=5, ge=1)

    # --- Embeddings -------------------------------------------------------
    modele_embeddings: str = "jina-embeddings-v5-nano"
    url_jina: str = "https://api.jina.ai/v1"

    # --- Stockage ---------------------------------------------------------
    taille_max_metadata: int = Field(default=60_000, ge=1_000)


def charger_parametres() -> Parametres:
    """Charge les paramètres depuis l'environnement.

    Returns:
        Les paramètres validés.
    """
    return Parametres()
