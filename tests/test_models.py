import unittest

from steamdeck_monitor.models import ALL_PACKAGE_IDS, MODELS, parse_watch


class ModelsTest(unittest.TestCase):
    def test_model_table(self):
        self.assertEqual(
            {k: m.package_id for k, m in MODELS.items()},
            {"512oled": 1202542, "1tboled": 1202547, "dock": 761892,
             "64lcd": 903905, "256lcd": 903906, "512lcd": 903907},
        )
        self.assertEqual(ALL_PACKAGE_IDS,
                         [1202542, 1202547, 761892, 903905, 903906, 903907])

    def test_unknown_watch_key_raises(self):
        with self.assertRaises(ValueError):
            parse_watch("512oled,bogus")

    def test_empty_watch_raises(self):
        with self.assertRaises(ValueError):
            parse_watch(" , ")

    def test_parse_watch_trims_and_orders(self):
        self.assertEqual([m.key for m in parse_watch("1tboled, dock")],
                         ["1tboled", "dock"])
