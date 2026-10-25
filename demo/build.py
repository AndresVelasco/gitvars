"""Build the README as static HTML, adding one live Git-variable table."""

from html import escape
from pathlib import Path
import re

from gitvars.config import Config
from gitvars.errors import GitvarsError
from gitvars.files import atomic_write
from gitvars.git import collect_snapshot, repository_root
from gitvars.render import NAMES, Renderer


MARKER = "<!-- README_CONTENT -->"


def markdown_parser():
    try:
        from markdown_it import MarkdownIt
    except ImportError as exc:
        raise GitvarsError("Install demo build dependencies: python -m pip install -e '.[demo]'") from exc
    return MarkdownIt("commonmark", {"html": False}).enable("table")


def readme_tokens(parser, readme: str):
    tokens = parser.parse(readme)
    headings = set()
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            text = "".join(child.content for child in tokens[index + 1].children or [])
            base = re.sub(r"[^\w\s-]", "", text.lower()).strip().replace(" ", "-")
            anchor = base
            suffix = 1
            while anchor in headings:
                anchor = f"{base}-{suffix}"
                suffix += 1
            headings.add(anchor)
            token.attrSet("id", anchor)
        for child in token.children or []:
            if child.type == "link_open" and child.attrGet("href") == "demo/index.html":
                child.attrSet("href", "index.html")
    return tokens


def variable_table(parser, readme: str, values: dict[str, str]) -> str:
    # Reuse the explanations in the README's placeholder reference.
    variables = re.findall(r"^\| `(__git_([a-z_]+)__)` \| (.+) \|$", readme, re.MULTILINE)
    if len(variables) != len(NAMES) or {name for _, name, _ in variables} != set(NAMES):
        raise ValueError("The README placeholder reference must document every supported variable exactly once")
    renderer = Renderer("__git_", escape=True)
    rows = []
    for literal, name, explanation in variables:
        replaced, _ = renderer.render(literal, values)
        displayed = (
            f'<code class="value">{escape(replaced)}</code>' if replaced
            else '<span class="empty">Empty</span>'
        )
        rows.append(
            f'<tr data-variable="{name}"><th scope="row"><code>{escape(literal)}</code></th>'
            f'<td>{displayed}</td><td>{parser.renderInline(explanation)}</td></tr>'
        )
    return (
        '<section id="gitvars-demo" class="live-demo" aria-label="Live gitvars demonstration">\n'
        '<p>What you are looking at is a demo of gitvars. This page contains the README '
        'with this additional table: each literal variable is paired with the value '
        'gitvars replaces it with from this build’s Git checkout. Unavailable values '
        'are marked as “Empty”. The source-file permalink points to README.md.</p>\n'
        '<table><thead><tr><th scope="col">Literal variable</th>'
        '<th scope="col">Replaced variable</th><th scope="col">Explanation</th></tr></thead>\n'
        '<tbody>\n' + '\n'.join(rows) + '\n</tbody></table>\n</section>\n'
    )


def render_page(readme: str, shell: str, values: dict[str, str]) -> str:
    if shell.count(MARKER) != 1:
        raise ValueError("The demo shell must contain one README content marker")
    parser = markdown_parser()
    tokens = readme_tokens(parser, readme)
    insertion = next(
        (index for index, token in enumerate(tokens) if token.type == "heading_open" and token.tag == "h2"),
        len(tokens),
    )
    body = (
        parser.renderer.render(tokens[:insertion], parser.options, {})
        + variable_table(parser, readme, values)
        + parser.renderer.render(tokens[insertion:], parser.options, {})
    )
    return shell.replace(MARKER, body)


def build(project: Path | None = None, destination: Path | None = None) -> Path:
    project = project or Path(__file__).resolve().parents[1]
    readme = project / "README.md"
    root = repository_root(readme)
    snapshot = collect_snapshot(root, Config())
    html = render_page(
        readme.read_text(encoding="utf-8"),
        (project / "demo/index.html").read_text(encoding="utf-8"),
        snapshot.for_file(readme.relative_to(root).as_posix()),
    )
    destination = destination or project / "build/demo/index.html"
    atomic_write(destination, html.encode("utf-8"), 0o644)
    return destination


if __name__ == "__main__":
    try:
        print(f"Built {build()}")
    except (GitvarsError, OSError, ValueError) as exc:
        print(f"Demo build failed: {exc}")
        raise SystemExit(2)
