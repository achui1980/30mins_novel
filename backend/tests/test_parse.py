"""Unit tests for backend/app/pipeline/parse.py's MOBI support.

mobi.extract() unpacks a .mobi container to a temp dir and returns a path to
the produced file, which is either .epub (KF8/mobi8), .html (older
MOBI7/PalmDOC), or .pdf (Kindle "Print Replica" -- not supported). We mock
mobi.extract() so no binary .mobi fixture is needed.
"""

import mobi
import pytest

from app.pipeline.parse import ParseError, parse_mobi


def test_parse_mobi_html_source(tmp_path, monkeypatch):
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    html_file = extracted_dir / "book.html"
    html_file.write_text(
        "<html><body><h1>第一章</h1><p>正文内容一。</p></body></html>",
        encoding="utf-8",
    )

    def fake_extract(path):
        return str(extracted_dir), str(html_file)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    novel = parse_mobi(tmp_path / "book.mobi", "测试书名")

    assert len(novel.chapters) == 1
    assert novel.chapters[0].title == "第一章"
    assert novel.chapters[0].text == "正文内容一。"


def test_parse_mobi_epub_source(tmp_path, monkeypatch):
    from ebooklib import epub as epub_mod

    book = epub_mod.EpubBook()
    book.set_identifier("id123")
    book.set_title("测试电子书")
    book.set_language("zh")

    chapter = epub_mod.EpubHtml(title="第一章", file_name="chap_1.xhtml", lang="zh")
    chapter.content = "<h1>第一章</h1><p>正文内容一。</p>"
    book.add_item(chapter)
    book.toc = (chapter,)
    book.add_item(epub_mod.EpubNcx())
    book.add_item(epub_mod.EpubNav())
    book.spine = ["nav", chapter]

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    epub_path = extracted_dir / "book.epub"
    epub_mod.write_epub(str(epub_path), book)

    def fake_extract(path):
        return str(extracted_dir), str(epub_path)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    novel = parse_mobi(tmp_path / "book.mobi", "测试电子书")

    # parse_epub() also picks up the EPUB's own nav document as a spurious
    # extra "chapter" (pre-existing behavior, out of scope here) -- assert on
    # the real chapter by title instead of exact chapter count.
    real_chapter = next(c for c in novel.chapters if c.title == "第一章")
    assert "正文内容一" in real_chapter.text


def test_parse_mobi_unsupported_inner_format(tmp_path, monkeypatch):
    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    pdf_file = extracted_dir / "book.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 fake print-replica content")

    def fake_extract(path):
        return str(extracted_dir), str(pdf_file)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    with pytest.raises(ParseError):
        parse_mobi(tmp_path / "book.mobi", "测试书名")

    # The temp dir mobi.extract() produced must be cleaned up even on error.
    assert not extracted_dir.exists()


def test_parse_mobi_extract_failure_raises_parse_error(tmp_path, monkeypatch):
    def fake_extract(path):
        raise RuntimeError("corrupted or DRM-protected mobi file")

    monkeypatch.setattr(mobi, "extract", fake_extract)

    with pytest.raises(ParseError):
        parse_mobi(tmp_path / "book.mobi", "测试书名")


def test_parse_upload_dispatches_mobi_extension(tmp_path, monkeypatch):
    from app.pipeline.parse import parse_upload

    extracted_dir = tmp_path / "extracted"
    extracted_dir.mkdir()
    html_file = extracted_dir / "book.html"
    html_file.write_text(
        "<html><body><h1>第一章</h1><p>正文内容。</p></body></html>",
        encoding="utf-8",
    )

    def fake_extract(path):
        return str(extracted_dir), str(html_file)

    monkeypatch.setattr(mobi, "extract", fake_extract)

    mobi_path = tmp_path / "book.mobi"
    mobi_path.write_bytes(b"fake mobi container bytes")

    novel = parse_upload(mobi_path, "book.mobi")

    assert novel.chapters[0].title == "第一章"
