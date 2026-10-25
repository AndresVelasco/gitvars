"""Single-pass substitution of supported tokens, with optional escaping."""

import difflib
import re


NAMES = (
    "commit", "commit_short", "author_name", "author_email", "committer_name",
    "committer_email", "commit_subject", "commit_message", "commit_date",
    "branch", "tag", "repository", "commit_url", "file_url",
)


class Renderer:
    def __init__(self, prefix: str, escape: bool):
        escaped = r"(?P<escaped>\\)?" if escape else ""
        self.pattern = re.compile(escaped + re.escape(prefix) + r"(?P<name>" + "|".join(NAMES) + r")__")
        self.escape = escape

    def render(self, text: str, values: dict[str, str]) -> tuple[str, set[str]]:
        unavailable = set()

        def replace(match: re.Match) -> str:
            if self.escape and match.group("escaped"):
                return match.group()[1:]
            name = match.group("name")
            value = values[name]
            if not value:
                unavailable.add(name)
            return value

        return self.pattern.sub(replace, text), unavailable


def unified_diff(before: str, after: str, relative: str, destination: str | None = None) -> str:
    parts = []
    for line in difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"a/{relative}", tofile=destination or f"b/{relative}",
    ):
        parts.append(line)
        if not line.endswith("\n"):
            parts.append("\n\\ No newline at end of file\n")
    return "".join(parts)
