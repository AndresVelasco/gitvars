import argparse
from pathlib import Path
import tempfile
import unittest

from gitvars.config import Config, Selector, discover_config, load_config, match_glob
from gitvars.errors import GitvarsError


class GlobTests(unittest.TestCase):
    def test_repository_relative_globs(self):
        cases = [
            ("page.md", "*.md", True),
            ("docs/page.md", "*.md", False),
            ("page.md", "**/*.md", True),
            ("docs/nested/page.md", "**/*.md", True),
            ("demo/index.html", "demo/**/*.html", True),
            ("build", "build/**", True),
            ("build/nested/file.sql", "build/**", True),
            ("other/build/file.sql", "build/**", False),
            ("test.sql", "t?st.[sq]*", True),
            ("README.MD", "**/*.md", False),
        ]
        for path, pattern, expected in cases:
            with self.subTest(path=path, pattern=pattern):
                self.assertEqual(match_glob(path, pattern), expected)

    def test_regex_exclusions_and_excluded_ancestors(self):
        selector = Selector(Config(exclude=("build",), exclude_regex=(r"(^|/)README\.md$",)))
        self.assertTrue(selector.excluded("docs/README.md"))
        self.assertTrue(selector.excluded("build/nested/input.sql"))
        self.assertFalse(selector.excluded("docs/page.md"))


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = argparse.Namespace(
            config=None, prefix=None, escape=None,
            include=None, exclude=None, exclude_regex=None,
        )

    def write(self, text):
        (self.root / ".gitvars").write_text(text, encoding="utf-8")

    def test_nearest_upward_configuration(self):
        nested = self.root / "templates" / "pages"
        nested.mkdir(parents=True)
        self.write('prefix = "outer_"')
        (nested.parent / ".gitvars").write_text('prefix = "inner_"')
        self.assertEqual(discover_config(nested), nested.parent / ".gitvars")
        self.assertEqual(load_config(nested, self.args).prefix, "inner_")

    def test_cli_extends_lists_and_overrides_scalars(self):
        self.write('include = ["**/*.sql"]\nexclude = ["build/**"]\nescape = false\nprefix = "old_"')
        self.args.include = ["**/*.yml"]
        self.args.exclude = ["docs/**"]
        self.args.escape = True
        self.args.prefix = "new_"
        config = load_config(self.root, self.args)
        self.assertEqual(config.include, ("**/*.sql", "**/*.yml"))
        self.assertEqual(config.exclude, ("build/**", "docs/**"))
        self.assertEqual(config.prefix, "new_")
        self.assertTrue(config.escape)

    def test_explicit_configuration_overrides_discovery(self):
        self.write('prefix = "outer_"')
        explicit = self.root / "custom.toml"
        explicit.write_text('prefix = "explicit_"')
        self.args.config = str(explicit)
        self.assertEqual(load_config(self.root, self.args).prefix, "explicit_")

    def test_invalid_configuration_fails_clearly(self):
        cases = [
            'include = "*.sql"', 'escape = "false"', 'provider = "unknown"',
            'exclude_regex = ["["]', 'prefix = ""', 'unknown_key = true',
            'include = ["/absolute/**"]', 'prefix = ["not a string"]',
        ]
        for source in cases:
            with self.subTest(source=source):
                self.write(source)
                with self.assertRaises(GitvarsError):
                    load_config(self.root, self.args)
