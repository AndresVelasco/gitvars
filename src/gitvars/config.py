"""Configuration discovery and repository-relative file selection."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
import re
import tomllib

from .errors import GitvarsError


@dataclass(frozen=True)
class Config:
    prefix: str = "__git_"
    remote: str = "origin"
    provider: str = "auto"
    url_prefix: str | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    exclude_regex: tuple[str, ...] = ()
    escape: bool = True


def discover_config(cwd: Path) -> Path | None:
    for directory in (cwd, *cwd.parents):
        candidate = directory / ".gitvars"
        if candidate.exists():
            return candidate
    return None


def load_config(cwd: Path, args) -> Config:
    path = Path(args.config) if args.config else discover_config(cwd)
    values = {}
    if path is not None:
        try:
            with path.open("rb") as stream:
                values = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise GitvarsError(f"Cannot read configuration {path}: {exc}") from exc
    unknown = values.keys() - Config.__dataclass_fields__.keys()
    if unknown:
        raise GitvarsError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    for key in ("prefix", "remote", "provider", "url_prefix"):
        if key in values and (not isinstance(values[key], str) or not values[key]):
            raise GitvarsError(f"Configuration '{key}' must be a nonempty string")
    for key in ("include", "exclude", "exclude_regex"):
        items = values.get(key, [])
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item for item in items
        ):
            raise GitvarsError(f"Configuration '{key}' must be a list of nonempty strings")
        values[key] = tuple(items) + tuple(getattr(args, key, None) or ())
    if "escape" in values and not isinstance(values["escape"], bool):
        raise GitvarsError("Configuration 'escape' must be true or false")
    if args.prefix is not None:
        values["prefix"] = args.prefix
    if args.escape is not None:
        values["escape"] = args.escape
    config = Config(**values)
    if not config.prefix or any(char in config.prefix for char in "\r\n\\\x00"):
        raise GitvarsError("Prefix must be nonempty and contain no newline, NUL, or backslash")
    if config.provider not in {"auto", "github", "gitlab", "bitbucket_cloud"}:
        raise GitvarsError("Provider must be auto, github, gitlab, or bitbucket_cloud")
    for pattern in (*config.include, *config.exclude):
        if pattern.startswith("/") or ".." in pattern.split("/"):
            raise GitvarsError(f"Glob must be repository-relative: {pattern!r}")
    for pattern in config.exclude_regex:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise GitvarsError(f"Invalid exclusion regex {pattern!r}: {exc}") from exc
    return config


def match_glob(path: str, pattern: str) -> bool:
    """Match whole POSIX paths; ** matches zero or more complete segments."""
    parts = tuple(path.split("/"))
    patterns = tuple(pattern.split("/"))

    @cache
    def match(index: int, pattern_index: int) -> bool:
        if pattern_index == len(patterns):
            return index == len(parts)
        token = patterns[pattern_index]
        if token == "**":
            return match(index, pattern_index + 1) or (
                index < len(parts) and match(index + 1, pattern_index)
            )
        return (
            index < len(parts)
            and fnmatchcase(parts[index], token)
            and match(index + 1, pattern_index + 1)
        )

    return match(0, 0)


class Selector:
    def __init__(self, config: Config):
        self.config = config
        self.regexes = tuple(re.compile(pattern) for pattern in config.exclude_regex)

    def excluded(self, relative: str) -> bool:
        path = Path(relative)
        candidates = (relative, *(parent.as_posix() for parent in path.parents if parent != Path(".")))
        return any(
            any(match_glob(candidate, pattern) for pattern in self.config.exclude)
            or any(regex.search(candidate) for regex in self.regexes)
            for candidate in candidates
        )

    def included(self, relative: str) -> bool:
        return any(match_glob(relative, pattern) for pattern in self.config.include)
