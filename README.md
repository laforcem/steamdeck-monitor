# steamdeck-monitor

Sends a Telegram message when a Steam Deck **Certified Refurbished** model (or the Dock) comes into stock on the US Steam store, and another when it sells out again. Alerts fire on state changes only: no repeat pings.

It polls Steam's `IStoreBrowseService/GetHardwareItems` endpoint (the one Valve's own sale page uses) once a minute, and cross-checks the result against [steamhardwarestock.com](https://steamhardwarestock.com/) every 15 minutes. If the two disagree, or Steam fails or rate-limits it for 30 minutes, it tells you, so a broken monitor doesn't look like an empty shelf.

Python 3 standard library only.

## Run

```sh
docker run --rm ghcr.io/laforcem/steamdeck-monitor:v0.1.0 --once          # one check, no Telegram needed
docker run --rm -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_CHAT_ID=... \
  ghcr.io/laforcem/steamdeck-monitor:v0.1.0 --test-telegram                # send a test message
```

Without flags it runs forever. Exit code 78 means bad configuration (the container shouldn't restart-loop on it).

## Configuration

Each secret also accepts a `*_FILE` variant (path to a file holding the value), which wins over the plain variable.

| Variable | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_TOKEN_FILE` | required | from @BotFather |
| `TELEGRAM_CHAT_ID`, `TELEGRAM_CHAT_ID_FILE` | required | |
| `HEALTHCHECKS_PING_URL`, `..._FILE` | unset | pinged after every loop iteration |
| `WATCH` | `512oled,1tboled` | any of `512oled,1tboled,dock,64lcd,256lcd,512lcd` |
| `COUNTRY_CODE` | `US` | Steam storefront country |
| `CHECK_INTERVAL` | `60` | seconds, minimum 30 |
| `CROSSCHECK_INTERVAL` | `900` | seconds, `0` disables the steamhardwarestock cross-check |
| `LOG_LEVEL` | `INFO` | |

## Develop

```sh
python3 -W error -m unittest discover -s tests -v
```

Design: [`docs/superpowers/specs/2026-10-31-steamdeck-monitor-design.md`](docs/superpowers/specs/2026-10-31-steamdeck-monitor-design.md). Images are published to ghcr.io only for `v*` tags.

## Credits

Stock classification rules adapted from [rfsbraz/steamhardwarestock](https://github.com/rfsbraz/steamhardwarestock) (MIT). Not affiliated with Valve.

## License

MIT.
