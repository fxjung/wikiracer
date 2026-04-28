import sys
from os import environ
from pathlib import Path
from typing import Annotated

import typer

from .options import DEFAULT_PROXY_HOST, DEFAULT_PROXY_PORT


app = typer.Typer(
    add_completion=False,
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    },
)


def run_mitmproxy(args: list[str], host: str, port: int) -> None:
    """Run mitmproxy with the packaged addon loaded."""
    from mitmproxy.tools.main import mitmproxy

    addon_path = Path(__file__).with_name("addon.py")
    mitmproxy_args = [
        "--listen-host",
        host,
        "--listen-port",
        str(port),
    ]
    if host not in {"127.0.0.1", "::1", "localhost"}:
        mitmproxy_args.extend(["--set", "block_global=false"])

    sys.argv = [
        "mitmproxy",
        *mitmproxy_args,
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
    host: Annotated[
        str,
        typer.Option(
            "--host",
            help="Bind host for the proxy (0.0.0.0 for LAN access).",
        ),
    ] = DEFAULT_PROXY_HOST,
    port: Annotated[
        int,
        typer.Option(
            "--port",
            min=1,
            max=65535,
            help="Bind port for the proxy.",
        ),
    ] = DEFAULT_PROXY_PORT,
    monitor_host: Annotated[
        str | None,
        typer.Option(
            "--monitor-host",
            help="Bind host for the monitor UI (defaults to --host).",
        ),
    ] = None,
    monitor_port: Annotated[
        int | None,
        typer.Option(
            "--monitor-port",
            min=1,
            max=65535,
            help="Bind port for the monitor UI (defaults to 9999).",
        ),
    ] = None,
) -> None:
    """Run the Wikipedia race mitmproxy addon.

    Unknown arguments are passed through to mitmproxy.
    """
    if except_option:
        environ["WIKIRACE_EXCEPTIONS"] = except_option
    if highlight_disabled_links:
        environ["WIKIRACE_HIGHLIGHT_DISABLED_LINKS"] = "1"
    environ["WIKIRACE_PROXY_HOST"] = host
    environ["WIKIRACE_PROXY_PORT"] = str(port)
    resolved_monitor_host = monitor_host if monitor_host is not None else host
    resolved_monitor_port = (
        monitor_port if monitor_port is not None else (10000 if port == 9999 else 9999)
    )
    if resolved_monitor_host == host and resolved_monitor_port == port:
        raise typer.BadParameter(
            "--monitor-host/--monitor-port must not be identical to --host/--port."
        )
    environ["WIKIRACE_MONITOR_HOST"] = resolved_monitor_host
    environ["WIKIRACE_MONITOR_PORT"] = str(resolved_monitor_port)

    run_mitmproxy(list(ctx.args), host=host, port=port)


def main() -> None:
    app()
