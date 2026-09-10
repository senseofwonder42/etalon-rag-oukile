"""Fixtures partagées : faux client Kili en mémoire, sans réseau."""

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))


class FauxKili:
    """Client Kili en mémoire, limité aux appels utilisés par le projet."""

    def __init__(self):
        self.projets = {}
        self.donnees = {}
        self.appels = []

    # --- projets ------------------------------------------------------
    def create_project(
        self, title, input_type, json_interface, description=""
    ):
        identifiant = f"projet_{len(self.projets) + 1}"
        self.projets[identifiant] = {
            "title": title,
            "inputType": input_type,
            "jsonInterface": json_interface,
            "description": description,
            "archived": False,
        }
        self.donnees[identifiant] = {}
        return {"id": identifiant}

    def archive_project(self, project_id):
        self.projets[project_id]["archived"] = True
        return {"id": project_id}

    def delete_project(self, project_id):
        del self.projets[project_id]
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
        registre = self.donnees.setdefault(project_id, {})
        for indice, external_id in enumerate(external_id_array):
            if external_id in registre:
                continue
            registre[external_id] = {
                "id": f"{project_id}_{external_id}",
                "externalId": external_id,
                "jsonMetadata": json_metadata_array[indice],
                "jsonContent": json_content_array[indice]
                if json_content_array
                else None,
                "content": content_array[indice] if content_array else None,
                "labels": [],
                "priority": 0,
                "status": "TODO",
            }
        return {"id": project_id}

    def assets(
        self, project_id, fields=None, metadata_where=None, **kwargs
    ):
        del fields, kwargs
        resultat = []
        for asset in self.donnees.get(project_id, {}).values():
            metadata = asset["jsonMetadata"] or {}
            if metadata_where and any(
                metadata.get(cle) != valeur
                for cle, valeur in metadata_where.items()
            ):
                continue
            resultat.append(json.loads(json.dumps(asset)))
        return resultat

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
        registre = self.donnees[project_id]
        for indice, external_id in enumerate(external_ids):
            asset = registre[external_id]
            if json_metadatas is not None:
                asset["jsonMetadata"] = json_metadatas[indice]
            if json_contents is not None:
                # Le SDK attend une chaîne pour `json_contents`.
                assert isinstance(json_contents[indice], str)
                asset["jsonContent"] = json.loads(json_contents[indice])
            if priorities is not None:
                asset["priority"] = priorities[indice]
        return [{"id": registre[e]["id"]} for e in external_ids]

    def send_back_to_queue(self, project_id=None, external_ids=None):
        for external_id in external_ids:
            self.donnees[project_id][external_id]["status"] = "TODO"
        self.appels.append(("send_back_to_queue", tuple(external_ids)))
        return {"id": project_id}

    def delete_many_from_dataset(self, project_id=None, external_ids=None):
        for external_id in external_ids:
            self.donnees[project_id].pop(external_id, None)
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
        for indice, external_id in enumerate(asset_external_id_array):
            self.ajouter_label(
                project_id,
                external_id,
                json_response_array[indice],
                auteur="cle-api@exemple.fr",
                date="2026-09-10",
                label_type=label_type,
            )
        return [{"id": "label"} for _ in asset_external_id_array]

    # --- utilitaires de test -----------------------------------------
    def ajouter_label(
        self,
        project_id,
        external_id,
        json_response,
        auteur="m.leroy@exemple.fr",
        date="2026-07-18",
        label_type="DEFAULT",
    ):
        """Ajoute un label à un asset, comme le ferait un annotateur."""
        labels = self.donnees[project_id][external_id]["labels"]
        labels.append(
            {
                "id": f"label_{len(labels)}",
                "author": {"email": auteur},
                "createdAt": f"{date}T10:00:00.000Z",
                "jsonResponse": json_response,
                "labelType": label_type,
            }
        )

    def metadata(self, project_id, external_id):
        """Renvoie la metadata courante d'un asset."""
        return self.donnees[project_id][external_id]["jsonMetadata"]


@pytest.fixture
def kili():
    """Faux client Kili en mémoire."""
    return FauxKili()
