from contextpull.parse import Code, Heading, ListBlock, Paragraph, Table, parse_markdown, parse_text


def test_front_matter_headings_and_paragraphs():
    p = parse_markdown("---\ntitle: My Doc\n---\n\n# Ignored H1\n\nIntro text.\n\n## Part\n\nBody.\n")
    assert p.title == "My Doc"
    kinds = [type(b).__name__ for b in p.blocks]
    assert kinds == ["Heading", "Paragraph", "Heading", "Paragraph"]
    assert p.blocks[0].level == 1 and p.blocks[2].level == 2


def test_fence_is_one_block_even_with_blank_lines_and_hashes():
    md = "# T\n\n```python\n# not a heading\n\nprint(1)\n```\n\nafter\n"
    p = parse_markdown(md)
    code = [b for b in p.blocks if isinstance(b, Code)]
    assert len(code) == 1 and code[0].lang == "python" and "# not a heading" in code[0].raw
    assert sum(isinstance(b, Heading) for b in p.blocks) == 1


def test_pipe_table_parsed_with_header_and_rows():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\ntext\n"
    p = parse_markdown(md)
    t = p.blocks[0]
    assert isinstance(t, Table) and t.header.startswith("| a") and len(t.rows) == 2
    assert isinstance(p.blocks[1], Paragraph)


def test_setext_and_lists():
    p = parse_markdown("Title\n=====\n\n- one\n- two\n\nSub\n---\n\npara\n")
    assert isinstance(p.blocks[0], Heading) and p.blocks[0].level == 1
    assert isinstance(p.blocks[1], ListBlock)
    assert isinstance(p.blocks[2], Heading) and p.blocks[2].level == 2
    assert p.title == "Title"


def test_plain_text_headings():
    p = parse_text("Release Notes\n\nVersion 2.1 adds things.\n\nKnown Issues\n\nSomething is off.\n")
    assert [type(b).__name__ for b in p.blocks] == ["Heading", "Paragraph", "Heading", "Paragraph"]
    assert p.title == "Release Notes"


def test_fence_with_info_string_and_indentation():
    md = (
        "# T\n\n```toml title=\"pyproject.toml\"\n[tool]\nx = 1\n```\n\n## Next\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "=== \"Tab\"\n\n    ```console\n    $ run\n    ```\n\nend\n"
    )
    p = parse_markdown(md)
    kinds = [type(b).__name__ for b in p.blocks]
    assert kinds == ["Heading", "Code", "Heading", "Table", "Paragraph", "Code", "Paragraph"]
    assert p.blocks[1].lang == "toml"
    assert p.blocks[5].lang == "console" and p.blocks[5].raw.strip().endswith("```")
