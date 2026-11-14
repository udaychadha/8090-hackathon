"""Local PDF text intake preserves originals and verifies reusable Markdown."""

import hashlib
import json

import pymupdf
import pytest

from factory.agents import extractor


@pytest.fixture
def paper(tmp_path):
    path = tmp_path / "fixture.pdf"
    with pymupdf.open() as document:
        for text in ("Research title\nAuthor One\nA trading rule.", "More text on page two."):
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(path)
    path.with_suffix(".spec.json").write_text(
        json.dumps(
            {
                "source": {
                    "title": "Research title",
                    "authors": ["Author One"],
                    "url": "https://example.org/approved-paper.pdf",
                    "version": "working paper",
                }
            }
        )
    )
    return path


def test_prepare_reuses_cache_and_retains_provenance(paper, monkeypatch):
    original = paper.read_bytes()
    text = extractor.paper_text(paper)
    assert "## Page 1" in text and "## Page 2" in text and "More text" in text
    assert paper.read_bytes() == original
    metadata = extractor.paper_metadata(paper)
    assert metadata["source"]["url"] == "https://example.org/approved-paper.pdf"
    assert metadata["source"]["version"] == "working paper"
    assert metadata["source"]["sha256"] == hashlib.sha256(original).hexdigest()
    assert metadata["source"]["markdown_extraction"]["summarized"] is False

    def never_parse(*args):
        raise AssertionError("Cached extraction must not parse the PDF again")

    monkeypatch.setattr(extractor, "_pdf_pages", never_parse)
    assert extractor.paper_text(paper) == text


@pytest.mark.parametrize("changed", ["pdf", "md"])
def test_changed_source_or_cache_is_not_silently_accepted(paper, changed):
    extractor.paper_text(paper)
    path = paper.with_suffix("." + changed)
    path.write_bytes(path.read_bytes() + b"\nchanged")
    with pytest.raises(extractor.ExtractionError, match="fingerprint"):
        extractor.paper_text(paper)


def test_pdf_parser_rejects_non_pdf_and_empty_documents(tmp_path):
    path = tmp_path / "invalid.pdf"
    path.write_text("This is not a PDF")
    with pytest.raises(extractor.ExtractionError, match="could not be read"):
        extractor.pdf_text(path)
    with pymupdf.open() as document:
        document.new_page()
        document.save(tmp_path / "blank.pdf")
    with pytest.raises(extractor.ExtractionError, match="no extractable text"):
        extractor.pdf_text(tmp_path / "blank.pdf")
