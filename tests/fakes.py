import json
import os

from steamdeck_monitor.http import Response


class FakeHttp:
    """Plays back queued responses (or raises queued exceptions) in order."""

    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, data=None, timeout=10):
        self.calls.append((method, url, data))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def detail(package_id, inventory=True, allowed=True, reservation=False,
           restricted=False, high_pending=False):
    return {
        "packageid": package_id,
        "inventory_available": inventory,
        "allow_purchase_in_country": allowed,
        "requires_reservation": reservation,
        "account_restricted_from_purchasing": restricted,
        "high_pending_orders": high_pending,
    }


def steam_response(details, status=200, headers=None):
    body = json.dumps({"response": {"details": details}}).encode()
    return Response(status, {"x-eresult": "1", **(headers or {})}, body)


class Router:
    """Routes requests by URL prefix to per-prefix queues of responses."""

    def __init__(self, routes):
        self.routes = {prefix: list(items) for prefix, items in routes.items()}
        self.calls = []

    def request(self, method, url, data=None, timeout=10):
        self.calls.append((method, url, data))
        for prefix, queue in self.routes.items():
            if url.startswith(prefix):
                item = queue.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        raise AssertionError(f"unrouted request: {method} {url}")

    def count(self, prefix):
        return sum(1 for _, url, _ in self.calls if url.startswith(prefix))


def shs_response():
    """steamhardwarestock status.json (everything out of stock)."""
    path = os.path.join(os.path.dirname(__file__), "fixtures", "status.json")
    with open(path, "rb") as f:
        return Response(200, {}, f.read())
