import calendar
import json
import os
import time
import unittest

from fakes import FakeHttp
from steamdeck_monitor.crosscheck import CrossChecker, fetch_status, parse_status
from steamdeck_monitor.http import HttpError, Response
from steamdeck_monitor.models import ALL_PACKAGE_IDS

OLED = 1202542
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "status.json")
GENERATED = calendar.timegm(time.strptime("2026-10-31T23:30:39", "%Y-%m-%dT%H:%M:%S"))


def fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def body(**changes):
    d = fixture()
    d.update(changes)
    return json.dumps(d).encode()


def agree(**flips):
    states = {pid: False for pid in ALL_PACKAGE_IDS}
    states.update({int(k.lstrip("p")): v for k, v in flips.items()})
    return states


class ParseStatusTest(unittest.TestCase):
    def test_parse_fixture(self):
        got = parse_status(body(), "US", GENERATED + 60)
        self.assertEqual(got, {pid: False for pid in ALL_PACKAGE_IDS})

    def test_in_stock_status_maps_to_true(self):
        d = fixture()
        d["products"]["steam-deck-refurbished"]["US"]["packages"][0]["status"] = "in_stock"
        first = d["products"]["steam-deck-refurbished"]["US"]["packages"][0]["id"]
        got = parse_status(json.dumps(d).encode(), "US", GENERATED + 60)
        self.assertIs(got[first], True)

    def test_stale_is_none(self):
        self.assertIsNone(parse_status(body(), "US", GENERATED + 31 * 60))

    def test_bad_json_is_none(self):
        self.assertIsNone(parse_status(b"<html>", "US", GENERATED))

    def test_missing_country_is_none(self):
        self.assertIsNone(parse_status(body(), "DE", GENERATED + 60))

    def test_fetch_status_none_on_http_failure(self):
        self.assertIsNone(fetch_status(FakeHttp([HttpError("x")]), "US", GENERATED))
        self.assertIsNone(fetch_status(FakeHttp([Response(503, {}, b"")]), "US", GENERATED))

    def test_fetch_status_parses(self):
        http = FakeHttp([Response(200, {}, body())])
        self.assertEqual(len(fetch_status(http, "US", GENERATED + 60)), 6)
        self.assertEqual(http.calls[0][1], "https://steamhardwarestock.com/status.json")


class CrossCheckerTest(unittest.TestCase):
    def test_agreement_is_silent(self):
        c = CrossChecker(0)
        self.assertEqual(c.compare(agree(), agree(), 0), [])

    def test_single_mismatch_silent(self):
        c = CrossChecker(0)
        self.assertEqual(c.compare(agree(**{f"p{OLED}": True}), agree(), 0), [])

    def test_two_consecutive_mismatches_alert_once(self):
        c = CrossChecker(0)
        ours = agree(**{f"p{OLED}": True})
        c.compare(ours, agree(), 0)
        second = c.compare(ours, agree(), 900)
        self.assertEqual(len(second), 1)
        self.assertIn("steamhardwarestock", second[0])
        self.assertIn("512 GB OLED", second[0])
        self.assertEqual(c.compare(ours, agree(), 1800), [])

    def test_mismatch_streak_resets_on_agreement(self):
        c = CrossChecker(0)
        ours = agree(**{f"p{OLED}": True})
        c.compare(ours, agree(), 0)
        c.compare(agree(), agree(), 900)
        self.assertEqual(c.compare(ours, agree(), 1800), [])

    def test_recovery_after_mismatch(self):
        c = CrossChecker(0)
        ours = agree(**{f"p{OLED}": True})
        c.compare(ours, agree(), 0)
        c.compare(ours, agree(), 900)
        back = c.compare(agree(), agree(), 1800)
        self.assertEqual(len(back), 1)
        self.assertIn("agree again", back[0])
        self.assertEqual(c.compare(agree(), agree(), 2700), [])

    def test_unknown_ours_not_a_mismatch(self):
        c = CrossChecker(0)
        ours = agree(**{f"p{OLED}": None})
        c.compare(ours, agree(**{f"p{OLED}": True}), 0)
        self.assertEqual(c.compare(ours, agree(**{f"p{OLED}": True}), 900), [])

    def test_unavailable_24h_alerts_once_then_recovers(self):
        c = CrossChecker(0)
        sent = []
        for t in range(0, 25 * 3600, 900):
            sent += c.compare(agree(), None, t)
        self.assertEqual(len(sent), 1)
        self.assertIn("unavailable", sent[0])
        back = c.compare(agree(), agree(), 25 * 3600)
        self.assertEqual(len(back), 1)
        self.assertIn("available again", back[0])

    def test_short_outage_is_silent(self):
        c = CrossChecker(0)
        sent = []
        for t in range(0, 2 * 3600, 900):
            sent += c.compare(agree(), None, t)
        sent += c.compare(agree(), agree(), 2 * 3600)
        self.assertEqual(sent, [])
