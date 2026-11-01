import json

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
