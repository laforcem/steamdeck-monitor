import io
import unittest
import urllib.error
from unittest import mock

from steamdeck_monitor.http import Http, HttpError


class HttpTest(unittest.TestCase):
    def test_http_error_text_has_no_url(self):
        leaky = urllib.error.URLError(
            "failed to reach https://api.telegram.org/botSECRET/x")
        with mock.patch("urllib.request.urlopen", side_effect=leaky):
            with self.assertRaises(HttpError) as cm:
                Http().request("GET", "https://api.telegram.org/botSECRET/x")
        self.assertNotIn("SECRET", str(cm.exception))

    def test_4xx_is_a_response_not_an_exception(self):
        err = urllib.error.HTTPError("u", 404, "nf", {"X-Eresult": "9"},
                                     io.BytesIO(b"nope"))
        self.addCleanup(err.close)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            resp = Http().request("GET", "https://example.test/")
        self.assertEqual(resp.status, 404)
        self.assertEqual(resp.body, b"nope")
        self.assertEqual(resp.headers["x-eresult"], "9")

    def test_unreadable_error_body_is_still_a_response(self):
        class BadFp:
            def read(self, *a):
                raise OSError("timed out")

            def close(self):
                pass

        err = urllib.error.HTTPError("u", 500, "boom", {}, BadFp())
        with mock.patch("urllib.request.urlopen", side_effect=err):
            resp = Http().request("GET", "https://example.test/")
        self.assertEqual(resp.status, 500)
        self.assertEqual(resp.body, b"")
