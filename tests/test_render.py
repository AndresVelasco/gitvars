import unittest

from gitvars.render import NAMES, Renderer, unified_diff


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.values = {name: f"value-{name}" for name in NAMES}

    def test_all_supported_names_and_adjacent_tokens(self):
        source = "".join(f"__git_{name}__" for name in NAMES)
        result, missing = Renderer("__git_", True).render(source, self.values)
        self.assertEqual(result, "".join(self.values.values()))
        self.assertEqual(missing, set())

    def test_unsupported_and_incomplete_tokens_are_literal(self):
        source = r"__git_xyz__ __git_commit_ \__git_xyz__"
        self.assertEqual(Renderer("__git_", True).render(source, self.values)[0], source)

    def test_escapes_and_other_backslashes(self):
        source = r"\__git_commit__ \\__git_branch__ C:\templates\file.sql"
        expected = r"__git_commit__ \__git_branch__ C:\templates\file.sql"
        self.assertEqual(Renderer("__git_", True).render(source, self.values)[0], expected)

    def test_escape_can_be_disabled(self):
        result, _ = Renderer("__git_", False).render(r"\__git_commit__", self.values)
        self.assertEqual(result, r"\value-commit")

    def test_inserted_metadata_is_never_rendered_again(self):
        self.values["commit_message"] = "Example: __git_commit__\n\\__git_branch__\n"
        for escape in (True, False):
            result, _ = Renderer("__git_", escape).render("__git_commit_message__", self.values)
            self.assertEqual(result, self.values["commit_message"])

    def test_prefix_is_literal_not_regex(self):
        result, _ = Renderer("[git].", True).render("[git].commit__", self.values)
        self.assertEqual(result, "value-commit")

    def test_original_mixed_newlines_and_bom_survive(self):
        source = "\ufefffirst\r\n__git_commit__\nlast\r\n"
        result, _ = Renderer("__git_", True).render(source, self.values)
        self.assertEqual(result, "\ufefffirst\r\nvalue-commit\nlast\r\n")

    def test_missing_values_only_warn_when_used_unescaped(self):
        self.values["tag"] = ""
        self.assertEqual(Renderer("__git_", True).render(r"\__git_tag__", self.values)[1], set())
        self.assertEqual(Renderer("__git_", True).render("__git_tag__", self.values), ("", {"tag"}))

    def test_diff_describes_missing_final_newline(self):
        diff = unified_diff("old", "new", "template.sql")
        self.assertIn("--- a/template.sql\n+++ b/template.sql\n", diff)
        self.assertIn("-old\n\\ No newline at end of file\n", diff)
        self.assertIn("+new\n\\ No newline at end of file\n", diff)
