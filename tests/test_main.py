import contextlib
import io
import unittest
from unittest import mock

from fakes import FakeHttp, Router, detail, steam_response
from steamdeck_monitor.__main__ import main, run
from steamdeck_monitor.config import load_config
from steamdeck_monitor.http import HttpError, Response
from steamdeck_monitor.telegram import Telegram

OLED, TB = 1202542, 1202547
STEAM = "https://api.steampowered.com/"
TELEGRAM = "https://api.telegram.org/"
HC = "https://hc.example.test/ping/"
SHS = "https://steamhardwarestock.com/"
TG_OK = Response(200, {}, b'{"ok": true}')
ENV = {"TELEGRAM_BOT_TOKEN": "1:T", "TELEGRAM_CHAT_ID": "42"}


def stock(oled=False, tb=False):
    return steam_response([detail(OLED, inventory=oled), detail(TB, inventory=tb)])


def run_iterations(http, n, **env):
    cfg = load_config({**ENV, "HEALTHCHECKS_PING_URL": HC + "abc",
                       "CROSSCHECK_INTERVAL": "0", **env})
    run(cfg, http, Telegram(http, "1:T", "42", sleep=lambda s: None),
        sleep=lambda s: None, clock=iter(range(0, 10_000, 60)).__next__,
        max_iterations=n)


class MainTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("logging.basicConfig")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, argv, env, http):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(argv, env=env, http=http)
        return code, out.getvalue()

    def test_once_output_and_exit(self):
        code, out = self.run_main(["--once"], {}, FakeHttp([stock(oled=True)]))
        self.assertEqual(code, 0)
        self.assertIn("512 GB OLED", out)
        self.assertIn("in stock", out)
        self.assertIn("out of stock", out)

    def test_once_unknown_exits_2(self):
        code, out = self.run_main(["--once"], {}, FakeHttp([Response(500, {}, b"")]))
        self.assertEqual(code, 2)
        self.assertIn("unknown", out)

    def test_missing_token_exits_78(self):
        http = FakeHttp([])
        code, _ = self.run_main([], {}, http)
        self.assertEqual(code, 78)
        self.assertEqual(http.calls, [])

    def test_bad_watch_exits_78_in_every_mode(self):
        for argv in ([], ["--once"], ["--test-telegram"]):
            code, _ = self.run_main(argv, {**ENV, "WATCH": "bogus"}, FakeHttp([]))
            self.assertEqual(code, 78, argv)

    def test_failed_get_me_exits_78(self):
        http = FakeHttp([Response(401, {}, b"")])
        code, _ = self.run_main([], ENV, http)
        self.assertEqual(code, 78)

    def test_test_telegram_sends_one_message(self):
        http = FakeHttp([TG_OK])
        code, _ = self.run_main(["--test-telegram"], ENV, http)
        self.assertEqual(code, 0)
        self.assertEqual(len(http.calls), 1)

    def test_test_telegram_failure_exits_1(self):
        code, _ = self.run_main(["--test-telegram"], ENV,
                                FakeHttp([Response(401, {}, b"")]))
        self.assertEqual(code, 1)


class LoopTest(unittest.TestCase):
    def test_loop_alerts_and_pings(self):
        http = Router({STEAM: [stock(), stock(oled=True)],
                       TELEGRAM: [TG_OK], HC: [TG_OK, TG_OK]})
        run_iterations(http, 2)
        self.assertEqual(http.count(TELEGRAM), 1)
        self.assertEqual(http.count(HC), 2)

    def test_ping_even_when_steam_fails(self):
        http = Router({STEAM: [Response(500, {}, b"")], HC: [TG_OK]})
        run_iterations(http, 1)
        self.assertEqual(http.count(HC), 1)

    def test_failed_ping_does_not_stop_loop(self):
        http = Router({STEAM: [stock(), stock()],
                       HC: [HttpError("URLError"), TG_OK]})
        run_iterations(http, 2)
        self.assertEqual(http.count(STEAM), 2)

    def test_crosscheck_disabled_makes_no_request(self):
        http = Router({STEAM: [stock()], HC: [TG_OK]})
        run_iterations(http, 1)
        self.assertEqual(http.count(SHS), 0)

    def test_crosscheck_runs_once_when_due(self):
        http = Router({STEAM: [stock(), stock()], HC: [TG_OK, TG_OK],
                       SHS: [Response(503, {}, b"")]})
        run_iterations(http, 2, CROSSCHECK_INTERVAL="900")
        self.assertEqual(http.count(SHS), 1)

    def test_telegram_down_keeps_message_for_next_iteration(self):
        http = Router({STEAM: [stock(oled=True), stock(oled=True)],
                       TELEGRAM: [Response(500, {}, b"")] * 3 + [TG_OK],
                       HC: [TG_OK, TG_OK]})
        run_iterations(http, 2)
        self.assertEqual(http.count(TELEGRAM), 4)
