# steamdeck-monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A long-running Python service that sends one Telegram message whenever a watched Steam Deck refurb model's US stock state changes, and alerts loudly when the monitor itself is broken.

**Architecture:** One package, `steamdeck_monitor/`, built as pure-logic modules (models, steam parsing, monitor state machine, cross-check, outbox) around one thin I/O layer (`http.py`). A `__main__` loop wires them together. Every module takes an injected `Http` and an explicit `now`, so tests never touch the network or the clock.

**Tech Stack:** Python 3.12 standard library only, `unittest`, Alpine 3.21 image, GitHub Actions publishing to ghcr.io on `v*` tags.

**Spec:** `docs/superpowers/specs/2026-10-31-steamdeck-monitor-design.md` (read it; this plan argues from it).

## Global Constraints

- Standard library only: no pip dependencies, at runtime or in tests.
- Never copy code from `germant-cyberdictator/steamdeck-monitor` (unlicensed). The classification rules are adapted from `rfsbraz/steamhardwarestock` (MIT). Credit it in the README.
- No secret (bot token, chat ID, Healthchecks URL) may ever appear in a log line or exception text.
- Steam endpoint: `https://api.steampowered.com/IStoreBrowseService/GetHardwareItems/v1/`, using `input_json`, with **all six** package IDs in one request.
- Cross-check: `https://steamhardwarestock.com/status.json`.
- `User-Agent: steamdeck-monitor/<version> (+https://github.com/laforcem/steamdeck-monitor)` on every request.
- Tests: `python3 -W error -m unittest discover -s tests -v` must pass with no network.
- Copy ppld-calendar's CI shape: tests on push and PR, image push only on `v*` tags.

## Review Focus

1. **Steam returns 200 with an HTML or error body** (e.g. a maintenance page). It must count as a failure, not "out of stock". Test: `test_html_body_is_failure` (Task 2).
2. **Steam gives `inventory_available: true` but `requires_reservation: true`.** It must not alert. Test: `test_reservation_is_not_in_stock` (Task 2).
3. **A restart while a model is in stock** sends exactly one "IN STOCK" message. Startup from out of stock sends nothing. Tests: `test_first_poll_in_stock_alerts`, `test_first_poll_out_is_silent` (Task 3).
4. **Telegram down across an in → out flip.** Both messages are delivered later, in order. Test: `test_outbox_preserves_order_across_failures` (Task 5).
5. **Token leaking through a network exception.** A `URLError` whose text contains the request URL must not reach the logs. Test: `test_http_error_text_has_no_url` (Task 2).

---

### Task 1: Models and config

