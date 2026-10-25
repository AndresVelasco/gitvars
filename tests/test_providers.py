import unittest

from gitvars.config import Config
from gitvars.errors import GitvarsError
from gitvars.providers import resolve_repository_url


class ProviderTests(unittest.TestCase):
    def test_public_providers_and_common_remote_forms(self):
        cases = [
            ("https://github.com/team/repo.git", "commit", "blob"),
            ("git@github.com:team/repo.git", "commit", "blob"),
            ("git@github.com:team/repo.git/", "commit", "blob"),
            ("ssh://git@github.com:2222/team/repo.git", "commit", "blob"),
            ("git@gitlab.com:team/group/repo.git", "-/commit", "-/blob"),
            ("https://bitbucket.org/team/repo.git", "commits", "src"),
        ]
        for remote, commit_route, file_route in cases:
            with self.subTest(remote=remote):
                url = resolve_repository_url(Config(), remote, "checkout")
                self.assertEqual(url.name, "repo")
                self.assertTrue(url.provider.commit_url(url.base, "abc").endswith(f"/{commit_route}/abc"))
                self.assertTrue(url.provider.file_url(url.base, "abc", "a b/ü#?.sql").endswith(f"/{file_route}/abc/a%20b/%C3%BC%23%3F.sql"))
                self.assertNotIn(":2222", url.base)

    def test_configured_url_takes_precedence_and_keeps_gitlab_groups(self):
        config = Config(provider="gitlab", url_prefix="https://git.company.com/team/group/analytics/")
        url = resolve_repository_url(config, "git@github.com:other/repository.git", "checkout")
        self.assertEqual(url.name, "analytics")
        self.assertEqual(url.provider.file_url(url.base, "abc", "file.sql"), "https://git.company.com/team/group/analytics/-/blob/abc/file.sql")

    def test_auto_infers_from_configured_public_url(self):
        url = resolve_repository_url(Config(url_prefix="https://github.com/team/repo"), None, "checkout")
        self.assertEqual(url.provider.commit_url(url.base, "abc"), "https://github.com/team/repo/commit/abc")

    def test_unknown_remote_can_still_supply_name(self):
        url = resolve_repository_url(Config(), "git@git.company.com:group/analytics.git", "checkout")
        self.assertEqual(url.name, "analytics")
        self.assertIsNone(url.provider)

    def test_name_falls_back_to_directory_without_remote(self):
        self.assertEqual(resolve_repository_url(Config(), None, "checkout").name, "checkout")

    def test_invalid_explicit_urls_and_unknown_self_hosted_provider(self):
        cases = [
            Config(url_prefix="https://git.company.com/team/repo"),
            Config(url_prefix="not-a-url", provider="gitlab"),
            Config(url_prefix="https://github.com/team"),
            Config(url_prefix="https://github.com/team/repo?query=1"),
            Config(url_prefix="https://user:secret@github.com/team/repo"),
            Config(url_prefix="https://git.company.com/team/repo", provider="bitbucket_cloud"),
        ]
        for config in cases:
            with self.subTest(config=config):
                with self.assertRaises(GitvarsError):
                    resolve_repository_url(config, None, "checkout")

    def test_http_remote_port_preserved_and_credentials_removed(self):
        url = resolve_repository_url(Config(provider="gitlab"), "http://user:pass@git.company.com:8080/team/repo.git", "checkout")
        self.assertEqual(url.base, "http://git.company.com:8080/team/repo")
