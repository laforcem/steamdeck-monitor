import json
import unittest
import urllib.parse

from steamdeck_monitor.http import HttpError, Response
from steamdeck_monitor.models import ALL_PACKAGE_IDS
from steamdeck_monitor.steam import classify, poll, steam_url

from fakes import FakeHttp, detail, steam_response

OLED = 1202542


class SteamTest(unittest.TestCase):
    def test_url_has_all_ids_one_request(self):
        q = urllib.parse.urlparse(steam_url(ALL_PACKAGE_IDS, "US")).query
        payload = json.loads(urllib.parse.parse_qs(q)["input_json"][0])
        self.assertEqual(payload, {
            "packageid": [1202542, 1202547, 761892, 903905, 903906, 903907],
            "context": {"country_code": "US", "language": "english"},
        })

    def test_poll_makes_one_request(self):
        http = FakeHttp([steam_response([detail(OLED)])])
        poll(http, "US")
        self.assertEqual(len(http.calls), 1)

    def test_in_stock(self):
        r = poll(FakeHttp([steam_response([detail(OLED)])]), "US")
        self.assertEqual(r.kind, "ok")
        self.assertIs(r.states[OLED], True)

    def test_out_of_stock(self):
        r = poll(FakeHttp([steam_response([detail(OLED, inventory=False)])]), "US")
        self.assertIs(r.states[OLED], False)

    def test_reservation_is_not_in_stock(self):
        self.assertIs(classify(detail(OLED, reservation=True)), False)

    def test_restricted_is_not_in_stock(self):
        self.assertIs(classify(detail(OLED, restricted=True)), False)

    def test_not_sold_in_country(self):
        self.assertIs(classify(detail(OLED, allowed=False)), False)

    def test_high_pending_orders_ignored(self):
        self.assertIs(classify(detail(OLED, high_pending=True)), True)

    def test_non_bool_inventory_is_none(self):
        self.assertIsNone(classify({"packageid": OLED, "inventory_available": "yes"}))

    def test_missing_package_is_none(self):
        r = poll(FakeHttp([steam_response([detail(OLED)])]), "US")
        self.assertIsNone(r.states[1202547])
        self.assertEqual(set(r.states), set(ALL_PACKAGE_IDS))

    def test_429_is_rate_limited(self):
        r = poll(FakeHttp([Response(429, {}, b"")]), "US")
        self.assertEqual(r.kind, "rate_limited")

    def test_eresult_25_is_rate_limited(self):
        r = poll(FakeHttp([steam_response([], headers={"x-eresult": "25"})]), "US")
        self.assertEqual(r.kind, "rate_limited")

    def test_eresult_84_is_rate_limited(self):
        r = poll(FakeHttp([steam_response([], headers={"x-eresult": "84"})]), "US")
        self.assertEqual(r.kind, "rate_limited")

    def test_404_is_failed(self):
        r = poll(FakeHttp([Response(404, {}, b"<html>Not Found</html>")]), "US")
        self.assertEqual(r.kind, "failed")
        self.assertIn("404", r.error)

    def test_html_body_is_failure(self):
        r = poll(FakeHttp([Response(200, {}, b"<html>maintenance</html>")]), "US")
        self.assertEqual(r.kind, "failed")

    def test_unexpected_shape_is_failure(self):
        r = poll(FakeHttp([Response(200, {}, b'{"response": {}}')]), "US")
        self.assertEqual(r.kind, "failed")

    def test_transport_error_is_failed(self):
        r = poll(FakeHttp([HttpError("URLError")]), "US")
        self.assertEqual(r.kind, "failed")

    def test_unhashable_packageid_is_failure(self):
        r = poll(FakeHttp([steam_response([{"packageid": [1]}])]), "US")
        self.assertEqual(r.kind, "failed")
