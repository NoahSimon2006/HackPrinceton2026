"""Verify tile credentials, validation, caching, and upstream failures offline."""
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import server


class VexcelTilesTest(unittest.TestCase):
    def setUp(self):
        server.aerial_tile.cache_clear()
        self.addCleanup(server.aerial_tile.cache_clear)
        self.key = patch.dict(server.os.environ, {"VEXCEL_API_KEY": "test-only-key"})
        self.key.start()
        self.addCleanup(self.key.stop)

    @patch("server.vexcel_image", return_value=b"\xff\xd8\xfftile")
    def test_fixed_endpoint_header_auth_and_cache(self, fetch):
        first = server.aerial_tile(16, 11239, 26168)
        self.assertEqual(first, server.aerial_tile(16, 11239, 26168))
        fetch.assert_called_once()
        request, limit = fetch.call_args.args
        parts = urlsplit(request.full_url)
        self.assertEqual(parts.scheme, "https")
        self.assertEqual(parts.netloc, "api.vexcelgroup.com")
        self.assertEqual(parts.path, "/v2/ortho/tile")
        self.assertEqual(parse_qs(parts.query)["tile-x"], ["11239"])
        self.assertEqual(parse_qs(parts.query)["tile-y"], ["26168"])
        self.assertEqual(request.get_header("X-api-key"), "test-only-key")
        self.assertNotIn("test-only-key", request.full_url)
        self.assertEqual(limit, server.MAX_TILE)

    @patch("server.vexcel_image")
    def test_invalid_coordinates_never_reach_provider(self, fetch):
        for coords in [(9, 0, 0), (21, 0, 0), (16, -1, 1), (16, 1, 65536)]:
            with self.subTest(coords=coords), self.assertRaises(server.RequestError):
                server.aerial_tile(*coords)
        fetch.assert_not_called()

    @patch("server.vexcel_image")
    def test_missing_key_does_not_make_request(self, fetch):
        with patch.dict(server.os.environ, {"VEXCEL_API_KEY": ""}):
            with self.assertRaises(server.RequestError) as error:
                server.aerial_tile(16, 11239, 26168)
        self.assertEqual(error.exception.status, 503)
        fetch.assert_not_called()

    @patch("server.build_opener")
    def test_provider_error_details_are_not_returned(self, opener):
        opener.return_value.open.side_effect = HTTPError(
            "https://api.vexcelgroup.com/", 403, "sensitive-provider-detail", {}, None)
        with self.assertRaises(server.RequestError) as error:
            server.aerial_tile(16, 11239, 26168)
        self.assertNotIn("sensitive-provider-detail", str(error.exception))
        self.assertNotIn("test-only-key", str(error.exception))
        self.assertEqual(server.aerial_tile.cache_info().currsize, 0)

    @patch("server.build_opener")
    def test_non_images_and_oversized_images_are_rejected(self, opener):
        response = MagicMock()
        opener.return_value.open.return_value.__enter__.return_value = response
        response.status = 200
        for kind, data in [("text/html", b"error"), ("image/jpeg", b"not a jpeg"),
                           ("image/jpeg", b"\xff\xd8\xff" + b"x" * server.MAX_TILE)]:
            response.headers.get_content_type.return_value = kind
            response.read.return_value = data
            with self.subTest(kind=kind, size=len(data)), self.assertRaises(server.RequestError):
                server.aerial_tile(16, 11239, 26168)
        self.assertEqual(server.aerial_tile.cache_info().currsize, 0)

    @patch("server.vexcel_image", return_value=b"\xff\xd8\xfftile")
    def test_memory_cache_is_bounded(self, fetch):
        for x in range(129):
            server.aerial_tile(16, x, 100)
        self.assertEqual(server.aerial_tile.cache_info().currsize, 128)


if __name__ == "__main__":
    unittest.main()
