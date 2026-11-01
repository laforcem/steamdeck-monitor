import unittest

from fakes import detail, steam_response  # noqa: F401  (shared helpers)
from steamdeck_monitor.models import ALL_PACKAGE_IDS, MODELS
from steamdeck_monitor.monitor import Monitor
from steamdeck_monitor.steam import PollResult

OLED, TB, DOCK = 1202542, 1202547, 761892
WATCH = [MODELS["512oled"], MODELS["1tboled"]]


def ok(**overrides):
    states = {pid: False for pid in ALL_PACKAGE_IDS}
    states.update({int(k.lstrip("p")): v for k, v in overrides.items()})
    return PollResult("ok", states)


def failed(kind="failed"):
    return PollResult(kind, {pid: None for pid in ALL_PACKAGE_IDS}, "boom")


def monitor():
    return Monitor(WATCH, 60, start=0)


class StockTransitionsTest(unittest.TestCase):
    def test_first_poll_out_is_silent(self):
        self.assertEqual(monitor().on_poll(ok(), 0), [])

    def test_first_poll_in_stock_alerts(self):
        msgs = monitor().on_poll(ok(**{f"p{OLED}": True}), 0)
        self.assertEqual(len(msgs), 1)
        self.assertIn("IN STOCK", msgs[0])
        self.assertIn(f"https://store.steampowered.com/sub/{OLED}/", msgs[0])
        self.assertIn("https://store.steampowered.com/sale/steamdeckrefurbished/",
                      msgs[0])

    def test_in_then_in_sends_nothing(self):
        m = monitor()
        m.on_poll(ok(**{f"p{OLED}": True}), 0)
        self.assertEqual(m.on_poll(ok(**{f"p{OLED}": True}), 60), [])

    def test_in_to_out_sends_sold_out(self):
        m = monitor()
        m.on_poll(ok(**{f"p{OLED}": True}), 0)
        msgs = m.on_poll(ok(), 600)
        self.assertEqual(len(msgs), 1)
        self.assertIn("sold out", msgs[0])
        self.assertIn("10 min", msgs[0])

    def test_unwatched_change_sends_nothing(self):
        self.assertEqual(monitor().on_poll(ok(**{f"p{DOCK}": True}), 0), [])

    def test_unwatched_state_is_still_tracked(self):
        m = monitor()
        m.on_poll(ok(**{f"p{DOCK}": True}), 0)
        self.assertIs(m.states[DOCK], True)

    def test_unknown_does_not_transition(self):
        m = monitor()
        sent = m.on_poll(ok(**{f"p{OLED}": True}), 0)
        partial = ok(**{f"p{OLED}": None, f"p{TB}": False})
        sent += m.on_poll(partial, 60)
        sent += m.on_poll(ok(**{f"p{OLED}": True}), 120)
        self.assertEqual(len(sent), 1)

    def test_dock_alert_has_no_refurb_link(self):
        m = Monitor([MODELS["dock"]], 60, start=0)
        msgs = m.on_poll(ok(**{f"p{DOCK}": True}), 0)
        self.assertNotIn("steamdeckrefurbished", msgs[0])
        self.assertIn(f"/sub/{DOCK}/", msgs[0])


class FaultTest(unittest.TestCase):
    def test_watched_unknown_counts_as_failure(self):
        m = monitor()
        sent = []
        for t in range(0, 31 * 60, 60):
            sent += m.on_poll(ok(**{f"p{OLED}": None}), t)
        faults = [s for s in sent if "steamdeck-monitor:" in s]
        self.assertEqual(len(faults), 1)
        self.assertIn("Steam failing", faults[0])

    def test_fault_once_and_recovery(self):
        m = monitor()
        sent = []
        for t in range(0, 40 * 60, 60):
            sent += m.on_poll(failed(), t)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("⚠️ steamdeck-monitor:"))
        back = m.on_poll(ok(), 40 * 60)
        self.assertEqual(len(back), 1)
        self.assertTrue(back[0].startswith("🔧 steamdeck-monitor:"))
        self.assertEqual(m.on_poll(ok(), 41 * 60), [])

    def test_no_fault_before_30_minutes(self):
        m = monitor()
        sent = []
        for t in range(0, 29 * 60, 60):
            sent += m.on_poll(failed(), t)
        self.assertEqual(sent, [])

    def test_success_resets_fault_clock(self):
        m = monitor()
        sent = []
        for t in range(0, 25 * 60, 60):
            sent += m.on_poll(failed(), t)
        sent += m.on_poll(ok(), 25 * 60)
        for t in range(26 * 60, 50 * 60, 60):
            sent += m.on_poll(failed(), t)
        self.assertEqual(sent, [])

    def test_fault_label_rate_limited(self):
        m = monitor()
        sent = []
        for t in range(0, 31 * 60, 60):
            sent += m.on_poll(failed("rate_limited"), t)
        self.assertEqual(len(sent), 1)
        self.assertIn("rate limited", sent[0])


class BackoffTest(unittest.TestCase):
    def test_backoff_doubles_and_caps(self):
        m = monitor()
        delays = []
        for n in range(1, 11):
            m.on_poll(failed("rate_limited"), n)
            delays.append(m.next_delay())
        self.assertEqual([delays[0], delays[1], delays[2], delays[9]],
                         [120, 240, 480, 1800])

    def test_other_failure_resets_to_normal(self):
        m = monitor()
        m.on_poll(failed("rate_limited"), 0)
        m.on_poll(failed(), 1)
        self.assertEqual(m.next_delay(), 60)

    def test_normal_delay_is_check_interval(self):
        self.assertEqual(monitor().next_delay(), 60)

    def test_long_rate_limit_streak_does_not_overflow(self):
        m = Monitor(WATCH, 60.0, start=0)  # config yields floats
        for n in range(2000):
            m.on_poll(failed("rate_limited"), n)
        self.assertEqual(m.next_delay(), 1800)
