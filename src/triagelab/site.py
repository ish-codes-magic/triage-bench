"""The static results site (AGENTS.md §17): the committed reports, as web pages.

Every table and figure under `reports/` is already generated from the run registry by a
command. The site adds nothing to them: each page is a list of those Markdown files,
converted and wrapped in one layout (`reports/site.yaml` says which files go where). So
it builds on a fresh checkout with no data and no model, which is what lets CI publish it.

Markdown-to-HTML conversion is a library's job (markdown-it). What is ours is the
assembly, because it is where a static site usually breaks:
  - images are copied next to the pages and their paths rewritten;
  - a link to another report becomes a link to the page that contains it;
  - a link to any other file in the repository becomes a link to it on GitHub.
"""

import html
import posixpath
import re
import shutil
from pathlib import Path, PurePosixPath

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import BaseModel

SPEC = Path("reports/site.yaml")


class Page(BaseModel):
    slug: str  # the file name without .html; "index" is the front page
    title: str  # shown in the navigation
    sources: list[str]  # Markdown files, relative to the repository root, in order


class SiteSpec(BaseModel):
    title: str
    tagline: str
    repo_url: str
    branch: str = "main"
    pages: list[Page]


def load_spec(path: Path) -> SiteSpec:
    return SiteSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def anchor(source: str) -> str:
    """The id of a source file's section on its page."""
    return "src-" + re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")


def asset_name(repo_path: str) -> str:
    """Where an image lands under assets/: its repository path, flattened."""
    return repo_path.replace("/", "__")


