"""Command-line entry point.

Kept deliberately thin: each command parses arguments, loads config, and calls one
function from the library. No business logic lives here, so everything the CLI does
is also reachable (and testable) from Python.
"""

import typer

from triagelab import __version__

app = typer.Typer(
    help="Eval-driven GitHub issue triage.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """Eval-driven GitHub issue triage."""


@app.command()
def version() -> None:
    """Print the installed triagelab version."""
    typer.echo(__version__)
