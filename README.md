# gitvars

`gitvars` exists so that ***your deployed assets can point back to their source.***

Git knows the commit, its author, and the code behind a change. `gitvars` carries
that context into the files you deploy. Add placeholders to your configuration,
code, or documentation, and replace them with Git metadata during your build—
including links to the exact commit and source file.

## Why gitvars exists

I built it for a recurring need in data engineering: **labeling data assets and
pipelines with the version of code behind them.** When inspecting a table or an
Airflow DAG, I wanted a direct route back to the change that produced it.
Embedding Git metadata in labels, descriptions, and configuration makes that
connection easier to follow when investigating an issue or understanding a
deployment.

The same idea works for Terraform resources, application configuration, and
documentation. The [example page](demo/index.html) uses `gitvars` to fill in its
Git metadata at build time.

## Installation

The Python package is named `gitvars` and installs the `gitvars` command. It
requires Python 3.11+ and Git on `PATH`, with no runtime dependencies or network
calls during rendering.

Install the package from a source checkout into your Python environment,
replacing `/path/to/gitvars` with the directory containing its `pyproject.toml`:

```sh
python -m pip install /path/to/gitvars
```

Once this project is published to PyPI, install its release by package name:

```sh
python -m pip install gitvars
```

## Usage

Run `gitvars` in the Git repository containing the files you want to process.
There are two commands:

| Command | Behavior |
| --- | --- |
| `gitvars render [PATH ...]` | Replace placeholders in selected files, in place by default, or write copies with `--output-dir`. |
| `gitvars check [PATH ...]` | Read selected files without writing. Exit `1` if rendering would change any file, or `0` if no changes are needed. |

Add `--dry-run` to `render` to preview a unified diff without writing anything.
Both commands read configuration from the nearest `.gitvars` found by searching
upward from the **working directory**, not from each input path. Use
`--config FILE` to select a specific configuration file. A configuration file is optional:
you can supply file selection and other options on the command line instead.

### Select files and directories

Both commands accept **zero, one, or several positional paths**. Paths are files
or directories relative to your working directory; absolute paths also work.
You may mix files and directories, but every input must belong to the same Git
repository. Overlapping inputs are deduplicated.

| Inputs | Selection |
| --- | --- |
| No paths | Scan the current directory recursively. |
| One or more directories | Scan those directories recursively. |
| One or more files | Select those files directly; no include patterns are required. |

**Paths choose where to scan; include patterns choose which files to render.**
Directory scans require `include` patterns in `.gitvars` or repeatable
`--include` options. Globs are relative to the repository root. Exclusions still
apply to explicitly supplied files, even though include patterns are unnecessary
for them.

For example, preview SQL files under `models/` and Markdown files under `docs/`,
without requiring a configuration file:

```sh
gitvars render models docs --include '**/*.sql' --include '**/*.md' --dry-run
```

Or preview two specific files without `--include`:

```sh
gitvars render models/model.sql docs/pipeline.md --dry-run
```

To keep selection in configuration, create `.gitvars` at the repository root:

```toml
include = ["**/*.sql", "**/*.md"]
exclude = ["build/**", "dist/**", ".venv/**"]
```

With that configuration, no CLI `--include` is needed. Narrow the scan to the
two directories, or omit paths to scan the current directory:

```sh
gitvars render models docs --dry-run
gitvars check models docs
gitvars render --dry-run
```

