import json
import logging
import time
import urllib.parse
from collections import deque

from .http import HttpError

log = logging.getLogger("steamdeck-monitor")

API = "https://api.telegram.org"
ATTEMPTS = 3
MAX_RETRY_AFTER = 60


class Telegram:
    def __init__(self, http, token, chat_id, sleep=time.sleep):
        self._http = http
        self._token = token
        self._chat_id = chat_id
        self._sleep = sleep

    def _url(self, method):
        return f"{API}/bot{self._token}/{method}"

    def _safe(self, text):
        return str(text).replace(self._token, "<token>")

    def get_me(self):
        try:
            resp = self._http.request("GET", self._url("getMe"))
        except HttpError as e:
            log.error("Telegram getMe failed: %s", self._safe(e))
            return False
        if resp.status != 200:
            log.error("Telegram getMe returned HTTP %s", resp.status)
        return resp.status == 200

    def send(self, text):
        """Send one message. Returns True on success; never raises."""
        data = urllib.parse.urlencode({
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        for attempt in range(ATTEMPTS):
            last = attempt == ATTEMPTS - 1
            try:
                resp = self._http.request("POST", self._url("sendMessage"), data)
            except HttpError as e:
                log.error("Telegram send failed (attempt %d): %s",
                          attempt + 1, self._safe(e))
                resp = None
            if resp is not None:
                if resp.status == 200:
                    return True
                log.error("Telegram HTTP %s (attempt %d)", resp.status, attempt + 1)
                if resp.status in (400, 401, 403):
                    return False  # bad token / chat id: retrying won't help
                if resp.status == 429 and not last:
                    self._sleep(min(self._retry_after(resp), MAX_RETRY_AFTER))
                    continue
            if not last:
                self._sleep(2 * (attempt + 1))
        return False

    @staticmethod
    def _retry_after(resp):
        try:
            return float(json.loads(resp.body)["parameters"]["retry_after"])
        except (ValueError, KeyError, TypeError):
            return 5.0


class Outbox:
    """Ordered, bounded, in-memory queue of messages waiting for Telegram."""

    def __init__(self, maxlen=50):
        self._queue = deque(maxlen=maxlen)

    def add(self, text):
        self._queue.append(text)

    def flush(self, send):
        sent = 0
        while self._queue and send(self._queue[0]):
            self._queue.popleft()
            sent += 1
        return sent

    def __len__(self):
        return len(self._queue)
