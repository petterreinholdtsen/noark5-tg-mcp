# -*- coding: utf-8 -*-
# Copyright 2026 Petter Reinholdtsen <pere@hungry.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Low-level HTTP tests for Noark5Client.

These tests mock urllib.request.urlopen directly instead of higher-level methods,
to exercise actual request/response handling code paths including error branches.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import urllib.error as urr

from noark5_tg_mcp.client import (
    NIKITA_RELBASE,
    Noark5Client,
    Noark5Error,
    RELBASE,
)


class MockResponse:
    """Helper to create mock HTTP responses."""

    def __init__(self, body: dict | list | bytes, status=200, headers=None):
        if isinstance(body, (dict, list)):
            self._body = json.dumps(body).encode("utf-8")
        else:
            self._body = body
        self.status = status
        self.headers = headers or {}

    def read(self):
        return self._body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


class TestRequestLowLevel(unittest.TestCase):
    """Test _request method via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_request_get_success(self, mock_urlopen):
        """_request builds correct URL and headers for GET."""
        mock_urlopen.return_value = MockResponse({"key": "value"})

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        content, res = client._request("GET", "/test/path")
        self.assertEqual(json.loads(content), {"key": "value"})

        # Verify request was built correctly.
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertEqual(req.full_url, "https://example.com/test/path")
        self.assertIn("Authorization", req.headers)
        self.assertEqual(req.headers["Accept"], "application/vnd.noark5+json, application/json")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_request_post_with_data(self, mock_urlopen):
        """_request sends POST data with correct content-type."""
        captured_req = {}

        def fake_urlopen(req):
            captured_req["req"] = req
            return MockResponse({"created": True})

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        body = json.dumps({"tittel": "Test"}).encode()
        content, _ = client._request(
            "POST", "/entities", data=body, content_type="application/json"
        )
        self.assertEqual(json.loads(content), {"created": True})

        req = captured_req["req"]
        self.assertIn("Content-type", req.headers)
        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertIn("Content-length", req.headers)

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_request_http_error_json(self, mock_urlopen):
        """_request parses JSON error response."""
        err_resp = MagicMock()
        err_resp.read.return_value = json.dumps({"feil": {"beskrivelse": "Not found"}}).encode()
        err_resp.code = 404
        mock_urlopen.side_effect = urr.HTTPError(
            "https://example.com/test", 404, "Not Found", {}, err_resp
        )

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        with self.assertRaises(Noark5Error) as ctx:
            client._request("GET", "/test")
        self.assertEqual(ctx.exception.code, 404)
        self.assertIn("Not found", str(ctx.exception))

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_request_http_error_plain(self, mock_urlopen):
        """_request handles non-JSON error response."""
        err_resp = MagicMock()
        err_resp.read.return_value = b"Internal Server Error"
        err_resp.code = 500
        mock_urlopen.side_effect = urr.HTTPError(
            "https://example.com/test", 500, "Server Error", {}, err_resp
        )

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        with self.assertRaises(Noark5Error) as ctx:
            client._request("GET", "/test")
        self.assertEqual(ctx.exception.code, 500)


class TestGetJsonLowLevel(unittest.TestCase):
    """Test _get_json via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_get_json_success(self, mock_urlopen):
        """_get_json parses JSON response correctly."""
        mock_urlopen.return_value = MockResponse({"systemID": "abc123", "tittel": "Test"})

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client._get_json("/entity/123")
        self.assertEqual(result["systemID"], "abc123")
        self.assertEqual(result["tittel"], "Test")


