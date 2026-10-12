import pymupdf
import pytest
from check_env import check_documents, check_project

from rag_referentiel.interfaces import REFERENCE_INTERFACE, REVIEW_INTERFACE


class _Projects:
    def __init__(self, projects):
        self._projects = projects

    def projects(self, project_id, fields):
        return [p for i, p in self._projects.items() if i == project_id]


def test_a_project_with_the_expected_jobs_passes():
    kili = _Projects(
        {"a": {"title": "Réf", "jsonInterface": REFERENCE_INTERFACE}}
    )
    assert check_project(kili, "a", REFERENCE_INTERFACE) == "Réf"


def test_swapped_projects_are_reported():
    kili = _Projects(
        {"b": {"title": "Revue", "jsonInterface": REVIEW_INTERFACE}}
    )
    with pytest.raises(RuntimeError, match="inversés"):
        check_project(kili, "b", REFERENCE_INTERFACE)


def test_a_missing_project_is_reported():
    with pytest.raises(RuntimeError, match="introuvable"):
        check_project(_Projects({}), "x", REFERENCE_INTERFACE)


def test_an_unreadable_pdf_is_reported(tmp_path):
    document = pymupdf.open()
    document.new_page()
    document.save(tmp_path / "cg.pdf")
    assert check_documents(tmp_path).startswith("1 PDF lisibles")
    (tmp_path / "casse.pdf").write_text("pas un pdf", encoding="utf-8")
    with pytest.raises(RuntimeError, match="1 PDF illisibles sur 2"):
        check_documents(tmp_path)


def test_an_unset_documents_directory_is_reported():
    with pytest.raises(RuntimeError, match="DOCUMENTS_DIR"):
        check_documents(None)