For the complete configuration options and matching rules, see
[Configuration](#configuration).

### Choose where rendering writes

`render` defaults to **in-place replacement**. This is intended for fresh CI
checkouts: substitution consumes the placeholders. Local use is supported, but
every selected input must be tracked and have no staged or unstaged changes.
Unrelated modified files do not block rendering. Restore the templates from Git
before rendering them again for a different commit.

Using the configuration above, render both directories in place:

```sh
gitvars render models docs
```

For generated artifacts, keep templates intact and render copies instead:

```sh
gitvars render models docs --output-dir build
```

`models/nested/model.sql` becomes `build/models/nested/model.sql`: paths
are always relative to the repository root, without flattening. Unselected files
in input directories are copied unchanged as bytes, including images and other
assets. Excluded files are omitted.

The output directory must be empty or absent. Use `-f` / `--force` to clear a
nonempty output directory before generating it again. Its contents are removed,
including files unrelated to the previous run. The flag never permits overlapping
inputs and outputs: an output directory cannot be inside an input directory,
equal an input, or contain an input. Symlink destinations and destinations inside
`.git` are refused. A common safe layout is sibling `models/`, `docs/`, and
`build/` directories, with only `models docs` as the inputs. Omitting the paths
would scan the current directory, so a `build/` destination inside it would be
rejected even if `build/**` is excluded.

```sh
gitvars render models docs --output-dir build --force
gitvars render models docs --output-dir build --force --dry-run
```

`--dry-run` prints unified diffs without changing any files, creating directories,
or clearing existing output. `check` reports whether rendering would change
selected files. Both can inspect dirty or untracked inputs.

## Configuration

Use TOML in `.gitvars`. The nearest file found by searching upward from the
working directory wins. `--config FILE` overrides discovery. A directory input
requires include patterns from configuration or `--include`; with no paths,
the input is the working directory.

```toml
prefix = "__git_"
escape = true
remote = "origin"
provider = "auto"
include = ["**/*.sql", "**/*.md", "**/*.yml", "**/*.yaml"]
exclude = ["build/**", "dist/**", ".venv/**"]
exclude_regex = ['(^|/)README\.md$']
# Optional repository web root, including owner/group and repository:
# url_prefix = "https://git.company.com/team/analytics"
# provider = "gitlab"  # Required for self-hosted hosts.
```

All selection patterns are **repository-relative**, regardless of the working
directory or configuration location. Paths use `/`, and matching is case-sensitive:

| Pattern | Matches |
| --- | --- |
| `*.md` | Markdown files at the repository root |
| `**/*.md` | Markdown files at any depth, including the root |
| `build/**` | The root build directory and everything beneath it |
| `templates/?.sql` | One-character SQL filenames directly under `templates/` |

`*`, `?`, and character classes match within a path segment. A standalone `**`
segment matches zero or more directories. Globs match the whole relative path;
regex exclusions search it. Matching an excluded directory excludes its subtree.
There are no negation/reinclude rules. `.gitignore` is not implicitly consulted.

CLI `--include`, `--exclude`, and `--exclude-regex` are repeatable and extend their
configuration lists. CLI `--prefix` and `--escape` / `--no-escape` override scalar
configuration. Matching any exclusion wins over inclusion or an explicit file.

Symlinks, `.git`, and nested repositories are skipped during traversal. Explicit
inputs from different repositories are rejected. All files in an invocation use
one commit snapshot. A repository without a commit at `HEAD` is an error.

## Placeholders

| Placeholder | Value |
| --- | --- |
| `__git_commit__` | Full `HEAD` commit SHA |
| `__git_commit_short__` | Git's abbreviated SHA |
| `__git_author_name__` | Commit author name |
| `__git_author_email__` | Commit author email |
| `__git_committer_name__` | Committer name |
| `__git_committer_email__` | Committer email |
| `__git_commit_subject__` | Commit subject |
| `__git_commit_message__` | Full commit message, including newlines |
| `__git_commit_date__` | Author date in ISO 8601 with timezone |
| `__git_branch__` | Current branch; empty in detached HEAD |
| `__git_tag__` | Highest version-ordered tag pointing at `HEAD`; empty if none |
| `__git_repository__` | Repository name |
| `__git_commit_url__` | Commit browser URL, if available |
| `__git_file_url__` | Input-file permalink at `HEAD`, if the file exists there |

Commit metadata describes checked-out `HEAD`, including when output-directory
inputs have local edits. It does not identify the deployer or the last author of
each file. File links refer to the version committed at `HEAD`, which can differ
from a dirty local input. Tags are ordered using Git's version sort, not creation
date; only tags available in the local checkout participate.

Supported placeholders are replaced everywhere, including Markdown inline code
and fenced code blocks. Unknown or incomplete placeholders are left untouched.
Prefix strings are literal, not regexes. Unavailable known values become empty
strings, with warnings under `--verbose`.

Escape a supported placeholder with an immediately preceding backslash:

```text
__git_commit__    -> the actual SHA
\__git_commit__   -> literal __git_commit__
```

One escape backslash is consumed; all other backslashes remain unchanged.
Disable escape handling with `escape = false` or `--no-escape`. Then a backslash
is ordinary text: `\__git_commit__` becomes a backslash followed by the SHA.
Replacement is always one-pass; inserted metadata and escaped tokens are never
processed again during that invocation.

Values are inserted verbatim. Template authors are responsible for quoting and
escaping them for SQL, YAML, HTML, or other output formats.

## Repository URLs

GitHub, GitLab, and Bitbucket Cloud are supported, including common HTTPS,
SCP-style SSH, and `ssh://` remotes. `provider = "auto"` recognizes `github.com`,
`gitlab.com`, and `bitbucket.org`. Self-hosted GitHub/GitLab installations require
an explicit `provider`. A self-hosted `url_prefix` with `auto` is a configuration
error; an unrecognized remote without an override simply produces empty links.

`url_prefix` takes precedence over the selected remote for links and repository
names. Name discovery uses its final path component, then the selected remote's,
then the local repository-root directory name. A trailing `.git` is removed from
URL-derived names. The default remote is `origin`. No hosting APIs are used.
File URLs use the original input's repository-relative path, with components
URL-encoded, and the full commit SHA. A file absent from `HEAD` has no permalink.

## Files, failures, and exit codes

Only selected files are decoded as UTF-8; there is no binary detection. A selected
file that cannot be decoded produces an error. Original newline characters,
including mixed line endings and the UTF-8 BOM, are preserved outside substituted
values. Multiline metadata is inserted verbatim. File permissions are preserved;
unchanged in-place files are not rewritten. Each changed file is replaced atomically.

Inputs, repository membership, selections, and destination safety are checked
before writing or clearing output. In-place clean-input checks also happen before
writing. Files are then processed sequentially: there is no bulk token validation
or automatic rollback. A later decoding, reading, or writing failure can leave
earlier files rendered. Restore affected in-place files from Git, or delete and
regenerate output-directory contents.

| Exit | Meaning |
| --- | --- |
| `0` | Successful render/dry-run, even with changes; or check needs no changes |
| `1` | Check found files rendering would change |
| `2` | Invalid arguments/configuration, missing Git/commit/repository, dirty in-place inputs, or an I/O/encoding error |

All logging and diagnostics go to stdout. Default output is a concise summary;
`--verbose` adds paths and unavailable-value warnings, and `--quiet` suppresses
routine logging. Dry-run diffs and errors remain visible with `--quiet`.

## Development and demo

```sh
python -m pip install -e '.[demo]'
python -m unittest discover -s tests -v
python demo/build.py
```

The build reads this README and generates `build/demo/index.html` with the same
content, adding a live variable table immediately after the introduction. Its
three columns show the literal variable, its replaced value, and its explanation.
The table uses gitvars' renderer and one Git snapshot; file permalinks refer to
the README. Values are escaped for HTML, preserving names and multiline commit
messages as text. The resulting page is static and opens directly in a browser.

The optional `demo` dependencies are needed only to convert Markdown to HTML;
the gitvars CLI itself still has no runtime dependencies. The Pages workflow
builds from a fresh checkout and uploads `build/demo/`.
Select **GitHub Actions** as the repository's Pages publishing source to enable
deployment, following the [GitHub Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
Generated output is not committed, so the page can link to the exact source
commit without a self-referential SHA update.

CI is configured to run the standard-library test suite on Python 3.11–3.14 on Linux, plus Python
3.12 on Windows and macOS. The local implementation has been validated on Python
3.12 and Git 2.43; hosted CI results determine broader compatibility.
