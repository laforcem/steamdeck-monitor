import calendar
import json
import time

from . import messages
from .http import HttpError
from .models import ALL_PACKAGE_IDS, MODELS

STATUS_URL = "https://steamhardwarestock.com/status.json"
PRODUCTS = ("steam-deck-refurbished", "steam-dock")
MAX_AGE = 30 * 60
CONFIRM_READS = 2
DOWN_ALERT_AFTER = 24 * 3600

_BY_ID = {m.package_id: m for m in MODELS.values()}


def parse_status(body, country, now):
    """{package id: in stock?} from steamhardwarestock, or None if unusable."""
    try:
        doc = json.loads(body)
        generated = calendar.timegm(
            time.strptime(doc["generatedAt"][:19], "%Y-%m-%dT%H:%M:%S"))
        if now - generated > MAX_AGE:
            return None
        found = {}
        for product in PRODUCTS:
            for pkg in doc["products"][product][country]["packages"]:
                if pkg["id"] in ALL_PACKAGE_IDS:
                    found[pkg["id"]] = pkg["status"] == "in_stock"
        return found or None
    except (ValueError, KeyError, TypeError):
        return None


def fetch_status(http, country, now):
    try:
        resp = http.request("GET", STATUS_URL, timeout=20)
    except HttpError:
        return None
    return parse_status(resp.body, country, now) if resp.status == 200 else None


class CrossChecker:
    def __init__(self, start):
        self._streak = {}
        self._alerted = False
        self._down_since = None
        self._down_alerted = False

    def compare(self, ours, theirs, now):
        if theirs is None:
            return self._unavailable(now)
        msgs = []
        if self._down_alerted:
            msgs.append(messages.crosscheck_up())
        self._down_since, self._down_alerted = None, False

        mismatched = {pid for pid, ours_ in ours.items()
                      if ours_ is not None and pid in theirs and ours_ != theirs[pid]}
        self._streak = {pid: self._streak.get(pid, 0) + 1 for pid in mismatched}
        confirmed = sorted(pid for pid, n in self._streak.items()
                           if n >= CONFIRM_READS)
        if confirmed and not self._alerted:
            self._alerted = True
            msgs.append(messages.out_of_sync(
                [(_BY_ID[pid], ours[pid], theirs[pid]) for pid in confirmed]))
        elif self._alerted and not mismatched:
            self._alerted = False
            msgs.append(messages.in_sync())
        return msgs

    def _unavailable(self, now):
        if self._down_since is None:
            self._down_since = now
        if (not self._down_alerted
                and now - self._down_since >= DOWN_ALERT_AFTER):
            self._down_alerted = True
            return [messages.crosscheck_down(self._down_since)]
        return []