class TestPostJsonLowLevel(unittest.TestCase):
    """Test _post_json via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_post_json_success(self, mock_urlopen):
        """_post_json sends data and parses response."""
        mock_urlopen.return_value = MockResponse({"systemID": "new-123", "tittel": "Created"})

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client._post_json("/ny-entity", {"tittel": "New Entity"})
        self.assertEqual(result["systemID"], "new-123")

        # Verify request body.
        req = mock_urlopen.call_args[0][0]
        sent_data = json.loads(req.data.decode())
        self.assertEqual(sent_data, {"tittel": "New Entity"})


class TestDeleteEntityLowLevel(unittest.TestCase):
    """Test delete_entity via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_delete_success(self, mock_urlopen):
        """delete_entity sends DELETE request."""
        mock_urlopen.return_value = MockResponse(b"{}")

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.delete_entity("/entity/123")
        self.assertEqual(result, "{}")

        req = mock_urlopen.call_args[0][0]
        # Verify it's a DELETE request (method is set via get_method lambda).
        self.assertEqual(req.get_method(), "DELETE")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_delete_http_error(self, mock_urlopen):
        """delete_entity raises Noark5Error on HTTP error."""
        err_resp = MagicMock()
        err_resp.read.return_value = b"Conflict"
        err_resp.code = 409
        mock_urlopen.side_effect = urr.HTTPError(
            "https://example.com/entity/123", 409, "Conflict", {}, err_resp
        )

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        with self.assertRaises(Noark5Error) as ctx:
            client.delete_entity("/entity/123")
        self.assertEqual(ctx.exception.code, 409)


class TestPatchJsonLowLevel(unittest.TestCase):
    """Test _patch_json_with_etag via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_patch_success(self, mock_urlopen):
        """_patch_json_with_etag sends correct headers and body."""
        captured_req = {}

        def fake_urlopen(req):
            captured_req["req"] = req
            return MockResponse({"tittel": "Updated"})

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client._patch_json_with_etag("/entity/123", {"tittel": "Updated"}, '"abc123"')
        self.assertEqual(result["tittel"], "Updated")

        req = captured_req["req"]
        self.assertIn("content-type", [k.lower() for k in req.headers.keys()])
        self.assertEqual(req.headers.get("Content-type"), "application/merge-patch+json")
        self.assertEqual(req.headers.get("If-match"), '"abc123"')
        sent_data = json.loads(req.data.decode())
        self.assertEqual(sent_data, {"tittel": "Updated"})

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_patch_no_etag_uses_star(self, mock_urlopen):
        """When etag is None, If-Match defaults to *."""
        captured_req = {}

        def fake_urlopen(req):
            captured_req["req"] = req
            return MockResponse({})

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        client._patch_json_with_etag("/entity/123", {"tittel": "Test"}, None)

        req = captured_req["req"]
        self.assertEqual(req.headers.get("If-match"), "*")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_patch_http_error(self, mock_urlopen):
        """_patch_json_with_etag raises Noark5Error on conflict."""
        err_resp = MagicMock()
        err_resp.read.return_value = b"Precondition Failed"
        err_resp.code = 412
        mock_urlopen.side_effect = urr.HTTPError(
            "https://example.com/entity/123", 412, "Conflict", {}, err_resp
        )

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        with self.assertRaises(Noark5Error) as ctx:
            client._patch_json_with_etag("/entity/123", {"tittel": "Test"}, '"old-etag"')
        self.assertEqual(ctx.exception.code, 412)


class TestGetWithEtagLowLevel(unittest.TestCase):
    """Test _get_with_etag via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_get_with_etag_success(self, mock_urlopen):
        """_get_with_etag returns data and ETag header."""
        resp = MockResponse(
            {"systemID": "abc", "tittel": "Test"},
            headers={"ETag": '"v1-etag"'}
        )
        mock_urlopen.return_value = resp

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        data, etag = client._get_with_etag("/entity/abc")
        self.assertEqual(data["systemID"], "abc")
        self.assertEqual(etag, "v1-etag")  # Quotes stripped.

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_get_with_etag_no_header(self, mock_urlopen):
        """_get_with_etag handles missing ETag header."""
        resp = MockResponse({"systemID": "abc"}, headers={})
        mock_urlopen.return_value = resp

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        data, etag = client._get_with_etag("/entity/abc")
        self.assertEqual(data["systemID"], "abc")
        self.assertEqual(etag, "")


