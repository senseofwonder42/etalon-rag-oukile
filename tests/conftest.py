"""Shared fixtures: in-memory fake Kili client, no network."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


class FakeKili:
    """In-memory Kili client, limited to the calls this project makes."""

    def __init__(self):
        self.projects = {}
        self.data = {}
        self.calls = []

    # --- projets ------------------------------------------------------
    def create_project(
        self, title, input_type, json_interface, description=""
    ):
        identifier = f"projet_{len(self.projects) + 1}"
        self.projects[identifier] = {
            "title": title,
            "inputType": input_type,
            "jsonInterface": json_interface,
            "description": description,
            "archived": False,
        }
        self.data[identifier] = {}
        return {"id": identifier}

    def archive_project(self, project_id):
        self.projects[project_id]["archived"] = True
        return {"id": project_id}

    def delete_project(self, project_id):
        del self.projects[project_id]
        return project_id

    # --- assets -------------------------------------------------------
    def append_many_to_dataset(
        self,
        project_id,
        external_id_array=None,
        json_content_array=None,
        json_metadata_array=None,
        content_array=None,
    ):
        assert content_array is None or json_content_array is None
        registry = self.data.setdefault(project_id, {})
        for index, external_id in enumerate(external_id_array):
            if external_id in registry:
                continue
            registry[external_id] = {
                "id": f"{project_id}_{external_id}",
                "externalId": external_id,
                "jsonMetadata": json_metadata_array[index],
                "jsonContent": json_content_array[index]
                if json_content_array
                else None,
                "content": content_array[index] if content_array else None,
                "labels": [],
                "priority": 0,
                "status": "TODO",
            }
        return {"id": project_id}

    def assets(self, project_id, fields=None, metadata_where=None, **kwargs):
        del fields, kwargs
        result = []
        for asset in self.data.get(project_id, {}).values():
            metadata = asset["jsonMetadata"] or {}
            if metadata_where and any(
                metadata.get(key) != value
                for key, value in metadata_where.items()
            ):
                continue
            result.append(json.loads(json.dumps(asset)))
        return result

    def update_properties_in_assets(
        self,
        project_id=None,
        external_ids=None,
        json_metadatas=None,
        json_contents=None,
        priorities=None,
        **kwargs,
    ):
        del kwargs
        registry = self.data[project_id]
        for index, external_id in enumerate(external_ids):
            asset = registry[external_id]
            if json_metadatas is not None:
                asset["jsonMetadata"] = json_metadatas[index]
            if json_contents is not None:
                # Le SDK attend une chaîne pour `json_contents`.
                assert isinstance(json_contents[index], str)
                asset["jsonContent"] = json.loads(json_contents[index])
            if priorities is not None:
                asset["priority"] = priorities[index]
        return [{"id": registry[e]["id"]} for e in external_ids]

    def send_back_to_queue(self, project_id=None, external_ids=None):
        for external_id in external_ids:
            self.data[project_id][external_id]["status"] = "TODO"
        self.calls.append(("send_back_to_queue", tuple(external_ids)))
        return {"id": project_id}

    def delete_many_from_dataset(self, project_id=None, external_ids=None):
        for external_id in external_ids:
            self.data[project_id].pop(external_id, None)
        return {"id": project_id}

    # --- labels -------------------------------------------------------
    def append_labels(
        self,
        project_id=None,
        asset_external_id_array=None,
        json_response_array=None,
        label_type="DEFAULT",
        **kwargs,
    ):
        del kwargs
        for index, external_id in enumerate(asset_external_id_array):
            self.add_label(
                project_id,
                external_id,
                json_response_array[index],
                author="cle-api@exemple.fr",
                date="2026-09-10",
                label_type=label_type,
            )
        return [{"id": "label"} for _ in asset_external_id_array]

    # --- utilitaires de test -----------------------------------------
    def add_label(
        self,
        project_id,
        external_id,
        json_response,
        author="m.leroy@exemple.fr",
        date="2026-07-18",
        label_type="DEFAULT",
    ):
        """Add a label to an asset, the way an annotator would."""
        labels = self.data[project_id][external_id]["labels"]
        labels.append(
            {
                "id": f"label_{len(labels)}",
                "author": {"email": author},
                "createdAt": f"{date}T10:00:00.000Z",
                "jsonResponse": json_response,
                "labelType": label_type,
            }
        )

    def metadata(self, project_id, external_id):
        """Return the current metadata of an asset."""
        return self.data[project_id][external_id]["jsonMetadata"]


@pytest.fixture
def kili():
    """In-memory fake Kili client."""
    return FakeKili()
