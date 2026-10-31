import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from packaging.version import Version

from scripts.release import make_plan, release_version


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="gitvars-release-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name).resolve()
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.test")
        self.commit_version("0.1.0")

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.project, env=self.env, stderr=subprocess.DEVNULL,
        ).decode().strip()

    def commit_version(self, version, name="gitvars-render"):
        (self.project / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "{version}"\n', encoding="utf-8",
        )
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", "Version change")

    def test_no_release_tags_publish_only_a_development_build(self):
        plan = make_plan(self.project, run_id=123, attempt=1)
        self.assertEqual((plan.kind, plan.version, plan.tag, plan.create_tag), ("development", "0.1.0.dev1230001", "", False))
        self.assertEqual(plan.sha, self.git("rev-parse", "HEAD"))

    def test_version_bump_uses_numeric_order_and_ignores_unrelated_tags(self):
        self.commit_version("0.9.0")
        self.git("tag", "v0.9.0")
        self.git("tag", "v99.0.0rc1")
        self.git("tag", "checkpoint")
        self.commit_version("0.10.0")
        plan = make_plan(self.project)
        self.assertEqual((plan.kind, plan.tag, plan.create_tag), ("release", "v0.10.0", True))

    def test_ordinary_commits_have_unique_development_versions(self):
        self.git("tag", "v0.1.0")
        self.commit_version("0.1.0")
        first = make_plan(self.project, run_id=123, attempt=1)
        retry = make_plan(self.project, run_id=123, attempt=2)
        following = make_plan(self.project, run_id=124, attempt=1)
        self.assertEqual(first.kind, "development")
        self.assertEqual(first.version, "0.1.1.dev1230001")
        self.assertFalse(first.tag)
        self.assertFalse(first.create_tag)
        self.assertLess(Version(first.version), Version(retry.version))
        self.assertLess(Version(retry.version), Version(following.version))
        self.assertLess(Version(following.version), Version("0.1.1"))

    def test_tagged_commit_can_retry_release_without_creating_or_moving_tag(self):
        self.git("tag", "-a", "v0.1.0", "-m", "First release")
        for tag in ("", "v0.1.0"):
            with self.subTest(tag=tag):
                plan = make_plan(self.project, tag=tag)
                self.assertEqual(plan.kind, "release")
                self.assertEqual(plan.tag, "v0.1.0")
                self.assertFalse(plan.create_tag)

    def test_mismatched_tag_or_commit_is_rejected(self):
        self.git("tag", "v0.1.0")
        with self.assertRaisesRegex(ValueError, "must match"):
            make_plan(self.project, tag="v0.2.0")
        self.commit_version("0.1.0")
        with self.assertRaisesRegex(ValueError, "tested commit"):
            make_plan(self.project, tag="v0.1.0")

    def test_version_below_latest_release_is_rejected(self):
        self.git("tag", "v0.2.0")
        with self.assertRaisesRegex(ValueError, "below the latest"):
            make_plan(self.project)

    def test_wrong_distribution_name_is_rejected(self):
        self.commit_version("0.1.0", name="gitvars")
        with self.assertRaisesRegex(ValueError, "distribution name"):
            make_plan(self.project)

    def test_release_versions_are_canonical_stable_triplets(self):
        for value in ("0.1", "v0.1.0", "0.1.0rc1", "0.1.0.dev1", "0.1.0.post1", "0.1.0+local", "1!0.1.0"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release_version(value)

    def test_development_build_requires_valid_run_identity(self):
        self.git("tag", "v0.1.0")
        self.commit_version("0.1.0")
        for run_id, attempt in ((0, 1), (-1, 1), (123, 0), (123, 10000)):
            with self.subTest(run_id=run_id, attempt=attempt), self.assertRaises(ValueError):
                make_plan(self.project, run_id=run_id, attempt=attempt)