class TestUpdateEntityLowLevel(unittest.TestCase):
    """Test update_entity end-to-end via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_update_entity_full_flow(self, mock_urlopen):
        """update_entity does GET for etag then PATCH with changes."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if req.get_method() == "GET":
                return MockResponse(
                    {"tittel": "Old", "beskrivelse": "Existing"},
                    headers={"ETag": '"old-etag"'}
                )
            else:
                return MockResponse({"tittel": "New", "beskrivelse": "Existing"})

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.update_entity("/entity/123", {"tittel": "New"})
        self.assertEqual(result["tittel"], "New")
        self.assertGreaterEqual(call_count[0], 2)

        # Verify PATCH request used correct ETag (quotes stripped by _get_with_etag).
        patch_reqs = [c[0][0] for c in mock_urlopen.call_args_list if c[0][0].get_method() == "PATCH"]
        self.assertEqual(patch_reqs[0].headers.get("If-match"), 'old-etag')


class TestListOperationsLowLevel(unittest.TestCase):
    """Test list operations via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_list_arkiv_full_flow(self, mock_urlopen):
        """list_arkiv walks links then fetches collection."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if "archives" in req.full_url:
                return MockResponse({"results": [{"systemID": "a1", "tittel": "Archive 1"}]})
            else:
                return MockResponse({
                    "systemID": "root",
                    "_links": {
                        RELBASE + "arkivstruktur/arkiv/": {"href": "https://example.com/archives"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.list_arkiv()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tittel"], "Archive 1")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_list_mapper_full_flow(self, mock_urlopen):
        """list_mapper fetches parent entity then mapper collection."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if "mapper" in req.full_url:
                return MockResponse({"results": [{"systemID": "m1", "tittel": "File 1"}]})
            else:
                return MockResponse({
                    "_links": {
                        RELBASE + "arkivstruktur/mappe/": {"href": "https://example.com/mapper"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.list_mapper("http://parent/123")
        self.assertEqual(len(result), 1)

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_list_mapper_no_relation(self, mock_urlopen):
        """list_mapper returns empty when parent has no mappe relation."""
        parent = {"_links": {}}
        mock_urlopen.return_value = MockResponse(parent)

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.list_mapper("http://parent/123")
        self.assertEqual(result, [])


class TestCreateEntityLowLevel(unittest.TestCase):
    """Test create operations via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_create_entity_full_flow(self, mock_urlopen):
        """_create_entity fetches parent, template defaults, then POSTs."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if req.get_method() == "POST":
                return MockResponse({"systemID": "new-123", "tittel": "New File"})
            elif "ny-mappe" in req.full_url:
                return MockResponse({"dokumentmedium": {"kode": "E"}})
            else:
                return MockResponse({
                    "_links": {
                        RELBASE + "arkivstruktur/ny-mappe/": {"href": "https://example.com/ny-mappe"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.create_mappe("http://parent/123", "New File")
        self.assertEqual(result["systemID"], "new-123")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_create_entity_template_unavailable(self, mock_urlopen):
        """_create_entity handles template GET failure gracefully."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if req.get_method() == "POST":
                return MockResponse({"systemID": "new-123", "tittel": "New File"})
            elif "ny-mappe" in req.full_url:
                err_resp = MagicMock()
                err_resp.read.return_value = b"Not Found"
                err_resp.code = 404
                raise urr.HTTPError("https://example.com/", 404, "Not Found", {}, err_resp)
            else:
                return MockResponse({
                    "_links": {
                        RELBASE + "arkivstruktur/ny-mappe/": {"href": "https://example.com/ny-mappe"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.create_mappe("http://parent/123", "New File")
        self.assertEqual(result["systemID"], "new-123")


class TestCreateAtRootLowLevel(unittest.TestCase):
    """Test root-level create operations via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_create_arkiv_full_flow(self, mock_urlopen):
        """create_arkiv finds relation at root, then POSTs."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if req.get_method() == "POST":
                return MockResponse({"systemID": "new-archive", "tittel": "My Archive"})
            elif "ny-arkiv" in req.full_url:
                return MockResponse({})
            else:
                return MockResponse({
                    "_links": {
                        RELBASE + "arkivstruktur/ny-arkiv/": {"href": "https://example.com/ny-arkiv"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        result = client.create_arkiv("My Archive")
        self.assertEqual(result["systemID"], "new-archive")


class TestSearchLowLevel(unittest.TestCase):
    """Test search operations via urlopen mock."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_search_handles_collection_error(self, mock_urlopen):
        """search_entities continues when a collection query fails."""
        call_count = [0]

        def fake_urlopen(req):
            call_count[0] += 1
            if "$search=" in req.full_url:
                if "archives" in req.full_url:
                    return MockResponse({
                        "results": [
                            {"tittel": "Found Archive", "_links": {"self": {"href": "http://a1"}}}
                        ]
                    })
                elif "mapper" in req.full_url:
                    err_resp = MagicMock()
                    err_resp.read.return_value = b"Forbidden"
                    err_resp.code = 403
                    raise urr.HTTPError("https://example.com/", 403, "Forbidden", {}, err_resp)
                else:
                    return MockResponse({"results": []})
            else:
                return MockResponse({
                    "systemID": "root",
                    "_links": {
                        RELBASE + "arkivstruktur/arkiv/": {"href": "https://example.com/archives"},
                        RELBASE + "arkivstruktur/mappe/": {"href": "https://example.com/mapper"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        results = client.search_entities("test query")
        # Should have results from the successful collection, despite the error.
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "Found Archive")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_search_with_filter_sends_both_params(self, mock_urlopen):
        """search_entities with filter_str sends both $search and $filter."""
        captured_urls = []

        def fake_urlopen(req):
            if "$search=" in req.full_url:
                captured_urls.append(req.full_url)
                return MockResponse({
                    "results": [
                        {"tittel": "Matched", "_links": {"self": {"href": "http://x"}}}
                    ]
                })
            else:
                return MockResponse({
                    "systemID": "root",
                    "_links": {
                        RELBASE + "arkivstruktur/arkiv/": {"href": "https://example.com/archives"},
                    },
                })

        mock_urlopen.side_effect = fake_urlopen

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"

        results = client.search_entities("test", filter_str="contains(tittel, 'Matched')")
        self.assertEqual(len(results), 1)
        # Verify both parameters are present.
        url_with_both = [u for u in captured_urls if "$search=" in u and "$filter=" in u]
        self.assertEqual(len(url_with_both), 1)


class TestExpandUrl(unittest.TestCase):
    """Test _expand_url method."""

    def test_expand_relative_path(self):
        client = Noark5Client("https://example.com/api/")
        self.assertEqual(client._expand_url("/entity/123"), "https://example.com/entity/123")

    def test_expand_absolute_url_unchanged(self):
        client = Noark5Client("https://example.com/api/")
        url = "https://other.com/entity"
        self.assertEqual(client._expand_url(url), url)

    def test_expand_empty_path_raises(self):
        client = Noark5Client("https://example.com/")
        with self.assertRaises(ValueError):
            client._expand_url("")


class TestAuthHeadersLowLevel(unittest.TestCase):
    """Test _auth_headers method behavior."""

    def test_auth_headers_basic_token(self):
        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        headers = client._auth_headers()
        self.assertEqual(headers["Authorization"], "Basic dXNlcjpwYXNz")

    def test_auth_headers_no_token(self):
        client = Noark5Client("https://example.com/")
        headers = client._auth_headers()
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
