# steamdeck-monitor design

Date: 2026-10-31

## Intent

Malc wants a Steam Deck **512 GB OLED, Valve Certified Refurbished** (US store, $629). Refurb stock comes from customer returns, appears without warning, and can sell out within minutes. This service watches Steam and sends one Telegram message when a watched model comes into stock and one when it goes out of stock again. It's for one person, running on warden in the homelab.

It replaces an unmaintained third-party script (`germant-cyberdictator/steamdeck-monitor`). That script's Steam endpoint (`IPhysicalGoodsService/CheckInventoryAvailableByPackage`) now returns HTTP 404, so it fails silently except for a slow "all checks failing" alert. Avoiding that failure mode, a dead upstream API going unnoticed, is the main reason this is a fresh build with a cross-check.

## Goals

- Alert within about a minute of a watched model's stock state changing.
- **State-change only**: one message on out→in, one message on in→out. No repeat pings while in stock.
- Fail loudly: if the Steam API breaks, changes shape, or rate-limits us, Malc finds out, and can tell those cases apart from "no stock".
- Small, tested, boring to maintain.

## Non-goals

- Countries other than one configured storefront (default `US`).
- New (non-refurb) Decks, other Steam hardware beyond the Dock, price tracking, auto-purchase, a web UI.
- Quiet hours. Malc's phone and Telegram's per-chat settings handle Do Not Disturb.
- A daily "still alive" Telegram message. Liveness goes to Healthchecks instead (see below).
- Persisting state across restarts.

## Anti-goals

- **Silent failure.** A monitor that reports "out of stock" forever because the API died is worse than none.
- **Spam.** Anything beyond one message per real state change (or per real fault and recovery) is a bug.
- **Hammering Steam.** One request per poll, never more, with backoff on rate limits.

## Constraints

- **Licensing.** The repo is public and MIT. The original script has no license, so none of its code may be copied. Write this from scratch. The stock-classification rules below are adapted from `rfsbraz/steamhardwarestock` (MIT, `public/stock-status.js`). Credit it in the README.
- **Repo pattern.** Copy `laforcem/ppld-calendar`: Alpine base image, Python 3 standard library only (no pip dependencies), `unittest` tests in `tests/`, and a GitHub Actions CI that runs the tests on every push and PR. It pushes `ghcr.io/laforcem/steamdeck-monitor:<tag>` only on `v*` tags, so warden always runs a pinned version.
- **Secrets** arrive as files through the `*_FILE` environment pattern, the same as `icloudpd-telegram-bot`. Never log a secret, including the bot token inside a Telegram URL in an exception message.
- **Rate limits.** Valve publishes no limit for this endpoint. The only official figure is 100,000 calls a day, for key-based Web API calls. Community reports suggest the store throttles somewhere around 200 requests per 5 minutes. We make 1 request a minute.

## Approaches

Three were considered. Malc picked **A**.

- **A. Long-running Python service (chosen).** One process loops: check, compare with in-memory state, notify on change, ping Healthchecks, sleep. It's the simplest, it matches `ppld-calendar`, and backoff lives naturally in the loop. Cost: a restart while a model is in stock re-sends that "in stock" alert once. Accepted.
- **B. One-shot check on a schedule** (container cron or k3s CronJob) with a state file. State survives restarts, but a 60-second schedule is clumsy and backoff needs state carried between runs. Rejected: more moving parts for the same result.
- **C. Prometheus json_exporter plus Alertmanager on k3s.** No custom code, and firing/resolved maps onto in/out of stock. Rejected: it runs on chimaera rather than warden, adds scrape and grouping latency, makes the cross-check and rate-limit handling awkward, and mixes a personal hunt into infrastructure alerting.

## How it works

### Primary source: Steam, every 60 seconds

`GET https://api.steampowered.com/IStoreBrowseService/GetHardwareItems/v1/?input_json=<urlencoded JSON>`

```json
{"packageid": [1202542, 1202547], "context": {"country_code": "US", "language": "english"}}
```

