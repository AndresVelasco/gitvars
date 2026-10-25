"""Read one immutable commit snapshot using the installed Git executable."""

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess

from .config import Config
from .errors import GitvarsError
from .providers import RepositoryURL, resolve_repository_url


def git(directory: Path, *arguments: str, optional: bool = False) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitvarsError("Git is not installed or not on PATH; install Git to use gitvars") from exc
    if result.returncode and not optional:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitvarsError(f"Git failed in {directory}: {detail}")
    return result.stdout if result.returncode == 0 else b""


def repository_root(path: Path) -> Path:
    directory = path if path.is_dir() and not path.is_symlink() else path.parent
    result = git(directory, "rev-parse", "--show-toplevel", optional=True)
    if not result:
        raise GitvarsError(f"Input is outside a Git working tree: {path}")
    return Path(os.fsdecode(result.rstrip(b"\n"))).resolve()


@dataclass(frozen=True)
class Snapshot:
    root: Path
    values: dict[str, str]
    files: frozenset[str]
    repository_url: RepositoryURL

    def for_file(self, relative: str) -> dict[str, str]:
        values = dict(self.values)
        url = self.repository_url
        values["file_url"] = (
            url.provider.file_url(url.base, values["commit"], relative)
            if relative in self.files and url.base and url.provider else ""
        )
        return values


def collect_snapshot(root: Path, config: Config) -> Snapshot:
    commit = git(root, "rev-parse", "--verify", "HEAD", optional=True).decode().strip()
    if not commit:
        raise GitvarsError(f"Repository has no commit at HEAD: {root}; create a commit before rendering")
    fields = (
        "commit", "commit_short", "author_name", "author_email", "committer_name",
        "committer_email", "commit_subject", "commit_message", "commit_date",
    )
    output = git(
        root, "show", "--no-patch", "--no-show-signature", "--encoding=UTF-8",
        "--format=%H%x00%h%x00%an%x00%ae%x00%cn%x00%ce%x00%s%x00%B%x00%aI%x00", commit,
    )
    values = dict(zip(fields, output.decode("utf-8", errors="replace").split("\x00")[:len(fields)]))
    values["branch"] = git(root, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True).decode().strip()
    tags = git(
        root, "tag", "--points-at", commit, "--sort=-version:refname", "--no-column", "--color=never",
    ).decode().splitlines()
    values["tag"] = tags[0] if tags else ""
    remote = git(root, "remote", "get-url", "--", config.remote, optional=True).decode().strip() or None
    url = resolve_repository_url(config, remote, root.name)
    values["repository"] = url.name
    values["commit_url"] = url.provider.commit_url(url.base, commit) if url.base and url.provider else ""
    files = set()
    for record in git(root, "ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
        if record:
            info, path = record.split(b"\t", 1)
            if info.split()[0] in {b"100644", b"100755"}:
                files.add(os.fsdecode(path))
    return Snapshot(root, values, frozenset(files), url)


def require_clean_inputs(snapshot: Snapshot, relatives: list[str]) -> None:
    dirty = set()
    for staged in (False, True):
        arguments = ["diff", "--no-ext-diff", "--no-renames", "--name-only", "-z"]
        if staged:
            arguments.append("--cached")
        dirty.update(os.fsdecode(path) for path in git(snapshot.root, *arguments).split(b"\0") if path)
    unsafe = [path for path in relatives if path not in snapshot.files or path in dirty]
    if unsafe:
        sample = ", ".join(unsafe[:5])
        raise GitvarsError(
            f"In-place rendering requires clean tracked inputs: {sample}. "
            "Commit or restore those files, or use --output-dir"
        )
