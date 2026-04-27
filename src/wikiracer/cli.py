import sys
from os import environ
from pathlib import Path
from typing import Annotated

import typer


app = typer.Typer(
    add_completion=False,
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)


def run_mitmproxy(args: list[str]) -> None:
    """Run mitmproxy with the packaged addon loaded."""
    from mitmproxy.tools.main import mitmproxy

    addon_path = Path(__file__).with_name("addon.py")
    sys.argv = [
        "mitmproxy",
        "-s",
        str(addon_path),
        *args,
    ]
    mitmproxy()


@app.command()
def cli(
    ctx: typer.Context,
    except_option: Annotated[
        str | None,
        typer.Option(
            "--except",
            "--exceptions",
            help="Comma-separated article titles, paths, or URLs that remain enabled.",
        ),
    ] = None,
    highlight_disabled_links: Annotated[
        bool,
        typer.Option(
            "--highlight-disabled-links",
            "--red-disabled-links",
            help="Render disabled links as red text instead of plain text.",
        ),
    ] = False,
) -> None:
    """Run the Wikipedia race mitmproxy addon.

    Unknown arguments are passed through to mitmproxy.
    """
    if except_option:
        environ["WIKIRACE_EXCEPTIONS"] = except_option
    if highlight_disabled_links:
        environ["WIKIRACE_HIGHLIGHT_DISABLED_LINKS"] = "1"

    run_mitmproxy(list(ctx.args))


def main() -> None:
    app()
