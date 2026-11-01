import json
import unittest
import urllib.parse

from fakes import FakeHttp
from steamdeck_monitor.http import HttpError, Response
from steamdeck_monitor.telegram import Outbox, Telegram

TOKEN = "123:SECRET"


def ok_response():
    return Response(200, {}, b'{"ok": true}')


def tg(responses):
    http = FakeHttp(responses)
    slept = []
    return Telegram(http, TOKEN, "42", sleep=slept.append), http, slept


class TelegramTest(unittest.TestCase):
    def test_send_posts_expected_form(self):
        t, http, _ = tg([ok_response()])
        self.assertTrue(t.send("hello <b>x</b>"))
        method, url, data = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/sendMessage"))
        form = urllib.parse.parse_qs(data.decode())
        self.assertEqual(form["parse_mode"], ["HTML"])
        self.assertEqual(form["disable_web_page_preview"], ["true"])
        self.assertEqual(form["chat_id"], ["42"])
        self.assertEqual(form["text"], ["hello <b>x</b>"])
        self.assertNotIn("disable_notification", form)

    def test_no_retry_on_401(self):
        t, http, _ = tg([Response(401, {}, b'{"ok": false}')])
        self.assertFalse(t.send("x"))
        self.assertEqual(len(http.calls), 1)

    def test_retry_on_500_then_ok(self):
        t, http, _ = tg([Response(500, {}, b""), ok_response()])
        self.assertTrue(t.send("x"))
        self.assertEqual(len(http.calls), 2)

    def test_retry_on_transport_error_then_ok(self):
        t, http, _ = tg([HttpError("URLError"), ok_response()])
        self.assertTrue(t.send("x"))

    def test_gives_up_after_three_attempts(self):
        t, http, _ = tg([Response(500, {}, b"")] * 3)
        self.assertFalse(t.send("x"))
        self.assertEqual(len(http.calls), 3)

    def test_429_honours_retry_after(self):
        body = json.dumps({"ok": False, "parameters": {"retry_after": 7}}).encode()
        t, http, slept = tg([Response(429, {}, body), ok_response()])
        self.assertTrue(t.send("x"))
        self.assertEqual(slept, [7])

    def test_429_retry_after_is_capped(self):
        body = json.dumps({"parameters": {"retry_after": 9999}}).encode()
        t, _, slept = tg([Response(429, {}, body), ok_response()])
        t.send("x")
        self.assertEqual(slept, [60])

    def test_logs_never_contain_token(self):
        leaky = HttpError(f"boom at https://api.telegram.org/bot{TOKEN}/sendMessage")
        t, _, _ = tg([leaky, Response(500, {}, TOKEN.encode()),
                      Response(401, {}, TOKEN.encode())])
        with self.assertLogs("steamdeck-monitor", level="DEBUG") as logs:
            t.send("x")
        self.assertTrue(logs.records)
        self.assertNotIn("SECRET", "\n".join(r.getMessage() for r in logs.records))

    def test_get_me(self):
        t, http, _ = tg([ok_response()])
        self.assertTrue(t.get_me())
        self.assertTrue(http.calls[0][1].endswith("/getMe"))
        t, _, _ = tg([Response(401, {}, b"")])
        self.assertFalse(t.get_me())


class OutboxTest(unittest.TestCase):
    def test_outbox_preserves_order_across_failures(self):
        box = Outbox()
        box.add("A")
        box.add("B")
        self.assertEqual(box.flush(lambda text: False), 0)
        self.assertEqual(len(box), 2)
        sent = []
        self.assertEqual(box.flush(lambda text: sent.append(text) or True), 2)
        self.assertEqual(sent, ["A", "B"])
        self.assertEqual(len(box), 0)

    def test_flush_stops_at_first_failure(self):
        box = Outbox()
        for text in "ABC":
            box.add(text)
        sent = []

        def send(text):
            sent.append(text)
            return text != "B"

        self.assertEqual(box.flush(send), 1)
        self.assertEqual(sent, ["A", "B"])
        self.assertEqual(len(box), 2)

    def test_outbox_caps_at_maxlen(self):
        box = Outbox(maxlen=2)
        for text in "ABC":
            box.add(text)
        sent = []
        box.flush(lambda text: sent.append(text) or True)
        self.assertEqual(sent, ["B", "C"])
