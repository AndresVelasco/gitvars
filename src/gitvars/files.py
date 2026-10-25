"""Traversal, destination validation, and per-file atomic writes."""

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import stat
import tempfile

from .config import Config, Selector
from .errors import GitvarsError
from .git import git, repository_root


@dataclass(frozen=True)
class Entry:
    source: Path
    relative: str
    render: bool


@dataclass
class Stats:
    scanned: int = 0
    changed: int = 0
    copied: int = 0
    skipped: int = 0
    errors: int = 0


def absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(path))


def has_symlink(path: Path) -> bool:
    return any(part.is_symlink() for part in (path, *path.parents))


def prepare_inputs(paths: list[str], config: Config) -> tuple[Path, list[Path]]:
    inputs = list(dict.fromkeys(absolute(path) for path in paths))
    for path in inputs:
        if not path.exists() and not path.is_symlink():
            raise GitvarsError(f"Input does not exist: {path}")
        if path.is_dir() and not has_symlink(path) and not config.include:
            raise GitvarsError("Directory inputs require include patterns in .gitvars or --include; alternatively supply files explicitly")
    root = repository_root(inputs[0])
    for path in inputs:
        if has_symlink(path):
            continue
        if repository_root(path) != root:
            raise GitvarsError("Each invocation must use one Git repository; inputs span multiple repositories")
    return root, inputs


def discover_entries(root: Path, inputs: list[Path], config: Config, stats: Stats) -> list[Entry]:
    selector = Selector(config)
    entries: dict[Path, Entry] = {}

    def visit(path: Path, explicit: bool = False) -> None:
        if has_symlink(path) or ".git" in path.relative_to(root).parts:
            stats.skipped += 1
            return
        relative = path.relative_to(root).as_posix()
        if relative != "." and selector.excluded(relative):
            stats.skipped += 1
            return
        if path.is_dir():
            if path != root and (path / ".git").exists():
                stats.skipped += 1
                return
            for child in sorted(path.iterdir()):
                visit(child)
        elif path.is_file():
            render = explicit or selector.included(relative)
            previous = entries.get(path)
            entries[path] = Entry(path, relative, render or bool(previous and previous.render))
        else:
            stats.skipped += 1

    for path in inputs:
        # Explicit symlinks can point outside the root; never traverse them.
        if has_symlink(path):
            stats.skipped += 1
            continue
        visit(path, explicit=path.is_file())
    return sorted(entries.values(), key=lambda entry: entry.relative)


def validate_output(output: Path, inputs: list[Path], root: Path, force: bool) -> None:
    if has_symlink(output):
        raise GitvarsError(f"Output directory and its parents must not be symlinks: {output}")
    for path in inputs:
        source = path.resolve()
        if output == source or output in source.parents or (path.is_dir() and source in output.parents):
            raise GitvarsError(f"Output directory overlaps an input: {output}; choose a disjoint destination")
    if ".git" in output.parts:
        raise GitvarsError("Output must not be inside Git metadata (.git)")
    if output.exists():
        if not output.is_dir():
            raise GitvarsError(f"Output path is not a directory: {output}")
        if any(output.iterdir()) and not force:
            raise GitvarsError(f"Output directory is not empty: {output}; pass -f/--force to clear it")
    # --separate-git-dir and linked worktrees need not store metadata under .git.
    for option in ("--absolute-git-dir", "--git-common-dir"):
        location = Path(os.fsdecode(git(root, "rev-parse", option).rstrip(b"\n")))
        metadata = (root / location).resolve()
        if output == metadata or output in metadata.parents or metadata in output.parents:
            raise GitvarsError("Output directory must not overlap Git metadata")


def prepare_output(output: Path) -> None:
    if output.exists():
        for child in output.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    else:
        output.mkdir(parents=True)


def atomic_write(destination: Path, content: bytes, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.gitvars-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        temporary.chmod(stat.S_IMODE(mode))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
