from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import re
import unittest

from demo.build import markdown_parser, render_page
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
        self.shell = (PROJECT / "demo/index.html").read_text(encoding="utf-8")
        self.values = {name: f"rendered-{name}" for name in NAMES}

    def test_readme_content_is_identical_except_for_inserted_demo(self):
        for readme in (self.readme, self.readme + "\n## A future section\n\nNew documentation.\n"):
            with self.subTest(readme_changed=readme != self.readme):
                expected = Content()
                expected.feed("<main>" + markdown_parser().render(readme) + "</main>")
                actual = Content()
                html = render_page(readme, self.shell, self.values)
                actual.feed(html)
                self.assertEqual(actual.normalized_text(), expected.normalized_text())
                self.assertLess(html.index('id="gitvars-demo"'), html.index('id="why-gitvars-exists"'))
                self.assertLess(html.index("including links to the exact commit and source file."), html.index('id="gitvars-demo"'))
                self.assertNotIn("<script", html)

    def test_table_has_three_columns_and_every_variable(self):
        self.values["commit_message"] = 'A <script>example</script> & "quotes"\nLiteral __git_branch__\n'
        self.values["tag"] = ""
        page = Content()
        html = render_page(self.readme, self.shell, self.values)
        page.feed(html)
        self.assertEqual(page.rows[0], ["Literal variable", "Replaced variable", "Explanation"])
        self.assertEqual(len(page.rows), len(NAMES) + 1)
        rows = {row[0]: row for row in page.rows[1:]}
        for name in NAMES:
            row = rows[f"__git_{name}__"]
            self.assertEqual(len(row), 3)
            self.assertEqual(row[1], self.values[name] or "Empty")
            self.assertTrue(row[2])
        self.assertIn("&lt;script&gt;example&lt;/script&gt;", html)
        self.assertNotIn("<script>example</script>", html)

    def test_readme_links_resolve_in_generated_page(self):
        page = Content()
        page.feed(render_page(self.readme, self.shell, self.values))
        self.assertIn("#configuration", page.links)
        self.assertIn("configuration", page.ids)
        self.assertIn("index.html", page.links)
        self.assertNotIn("demo/index.html", page.links)

    def test_missing_documented_variable_fails_instead_of_incomplete_table(self):
        readme = self.readme.replace("| `__git_commit__` | Full `HEAD` commit SHA |", "")
        with self.assertRaisesRegex(ValueError, "every supported variable"):
            render_page(readme, self.shell, self.values)
