import json
import urllib.parse
from dataclasses import dataclass

from .http import HttpError
from .models import ALL_PACKAGE_IDS

STEAM_ENDPOINT = ("https://api.steampowered.com/IStoreBrowseService/"
                  "GetHardwareItems/v1/")
RATE_LIMIT_ERESULTS = {"25", "84"}  # LimitExceeded, RateLimitExceeded


@dataclass
class PollResult:
    kind: str  # "ok" | "rate_limited" | "failed"
    states: dict
    error: "str | None" = None


def steam_url(package_ids, country):
    payload = {"packageid": package_ids,
               "context": {"country_code": country, "language": "english"}}
    return STEAM_ENDPOINT + "?" + urllib.parse.urlencode(
        {"input_json": json.dumps(payload)})


def classify(details):
    """True = buyable now, False = not, None = Steam's answer is unusable."""
    inventory = details.get("inventory_available")
    if not isinstance(inventory, bool):
        return None
    return (inventory
            and details.get("allow_purchase_in_country") is not False
            and not details.get("requires_reservation")
            and not details.get("account_restricted_from_purchasing"))


def _failed(error):
    return PollResult("failed", {pid: None for pid in ALL_PACKAGE_IDS}, error)


def poll(http, country):
    try:
        resp = http.request("GET", steam_url(ALL_PACKAGE_IDS, country))
    except HttpError as e:
        return _failed(f"HttpError: {e}")
    if resp.status == 429 or resp.headers.get("x-eresult") in RATE_LIMIT_ERESULTS:
        return PollResult("rate_limited", {pid: None for pid in ALL_PACKAGE_IDS},
                          f"rate limited (HTTP {resp.status}, "
                          f"x-eresult {resp.headers.get('x-eresult')})")
    if resp.status != 200:
        return _failed(f"HTTP {resp.status}")
    try:
        details = json.loads(resp.body)["response"]["details"]
        if not isinstance(details, list):
            raise TypeError("details is not a list")
        by_id = {d.get("packageid"): d for d in details if isinstance(d, dict)}
    except (ValueError, KeyError, TypeError):
        return _failed("bad JSON")
    states = {pid: classify(by_id[pid]) if pid in by_id else None
              for pid in ALL_PACKAGE_IDS}
    return PollResult("ok", states)
