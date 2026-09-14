"""Build the static site into site/ from the repo's Markdown docs and page templates.
Usage: uv run --with markdown python scripts/build_site.py
Output is committed; GitHub Pages deploys site/ on push (.github/workflows/pages.yml)."""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = ROOT / "site"
SRC = OUT / "src"
BASE = "/contextpull"  # GitHub Pages project path

FONTS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700&family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap">'


def chrome(title: str, body: str, active: str, depth: int = 0, extra_head: str = "", description: str = "") -> str:
    rel = "../" * depth
    links = [("index.html", "ContextPull", "home"), ("demo.html", "Demo", "demo"), ("docs/index.html", "Docs", "docs"), ("blog/index.html", "Blog", "blog"), ("ragbisect.html", "ragbisect", "ragbisect")]
    nav = "".join(f'<a href="{rel}{h}"{" class=\"active\"" if k == active else ""}>{t}</a>' for h, t, k in links)
    nav += '<a href="https://github.com/mi2arun/contextpull">GitHub</a>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title><meta name="description" content="{html.escape(description or 'Pull, don’t push: exact document sections on demand for LLM agents. MCP server, zero-dependency Python core, Node reader.')}">
{FONTS}<link rel="stylesheet" href="{rel}site.css">{extra_head}
</head><body>
<div class="nav"><div class="wrap"><a class="brand" href="{rel}index.html">ContextPull <small style="color:var(--muted);font-weight:500;font-size:13px"> · pull, don’t push</small></a><div class="nav-links">{nav}</div></div></div>
{body}
<footer><div class="wrap"><span>MIT · © 2026 Arunkumar S</span><a href="https://github.com/mi2arun/contextpull">github.com/mi2arun/contextpull</a><a href="https://pypi.org/project/contextpull/">PyPI</a><a href="https://www.npmjs.com/package/contextpull">npm</a><a href="https://github.com/mi2arun/ragbisect">ragbisect</a></div></footer>
</body></html>"""


# ---------------------------------------------------------------- markdown docs

def render_md(text: str, link_map: dict[str, str]) -> str:
    blocks: list[str] = []

    def stash(m):
        blocks.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks)-1}\n\n"

    text = re.sub(r"```mermaid\n(.*?)```", stash, text, flags=re.S)

    def relink(m):
        target = m.group(1)
        name = target.split("#")[0]
        anchor = ("#" + target.split("#", 1)[1]) if "#" in target else ""
        stem = Path(name).stem if name.endswith(".md") else name.rstrip("/")
        if stem in link_map:
            return f"]({link_map[stem]}{anchor})"
        return m.group(0)

    text = re.sub(r"\]\(((?:\./)?[\w\-./]+?\.md(?:#[\w\-]+)?|adr/(?:\d{3}[\w\-]*\.md)?)\)", relink, text)
    text = re.sub(r"\]\(adr/\)", "](adr.html)", text)
    text = re.sub(r"\]\(adr/(\d{3})[^)]*\)", lambda m: f"](adr.html#adr-{m.group(1)})", text)
    text = re.sub(r"\]\((\d{3})-[a-z0-9-]+\.md\)", lambda m: f"](adr.html#adr-{m.group(1)})", text)
    h = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists", "toc"])
    for i, b in enumerate(blocks):
        h = h.replace(f"<p>MERMAIDBLOCK{i}</p>", f'<pre class="mermaid">{html.escape(b)}</pre>')
    return h.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")


DOC_PAGES = [
    ("index", "README.md", "Overview"),
    ("architecture", "architecture.md", "Architecture"),
    ("design", "design.md", "Design document"),
    ("system-design", "system-design.md", "System design"),
    ("tool-reference", "tool-reference.md", "Tool reference"),
    ("evaluation", "evaluation.md", "Evaluation"),
    ("testing", "testing.md", "Testing"),
    ("embedding", "embedding.md", "Embedding in your product"),
    ("roadmap", "roadmap.md", "Roadmap"),
    ("sdk-plan", "sdk-plan.md", "Multi-language SDK plan"),
    ("store-format", "store-format.md", "Store format contract"),
]

MERMAID = '<script type="module">import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs"; mermaid.initialize({startOnLoad:true, theme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "neutral"});</script>'


def build_docs() -> None:
    (OUT / "docs").mkdir(parents=True, exist_ok=True)
    link_map = {Path(md).stem if md != "README.md" else "README": f"{slug}.html" for slug, md, _ in DOC_PAGES}
    link_map["README"] = "index.html"
    adrs = sorted((DOCS / "adr").glob("0*.md"))
    nav_items = [(slug, title) for slug, _, title in DOC_PAGES] + [("adr", "Decision records")]

    def sidebar(active: str) -> str:
        items = "".join(f'<a href="{s}.html"{" class=\"active\"" if s == active else ""}>{t}</a>' for s, t in nav_items)
        adr_links = "".join(f'<a href="adr.html#adr-{p.name[:3]}" style="padding-left:22px;font-size:13px">{p.name[:3]} · {re.match(r"# ADR \d{3} — (.*)", p.read_text()).group(1)}</a>' for p in adrs) if active == "adr" else ""
        return f'<nav><div class="grp">documents</div>{items}{adr_links}</nav>'

    for slug, md, title in DOC_PAGES:
        text = (DOCS / md).read_text()
        text = re.sub(r"^# .*\n", "", text, count=1)
        body = f'<div class="wrap docs">{sidebar(slug)}<article class="doc"><div class="eyebrow">document</div><h1>{title}</h1>{render_md(text, link_map)}</article></div>'
        (OUT / "docs" / f"{slug}.html").write_text(chrome(f"{title} · ContextPull docs", body, "docs", depth=1, extra_head=MERMAID))

    parts = ['<div class="eyebrow">decision records</div><h1>Decision records</h1><p>One page per decision that would be expensive to reverse: context, decision, consequences, alternatives.</p>']
    for p in adrs:
        num = p.name[:3]
        text = p.read_text()
        m = re.match(r"# ADR (\d{3}) — (.*)\n", text)
        parts.append(f'<article id="adr-{num}" class="adr"><h2><span class="num">ADR {num}</span>{html.escape(m.group(2))}</h2>{render_md(text[m.end():], link_map)}</article>')
    body = f'<div class="wrap docs">{sidebar("adr")}<article class="doc">{"".join(parts)}</article></div>'
    (OUT / "docs" / "adr.html").write_text(chrome("Decision records · ContextPull docs", body, "docs", depth=1))


# ---------------------------------------------------------------------- pages

def build_index() -> None:
    body = (SRC / "index-body.html").read_text()
    (OUT / "index.html").write_text(chrome("ContextPull — pull, don’t push", body, "home"))


def build_ragbisect() -> None:
    body = (SRC / "ragbisect-body.html").read_text()
    (OUT / "ragbisect.html").write_text(chrome("ragbisect — bisect a RAG pipeline to find the broken stage", body, "ragbisect",
                                        description="ragbisect builds its own eval set from your corpus and scores retrieval and ranking stage by stage, so it can tell you which stage is broken."))


def build_demo() -> None:
    src = (SRC / "demo-body.html").read_text()
    # The demo carries its own <title> and <style>; keep them, wrap in the site chrome.
    head_extra = re.search(r"(<link rel=\"preconnect\".*?)<style>", src, re.S)
    style = re.search(r"<style>(.*?)</style>", src, re.S).group(1)
    inner = src.split("</style>", 1)[1]
    body = f'<style>{style}\nbody{{padding-block:0 0}} .wrap{{max-width:1080px}}</style>{inner}'
    (OUT / "demo.html").write_text(chrome("ContextPull demo — push vs pull", body, "demo", description="Watch one comparison question go through classic push RAG and ContextPull's pull loop side by side."))


def build_blog() -> None:
    (OUT / "blog").mkdir(parents=True, exist_ok=True)
    posts = sorted((SRC / "blog").glob("*.md"), reverse=True)
    items = []
    for md in posts:
        text = md.read_text()
        m = re.match(r"# (.*)\n", text)
        title = m.group(1)
        date = md.name[:10]
        slug = md.stem[11:]
        body_md = text[m.end():]
        summary = re.search(r"^\*(.*?)\*\s*$", body_md, re.M)
        html_body = render_md(body_md, {})
        body = f'<div class="wrap docs" style="grid-template-columns: minmax(0, 1fr); max-width: 860px"><article class="doc"><div class="eyebrow">{date}</div><h1>{html.escape(title)}</h1>{html_body}</article></div>'
        (OUT / "blog" / f"{slug}.html").write_text(chrome(f"{title} · ContextPull", body, "blog", depth=1, description=summary.group(1)[:300] if summary else title))
        items.append(f'<li><div class="eyebrow">{date}</div><h3><a href="{slug}.html">{html.escape(title)}</a></h3>{f"<p>{html.escape(summary.group(1))}</p>" if summary else ""}</li>')
    body = f'<div class="wrap" style="max-width: 860px; padding-block: 48px 80px"><div class="eyebrow">blog</div><h1 style="margin: 6px 0 28px">Notes from measuring</h1><ul class="plain" style="list-style: none; padding: 0; display: grid; gap: 28px">{"".join(items)}</ul></div>'
    (OUT / "blog" / "index.html").write_text(chrome("Blog · ContextPull", body, "blog", depth=1))


def main() -> None:
    OUT.mkdir(exist_ok=True)
    shutil.copy(SRC / "site.css", OUT / "site.css")
    (OUT / ".nojekyll").write_text("")
    build_docs()
    build_index()
    build_ragbisect()
    build_demo()
    build_blog()
    n = len(list(OUT.rglob("*.html")))
    print(f"built {n} pages into {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
