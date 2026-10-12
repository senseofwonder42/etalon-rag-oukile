"""Local access to the source PDF documents.

The `doc_id` of a source is the name of a PDF file in the documents
directory. Names are indexed in composed Unicode form (NFC), like
`Source.doc_id`: a name copied from macOS arrives decomposed, and would
otherwise never match the file it designates.
"""

import unicodedata
from pathlib import Path

import pymupdf


class DocumentStore:
    """Read-only access to a directory of PDF files."""

    def __init__(self, directory: Path) -> None:
        """Index the PDF files of a directory, subdirectories included.

        Args:
            directory: Directory holding the source documents.

        Raises:
            FileNotFoundError: If the directory does not exist.
        """
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Répertoire des documents introuvable : {directory}"
            )
        self.directory = directory
        self._paths: dict[str, Path] = {}
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path.suffix.lower() == ".pdf":
                name = unicodedata.normalize("NFC", path.name)
                self._paths.setdefault(name, path)
        self._page_counts: dict[str, int] | None = None

    def page_counts(self) -> dict[str, int]:
        """Count the pages of every indexed document.

        Returns:
            The number of pages of each document, by `doc_id`. An
            unreadable PDF is left out: for the checks, it does not exist.
        """
        if self._page_counts is None:
            counts: dict[str, int] = {}
            for name, path in self._paths.items():
                try:
                    with pymupdf.open(path) as pdf:
                        counts[name] = pdf.page_count
                except (pymupdf.FileDataError, RuntimeError):
                    continue
            self._page_counts = counts
        return self._page_counts

    def render_page(self, doc_id: str, page: int, dpi: int) -> bytes:
        """Render one page of a document as a PNG image.

        Args:
            doc_id: Document name.
            page: Page number, starting at 1 like the sources.
            dpi: Rendering resolution.

        Returns:
            The PNG image of the page.

        Raises:
            KeyError: If the document is unknown.
            ValueError: If the page does not exist.
        """
        path = self._paths[unicodedata.normalize("NFC", doc_id)]
        with pymupdf.open(path) as pdf:
            if not 1 <= page <= pdf.page_count:
                raise ValueError(
                    f"{doc_id} n'a pas de page {page} "
                    f"({pdf.page_count} pages)."
                )
            return pdf[page - 1].get_pixmap(dpi=dpi).tobytes("png")
