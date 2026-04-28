# Wikiracer

Wikiracer is a small party-game host for Wikipedia racing. It runs as a
`mitmproxy` addon, watches the Wikipedia pages each player opens, disables links
to pages that have already been visited, and publishes a live progress view for
the audience.

The monitor shows every participant's current article, step count, full path,
and a graph of the routes through Wikipedia. An admin view lets the host name
participants and start a new round or a completely new game.

## The Game

In a wiki race, everyone starts on the same Wikipedia article and tries to reach
a chosen target article by clicking only links inside Wikipedia. Searching,
typing URLs, using browser history, or leaving Wikipedia is normally not allowed.

This version adds one important constraint: once any player has visited a page,
links to that page are disabled for everyone. That makes the race less about
following the obvious shortest path and more about finding alternate routes
through Wikipedia before somebody else uses them.

Typical host flow:

1. Pick a start article and a target article.
2. Have all players open the start article through the configured browser proxy.
3. Start the round and tell players the target.
4. Watch the live audience view while players race.
5. Use the admin view to reset paths for the next round, or reset the whole game
   to clear the globally visited pages.

## Server Setup

Install the command-line tool:

```bash
uv tool install https://github.com/fxjung/wikiracer.git
```

Then run the proxy and monitor:

```bash
wikiracer
```

The monitor UI runs on `http://127.0.0.1:9999` by default.

Useful options:

```bash
wikiracer --monitor-host 0.0.0.0 --monitor-port 9999
wikiracer --except "Main Page,Help:Contents"
wikiracer --highlight-disabled-links
```

- `--monitor-host` and `--monitor-port` control where the audience/admin UI is
  served.
- `--except` keeps specific article titles, paths, or URLs clickable even after
  they have been visited.
- `--highlight-disabled-links` renders disabled links as red text instead of
  plain text.
- Any unknown options are passed through to `mitmproxy`.

## Player Setup

For each player browser:

1. Create a dedicated Firefox profile.
2. Configure the Wikiracer server as the HTTP and HTTPS proxy.
3. Open [mitm.it](http://mitm.it/) in that profile and install the mitmproxy CA
   certificate.
4. Visit `wikipedia.org` through that profile and start racing.

## Views

- Player browser: `https://wikipedia.org`
- Audience view: `http://<server>:9999/`
- Admin view: `http://<server>:9999/admin`
