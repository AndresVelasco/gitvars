from html.parser import HTMLParser
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from demo.build import build, markdown_parser, render_template
from gitvars.config import Config
from gitvars.git import collect_snapshot
from gitvars.render import NAMES


PROJECT = Path(__file__).resolve().parents[1]


class Content(HTMLParser):
    """Capture README text separately from the inserted demonstration."""

    def __init__(self):
        super().__init__()
        self.in_main = False
        self.demo_depth = 0
        self.text = []
        self.rows = []
        self.cell = None
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main":
            self.in_main = True
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href"))
        if self.demo_depth:
            self.demo_depth += 1
        elif attrs.get("id") == "gitvars-demo":
            self.demo_depth = 1
        if self.demo_depth:
            if tag == "tr":
                self.rows.append([])
            if tag in {"th", "td"}:
                self.cell = []

    def handle_endtag(self, tag):
        if self.demo_depth:
            if tag in {"th", "td"} and self.cell is not None:
                self.rows[-1].append("".join(self.cell))
                self.cell = None
            self.demo_depth -= 1
        if tag == "main":
            self.in_main = False

    def handle_data(self, data):
        if self.demo_depth:
            if self.cell is not None:
                self.cell.append(data)
        elif self.in_main:
            self.text.append(data)

    def normalized_text(self):
        return re.sub(r"\s+", " ", "".join(self.text)).strip()


@unittest.skipUnless(importlib.util.find_spec("markdown_it"), "Install the optional demo dependencies")
class DemoTests(unittest.TestCase):
    def setUp(self):
        self.readme = (PROJECT / "README.md").read_text(encoding="utf-8")
        self.shell = (PROJECT / "demo/layout.html").read_text(encoding="utf-8")

    def test_readme_content_is_identical_except_for_inserted_demo(self):
        for readme in (self.readme, self.readme + "\n## A future section\n\nNew documentation.\n"):
            with self.subTest(readme_changed=readme != self.readme):
                expected = Content()
                expected.feed("<main>" + markdown_parser().render(readme) + "</main>")
                actual = Content()
                html = render_template(readme, self.shell)
                actual.feed(html)
                self.assertEqual(actual.normalized_text(), expected.normalized_text())
                self.assertLess(html.index('id="gitvars-demo"'), html.index('id="why-gitvars-exists"'))
                self.assertLess(html.index("including links to the exact commit and source file."), html.index('id="gitvars-demo"'))
                self.assertNotIn("<script", html)

    def test_table_has_three_columns_and_every_variable(self):
        page = Content()
        html = render_template(self.readme, self.shell)
        page.feed(html)
        self.assertEqual(page.rows[0], ["Literal variable", "Replaced variable", "Explanation"])
        self.assertEqual(len(page.rows), len(NAMES) + 1)
        rows = {row[0]: row for row in page.rows[1:]}
        for name in NAMES:
            row = rows[f"__git_{name}__"]
            self.assertEqual(len(row), 3)
            self.assertEqual(row[1], f"__git_{name}__")
            self.assertTrue(row[2])

    def test_readme_links_resolve_in_generated_page(self):
        page = Content()
        page.feed(render_template(self.readme, self.shell))
        self.assertIn("#configuration", page.links)
        self.assertIn("configuration", page.ids)
        self.assertIn("https://andresvelasco.github.io/gitvars/", page.links)

    def test_missing_documented_variable_fails_instead_of_incomplete_table(self):
        readme = self.readme.replace("| `__git_commit__` | Full `HEAD` commit SHA |", "")
        with self.assertRaisesRegex(ValueError, "every supported variable"):
            render_template(readme, self.shell)

    def make_project(self, git_repo=True):
        temporary = tempfile.TemporaryDirectory(prefix="gitvars-demo-test-")
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name).resolve()
        (project / "demo").mkdir()
        (project / "README.md").write_text(self.readme, encoding="utf-8")
        (project / ".gitignore").write_text("build/\n/demo/index.html\n", encoding="utf-8")
        (project / ".gitvars").write_text((PROJECT / ".gitvars").read_text(), encoding="utf-8")
        (project / "demo/layout.html").write_text(self.shell, encoding="utf-8")
        if not git_repo:
            return project
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        commands = (
            ("init", "-b", "main"),
            ("config", "user.name", "Demo Test"),
            ("config", "user.email", "demo@example.test"),
            ("remote", "add", "origin", "https://github.com/example/demo.git"),
            ("add", "."),
            ("commit", "-m", 'Demo <script>example</script> & "quotes"\n\nLiteral __git_branch__\n'),
        )
        for arguments in commands:
            subprocess.run(["git", *arguments], cwd=project, env=env, check=True, capture_output=True)
        return project

    def test_build_then_cli_renders_all_values_without_changing_source(self):
        project = self.make_project()
        template = build(project)
        self.assertEqual(template, project / "demo/index.html")
        original = template.read_bytes()
        self.assertIn(b'<code class="value">__git_commit__</code>', original)
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(PYTHONPATH=str(PROJECT / "src"), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        command = [
            sys.executable, "-m", "gitvars", "render", "demo/index.html",
            "--html-escape", "--output-dir", "build", "--force",
        ]
        subprocess.run(command, cwd=project, env=env, check=True, capture_output=True)
        destination = project / "build/demo/index.html"
        html = destination.read_text(encoding="utf-8")
        self.assertIn('id="gitvars-demo"', html)
        self.assertNotIn("<!-- README_CONTENT -->", html)
        page = Content()
        page.feed(html)
        rows = {row[0]: row for row in page.rows[1:]}
        values = collect_snapshot(project, Config()).for_file("demo/index.html")
        for name in NAMES:
            self.assertEqual(rows[f"__git_{name}__"][1], values[name])
        self.assertEqual(rows["__git_file_url__"][1], "")
        self.assertIn("&lt;script&gt;example&lt;/script&gt;", html)
        self.assertNotIn("<script>example</script>", html)
        self.assertEqual(template.read_bytes(), original)
        self.assertEqual((project / "README.md").read_text(encoding="utf-8"), self.readme)
        self.assertEqual((project / "demo/layout.html").read_text(encoding="utf-8"), self.shell)
        self.assertEqual(
            subprocess.check_output(
                ["git", "check-ignore", "demo/index.html", "build/demo/index.html"], cwd=project,
            ).splitlines(),
            [b"demo/index.html", b"build/demo/index.html"],
        )
        self.assertEqual(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=project), b"",
        )
        # Repeating the two commands rebuilds from placeholders, without a second
        # substitution of token-like text in the inserted commit message.
        build(project)
        subprocess.run(command, cwd=project, env=env, check=True, capture_output=True)
        self.assertEqual(destination.read_text(encoding="utf-8"), html)

    def test_rebuild_uses_updated_readme(self):
        project = self.make_project()
        build(project)
        (project / "README.md").write_text(self.readme + "\nUpdated documentation.\n", encoding="utf-8")
        output = build(project)
        self.assertIn("Updated documentation.", output.read_text(encoding="utf-8"))

    def test_build_needs_no_git_repository_and_preserves_placeholders(self):
        project = self.make_project(git_repo=False)
        template = build(project).read_text(encoding="utf-8")
        self.assertEqual(template.count("__git_commit__"), 1)
        page = Content()
        page.feed(template)
        self.assertEqual(len(page.rows), len(NAMES) + 1)
        for literal, replacement, explanation in page.rows[1:]:
            self.assertEqual(replacement, literal)
            self.assertTrue(explanation)