def _external(url: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", url)) or url.startswith(("#", "//"))


class _Linker:
    """Rewrites the links and images of one source file."""

    def __init__(self, spec: SiteSpec, root: Path, source: str) -> None:
        self._spec = spec
        self._root = root
        self._dir = posixpath.dirname(source)
        self._page_of = {s: page.slug for page in spec.pages for s in page.sources}
        self.assets: set[str] = set()

    def _repo_path(self, url: str) -> tuple[str, str]:
        path, _, fragment = url.partition("#")
        return posixpath.normpath(posixpath.join(self._dir, path)), fragment

    def link(self, url: str) -> str:
        if _external(url):
            return url
        target, fragment = self._repo_path(url)
        if target in self._page_of:  # another report that is on the site
            return f"{self._page_of[target]}.html#{fragment or anchor(target)}"
        if (self._root / target).exists():  # anything else in the repository
            kind = "tree" if (self._root / target).is_dir() else "blob"
            suffix = f"#{fragment}" if fragment else ""
            return f"{self._spec.repo_url}/{kind}/{self._spec.branch}/{target}{suffix}"
        return url

    def image(self, url: str) -> str:
        if _external(url):
            return url
        target, _ = self._repo_path(url)
        if not (self._root / target).is_file():
            return url
        self.assets.add(target)
        return f"assets/{asset_name(target)}"

    def rewrite(self, tokens: list[Token]) -> None:
        for token in tokens:
            if token.type == "link_open":
                token.attrSet("href", self.link(str(token.attrGet("href") or "")))
            elif token.type == "image":
                token.attrSet("src", self.image(str(token.attrGet("src") or "")))
            if token.children:
                self.rewrite(token.children)


def render_source(spec: SiteSpec, root: Path, source: str) -> tuple[str, set[str]]:
    """One Markdown file as an HTML section, and the images it needs."""
    md = MarkdownIt("commonmark").enable("table")
    text = (root / source).read_bytes().decode("utf-8")
    tokens = md.parse(text)
    linker = _Linker(spec, root, source)
    linker.rewrite(tokens)
    body = md.renderer.render(tokens, md.options, {})
    # Wide tables scroll inside their own box instead of stretching the page.
    body = body.replace("<table>", '<div class="table"><table>').replace(
        "</table>", "</table></div>"
    )
    origin = f"{spec.repo_url}/blob/{spec.branch}/{source}"
    section = (
        f'<section id="{anchor(source)}">\n{body}'
        f'<p class="origin">Source: <a href="{html.escape(origin)}">{html.escape(source)}</a></p>\n'
        "</section>\n"
    )
    return section, linker.assets


_STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --dim: #59636e; --bg: #fff; --line: #d1d9e0;
  --soft: #f6f8fa; --link: #0969da; }
@media (prefers-color-scheme: dark) { :root { --fg: #e6edf3; --dim: #9198a1; --bg: #0d1117;
  --line: #3d444d; --soft: #151b23; --link: #4493f8; } }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--fg); background: var(--bg); }
header, main { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
header { padding-top: 22px; border-bottom: 1px solid var(--line); }
header .title { font-size: 22px; font-weight: 650; }
header .tagline { color: var(--dim); margin-left: 10px; }
nav { margin: 12px 0 0; display: flex; flex-wrap: wrap; gap: 4px 18px; }
nav a { padding: 6px 0 10px; color: var(--dim); text-decoration: none;
  border-bottom: 2px solid transparent; }
nav a.here { color: var(--fg); border-color: var(--link); }
a { color: var(--link); }
section { padding: 8px 0 22px; border-bottom: 1px solid var(--line); }
h1 { font-size: 26px; margin: 26px 0 12px; } h2 { font-size: 20px; margin: 26px 0 10px; }
h3 { font-size: 17px; margin: 22px 0 8px; }
.table { overflow-x: auto; margin: 12px 0; }
table { border-collapse: collapse; font-size: 14px; }
th, td { border: 1px solid var(--line); padding: 5px 9px; text-align: left; vertical-align: top; }
th { background: var(--soft); }
code { background: var(--soft); padding: 1px 5px; border-radius: 4px; font-size: 13.5px; }
pre { background: var(--soft); padding: 14px; overflow-x: auto; border-radius: 6px;
  line-height: 1.4; }
pre code { background: none; padding: 0; font-size: 13px; }
img { max-width: 100%; height: auto; }
blockquote { margin: 12px 0; padding: 2px 14px; border-left: 3px solid var(--line);
  color: var(--dim); }
.origin { color: var(--dim); font-size: 13px; }
footer { max-width: 1080px; margin: 0 auto; padding: 18px 20px 40px; color: var(--dim);
  font-size: 13px; }
"""


def render_page(spec: SiteSpec, page: Page, sections: list[str]) -> str:
    nav = "\n".join(
        f'<a href="{p.slug}.html"{" class=" + chr(34) + "here" + chr(34) if p is page else ""}>'
        f"{html.escape(p.title)}</a>"
        for p in spec.pages
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(page.title)} · {html.escape(spec.title)}</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n"
        f'<header><span class="title">{html.escape(spec.title)}</span>'
        f'<span class="tagline">{html.escape(spec.tagline)}</span>\n<nav>\n{nav}\n</nav></header>\n'
        f"<main>\n{''.join(sections)}</main>\n"
        f'<footer>Built from the committed reports of <a href="{html.escape(spec.repo_url)}">'
        f"{html.escape(PurePosixPath(spec.repo_url).name)}</a>. Every table and figure is "
        "generated by a command from recorded runs.</footer>\n</body>\n</html>\n"
    )


def build_site(spec: SiteSpec, root: Path, out: Path) -> list[Path]:
    """Write every page and the images they use under `out`; returns the pages written."""
    missing = [s for page in spec.pages for s in page.sources if not (root / s).is_file()]
    if missing:
        raise FileNotFoundError(f"site sources not found: {missing}")
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    written: list[Path] = []
    assets: set[str] = set()
    for page in spec.pages:
        sections: list[str] = []
        for source in page.sources:
            section, used = render_source(spec, root, source)
            sections.append(section)
            assets |= used
        target = out / f"{page.slug}.html"
        target.write_bytes(render_page(spec, page, sections).encode("utf-8"))
        written.append(target)
    for asset in sorted(assets):
        shutil.copyfile(root / asset, out / "assets" / asset_name(asset))
    (out / ".nojekyll").write_bytes(b"")  # GitHub Pages: serve the files as they are
    return written