This is the endpoint Valve's own sale page calls, and the one steamhardwarestock uses. It needs no API key. **Every package ID in the model table goes in one request, watched or not**, so the cross-check has our view of all of them. Only watched models send stock alerts. Unwatched ones are tracked for the cross-check and nothing else. Verified live on 2026-10-31: HTTP 200, header `x-eresult: 1`, body `{"response": {"details": [ {...}, ... ]}}` with one object per package. Relevant fields: `packageid`, `inventory_available`, `allow_purchase_in_country`, `requires_reservation`, `account_restricted_from_purchasing`, `high_pending_orders`.

**Classification**, adapted from steamhardwarestock. A package counts as **in stock** only if all of these hold:

- `allow_purchase_in_country` is not `false`
- `requires_reservation` is falsy
- `account_restricted_from_purchasing` is falsy
- `inventory_available` is `true`

Anything else is **out of stock**. `high_pending_orders` doesn't affect the result.

A package missing from `details`, or a response that isn't the expected shape (e.g. `inventory_available` not a boolean), is **unknown**, not out of stock. Unknown never causes a transition and leaves the previous state as it was.

### Models

| Key | Package ID | Name | Default |
|---|---|---|---|
| `512oled` | 1202542 | Steam Deck 512 GB OLED (refurb) | watched |
| `1tboled` | 1202547 | Steam Deck 1 TB OLED (refurb) | watched |
| `dock` | 761892 | Steam Deck Docking Station (new) | off |
| `64lcd` | 903905 | Steam Deck 64 GB LCD (refurb) | off |
| `256lcd` | 903906 | Steam Deck 256 GB LCD (refurb) | off |
| `512lcd` | 903907 | Steam Deck 512 GB LCD (refurb) | off |

The package IDs were verified against the live sale page and against `IStoreBrowseService/GetItems` on 2026-10-31. Malc will turn on the Dock after buying a Deck.

### State and alerts

- Startup state for every model is **unknown**.
- unknown/out → in: send **"IN STOCK"**, with the model name and links to `https://store.steampowered.com/sub/<packageid>/` and the refurb sale page. On first start, a model that's already in stock alerts. That's intentional.
- in → out: send **"sold out again"**, with roughly how long it was up.
- unknown → out: silent.
- Anything → unknown: silent. Keep the last known state.
- Rapid flapping (in, out, in) alerts on every change. That's acceptable and matches "state-change monitoring".

### Fault alerts (also state-change only)

Each fault is a state with one message on entry and one on recovery. Wording must make it obvious these are monitor problems, not stock news.

1. **Rate limited.** An HTTP 429, or an `x-eresult` header of `25` (LimitExceeded) or `84` (RateLimitExceeded). Back off exponentially from 60 seconds, doubling, capped at 30 minutes, with jitter. Alert once if rate limiting has lasted **30 minutes**. Send a recovery message on the next success.
2. **Steam failing.** Any other failure: network error, non-200, an unexpected shape, or the endpoint returning 404 as the old one did. Alert once after **30 minutes** of every poll failing. Send a recovery message on the next success.
3. **Out of sync with the cross-check** (below).

**What counts as success.** A poll succeeds only if it returns 200, is the right shape, and classifies **every watched** package. A response that leaves a watched package unknown (missing from `details`, or a bad field) counts as a failure for the "Steam failing" timer. That catches a delisted or renumbered package, which would otherwise go quiet. Unwatched packages being unknown doesn't affect success.

**Timers (decided).** Both 30-minute alerts measure time since the **last successful poll**. When it passes 30 minutes, send one fault alert, labelled "rate limited" if most failures in that window were rate limits and "Steam failing" otherwise. A success resets everything and sends the recovery message if a fault alert went out. Only rate-limit responses trigger exponential backoff. Other failures keep polling at `CHECK_INTERVAL`.

All polling uses ±5 s of random jitter.

### Cross-check: steamhardwarestock, every 15 minutes

`GET https://steamhardwarestock.com/status.json` (about 356 KB; their server refreshes it every 600 s). Paths used:

- `products["steam-deck-refurbished"]["US"]["packages"][]` → `{id, status, ...}`
- `products["steam-dock"]["US"]["packages"][]`
- top-level `generatedAt` (ISO 8601)

Their `status == "in_stock"` is compared with our classification **for every package ID in the model table, watched or not**. That way a change in Steam's API is caught even though the watched models rarely restock.

