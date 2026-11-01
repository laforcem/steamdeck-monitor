import argparse
import logging
import os
import random
import signal
import sys
import time

from .config import load_config
from .crosscheck import CrossChecker, fetch_status
from .http import Http, HttpError
from .monitor import Monitor
from .steam import poll
from .telegram import Outbox, Telegram

log = logging.getLogger("steamdeck-monitor")

EX_CONFIG = 78  # systemd/docker restart policies shouldn't loop on this
JITTER = 5


def _word(state):
    return "unknown" if state is None else "in stock" if state else "out of stock"


def _ping(http, url):
    try:
        http.request("GET", url, timeout=10)
    except HttpError as e:
        log.warning("Healthchecks ping failed: %s", e)


def run(cfg, http, telegram, sleep, clock, max_iterations=None):
    monitor = Monitor(cfg.watch, cfg.check_interval, start=clock())
    crosscheck = CrossChecker(clock())
    outbox = Outbox()
    next_crosscheck = clock()
    log.info("Watching %s [%s], polling every %ds",
             ", ".join(m.key for m in cfg.watch), cfg.country,
             int(cfg.check_interval))

    iteration = 0
    while True:
        now = clock()
        for text in monitor.on_poll(poll(http, cfg.country), now):
            outbox.add(text)
        if cfg.crosscheck_interval > 0 and now >= next_crosscheck:
            next_crosscheck = now + cfg.crosscheck_interval
            theirs = fetch_status(http, cfg.country, now)
            for text in crosscheck.compare(monitor.states, theirs, now):
                outbox.add(text)
        outbox.flush(telegram.send)
        if cfg.hc_url:
            _ping(http, cfg.hc_url)

        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            return
        sleep(monitor.next_delay() + random.uniform(-JITTER, JITTER))


def main(argv=None, env=os.environ, http=None):
    parser = argparse.ArgumentParser(
        prog="steamdeck-monitor",
        description="Telegram alerts for Steam Deck refurbished stock changes")
    parser.add_argument("--once", action="store_true",
                        help="check once, print each watched model's state, exit")
    parser.add_argument("--test-telegram", action="store_true",
                        help="send one test message and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=(env.get("LOG_LEVEL") or "INFO").upper(), stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    try:
        cfg = load_config(env)
    except (ValueError, OSError) as e:
        log.critical("Bad configuration: %s", e)
        return EX_CONFIG
    http = http or Http()

    if args.once:
        result = poll(http, cfg.country)
        if result.error:
            log.warning("Steam check: %s", result.error)
        states = [result.states[m.package_id] for m in cfg.watch]
        for m, state in zip(cfg.watch, states):
            print(f"{m.name}: {_word(state)}")
        return 2 if None in states else 0

    if not cfg.token or not cfg.chat_id:
        log.critical("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
                     "(or their *_FILE variants).")
        return EX_CONFIG
    telegram = Telegram(http, cfg.token, cfg.chat_id)

    if args.test_telegram:
        ok = telegram.send("🔔 steamdeck-monitor test message")
        print("Telegram test:", "OK" if ok else "FAILED (see log above)")
        return 0 if ok else 1

    if not telegram.get_me():
        log.critical("Telegram rejected the bot token (check TELEGRAM_BOT_TOKEN).")
        return EX_CONFIG

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        run(cfg, http, telegram, time.sleep, time.time)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
