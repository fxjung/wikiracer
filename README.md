# Wiki racing game


## Server setup:

```bash
uv tool install https://github.com/fxjung/wikiracer.git
```

Then run:

```bash
wikiracer
```

## Client setup

- Create custom Firefox profile
- Set up server as proxy for http and https
- Visit [mitm.it](http://mitm.it/) to download and install MITM CA cert in Firefox
- Visit `wikipedia.org` to play, `<server>:<host>` for audience view, and `<server>:<host>/admin` for admin view