**Files:**
- Create: `steamdeck_monitor/__init__.py` (`__version__ = "0.1.0"`), `steamdeck_monitor/models.py`, `steamdeck_monitor/config.py`
- Test: `tests/__init__.py`, `tests/test_models.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `Model(key: str, package_id: int, name: str)`, a frozen dataclass.
  - `MODELS: dict[str, Model]` with exactly the six rows from the spec's model table (`512oled` 1202542, `1tboled` 1202547, `dock` 761892, `64lcd` 903905, `256lcd` 903906, `512lcd` 903907).
  - `ALL_PACKAGE_IDS: list[int]`.
  - `parse_watch(raw: str) -> list[Model]` raises `ValueError` on an unknown key or an empty list.
  - `Config` dataclass: `token: str | None, chat_id: str | None, hc_url: str | None, watch: list[Model], country: str, check_interval: float, crosscheck_interval: float, log_level: str`.
  - `load_config(env: Mapping[str, str]) -> Config`. `X_FILE` wins over `X`. File contents are stripped.

- [ ] **Step 1: Write failing tests**
  - `test_default_watch` → `[m.key for m in load_config({}).watch] == ["512oled", "1tboled"]`
  - `test_unknown_watch_key_raises` → `parse_watch("512oled,bogus")` raises `ValueError`
  - `test_file_var_wins` → a temp file containing `"abc\n"`, with `TELEGRAM_BOT_TOKEN_FILE` set to it and `TELEGRAM_BOT_TOKEN=zzz`, gives `token == "abc"`
  - `test_interval_floor` → `CHECK_INTERVAL=5` gives `check_interval == 30`
  - `test_defaults` → `country == "US"`, `check_interval == 60`, `crosscheck_interval == 900`
  - `test_crosscheck_zero_disables` → `CROSSCHECK_INTERVAL=0` gives `crosscheck_interval == 0`
  - `test_country_uppercased` → `COUNTRY_CODE=us` gives `"US"`
- [ ] **Step 2:** Run `python3 -W error -m unittest discover -s tests -v`. Expected: FAIL (import errors).
- [ ] **Step 3:** Implement `models.py` and `config.py` per the Interfaces block. Add a `.gitignore` covering `__pycache__/`.
- [ ] **Step 4:** Run the tests. Expected: all PASS.
- [ ] **Step 5:** Commit: `git add -A && git commit -m "feat: model table and config loading"`

### Task 2: HTTP layer and Steam polling

**Files:**
- Create: `steamdeck_monitor/http.py`, `steamdeck_monitor/steam.py`
- Test: `tests/fakes.py` (`FakeHttp`), `tests/test_steam.py`, `tests/test_http.py`

**Interfaces:**
- Consumes: `ALL_PACKAGE_IDS`, `__version__`.
- Produces:
  - `Response(status: int, headers: dict[str, str], body: bytes)`. Header keys are lowercased.
  - `class HttpError(Exception)`. Its message is only the exception class name plus `errno`/reason text with any URL stripped, never the URL itself.
  - `class Http`: `request(method: str, url: str, data: bytes | None = None, timeout: float = 10) -> Response`. It returns a Response for **any** HTTP status (including 4xx/5xx), and raises `HttpError` only for transport failures.
  - `tests/fakes.py: FakeHttp(responses: list[Response | Exception])`, which records `.calls: list[tuple[method, url, data]]`.
  - `classify(details: dict) -> bool | None`, implementing the spec's four-condition rule. Returns `None` if `inventory_available` isn't a bool.
  - `PollResult(kind: Literal["ok", "rate_limited", "failed"], states: dict[int, bool | None], error: str | None)`
  - `steam_url(package_ids: list[int], country: str) -> str`
  - `poll(http: Http, country: str) -> PollResult`. It polls `ALL_PACKAGE_IDS`. Any package missing from `details` maps to `None`.

- [ ] **Step 1: Write failing tests** (use `FakeHttp`)
  - `test_url_has_all_ids_one_request`: decode the `input_json` param of `steam_url(ALL_PACKAGE_IDS, "US")` and assert it equals `{"packageid": [1202542, 1202547, 761892, 903905, 903906, 903907], "context": {"country_code": "US", "language": "english"}}` (order must match `ALL_PACKAGE_IDS`).
  - `test_in_stock`: details `{"packageid": 1202542, "inventory_available": true, "allow_purchase_in_country": true, "requires_reservation": false, "account_restricted_from_purchasing": false}` → `states[1202542] is True`, `kind == "ok"`.
  - `test_reservation_is_not_in_stock`, `test_restricted_is_not_in_stock`, `test_not_sold_in_country`: each flips one field → `False`.
  - `test_high_pending_orders_ignored` → still `True`.
  - `test_missing_package_is_none`.
  - `test_non_bool_inventory_is_none`.
  - `test_429_is_rate_limited`; `test_eresult_25_is_rate_limited`; `test_eresult_84_is_rate_limited` (status 200 with header `x-eresult: 84`).
  - `test_404_is_failed`; `test_html_body_is_failure` (200 with `b"<html>"`) → `kind == "failed"`; `test_transport_error_is_failed` (the fake raises `HttpError`).
  - `test_http_error_text_has_no_url` (in `test_http.py`): feed the real `Http` a `urllib.error.URLError` whose reason contains `"https://api.telegram.org/botSECRET/x"`, by patching `urllib.request.urlopen`. Assert `"SECRET" not in str(raised HttpError)`.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement. `Http` wraps `urllib.request.urlopen`, catches `urllib.error.HTTPError` and converts it to a `Response`. It wraps every other exception as `HttpError(type(e).__name__)`, with no reason text unless a regex strips `https?://\S+`. A `failed` result's `error` is a short reason (`"HTTP 404"`, `"bad JSON"`, `"HttpError: URLError"`).
