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
