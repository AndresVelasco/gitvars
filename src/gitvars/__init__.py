"""Git provenance rendering with no runtime dependencies."""

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("gitvars-render")
except PackageNotFoundError:
    # A source checkout can be imported before the distribution is installed.
    __version__ = "0+unknown"