- [ ] **Step 4:** Run the tests. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat: Steam GetHardwareItems polling and classification`

### Task 3: Monitor state machine (stock, faults, backoff)

**Files:**
- Create: `steamdeck_monitor/monitor.py`, `steamdeck_monitor/messages.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Consumes: `Model`, `PollResult`.
- Produces:
  - `messages.py`: pure formatters returning HTML strings. `in_stock(m: Model, at: float)`, `sold_out(m: Model, at: float, up_seconds: float)`, `fault(label: Literal["rate limited", "Steam failing"], since: float)`, `fault_recovered()`, `out_of_sync(rows: list[tuple[Model, bool, bool]])`, `in_sync()`, `crosscheck_down(since: float)`, `crosscheck_up()`. `in_stock` includes `https://store.steampowered.com/sub/<id>/` and `https://store.steampowered.com/sale/steamdeckrefurbished/`. Timestamps are formatted `%Y-%m-%d %H:%M %Z` in local time. Fault and cross-check messages start with `"⚠️ steamdeck-monitor:"`, and recoveries start with `"🔧 steamdeck-monitor:"`, so they can't be confused with stock news.
  - `class Monitor(watch: list[Model], check_interval: float, start: float)`:
    - `on_poll(result: PollResult, now: float) -> list[str]`
    - `next_delay() -> float` (no jitter; the caller adds ±5 s)
    - `states -> dict[int, bool | None]` (all six packages, latest known)
- Rules (from the spec): success means `kind == "ok"` and every **watched** state is not `None`. Unknown never transitions. Stock messages go only for watched models. The fault clock runs from the last success (initially `start`). When it passes 1800 s, send `fault(...)` once, labelled by whichever kind dominates the failures since the last success. A success afterwards sends `fault_recovered()` once. Backoff: after `n` consecutive `rate_limited` results the delay is `min(60 * 2**n, 1800)`. Any other result resets `n` to 0 and the delay to `check_interval`.

- [ ] **Step 1: Write failing tests**
  - `test_first_poll_out_is_silent` → `[]`
  - `test_first_poll_in_stock_alerts` → one message containing `"1202542"` (the sub link)
  - `test_in_then_in_sends_nothing`
  - `test_in_to_out_sends_sold_out` → one message, `"sold out"` in lowercase text
  - `test_unwatched_change_sends_nothing` (dock 761892 flips in)
  - `test_unknown_does_not_transition`: in, then `None`, then in → only the first poll messages
  - `test_watched_unknown_counts_as_failure`: 31 minutes of `ok` polls where 1202542 is `None` → one `"Steam failing"` fault message
  - `test_fault_once_and_recovery`: failed polls every 60 s for 40 min → exactly one fault message; then an ok poll → exactly one recovery message
  - `test_fault_label_rate_limited`: mostly `rate_limited` → message contains `"rate limited"`
  - `test_backoff_doubles_and_caps` → delays after 1, 2, 3, 10 rate-limited results are 120, 240, 480, 1800; then after a `failed` result it's 60
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement per the rules above.
- [ ] **Step 4:** Run the tests. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat: stock state machine, fault clock and backoff`

### Task 4: Cross-check against steamhardwarestock

**Files:**
- Create: `steamdeck_monitor/crosscheck.py`
- Test: `tests/test_crosscheck.py`, `tests/fixtures/status.json` (a trimmed real shape: `generatedAt`, plus `products["steam-deck-refurbished"]["US"]["packages"]` and `products["steam-dock"]["US"]["packages"]`, each package `{"id": int, "status": str}`)

**Interfaces:**
- Consumes: `Http`, `ALL_PACKAGE_IDS`, `MODELS`, the `messages` formatters.
- Produces:
  - `parse_status(body: bytes, country: str, now: float) -> dict[int, bool] | None` returns `{id: status == "in_stock"}` for the six IDs present. Returns `None` on bad JSON, missing paths, or `generatedAt` more than 1800 s older than `now`.
  - `fetch_status(http: Http, country: str, now: float) -> dict[int, bool] | None` (`None` on any HTTP failure)
  - `class CrossChecker(start: float)`: `compare(ours: dict[int, bool | None], theirs: dict[int, bool] | None, now: float) -> list[str]`
- Rules: a package mismatches when both sides know it and they differ. An `out_of_sync` alert needs the **same** package mismatching on 2 consecutive `compare` calls with data, sent once until everything agrees again, then `in_sync()` once. `theirs is None` for 24 h continuously sends `crosscheck_down` once, and the next good read sends `crosscheck_up`.

- [ ] **Step 1: Write failing tests**
  - `test_parse_fixture` → `{1202542: False, ..., 761892: False}` with all six keys
  - `test_stale_is_none` (`generatedAt` 31 min old)
  - `test_bad_json_is_none`; `test_missing_country_is_none`
  - `test_single_mismatch_silent`
  - `test_two_consecutive_mismatches_alert_once` (a third mismatch adds nothing)
  - `test_recovery_after_mismatch` → `in_sync` message
  - `test_unknown_ours_not_a_mismatch`
  - `test_unavailable_24h_alerts_once_then_recovers`
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat: steamhardwarestock cross-check`

