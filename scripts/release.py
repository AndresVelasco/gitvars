"""Select a release or development version for the tested Git commit."""

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
import tomllib

from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class Plan:
    kind: str
    version: str
    tag: str
    sha: str
    create_tag: bool


def release_version(value: str) -> Version:
    version = Version(value)
    if (
        len(version.release) != 3 or version.epoch or version.is_prerelease
        or version.is_postrelease or version.local or str(version) != value
    ):
        raise ValueError("Release versions must use MAJOR.MINOR.PATCH, for example 0.1.0")
    return version


def make_plan(project: Path, tag: str = "", run_id: int = 0, attempt: int = 1) -> Plan:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=project).decode().strip()

    metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if metadata["name"] != "gitvars-render":
        raise ValueError("The distribution name must match the gitvars-render trusted publisher")
    current = release_version(metadata["version"])
    sha = git("rev-parse", "HEAD")
    releases = {}
    for candidate in git("tag", "--list", "v*").splitlines():
        try:
            releases[release_version(candidate[1:])] = candidate
        except (InvalidVersion, ValueError):
            continue
    latest = max(releases, default=None)
    if latest is not None and current < latest:
        raise ValueError(f"Project version {current} is below the latest release tag {releases[latest]}")

    expected_tag = f"v{current}"
    if tag:
        if tag != expected_tag:
            raise ValueError(f"Tag {tag!r} must match the project version: {expected_tag}")
        if git("rev-parse", f"refs/tags/{tag}^{{commit}}") != sha:
            raise ValueError(f"Tag {tag} does not point to the tested commit")
        return Plan("release", str(current), tag, sha, False)
    if latest is not None and current > latest:
        return Plan("release", str(current), expected_tag, sha, True)
    if latest is not None and git("rev-parse", f"refs/tags/{expected_tag}^{{commit}}") == sha:
        # Permit retrying a failed upload without moving or recreating its tag.
        return Plan("release", str(current), expected_tag, sha, False)

    if run_id < 1 or not 1 <= attempt < 10000:
        raise ValueError("Development builds require a positive run ID and an attempt from 1 to 9999")
    major, minor, patch = current.release
    serial = run_id * 10000 + attempt
    target_patch = patch if latest is None else patch + 1
    development = f"{major}.{minor}.{target_patch}.dev{serial}"
    return Plan("development", development, "", sha, False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("RELEASE_TAG", ""))
    parser.add_argument("--run-id", type=int, default=int(os.environ.get("GITHUB_RUN_ID", "0")))
    parser.add_argument("--attempt", type=int, default=int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")))
    parser.add_argument("--output", type=Path, help="Append job outputs to this GitHub Actions output file")
    args = parser.parse_args(argv)
    try:
        plan = make_plan(Path(__file__).resolve().parents[1], args.tag, args.run_id, args.attempt)
        if args.output:
            with args.output.open("a", encoding="utf-8") as stream:
                for name, value in asdict(plan).items():
                    stream.write(f"{name}={str(value).lower() if isinstance(value, bool) else value}\n")
        print(json.dumps(asdict(plan), indent=2))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Release planning failed: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
