import os
import tempfile
import unittest

from steamdeck_monitor.config import load_config


class ConfigTest(unittest.TestCase):
    def test_default_watch(self):
        self.assertEqual([m.key for m in load_config({}).watch],
                         ["512oled", "1tboled"])

    def test_file_var_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "tok")
            with open(p, "w") as f:
                f.write("abc\n")
            cfg = load_config({"TELEGRAM_BOT_TOKEN_FILE": p,
                               "TELEGRAM_BOT_TOKEN": "zzz"})
        self.assertEqual(cfg.token, "abc")

    def test_plain_var_used_without_file(self):
        self.assertEqual(load_config({"TELEGRAM_CHAT_ID": "42"}).chat_id, "42")

    def test_missing_secrets_are_none(self):
        cfg = load_config({})
        self.assertIsNone(cfg.token)
        self.assertIsNone(cfg.chat_id)
        self.assertIsNone(cfg.hc_url)

    def test_interval_floor(self):
        self.assertEqual(load_config({"CHECK_INTERVAL": "5"}).check_interval, 30)

    def test_defaults(self):
        cfg = load_config({})
        self.assertEqual(cfg.country, "US")
        self.assertEqual(cfg.check_interval, 60)
        self.assertEqual(cfg.crosscheck_interval, 900)
        self.assertEqual(cfg.log_level, "INFO")

    def test_crosscheck_zero_disables(self):
        self.assertEqual(
            load_config({"CROSSCHECK_INTERVAL": "0"}).crosscheck_interval, 0)

    def test_country_uppercased(self):
        self.assertEqual(load_config({"COUNTRY_CODE": "us"}).country, "US")

    def test_invalid_log_level_raises(self):
        with self.assertRaises(ValueError):
            load_config({"LOG_LEVEL": "loud"})
