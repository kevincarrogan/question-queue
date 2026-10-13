from questionqueue.tui.highlight import extra_highlights


def names(text: str, row: int) -> set[str]:
    return {name for _, _, name in extra_highlights(text)[row]}


def test_inline_markup() -> None:
    text = "Some **bold**, *italic*, `code` and [a link](https://example.com)"
    assert names(text, 0) == {"bold", "italic", "inline_code", "link.label", "link.uri"}


def test_file_references_look_like_links() -> None:
    assert extra_highlights("See foo/bar/core.py:30")[0] == [(4, 22, "link.uri")]


def test_columns_are_bytes() -> None:
    # TextArea counts bytes: "é" is two.
    assert extra_highlights("é `x`")[0] == [(3, 6, "inline_code")]


def test_fenced_code_is_coloured_by_its_language() -> None:
    text = "Subject\n```py\ndef f():\n    return 'hi'\n```\n**after**"
    assert "keyword.function" in names(text, 2)
    assert {"keyword.return", "string"} <= names(text, 3)
    assert names(text, 5) == {"bold"}  # markup again after the fence


def test_no_markup_inside_a_fence() -> None:
    text = "```\n**not bold**\n```"
    assert 1 not in extra_highlights(text)


def test_an_unknown_language_is_left_alone() -> None:
    assert 1 not in extra_highlights("```klingon\nqapla'\n```")


def test_an_unclosed_fence_is_coloured_as_you_type() -> None:
    assert "keyword.function" in names("```python\ndef", 1)
