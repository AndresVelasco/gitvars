"""Build demo/index.html from the README and layout, leaving Git placeholders intact."""

import argparse
from html import escape
from pathlib import Path
import re

from gitvars.errors import GitvarsError
from gitvars.files import atomic_write
from gitvars.render import NAMES


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
    return tokens


def literal_variables(html: str) -> str:
    """Keep documented tokens visible without substituting them during rendering."""
    pattern = r"__git_(?:" + "|".join(NAMES) + r")__"
    return re.sub(pattern, lambda match: "&#95;" + match.group()[1:], html)


def variable_table(parser, readme: str) -> str:
    # Reuse the explanations in the README's placeholder reference.
    variables = re.findall(r"^\| `(__git_([a-z_]+)__)` \| (.+) \|$", readme, re.MULTILINE)
    if len(variables) != len(NAMES) or {name for _, name, _ in variables} != set(NAMES):
        raise ValueError("The README placeholder reference must document every supported variable exactly once")
    rows = []
    for literal, name, explanation in variables:
        rows.append(
            f'<tr data-variable="{name}"><th scope="row"><code>{literal_variables(escape(literal))}</code></th>'
            f'<td><code class="value">{literal}</code></td>'
            f'<td>{literal_variables(parser.renderInline(explanation))}</td></tr>'
        )
    return (
        '<section id="gitvars-demo" class="live-demo" aria-label="Live gitvars demonstration">\n'
        '<p>What you are looking at is a demo of gitvars. This page contains the README '
        'with this additional table: each literal variable is paired with the value '
        'gitvars replaces it with from this build’s Git checkout. Unavailable values '
        'produce empty cells. The file URL is empty because the generated HTML '
        'is not committed to Git.</p>\n'
        '<table><thead><tr><th scope="col">Literal variable</th>'
        '<th scope="col">Replaced variable</th><th scope="col">Explanation</th></tr></thead>\n'
        '<tbody>\n' + '\n'.join(rows) + '\n</tbody></table>\n</section>\n'
    )


def render_template(readme: str, shell: str) -> str:
    if shell.count(MARKER) != 1:
        raise ValueError("The demo shell must contain one README content marker")
    parser = markdown_parser()
    tokens = readme_tokens(parser, readme)
    insertion = next(
        (index for index, token in enumerate(tokens) if token.type == "heading_open" and token.tag == "h2"),
        len(tokens),
    )
    body = (
        literal_variables(parser.renderer.render(tokens[:insertion], parser.options, {}))
        + variable_table(parser, readme)
        + literal_variables(parser.renderer.render(tokens[insertion:], parser.options, {}))
    )
    return shell.replace(MARKER, body)


def build(project: Path | None = None) -> Path:
    project = project or Path(__file__).resolve().parents[1]
    readme = project / "README.md"
    template = render_template(
        readme.read_text(encoding="utf-8"),
        (project / "demo/layout.html").read_text(encoding="utf-8"),
    )
    destination = project / "demo/index.html"
    atomic_write(destination, template.encode("utf-8"), 0o644)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        print(f"Built {build()}")
    except KeyboardInterrupt:
        return 0
    except (GitvarsError, OSError, ValueError) as exc:
        print(f"Demo build failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
