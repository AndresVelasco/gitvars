"""Offline URL parsing and small provider-specific route adapters."""

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .config import Config
from .errors import GitvarsError


@dataclass(frozen=True)
class Provider:
    commit_route: str
    file_route: str

    def commit_url(self, base: str, commit: str) -> str:
        return f"{base}/{self.commit_route}/{commit}"

    def file_url(self, base: str, commit: str, path: str) -> str:
        return f"{base}/{self.file_route}/{commit}/{quote(path, safe='/')}"


PROVIDERS = {
    "github": Provider("commit", "blob"),
    "gitlab": Provider("-/commit", "-/blob"),
    "bitbucket_cloud": Provider("commits", "src"),
}
HOSTS = {"github.com": "github", "gitlab.com": "gitlab", "bitbucket.org": "bitbucket_cloud"}


@dataclass(frozen=True)
class RepositoryURL:
    name: str
    base: str | None = None
    provider: Provider | None = None


def remote_parts(remote: str) -> tuple[str | None, str | None, str]:
    """Return browser base, hostname, and repository name for common remotes."""
    if "://" in remote:
        parsed = urlsplit(remote)
        path = parsed.path.rstrip("/")
        hostname = parsed.hostname
        if parsed.scheme in {"http", "https", "ssh", "git"} and hostname:
            scheme = parsed.scheme if parsed.scheme in {"http", "https"} else "https"
            host = f"[{hostname}]" if ":" in hostname else hostname
            if scheme == parsed.scheme and parsed.port:
                host += f":{parsed.port}"
            base = urlunsplit((scheme, host, path, "", ""))
        else:
            base = None
    else:
        scp = re.fullmatch(r"(?:[^@/]+@)?([^/:]+):(.+)", remote)
        if scp:
            hostname, path = scp.groups()
            path = "/" + path.strip("/")
            base = f"https://{hostname}{path}"
        else:
            hostname, path, base = None, remote.rstrip("/"), None
    if path.endswith(".git"):
        path = path[:-4]
        if base is not None:
            base = base[:-4]
    name = unquote(PurePosixPath(path).name)
    if base is not None and len([part for part in path.split("/") if part]) < 2:
        base = None
    return base, hostname.lower() if hostname else None, name


def resolve_repository_url(config: Config, remote: str | None, directory_name: str) -> RepositoryURL:
    source = config.url_prefix or remote
    if source is None:
        return RepositoryURL(directory_name)
    try:
        base, host, name = remote_parts(source)
        if config.url_prefix:
            parsed = urlsplit(source)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or len([part for part in parsed.path.split("/") if part]) < 2
                or any(char.isspace() for char in source)
            ):
                raise GitvarsError("url_prefix must be an HTTP(S) repository web root, including owner and repository")
    except ValueError as exc:
        if config.url_prefix:
            raise GitvarsError(f"Invalid url_prefix: {exc}") from exc
        return RepositoryURL(directory_name)
    provider_name = config.provider if config.provider != "auto" else HOSTS.get(host)
    if config.url_prefix and provider_name is None:
        raise GitvarsError("Cannot infer provider from url_prefix; set provider explicitly for self-hosted domains")
    if provider_name == "bitbucket_cloud" and host != "bitbucket.org":
        raise GitvarsError("bitbucket_cloud supports bitbucket.org only")
    return RepositoryURL(name or directory_name, base, PROVIDERS.get(provider_name))
