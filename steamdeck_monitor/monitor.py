import logging

from . import messages
from .models import ALL_PACKAGE_IDS

log = logging.getLogger("steamdeck-monitor")

FAULT_AFTER = 30 * 60
MAX_BACKOFF = 30 * 60


class Monitor:
    """Turns poll results into messages. No I/O and no clock of its own."""

    def __init__(self, watch, check_interval, start):
        self.watch = watch
        self.check_interval = check_interval
        self.states = {pid: None for pid in ALL_PACKAGE_IDS}
        self._in_since = {}
        self._last_success = start
        self._failures = {"rate_limited": 0, "failed": 0}
        self._fault_sent = False
        self._rate_limited_streak = 0

    def on_poll(self, result, now):
        msgs = []
        if result.kind == "ok":
            msgs += self._apply_states(result.states, now)
        if result.kind == "ok" and all(
                result.states[m.package_id] is not None for m in self.watch):
            msgs += self._on_success(now)
        else:
            msgs += self._on_failure(result, now)
        self._rate_limited_streak = (
            self._rate_limited_streak + 1 if result.kind == "rate_limited" else 0)
        return msgs

    def next_delay(self):
        return min(self.check_interval * 2 ** self._rate_limited_streak,
                   MAX_BACKOFF)

    def _apply_states(self, states, now):
        msgs = []
        watched = {m.package_id: m for m in self.watch}
        for pid, new in states.items():
            if new is None:
                continue
            prev = self.states[pid]
            model = watched.get(pid)
            if new and not prev:
                self._in_since[pid] = now
                if model:
                    msgs.append(messages.in_stock(model, now))
            elif prev and not new and model:
                msgs.append(messages.sold_out(
                    model, now, now - self._in_since.pop(pid, now)))
            self.states[pid] = new
        return msgs

    def _on_success(self, now):
        msgs = [messages.fault_recovered()] if self._fault_sent else []
        self._last_success = now
        self._failures = {"rate_limited": 0, "failed": 0}
        self._fault_sent = False
        return msgs

    def _on_failure(self, result, now):
        # An "ok" poll that leaves a watched package unknown counts as a failed one.
        kind = "rate_limited" if result.kind == "rate_limited" else "failed"
        self._failures[kind] += 1
        log.warning("poll %s: %s", kind, result.error or "watched package unknown")
        if self._fault_sent or now - self._last_success < FAULT_AFTER:
            return []
        self._fault_sent = True
        label = ("rate limited"
                 if self._failures["rate_limited"] > self._failures["failed"]
                 else "Steam failing")
        return [messages.fault(label, self._last_success)]