Their data can be up to about 10 minutes behind ours, so **one disagreement doesn't alert**. A package must disagree on **two consecutive** cross-check reads (about 15–30 minutes) before the "out of sync" alert fires, naming the packages and both sides' view. Recovery sends one message.

If status.json is unreachable, unparsable, or `generatedAt` is more than 30 minutes old, the cross-check is **unavailable**. That's logged, not alerted. A third-party outage isn't Malc's problem unless it lasts. **Builder's call:** alert once if it has been unavailable for 24 hours, with a recovery message.

### Liveness: Healthchecks

Healthchecks covers **process liveness only**: "is the loop still running?" The in-app alerts cover API faults, so each fault produces exactly one alert, and that alert says what's wrong. GET the ping URL at the end of **every loop iteration**, whether or not the Steam poll succeeded, and including iterations in backoff. Set the check's period to about the longest sleep (30 minutes at maximum backoff) plus a margin. A failed ping is logged and otherwise ignored. No `/fail` pings.

### Telegram

- `sendMessage` with `parse_mode=HTML`, `disable_web_page_preview=true`, and normal notifications (no silent flag; DND is the phone's job).
- Retry transient failures (network, 5xx, 429 honouring `retry_after`) a few times. Don't retry 400/401/403.
- **Outbox (decided).** State always follows Steam. Telegram failures never roll it back. Messages go into an in-memory queue in order. Each loop iteration sends from the front until one fails, then stops until next time. That keeps the order "in stock" → "sold out" even if Telegram is down in between. Each message carries the time of the state change, so a late "IN STOCK" says when it actually happened. Queue size is capped (e.g. 50, dropping the oldest), and queued messages are lost on restart.
- At startup, call `getMe` to validate the token. Exit non-zero with a clear log line if it fails. Don't send a startup message.
- `--test-telegram`: send one test message and exit, for setup.
- `--once`: one Steam check, print each watched model's state, exit (0 if everything is known, non-zero if anything is unknown). Needs no Telegram config.

### Configuration (environment)

| Variable | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN_FILE` | required | new dedicated bot |
| `TELEGRAM_CHAT_ID_FILE` | required | |
| `HEALTHCHECKS_PING_URL_FILE` | optional | skip pings if unset |
| `WATCH` | `512oled,1tboled` | comma list of keys; unknown key = exit non-zero at startup |
| `COUNTRY_CODE` | `US` | used for both Steam and the cross-check |
| `CHECK_INTERVAL` | `60` | seconds; enforce a floor of 30 |
| `CROSSCHECK_INTERVAL` | `900` | seconds; `0` disables |
| `LOG_LEVEL` | `INFO` | logs to stdout |

The plain `TELEGRAM_BOT_TOKEN` etc. may also be accepted for local runs. Builder's call.

## Testing

- Unit tests with a fake HTTP layer. No network in CI.
- Cover: the classification rules; every state transition, including unknown handling; one alert per transition (no repeats); rate-limit detection by 429 and by `x-eresult` 25/84; backoff growth and cap; the 30-minute fault alerts and their recovery messages; cross-check mismatch needing two consecutive reads; cross-check staleness; and that secrets never appear in logs.
- Before tagging v0.1.0, run `--once` against live Steam and one real cross-check read.

## Deployment (homelab repo, after the image exists)

- Malc creates the bot with @BotFather and gets the chat ID. The token and chat ID go into bws (one project, per existing practice) without being printed.
- Create a Healthchecks check (period 30 min, grace 10 min, matching the ping rules above) and store its ping URL in bws.
- Add `compose/steamdeck-monitor/compose.yaml` to homelab: a pinned image tag, compose secrets fed from environment variables, and the `*_FILE` variables, following `compose/icloudpd/compose.yaml`.
- Add a `steamdeck-monitor` entry to doco-cd's `POLL_CONFIG` in `compose/doco-cd/compose.yaml`, with `external_secrets` set to the bws IDs. **Caveat from homelab AGENTS.md:** a `POLL_CONFIG` change doesn't take effect on merge. doco-cd has to be recreated by hand on warden using the documented procedure.
- Update `docs/current-state.md` in the same homelab change.

## Left to the builder

Module layout, message wording beyond the content listed above, retry counts, log format, the exact backoff jitter, and the calls marked "Builder's call" above.