### Task 5: Telegram client and outbox

**Files:**
- Create: `steamdeck_monitor/telegram.py`
- Test: `tests/test_telegram.py`

**Interfaces:**
- Consumes: `Http`, `Response`, `HttpError`.
- Produces:
  - `class Telegram(http: Http, token: str, chat_id: str, sleep: Callable[[float], None] = time.sleep)`:
    - `get_me() -> bool`
    - `send(text: str) -> bool`: POSTs `sendMessage` with `chat_id`, `text`, `parse_mode=HTML`, `disable_web_page_preview=true`. Up to 3 attempts. Retries transport errors and 5xx. Retries 429 after `parameters.retry_after` (capped at 60 s). Never retries 400/401/403. Never logs the URL.
  - `class Outbox(maxlen: int = 50)`: `add(text: str) -> None` (drops the oldest past `maxlen`); `flush(send: Callable[[str], bool]) -> int` sends from the front and stops at the first failure; `__len__`.

- [ ] **Step 1: Write failing tests**
  - `test_send_posts_expected_form`: parse the recorded `data` and assert `parse_mode == "HTML"` and `disable_web_page_preview == "true"`
  - `test_no_retry_on_401` → one call, returns `False`
  - `test_retry_on_500_then_ok` → two calls, `True`
  - `test_429_honours_retry_after`: the injected sleep is recorded with `retry_after` 7 → sleep called with 7
  - `test_logs_never_contain_token`: use `assertLogs` around a failing send with token `"123:SECRET"` and assert `"SECRET"` appears in no record
  - `test_outbox_preserves_order_across_failures`: add A, B; flush with a sender that fails → sent `[]`; flush with an ok sender → sent `[A, B]`
  - `test_outbox_caps_at_maxlen` (`maxlen=2`, add 3 → oldest dropped)
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat: Telegram client with ordered outbox`

### Task 6: Main loop, CLI and Healthchecks

**Files:**
- Create: `steamdeck_monitor/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `main(argv: list[str] | None = None, env: Mapping[str, str] = os.environ, http: Http | None = None) -> int`, invoked as `python3 -m steamdeck_monitor`.
  - `run(cfg: Config, http: Http, telegram: Telegram, sleep, clock, max_iterations: int | None = None) -> None`
- Behaviour:
  - `--once`: one poll. Prints one line per watched model, `"<name>: in stock|out of stock|unknown"`. Exits 0 if all watched models are known, else 2. Needs no Telegram config.
  - `--test-telegram`: send `"🔔 steamdeck-monitor test message"`. Exit 0 or 1.
  - `load_config` raising `ValueError` (bad `WATCH`) → log a critical line, exit 78, in every mode.
  - Default: missing token/chat ID or `get_me()` false → log a critical line, exit 78. Otherwise `run` forever.
  - Each loop iteration: poll → `Monitor.on_poll` → messages go to the outbox. If `crosscheck_interval > 0` and it's due, call `fetch_status` → `CrossChecker.compare(monitor.states, ...)` → outbox. Then `outbox.flush(telegram.send)`, then GET `hc_url` if set (failures logged only), then `sleep(monitor.next_delay() + random.uniform(-5, 5))`.
  - SIGTERM exits cleanly with 0.
  - Logging goes to stdout at `LOG_LEVEL`.

