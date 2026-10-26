from pathlib import Path
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gitvars.errors import GitvarsError
from gitvars.files import atomic_write
from gitvars.git import git


SOURCE = str(Path(__file__).resolve().parents[1] / "src")


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.env.update({
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTHONPATH": SOURCE, "GIT_AUTHOR_DATE": "2026-10-01T12:00:00+02:00",
            "GIT_COMMITTER_DATE": "2026-10-02T13:00:00+02:00",
        })
        self.initialize(self.root)

    def initialize(self, directory):
        self.command("git", "init", "-b", "main", cwd=directory)
        self.command("git", "config", "user.name", "Test Committer", cwd=directory)
        self.command("git", "config", "user.email", "committer@example.test", cwd=directory)

    def command(self, *args, cwd=None):
        return subprocess.run(args, cwd=cwd or self.root, env=self.env, capture_output=True, check=True).stdout.decode()

    def write(self, relative, content="__git_commit__", mode=None):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        if mode is not None:
            path.chmod(mode)
        return path

    def commit(self, message="Test subject\n\nBody with __git_branch__ example."):
        self.command("git", "add", ".")
        self.command("git", "commit", "--author=Test Author <author@example.test>", "-m", message)
        return self.command("git", "rev-parse", "HEAD").strip()

    def cli(self, *args, cwd=None, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "gitvars", *map(str, args)],
            cwd=cwd or self.root, env=self.env, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout.decode() + result.stderr.decode())
        self.assertEqual(result.stderr, b"", result.stderr.decode())
        return result.stdout.decode()

    def test_single_file_in_place_and_check_exit_codes(self):
        path = self.write("template.sql")
        commit = self.commit()
        self.cli("check", path, expected=1)
        self.cli("render", path)
        self.assertEqual(path.read_text(), commit)
        self.cli("check", path)

    def test_dry_run_leaves_dirty_inputs_untouched_and_prints_diff(self):
        path = self.write("template.sql", "original")
        self.commit()
        path.write_bytes(b"__git_commit__")
        before = path.stat().st_mtime_ns
        output = self.cli("render", path, "--dry-run", "--quiet")
        self.assertIn("--- a/template.sql", output)
        self.assertIn("No newline at end of file", output)
        self.assertEqual(path.read_bytes(), b"__git_commit__")
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_modified_staged_and_untracked_inputs_refused_before_any_write(self):
        clean = self.write("a.sql")
        dirty = self.write("b.sql")
        self.commit()
        dirty.write_text("__git_branch__")
        self.cli("render", clean, dirty, expected=2)
        self.assertEqual(clean.read_text(), "__git_commit__")
        self.command("git", "add", "b.sql")
        dirty.write_text("__git_commit__")  # Worktree equals HEAD but index is dirty.
        self.cli("render", clean, dirty, expected=2)
        fresh = self.write("fresh.sql")
        self.cli("render", fresh, expected=2)

    def test_unrelated_dirty_files_do_not_block(self):
        path = self.write("template.sql")
        self.write("unrelated.txt", "original")
        commit = self.commit()
        self.write("unrelated.txt", "edited")
        self.cli("render", path)
        self.assertEqual(path.read_text(), commit)

    def test_unchanged_in_place_file_keeps_mtime(self):
        path = self.write("literal.txt", "__git_unsupported__")
        self.commit()
        before = path.stat().st_mtime_ns
        self.cli("render", path)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_output_preserves_paths_and_copies_unselected_assets(self):
        self.write(".gitvars", 'include = ["**/*.sql"]\nexclude = ["templates/omit/**"]')
        source = self.write("templates/nested/model.sql", "\ufefffirst\r\n__git_commit__\nlast\r\n", 0o754)
        asset = self.write("templates/picture.bin", b"\x00\xff\x80")
        self.write("templates/static.txt", "__git_commit__")
        self.write("templates/omit/ignored.sql")
        commit = self.commit()
        output = self.root / "build"
        self.cli("render", "templates", "--output-dir", output)
        rendered = output / "templates/nested/model.sql"
        self.assertEqual(rendered.read_bytes(), f"\ufefffirst\r\n{commit}\nlast\r\n".encode())
        self.assertEqual(stat.S_IMODE(rendered.stat().st_mode), stat.S_IMODE(source.stat().st_mode))
        self.assertEqual((output / "templates/picture.bin").read_bytes(), asset.read_bytes())
        self.assertEqual((output / "templates/static.txt").read_text(), "__git_commit__")
        self.assertFalse((output / "templates/omit").exists())
        self.assertIn(b"__git_commit__", source.read_bytes())

    def test_output_copies_selected_unchanged_files(self):
        self.write("template.sql", "select 1\n")
        self.commit()
        self.cli("render", "template.sql", "--output-dir", "build")
        self.assertEqual((self.root / "build/template.sql").read_text(), "select 1\n")

    def test_force_clears_only_after_validation(self):
        self.write("template.sql")
        self.commit()
        sentinel = self.write("build/stale.txt", "keep")
        self.cli("render", "template.sql", "--output-dir", "build", expected=2)
        self.assertTrue(sentinel.exists())
        self.cli("render", "missing.sql", "--output-dir", "build", "--force", expected=2)
        self.assertTrue(sentinel.exists())
        self.cli("render", "template.sql", "--output-dir", "build", "--force", "--dry-run")
        self.assertTrue(sentinel.exists())
        self.cli("render", "template.sql", "--output-dir", "build", "-f")
        self.assertFalse(sentinel.exists())
        self.assertTrue((self.root / "build/template.sql").exists())

    def test_overlapping_output_refused_even_with_force(self):
        self.write("templates/page.sql")
        self.commit()
        for output in ("templates", "templates/build", "."):
            with self.subTest(output=output):
                self.cli("render", "templates", "--include", "**/*.sql", "--output-dir", output, "--force", expected=2)
        self.assertEqual((self.root / "templates/page.sql").read_text(), "__git_commit__")

    def test_symlinks_skipped_and_output_symlinks_refused(self):
        target = self.write("templates/page.sql")
        self.commit()
        try:
            (self.root / "templates/link.sql").symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this platform")
        (self.root / "templates/linked-dir").symlink_to(self.root, target_is_directory=True)
        output = self.root / "build"
        self.cli("render", "templates", "--include", "**/*.sql", "--output-dir", output)
        self.assertFalse((output / "templates/link.sql").exists())
        self.assertFalse((output / "templates/linked-dir").exists())
        (self.root / "out-link").symlink_to(output, target_is_directory=True)
        self.cli("render", "templates/page.sql", "--output-dir", "out-link", "--force", expected=2)

    def test_nested_repositories_skipped_and_explicit_mixed_repositories_rejected(self):
        self.write("outer.sql")
        self.commit()
        nested = self.root / "vendor/inner"
        nested.mkdir(parents=True)
        self.initialize(nested)
        (nested / "inner.sql").write_text("__git_commit__")
        self.cli("render", ".", "--include", "**/*.sql", "--output-dir", self.base / "output")
        self.assertFalse((self.base / "output/vendor/inner").exists())
        self.cli("check", "outer.sql", nested / "inner.sql", expected=2)

    def test_multiple_overlapping_inputs_are_deduplicated(self):
        self.write("templates/a.sql")
        self.write("templates/b.sql")
        self.commit()
        output = self.cli("render", "templates", "templates/a.sql", "--include", "**/*.sql", "--output-dir", "build")
        self.assertIn("scanned 2", output)

    def test_separate_git_directory_cannot_be_cleared_as_output(self):
        self.write("template.sql")
        commit = self.commit()
        metadata = self.base / "git-metadata"
        self.command("git", "init", f"--separate-git-dir={metadata}")
        output = self.cli("render", "template.sql", "--output-dir", metadata, "--force", expected=2)
        self.assertIn("Git metadata", output)
        self.assertEqual(self.command("git", "rev-parse", "HEAD").strip(), commit)

    def test_linked_worktree_uses_its_repository_root(self):
        self.write("templates/model.sql", "__git_commit__|__git_branch__")
        commit = self.commit()
        linked = self.base / "linked"
        self.command("git", "worktree", "add", "--detach", str(linked), "HEAD")
        output = self.base / "output"
        self.cli("render", "templates/model.sql", "--output-dir", output, cwd=linked)
        self.assertEqual((output / "templates/model.sql").read_text(), f"{commit}|")

    def test_exclusions_are_root_relative_and_additive_even_for_explicit_files(self):
        self.write(".gitvars", 'include = ["**/*.sql", "**/*.md"]\nexclude = ["build/**"]')
        self.write("templates/page.sql")
        self.write("templates/README.md")
        self.write("build/skip.sql")
        self.commit()
        destination = self.base / "output"
        self.cli("render", ".", "../build/skip.sql", "--exclude-regex", r"(^|/)README\.md$", "--output-dir", destination, cwd=self.root / "templates")
        self.assertTrue((destination / "templates/page.sql").exists())
        self.assertFalse((destination / "templates/README.md").exists())
        self.assertFalse((destination / "build").exists())

    def test_directory_requires_includes_but_explicit_file_does_not(self):
        self.write("template.sql")
        self.commit()
        self.cli("check", ".", expected=2)
        self.cli("check", "template.sql", expected=1)

    def test_invalid_selected_utf8_fails_but_unselected_bytes_are_not_decoded(self):
        self.write("templates/invalid.sql", b"\xff\xfe")
        self.write("templates/asset.bin", b"\xff\xfe")
        self.commit()
        self.cli("check", "templates", "--include", "**/*.sql", expected=2)
        self.cli("check", "templates", "--include", "**/*.md")

    def test_config_escape_override_and_unknown_tokens(self):
        self.write(".gitvars", 'escape = false')
        self.write("template.md", r"\__git_commit__ __git_xyz__")
        commit = self.commit()
        self.cli("render", "template.md", "--escape", "--output-dir", "build")
        self.assertEqual((self.root / "build/template.md").read_text(), "__git_commit__ __git_xyz__")
        self.cli("render", "template.md", "--no-escape", "--output-dir", "build", "-f")
        self.assertEqual((self.root / "build/template.md").read_text(), f"\\{commit} __git_xyz__")

    def test_snapshot_metadata_and_file_urls(self):
        path = self.write("templates/a #ü.sql", "|".join(f"__git_{name}__" for name in (
            "commit", "author_name", "committer_name", "commit_date", "branch", "repository", "file_url",
        )))
        commit = self.commit()
        self.command("git", "remote", "add", "origin", "git@github.com:team/analytics.git")
        self.cli("render", path, "--output-dir", "build")
        result = (self.root / "build/templates/a #ü.sql").read_text()
        self.assertEqual(result, f"{commit}|Test Author|Test Committer|2026-10-01T12:00:00+02:00|main|analytics|https://github.com/team/analytics/blob/{commit}/templates/a%20%23%C3%BC.sql")

    def test_html_escape_is_opt_in_and_preserves_template_and_inserted_tokens(self):
        self.write("page.html", '<code title="__git_commit_subject__">__git_commit_message__</code> &amp;')
        self.commit('A <tag> & "quotes"\n\nLiteral __git_branch__')
        self.cli("render", "page.html", "--output-dir", "build")
        plain = (self.root / "build/page.html").read_text()
        self.assertIn('A <tag> & "quotes"', plain)
        preview = self.cli("render", "page.html", "--html-escape", "--dry-run")
        self.assertIn("&lt;tag&gt; &amp; &quot;quotes&quot;", preview)
        self.cli("check", "page.html", "--html-escape", expected=1)
        self.cli("render", "page.html", "--html-escape", "--output-dir", "build", "-f")
        rendered = (self.root / "build/page.html").read_text()
        self.assertIn('title="A &lt;tag&gt; &amp; &quot;quotes&quot;"', rendered)
        self.assertIn("Literal __git_branch__", rendered)
        self.assertTrue(rendered.endswith("</code> &amp;"))

    def test_file_url_empty_for_untracked_and_absent_head_paths(self):
        self.write("tracked.sql", "original")
        self.commit()
        self.command("git", "remote", "add", "origin", "git@github.com:team/repo.git")
        self.write("new.sql", "__git_file_url__")
        self.cli("render", "new.sql", "--output-dir", "build", "-v")
        self.assertEqual((self.root / "build/new.sql").read_text(), "")
        self.command("git", "add", "new.sql")
        self.cli("render", "new.sql", "--output-dir", "build", "-f")
        self.assertEqual((self.root / "build/new.sql").read_text(), "")

    def test_version_ordered_tags_detached_head_and_multiline_message(self):
        self.write("template.txt", "tag=__git_tag__;branch=__git_branch__;message=__git_commit_message__")
        self.commit("Subject\n\nLiteral __git_commit__\nSecond body line")
        for tag in ("v2.9.0", "v2.10.0", "v1.0.0"):
            self.command("git", "tag", tag)
        self.command("git", "tag", "-a", "v2.11.0", "-m", "Annotated")
        self.command("git", "config", "column.tag", "always")
        self.command("git", "config", "color.ui", "always")
        self.command("git", "checkout", "--detach")
        self.cli("render", "template.txt", "--output-dir", "build", "-v")
        result = (self.root / "build/template.txt").read_text()
        self.assertTrue(result.startswith("tag=v2.11.0;branch=;message=Subject\n\nLiteral __git_commit__\nSecond body line"))

    def test_missing_metadata_warnings_are_verbose_only(self):
        self.write("template.txt", "__git_tag__|__git_commit_url__")
        self.commit()
        plain = self.cli("render", "template.txt", "--dry-run")
        verbose = self.cli("render", "template.txt", "--dry-run", "-v")
        self.assertNotIn("Warning:", plain)
        self.assertIn("Warning:", verbose)

    def test_no_commit_and_outside_repository_errors(self):
        self.write("template.sql")
        self.assertIn("no commit", self.cli("check", "template.sql", expected=2))
        outside = self.base / "outside.sql"
        outside.write_text("__git_commit__")
        self.assertIn("outside a Git", self.cli("check", outside, expected=2))

    def test_stdout_argument_errors_and_force_requires_output(self):
        self.cli("render", "--not-an-option", expected=2)
        self.cli("render", "--in-place", "--output-dir", "build", expected=2)
        self.cli("render", "--force", expected=2)

    def test_output_not_created_on_configuration_error_or_dry_run(self):
        self.write("template.sql")
        self.commit()
        self.cli("render", "template.sql", "--output-dir", "build", "--dry-run")
        self.assertFalse((self.root / "build").exists())
        self.write(".gitvars", 'url_prefix = "https://git.company.test/team/repo"')
        self.cli("render", "template.sql", "--output-dir", "build", expected=2)
        self.assertFalse((self.root / "build").exists())


class FailureTests(unittest.TestCase):
    def test_missing_git_is_actionable(self):
        with patch("gitvars.git.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(GitvarsError, "not installed"):
                git(Path.cwd(), "rev-parse", "HEAD")

    def test_failed_replace_keeps_original_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.sql"
            path.write_bytes(b"original")
            with patch("gitvars.files.os.replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    atomic_write(path, b"replacement", path.stat().st_mode)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])
