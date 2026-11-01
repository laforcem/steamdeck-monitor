import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

USER_AGENT = (f"steamdeck-monitor/{__version__} "
              "(+https://github.com/laforcem/steamdeck-monitor)")

_URL = re.compile(r"https?://\S+")


@dataclass
class Response:
    status: int
    headers: dict
    body: bytes


class HttpError(Exception):
    """Transport failure. The message never contains a URL (it may hold a token)."""


def _headers(msg):
    return {k.lower(): v for k, v in (msg or {}).items()}


class Http:
    def request(self, method, url, data=None, timeout=10):
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, _headers(resp.headers), resp.read())
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:  # noqa: BLE001 -- the status is what matters
                body = b""
            return Response(e.code, _headers(e.headers), body)
        except Exception as e:  # noqa: BLE001 -- anything else is transport
            reason = _URL.sub("<url>", str(getattr(e, "reason", "") or ""))
            raise HttpError(f"{type(e).__name__}: {reason}".rstrip(": ")) from None