- [ ] **Step 1: Write failing tests** (with a `FakeHttp` routing by URL prefix)
  - `test_once_output_and_exit`: Steam reports 1202542 in stock → stdout contains `"512 GB OLED"` and `"in stock"`, exit 0
  - `test_once_unknown_exits_2`
  - `test_missing_token_exits_78`
  - `test_loop_alerts_and_pings`: `max_iterations=2`, out then in → exactly one `sendMessage` call, and two Healthchecks GETs
  - `test_ping_even_when_steam_fails`: Steam 500 → Healthchecks GET still made
  - `test_crosscheck_disabled_makes_no_request` (`crosscheck_interval=0`)
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the tests. Expected: all PASS.
- [ ] **Step 5:** Commit: `feat: main loop, CLI and Healthchecks pings`

### Task 7: Packaging, CI, README and live check

**Files:**
- Create: `Dockerfile`, `.github/workflows/ci.yml`, `README.md`

**Interfaces:**
- Consumes: `python3 -m steamdeck_monitor`.

- [ ] **Step 1:** `Dockerfile`: `FROM alpine:3.21`, `apk add --no-cache python3 tzdata`, copy `steamdeck_monitor/` to `/app`, `USER 65534:65534`, `WORKDIR /app`, `ENTRYPOINT ["python3", "-m", "steamdeck_monitor"]`.
- [ ] **Step 2:** `ci.yml`: copy ppld-calendar's workflow exactly (test job running `python3 -W error -m unittest discover -s tests -v`; an image job on `v*` tags with buildx, ghcr login and build-push, tag `ghcr.io/${{ github.repository }}:${{ github.ref_name }}`).
- [ ] **Step 3:** `README.md`: what it does, the config table (copied from the spec), the `--once` and `--test-telegram` commands, and a credit line: "Stock classification rules adapted from [rfsbraz/steamhardwarestock](https://github.com/rfsbraz/steamhardwarestock) (MIT)."
- [ ] **Step 4:** Build and verify locally:
  Run: `docker build -t steamdeck-monitor:dev . && docker run --rm steamdeck-monitor:dev --once`
  Expected: two lines (512 GB OLED, 1 TB OLED), each `in stock` or `out of stock` (not `unknown`), exit 0.
- [ ] **Step 5:** Run one live cross-check read: `docker run --rm --entrypoint python3 steamdeck-monitor:dev -c "import time; from steamdeck_monitor.http import Http; from steamdeck_monitor.crosscheck import fetch_status; print(fetch_status(Http(), 'US', time.time()))"`
  Expected: a dict with six keys, not `None`.
- [ ] **Step 6:** Commit: `chore: Dockerfile, CI and README`
- [ ] **Step 7:** **Stop for Malc's go-ahead** before pushing `main` and tagging `v0.1.0` (both are outward-facing). After approval, push, tag, and confirm the CI image job succeeds with `gh run list --repo laforcem/steamdeck-monitor`.

### Task 8: Homelab deployment (in `~/repos/homelab`)

Prerequisites from Malc (ask, don't work around): create the bot with @BotFather, send it `/start`, and put the token and chat ID into bws. I get their bws IDs without printing their values.

**Files:**
- Create: `compose/steamdeck-monitor/compose.yaml`
- Modify: `compose/doco-cd/compose.yaml` (new POLL_CONFIG deployment entry), `docs/current-state.md`

- [ ] **Step 1:** Create a Healthchecks check `steamdeck-monitor` with period 1800 s and grace 600 s, using the Healthchecks MCP. Store its ping URL in bws.
- [ ] **Step 2:** `compose.yaml`: image `ghcr.io/laforcem/steamdeck-monitor:v0.1.0`, `restart: always`, `TZ` set to warden's zone, compose `secrets:` fed from env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `HEALTHCHECKS_PING_URL`, and the matching `*_FILE=/run/secrets/...` variables, following `compose/icloudpd/compose.yaml`.
- [ ] **Step 3:** doco-cd entry: `name: steamdeck-monitor`, `working_dir: compose/steamdeck-monitor`, `external_secrets` set to the three bws IDs.
- [ ] **Step 4:** Update `docs/current-state.md` (a warden workload line).
- [ ] **Step 5:** Open a homelab PR. After merge, **say so before** recreating doco-cd by hand on warden per homelab AGENTS.md. Confirm with `docker logs doco-cd | grep "self-update finalised"`, and check that the steamdeck-monitor container is running and its logs show a successful poll.
- [ ] **Step 6:** Verify end to end: run `--test-telegram` inside the container, check that the message arrives in the new chat, and check that the Healthchecks check shows "up".
