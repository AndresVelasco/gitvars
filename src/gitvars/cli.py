"""Console commands; all user-facing output is sent to stdout."""

import argparse
from pathlib import Path
import sys

from . import __version__
from .config import load_config
from .errors import GitvarsError
from .files import (
    Stats, absolute, atomic_write, copy_file, discover_entries, prepare_inputs,
    prepare_output, validate_output,
)
from .git import collect_snapshot, require_clean_inputs
from .render import Renderer, unified_diff


class Parser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if message:
            sys.stdout.write(message)


def build_parser() -> Parser:
    parser = Parser(prog="gitvars", description="Render Git provenance into selected UTF-8 files.")
    parser.add_argument("--version", action="version", version=f"gitvars {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("render", "check"):
        command = commands.add_parser(name, help="Render files" if name == "render" else "Check whether rendering would change files")
        command.add_argument("paths", nargs="*", metavar="PATH", help="Files or directories (default: current directory)")
        command.add_argument("--config", metavar="FILE")
        command.add_argument("--prefix", metavar="PREFIX")
        command.add_argument("--include", action="append", metavar="GLOB", help="Add a repository-relative rendering glob")
        command.add_argument("--exclude", action="append", metavar="GLOB", help="Add a repository-relative exclusion glob")
        command.add_argument("--exclude-regex", action="append", metavar="REGEX", help="Add a regex exclusion against repository-relative paths")
        command.add_argument("--escape", action=argparse.BooleanOptionalAction, default=None, help="Recognize backslash escapes (default: enabled)")
        verbosity = command.add_mutually_exclusive_group()
        verbosity.add_argument("-v", "--verbose", action="store_true")
        verbosity.add_argument("-q", "--quiet", action="store_true")
        if name == "render":
            command.add_argument("--dry-run", action="store_true", help="Print unified diffs without writing")
            mode = command.add_mutually_exclusive_group()
            mode.add_argument("--in-place", action="store_true", help="Replace clean tracked inputs (default)")
            mode.add_argument("--output-dir", metavar="DIR", help="Copy files under DIR using repository-relative paths")
            command.add_argument("-f", "--force", action="store_true", help="Clear a nonempty output directory; requires --output-dir")
    return parser


def run(args, stats: Stats) -> int:
    output_arg = getattr(args, "output_dir", None)
    force = getattr(args, "force", False)
    if force and output_arg is None:
        raise GitvarsError("-f/--force requires --output-dir; it cannot bypass clean-input checks")
    config = load_config(Path.cwd(), args)
    root, inputs = prepare_inputs(args.paths or ["."], config)
    output = absolute(output_arg) if output_arg is not None else None
    if output is not None:
        validate_output(output, inputs, root, force)
    entries = discover_entries(root, inputs, config, stats)
    snapshot = collect_snapshot(root, config)
    dry_run = getattr(args, "dry_run", False)
    writing = args.command == "render" and not dry_run
    if writing and output is None:
        require_clean_inputs(snapshot, [entry.relative for entry in entries if entry.render])
    if writing and output is not None:
        prepare_output(output)
    renderer = Renderer(config.prefix, config.escape)
    for entry in entries:
        stats.scanned += 1
        destination = output / entry.relative if output else entry.source
        if not entry.render:
            stats.skipped += 1
            if output is not None:
                if writing:
                    copy_file(entry.source, destination)
                stats.copied += 1
                if args.verbose:
                    print(f"{'Would copy' if dry_run else 'Copied'} {entry.relative} unchanged")
            continue
        try:
            original = entry.source.read_bytes()
            text = original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitvarsError(f"Selected file is not valid UTF-8: {entry.source}; adjust include/exclude patterns") from exc
        rendered, unavailable = renderer.render(text, snapshot.for_file(entry.relative))
        changed = rendered != text
        if changed:
            stats.changed += 1
        if args.verbose:
            for name in sorted(unavailable):
                print(f"Warning: {entry.relative}: {config.prefix}{name}__ is unavailable; using an empty string")
            action = "Would render" if not writing else "Rendered"
            print(f"{action} {entry.relative}" if changed else f"Unchanged {entry.relative}")
        if dry_run and changed:
            print(unified_diff(text, rendered, entry.relative, str(destination) if output else None), end="")
        if writing:
            if changed:
                atomic_write(destination, rendered.encode("utf-8"), entry.source.stat().st_mode)
            elif output is not None:
                copy_file(entry.source, destination)
        if output is not None:
            stats.copied += 1
    return 1 if args.command == "check" and stats.changed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stats = Stats()
    try:
        result = run(args, stats)
    except (GitvarsError, OSError) as exc:
        print(f"gitvars: error: {exc}")
        stats.errors += 1
        result = 2
    if not args.quiet:
        preview = "Dry run: " if getattr(args, "dry_run", False) else ""
        print(
            f"{preview}scanned {stats.scanned}; changed {stats.changed}; "
            f"copied {stats.copied}; skipped {stats.skipped}; errors {stats.errors}"
        )
    return result
