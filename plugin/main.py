"""Kili plugin: check that the sources typed by the business team exist.

Run by Kili on every submitted label. When the `SOURCES_CORRIGEES` job
names a document or a page that does not exist, or holds an unreadable
fragment, the plugin:

1. opens an issue on the label, saying exactly what is wrong;
2. sends the asset back to the annotator's queue;
3. on project B, sets `statut_revue` to `SOURCES_A_CORRIGER`, so that
   `promote.py` leaves the case alone until it is corrected.

A later valid submission puts the case back to `EN_ATTENTE`.

Kili runs the plugin on its own servers, without access to our files:
`scripts/deploy_plugin.py` therefore ships it with a generated
`catalogue` module (page count of each document) and with the
`rag_referentiel.sources` module, so that the plugin and `promote.py`
read and check sources exactly the same way. Only `.py` files and
`requirements.txt` are uploaded by the SDK.
"""

import json

from catalogue import PAGES
from kili.plugins import PluginCore

from rag_referentiel.sources import source_list_problems

ASSET_FIELDS = ["id", "externalId", "jsonMetadata"]
BLOCKED = "SOURCES_A_CORRIGER"
PENDING = "EN_ATTENTE"


def typed_sources(label: dict) -> str | None:
    """Read the corrected source list of a label.

    Args:
        label: Label sent by Kili to the plugin.

    Returns:
        The typed text, or `None` when the job is empty.
    """
    response = label.get("jsonResponse") or {}
    if isinstance(response, str):
        response = json.loads(response or "{}")
    text = (response.get("SOURCES_CORRIGEES") or {}).get("text")
    if isinstance(text, str) and text.strip():
        return text
    return None


class PluginHandler(PluginCore):
    """Checks the sources of every submitted or reviewed label."""

    def on_submit(self, label: dict, asset_id: str) -> None:
        """Check the sources of a submitted label.

        Args:
            label: Submitted label.
            asset_id: Identifier of the labelled asset.
        """
        self.check(label, asset_id)

    def on_review(self, label: dict, asset_id: str) -> None:
        """Check the sources of a reviewed label.

        Args:
            label: Review label.
            asset_id: Identifier of the reviewed asset.
        """
        self.check(label, asset_id)

    def check(self, label: dict, asset_id: str) -> None:
        """Flag the asset when its sources are wrong, release it otherwise.

        Args:
            label: Label to check.
            asset_id: Identifier of the asset.
        """
        text = typed_sources(label)
        problems = source_list_problems(text, PAGES) if text else []
        metadata = self._metadata(asset_id)
        status = metadata.get("statut_revue")

        if problems:
            self.logger.info(
                "Sources à corriger sur %s : %s", asset_id, problems
            )
            self.kili.create_issues(
                project_id=self.project_id,
                label_id_array=[label["id"]],
                text_array=[
                    "Sources à corriger avant que la réponse puisse être "
                    "prise en compte : " + " ; ".join(problems) + "."
                ],
            )
            if status == PENDING:
                self._set_status(asset_id, metadata, BLOCKED)
            self.kili.send_back_to_queue(asset_ids=[asset_id])
        elif status == BLOCKED:
            self._set_status(asset_id, metadata, PENDING)

    def _metadata(self, asset_id: str) -> dict:
        assets = self.kili.assets(
            project_id=self.project_id,
            asset_id=asset_id,
            fields=ASSET_FIELDS,
        )
        raw = assets[0].get("jsonMetadata") if assets else None
        if isinstance(raw, str):
            return json.loads(raw or "{}")
        return raw or {}

    def _set_status(self, asset_id: str, metadata: dict, status: str) -> None:
        self.kili.update_properties_in_assets(
            asset_ids=[asset_id],
            json_metadatas=[{**metadata, "statut_revue": status}],
        )
