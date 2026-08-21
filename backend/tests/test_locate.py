from app.pipeline.locate import (
    locate_paragraph,
    resolve_source_location,
    split_paragraphs,
)


def test_split_paragraphs_blank_line_delimited():
    text = "第一段第一句。第一段第二句。\n\n第二段内容。\n\n第三段内容。"
    assert split_paragraphs(text) == ["第一段第一句。第一段第二句。", "第二段内容。", "第三段内容。"]


def test_split_paragraphs_falls_back_to_single_newline():
    text = "第一行内容。\n第二行内容。\n第三行内容。"
    assert split_paragraphs(text) == ["第一行内容。", "第二行内容。", "第三行内容。"]


def test_split_paragraphs_falls_back_to_whole_chapter():
    text = "没有任何换行的一整段文字内容。"
    assert split_paragraphs(text) == ["没有任何换行的一整段文字内容。"]


def test_split_paragraphs_empty_text():
    assert split_paragraphs("") == []
    assert split_paragraphs("   \n\n  ") == []


def test_locate_paragraph_exact_substring_match():
    paragraphs = ["贾宝玉在园中读书。", "林黑玉忽然到来，两人相谈甚欢。", "夜幕降临，众人散去。"]
    assert locate_paragraph(paragraphs, "林黑玉忽然到来") == 1


def test_locate_paragraph_fuzzy_near_match():
    paragraphs = ["贾宝玉在园中读书写字。", "林黑玉忽然到来，两人相谈甚欢，情投意合。", "夜幕降临，众人散去。"]
    # Slightly reworded quote (near, not exact) should still resolve via difflib.
    assert locate_paragraph(paragraphs, "林黑玉忽然到来两人相谈甚欢情投意合") == 1


def test_locate_paragraph_below_threshold_returns_none():
    paragraphs = ["贾宝玉在园中读书。", "林黑玉忽然到来。"]
    assert locate_paragraph(paragraphs, "完全不相关的一句话内容") is None


def test_locate_paragraph_empty_quote_or_paragraphs_returns_none():
    assert locate_paragraph(["有内容的段落。"], "") is None
    assert locate_paragraph([], "任意引用") is None


def test_resolve_source_location_with_matched_paragraph():
    paragraphs_by_chapter = {"ch0001": ["贾宝玉在园中读书。", "林黑玉忽然到来。"]}
    loc = resolve_source_location("ch0001", "林黑玉忽然到来", paragraphs_by_chapter)
    assert loc == "ch0001#p1"


def test_resolve_source_location_with_unmatched_paragraph_falls_back_to_chapter():
    paragraphs_by_chapter = {"ch0001": ["贾宝玉在园中读书。"]}
    loc = resolve_source_location("ch0001", "完全不相关的内容", paragraphs_by_chapter)
    assert loc == "ch0001"


def test_resolve_source_location_with_no_chapter_returns_empty_string():
    assert resolve_source_location("", "任意引用", {}) == ""
    assert resolve_source_location(None, "任意引用", {}) == ""
