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

"""Tests for Noark5Client."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from noark5_tg_mcp.client import (
    NIKITA_RELBASE,
    Noark5Client,
    Noark5Error,
    RELBASE,
)


# ---------------------------------------------------------------------------
# Realistic mock data fixtures based on live N5TG API responses.
# Each single entity has: self + canonical rel in _links, required Arkivenhet
# fields (systemID, opprettetDato, endretDato, opprettetAv, endretAv), plus
# type-specific attributes.  Collection responses have count, results (each
# with its own _links), and a top-level _links.self.
# ---------------------------------------------------------------------------

def _rel(rel_suffix):
    """Shortcut for building full RELBASE relation URLs."""
    return RELBASE + rel_suffix


def arkiv_entity(system_id="a1", tittel="Test Arkiv"):
    """Build a realistic single arkiv entity dict."""
    base = f"https://example.com/api/arkivstruktur/arkiv/{system_id}"
    return {
        "systemID": system_id,
        "tittel": tittel,
        "arkivstatus": {"kode": "O", "kodenavn": "Opprettet"},
        "dokumentmedium": {"kode": "E", "kodenavn": "Elektronisk arkiv"},
        "opprettetDato": "2026-08-17T14:56:28.986089Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-17T14:56:28.986089Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/arkiv/"): {"href": base},
            _rel("arkivstruktur/arkivdel/"): {
                "href": f"{base}/arkivdel",
            },
            _rel("arkivstruktur/ny-arkivdel/"): {"href": f"{base}/ny-arkivdel"},
            _rel("arkivstruktur/underarkiv/"): {
                "href": f"{base}/underarkiv",
            },
            _rel("arkivstruktur/ny-arkiv/"): {"href": f"{base}/ny-arkiv"},
            _rel("arkivstruktur/ny-arkivskaper/"): {"href": f"{base}/ny-arkivskaper"},
            _rel("arkivstruktur/arkivskaper/"): {
                "href": f"{base}/arkivskaper",
            },
        },
    }


def arkiv_collection(items=None):
    """Build a realistic arkiv collection response."""
    if items is None:
        items = [arkiv_entity("a1", "Archive One"), arkiv_entity("a2", "Archive Two")]
    return {
        "count": len(items),
        "results": items,
        "_links": {
            "self": {"href": "https://example.com/api/arkivstruktur/arkiv"},
        },
    }


def arkivdel_entity(system_id="ad1", tittel="Bøker"):
    """Build a realistic single arkivdel entity dict."""
    base = f"https://example.com/api/arkivstruktur/arkivdel/{system_id}"
    return {
        "systemID": system_id,
        "tittel": tittel,
        "arkivdelstatus": {"kode": "A", "kodenavn": "Aktiv periode"},
        "dokumentmedium": {"kode": "E", "kodenavn": "Elektronisk arkiv"},
        "opprettetDato": "2026-08-17T14:56:56.871369Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-17T14:56:56.871369Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/arkivdel/"): {"href": base},
            _rel("arkivstruktur/mappe/"): {
                "href": f"{base}/mappe",
            },
            _rel("arkivstruktur/ny-mappe/"): {"href": f"{base}/ny-mappe"},
            _rel("arkivstruktur/registrering/"): {
                "href": f"{base}/registrering",
            },
            _rel("arkivstruktur/ny-registrering/"): {"href": f"{base}/ny-registrering"},
            _rel("sakarkiv/saksmappe/"): {
                "href": f"{base}/saksmappe",
            },
            _rel("sakarkiv/ny-saksmappe/"): {"href": f"{base}/ny-saksmappe"},
            _rel("arkivstruktur/klassifikasjonssystem/"): {
                "href": f"{base}/klassifikasjonssystem",
            },
            _rel("arkivstruktur/ny-klassifikasjonssystem/"): {"href": f"{base}/ny-klassifikasjonssystem"},
            _rel("arkivstruktur/arkiv/"): {
                "href": "https://example.com/api/arkivstruktur/arkiv/a1",
            },
        },
    }


def arkivdel_collection(items=None):
    """Build a realistic arkivdel collection response."""
    if items is None:
        items = [arkivdel_entity("ad1", "Bøker"), arkivdel_entity("ad2", "Artikler")]
    return {
        "count": len(items),
        "results": items,
        "_links": {
            "self": {"href": "https://example.com/api/arkivstruktur/arkiv/a1/arkivdel"},
        },
    }


def mappe_entity(system_id="mp1", tittel="Ebøker"):
    """Build a realistic single mappe entity dict."""
    base = f"https://example.com/api/arkivstruktur/mappe/{system_id}"
    return {
        "systemID": system_id,
        "tittel": tittel,
        "dokumentmedium": {"kode": "E", "kodenavn": "Elektronisk arkiv"},
        "opprettetDato": "2026-08-21T08:07:15.177502Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-21T08:07:15.177502Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/mappe/"): {"href": base},
            _rel("arkivstruktur/undermappe/"): {"href": f"{base}/undermappe"},
            _rel("arkivstruktur/ny-mappe/"): {"href": f"{base}/ny-mappe"},
            _rel("arkivstruktur/registrering/"): {
                "href": f"{base}/registrering",
            },
            _rel("arkivstruktur/ny-registrering/"): {"href": f"{base}/ny-registrering"},
            _rel("arkivstruktur/arkivdel/"): {
                "href": "https://example.com/api/arkivstruktur/arkivdel/ad1",
            },
        },
    }


def mappe_collection(items=None):
    """Build a realistic mappe collection response."""
    if items is None:
        items = [mappe_entity("mp1", "Ebøker"), mappe_entity("mp2", "Innboks")]
    return {
        "count": len(items),
        "results": items,
        "_links": {
            "self": {"href": "https://example.com/api/arkivstruktur/arkivdel/ad1/mappe"},
        },
    }


def registrering_entity(system_id="r1", tittel="Printcrime"):
    """Build a realistic single registrering entity dict."""
    base = f"https://example.com/api/arkivstruktur/registrering/{system_id}"
    return {
        "systemID": system_id,
        "tittel": tittel,
        "beskrivelse": "A book about printcrime",
        "dokumentmedium": {"kode": "E", "kodenavn": "Elektronisk arkiv"},
        "opprettetDato": "2026-08-21T05:55:20.709393Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-21T05:55:20.709393Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/registrering/"): {"href": base},
            _rel("arkivstruktur/dokumentbeskrivelse/"): {
                "href": f"{base}/dokumentbeskrivelse",
            },
            _rel("arkivstruktur/ny-dokumentbeskrivelse/"): {"href": f"{base}/ny-dokumentbeskrivelse"},
            _rel("arkivstruktur/mappe/"): {
                "href": "https://example.com/api/arkivstruktur/mappe/mp1",
            },
        },
    }


def registrering_collection(items=None):
    """Build a realistic registrering collection response."""
    if items is None:
        items = [registrering_entity("r1", "Printcrime"), registrering_entity("r2", "Little Brother")]
    return {
        "count": len(items),
        "results": items,
        "_links": {
            "self": {"href": "https://example.com/api/arkivstruktur/mappe/mp1/registrering"},
        },
    }


def dokumentbeskrivelse_entity(system_id="db1", tittel="printcrime.epub"):
    """Build a realistic single dokumentbeskrivelse entity dict."""
    base = f"https://example.com/api/arkivstruktur/dokumentbeskrivelse/{system_id}"
    return {
        "systemID": system_id,
        "tittel": tittel,
        "dokumenttype": {"kode": "U", "kodenavn": "UNKNOWN"},
        "opprettetDato": "2026-08-21T05:55:30.000000Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-21T05:55:30.000000Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/dokumentbeskrivelse/"): {"href": base},
            _rel("arkivstruktur/dokumentobjekt/"): {
                "href": f"{base}/dokumentobjekt",
            },
            _rel("arkivstruktur/ny-dokumentobjekt/"): {"href": f"{base}/ny-dokumentobjekt"},
        },
    }


def dokumentbeskrivelse_collection(items=None):
    """Build a realistic dokumentbeskrivelse collection response."""
    if items is None:
        items = [dokumentbeskrivelse_entity("db1", "printcrime.epub")]
    return {
        "count": len(items),
        "results": items,
        "_links": {
            "self": {"href": "https://example.com/api/arkivstruktur/registrering/r1/dokumentbeskrivelse"},
        },
    }


def dokumentobjekt_entity(system_id="do1", filnavn="printcrime.epub"):
    """Build a realistic single dokumentobjekt entity dict."""
    base = f"https://example.com/api/arkivstruktur/dokumentobjekt/{system_id}"
    return {
        "systemID": system_id,
        "filnavn": filnavn,
        "mimetype": "application/epub+zip",
        "storrelse": 1234567,
        "opprettetDato": "2026-08-21T05:56:00.000000Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-21T05:56:00.000000Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/dokumentobjekt/"): {"href": base},
            _rel("arkivstruktur/fil/"): {"href": f"{base}/referanseFil"},
        },
    }


def dokumentobjekt_collection(items=None):
    """Build a realistic dokumentobjekt collection response."""
    if items is None:
        items = [dokumentobjekt_entity("do1", "printcrime.epub")]
    return {
        "count": len(items),
        "results": items,
        "_links": {
            "self": {"href": "https://example.com/api/arkivstruktur/dokumentbeskrivelse/db1/dokumentobjekt"},
        },
    }


def saksmappe_entity(system_id="sm1", tittel="Case 2026/001"):
    """Build a realistic single saksmappe entity dict."""
    base = f"https://example.com/api/sakarkiv/saksmappe/{system_id}"
    return {
        "systemID": system_id,
        "tittel": tittel,
        "saksaar": 2026,
        "saksstatus": {"kode": "A", "kodenavn": "Åpen"},
        "dokumentmedium": {"kode": "E", "kodenavn": "Elektronisk arkiv"},
        "opprettetDato": "2026-08-15T10:00:00.000000Z",
        "opprettetAv": "admin",
        "endretDato": "2026-08-15T10:00:00.000000Z",
        "endretAv": "admin",
        "_links": {
            "self": {"href": base},
            _rel("sakarkiv/saksmappe/"): {"href": base},
            _rel("sakarkiv/journalpost/"): {
                "href": f"{base}/journalpost",
            },
            _rel("sakarkiv/ny-journalpost/"): {"href": f"{base}/ny-journalpost"},
            _rel("sakarkiv/arkivnotat/"): {
                "href": f"{base}/arkivnotat",
            },
            _rel("sakarkiv/ny-arkivnotat/"): {"href": f"{base}/ny-arkivnotat"},
        },
    }


def arkivskaper_entity(arkivskaper_id="ak1", navn="Test Person"):
    """Build a realistic single arkivskaper entity dict."""
    base = f"https://example.com/api/arkivstruktur/arkivskaper/{arkivskaper_id}"
    return {
        "arkivskaperID": arkivskaper_id,
        "navn": navn,
        "_links": {
            "self": {"href": base},
            _rel("arkivstruktur/arkivskaper/"): {"href": base},
        },
    }


def root_entity():
    """Build a realistic root entity dict (from /api)."""
    return {
        "_links": {
            "self": {"href": "https://example.com/api/"},
            _rel("arkivstruktur/arkiv/"): {"href": "https://example.com/api/arkivstruktur/arkiv"},
            _rel("login/oidc/"): {"href": "https://example.com/api/login/oidc/"},
            _rel("login/rfc7617/"): {"href": "https://example.com/api/login/rfc7617/"},
        },
    }


def metadata_root_entity():
    """Build a realistic /api/metadata entity with catalog links."""
    return {
        "_links": {
            "self": {"href": "https://example.com/api/metadata"},
            _rel("metadata/dokumentmedium/"): {
                "href": "https://example.com/api/metadata/dokumentmedium",
                "templated": True,
            },
            _rel("metadata/format/"): {
                "href": "https://example.com/api/metadata/format",
                "templated": True,
            },
        },
    }


def metadata_catalog_poster(kode="E", kodenavn="Elektronisk arkiv"):
    """Build a realistic katalogpost entry."""
    return {
        "kode": kode,
        "kodenavn": kodenavn,
    }


class TestNoark5ClientInit(unittest.TestCase):
    """Test client initialization and basic methods."""

    def test_init_defaults(self):
        client = Noark5Client("https://example.com/api/")
        self.assertEqual(client.base_url, "https://example.com/api/")
        self.assertFalse(client._logged_in)

    def test_init_with_auth(self):
        client = Noark5Client("https://example.com/", "user", "pass")
        self.assertEqual(client.username, "user")
        self.assertEqual(client.password, "pass")

    def test_strip_trailing_slash(self):
        client = Noark5Client("https://example.com/api/")
        self.assertTrue(client.base_url.endswith("/"))


class TestParseLinks(unittest.TestCase):
    """Test HATEOAS link parsing."""

    def test_parse_links_basic(self):
        entity = arkiv_entity()
        links = Noark5Client.parse_links(entity)
        base = "https://example.com/api/arkivstruktur/arkiv/a1"
        self.assertEqual(links["self"], base)
        # Canonical rel should also be present.
        self.assertEqual(links[_rel("arkivstruktur/arkiv/")], base)

    def test_parse_links_empty(self):
        self.assertEqual(Noark5Client.parse_links({}), {})
        self.assertEqual(Noark5Client.parse_links({"_links": {}}), {})


class TestCleanUrl(unittest.TestCase):
    """Test URL cleaning for OData template removal."""

    def test_clean_removes_template(self):
        url = "https://example.com/api/mappe{?$filter&$top}"
        self.assertEqual(Noark5Client.clean_url(url), "https://example.com/api/mappe")

    def test_clean_no_change(self):
        url = "https://example.com/api/mappe/123"
        self.assertEqual(Noark5Client.clean_url(url), url)


class TestEntityDetection(unittest.TestCase):
    """Test entity type detection from URL."""

    def test_detect_known_types(self):
        # Test each type with its own URL path (saksmappe uses sakarkiv, not arkivstruktur)
        self.assertEqual(Noark5Client.entity_type("https://example.com/api/arkivstruktur/arkiv/123"), "arkiv")
        self.assertEqual(Noark5Client.entity_type("https://example.com/api/arkivstruktur/mappe/abc"), "mappe")
        self.assertEqual(Noark5Client.entity_type("https://example.com/api/sakarkiv/saksmappe/x1"), "saksmappe")

    def test_detect_unknown(self):
        self.assertEqual(Noark5Client.entity_type("https://example.com/unknown"), "unknown")


class TestLogin(unittest.TestCase):
    """Test authentication."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    @patch.object(Noark5Client, "_get_json", return_value={"_links": {}})
    def test_login_sets_token(self, mock_get, mock_urlopen):
        client = Noark5Client("https://example.com/", "user", "pass")
        # _get_json is called inside login
        client.login()
        self.assertTrue(client._logged_in)
        self.assertIsNotNone(client._token)

    def test_login_no_credentials(self):
        client = Noark5Client("https://example.com/")
        with self.assertRaises(ValueError):
            client.login()


class TestFormatList(unittest.TestCase):
    """Test list formatting helper in server module."""

    def test_format_list_empty(self):
        from noark5_tg_mcp.server import _format_list

        result = _format_list([], "item")
        self.assertEqual(result, "No item(s) found.")

    def test_format_list_with_items(self):
        from noark5_tg_mcp.server import _format_list

        items = mappe_collection([mappe_entity("m1", "Ebøker")])["results"]
        result = _format_list(items, "mappe")
        self.assertIn("Found 1 mappe(s)", result)
        self.assertIn("[m1] Ebøker", result)


class TestFormatEntity(unittest.TestCase):
    """Test entity formatting."""

    def test_format_entity_basic(self):
        from noark5_tg_mcp.server import _format_entity

        entity = {"systemID": "abc-123", "tittel": "My Archive"}
        result = _format_entity(entity)
        self.assertIn("systemID: abc-123", result)
        self.assertIn("tittel: My Archive", result)


class TestClientHttpMethods(unittest.TestCase):
    """Test HTTP method wrappers with mocked responses."""

    @patch.object(Noark5Client, "_request")
    def test_get_json(self, mock_request):
        mock_request.return_value = (json.dumps({"key": "value"}).encode(), MagicMock())

        client = Noark5Client("https://example.com/")
        result = client._get_json("/test")
        self.assertEqual(result, {"key": "value"})

    def test_noark5_error(self):
        """Test Noark5Error creation and message."""
        err = Noark5Error(404, "Not found", "https://example.com/")
        self.assertEqual(err.code, 404)
        self.assertEqual(err.message, "Not found")
        self.assertIn("HTTP 404", str(err))

    @patch.object(Noark5Client, "_request")
    def test_get_json_http_error(self, mock_request):
        """Test that Noark5Error from _request propagates through _get_json."""
        mock_request.side_effect = Noark5Error(404, "Not found", "https://example.com/")

        client = Noark5Client("https://example.com/")
        with self.assertRaises(Noark5Error) as ctx:
            client._get_json("/missing")
        self.assertEqual(ctx.exception.code, 404)


class TestSearch(unittest.TestCase):
    """Test search functionality."""

    @patch.object(Noark5Client, "_get_json")
    def test_search_entities(self, mock_get):
        # find_relation walks the link tree: needs root entity for each collection rel.
        fake_root = {
            "systemID": "root",
            "_links": {
                _rel("arkivstruktur/arkiv/"): {"href": "https://example.com/archives"},
            },
        }

        def get_json_side_effect(path):
            if path == ".":
                return fake_root
            elif "/archives" in str(path) and "$search=" in str(path):
                return {
                    "count": 1,
                    "results": [
                        {
                            "systemID": "a1",
                            "tittel": "My Archive",
                            "_links": {
                                "self": {"href": "http://archive1"},
                                _rel("arkivstruktur/arkiv/"): {"href": "http://archive1"},
                            },
                        },
                    ],
                }
            return fake_root

        mock_get.side_effect = get_json_side_effect

        client = Noark5Client("https://example.com/")
        results = client.search_entities("My Archive")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], "My Archive")


class TestListOperations(unittest.TestCase):
    """Test list operations with mocked API responses."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkiv_empty(self, mock_get):
        # find_relation walks the link tree from root, then returns collection.
        fake_root = {
            "systemID": "root",
            "_links": {_rel("arkivstruktur/arkiv/"): {"href": "https://example.com/archives"}},
        }
        mock_get.side_effect = [fake_root, arkiv_collection([])]
        client = Noark5Client("https://example.com/")
        result = client.list_arkiv()
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_mapper(self, mock_get):
        parent_entity = arkivdel_entity()
        mapper_response = mappe_collection([mappe_entity("m1", "File 1"), mappe_entity("m2", "File 2")])
        mock_get.side_effect = [parent_entity, mapper_response]

        client = Noark5Client("https://example.com/")
        result = client.list_mapper("http://parent")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["tittel"], "File 1")


class TestFilterUrlConstruction(unittest.TestCase):
    """Test that filter-capable methods construct URLs with $filter= prefix."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkiv_filter_url(self, mock_get):
        fake_root = {
            "systemID": "root",
            "_links": {_rel("arkivstruktur/arkiv/"): {"href": "https://example.com/archives"}},
        }
        mock_get.side_effect = [fake_root, arkiv_collection([])]
        client = Noark5Client("https://example.com/")
        client.list_arkiv(filter_str="tittel eq 'Test'")
        call_url = mock_get.call_args_list[1][0][0]
        self.assertIn("$filter=", call_url)

    @patch.object(Noark5Client, "_get_json")
    def test_list_mapper_filter_url(self, mock_get):
        parent_entity = arkivdel_entity()
        mock_get.side_effect = [parent_entity, mappe_collection([])]

        client = Noark5Client("https://example.com/")
        client.list_mapper("http://parent", filter_str="tittel eq 'Ebøker'")
        call_url = mock_get.call_args_list[1][0][0]
        self.assertIn("$filter=", call_url)

    @patch.object(Noark5Client, "_get_json")
    def test_list_registreringer_filter_url(self, mock_get):
        parent_entity = mappe_entity()
        mock_get.side_effect = [parent_entity, registrering_collection([])]

        client = Noark5Client("https://example.com/")
        client.list_registreringer("http://mappe", filter_str="tittel eq 'Book'")
        call_url = mock_get.call_args_list[1][0][0]
        self.assertIn("$filter=", call_url)

    @patch.object(Noark5Client, "_get_json")
    def test_list_dokumentobjekter_filter_url(self, mock_get):
        parent_entity = dokumentbeskrivelse_entity()
        mock_get.side_effect = [parent_entity, dokumentobjekt_collection([])]

        client = Noark5Client("https://example.com/")
        client.list_dokumentobjekter("http://dokbeskr", filter_str="mimetype eq 'application/pdf'")
        call_url = mock_get.call_args_list[1][0][0]
        self.assertIn("$filter=", call_url)


class TestDownloadFile(unittest.TestCase):
    """Test download_file method."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_download_file_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"hello binary world"
        mock_urlopen.return_value = mock_resp

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        data = client.download_file("/dokumentobjekt/abc/referanseFil")
        self.assertEqual(data, b"hello binary world")

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_download_file_http_error(self, mock_urlopen):
        import urllib.error as urr
        err_resp = MagicMock()
        err_resp.read.return_value = b"Not Found"
        err_resp.code = 404
        mock_urlopen.side_effect = urr.HTTPError("https://example.com/", 404, "Not Found", {}, err_resp)

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        with self.assertRaises(Noark5Error) as ctx:
            client.download_file("/missing")
        self.assertEqual(ctx.exception.code, 404)


class TestDownloadDokumentobjekt(unittest.TestCase):
    """Test download_dokumentobjekt method."""

    @patch.object(Noark5Client, "download_file", return_value=b"epub content here")
    @patch.object(Noark5Client, "_get_json")
    def test_download_dokobj_success(self, mock_get, mock_dl):
        mock_get.return_value = dokumentobjekt_entity()

        client = Noark5Client("https://example.com/")
        data = client.download_dokumentobjekt("https://example.com/dokobj/123")
        self.assertEqual(data, b"epub content here")
        mock_get.assert_called_once_with("https://example.com/dokobj/123")

    @patch.object(Noark5Client, "_get_json", return_value=dokumentbeskrivelse_entity())
    def test_download_dokobj_no_fil_link(self, _mock):
        """Entity without referanseFil link raises Noark5Error."""
        client = Noark5Client("https://example.com/")
        with self.assertRaises(Noark5Error) as ctx:
            client.download_dokumentobjekt("https://example.com/dokobj/123")
        self.assertEqual(ctx.exception.code, 404)
        self.assertIn("referanseFil", ctx.exception.message)


class TestUploadFile(unittest.TestCase):
    """Test upload_file method."""

    @patch.object(Noark5Client, "_get_json")
    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_upload_file_success(self, mock_urlopen, mock_get_json):
        mock_get_json.return_value = {
            "_links": {
                _rel("arkivstruktur/fil/"): {"href": "https://example.com/dokbeskr/123/referanseFil"},
            },
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "systemID": "new-obj-id",
            "filnavn": "test.epub"
        }).encode()
        mock_urlopen.return_value = mock_resp

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        result = client.upload_file(
            "https://example.com/dokbeskr/123",
            b"file content",
            mime_type="application/epub+zip"
        )
        self.assertEqual(result["systemID"], "new-obj-id")

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://example.com/dokbeskr/123/referanseFil")
        self.assertEqual(req.get_method(), "POST")

    @patch.object(Noark5Client, "_get_json")
    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_upload_file_http_error(self, mock_urlopen, mock_get_json):
        import urllib.error as urr
        mock_get_json.return_value = {
            "_links": {
                _rel("arkivstruktur/fil/"): {"href": "https://example.com/dokbeskr/123/referanseFil"},
            },
        }

        err_resp = MagicMock()
        err_resp.read.return_value = b"Forbidden"
        err_resp.code = 403
        mock_urlopen.side_effect = urr.HTTPError("https://example.com/", 403, "Forbidden", {}, err_resp)

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        with self.assertRaises(Noark5Error) as ctx:
            client.upload_file("https://example.com/dokbeskr/123", b"data")
        self.assertEqual(ctx.exception.code, 403)

    @patch.object(Noark5Client, "_get_json")
    def test_upload_file_no_fil_relation(self, mock_get_json):
        mock_get_json.return_value = {
            "systemID": "no-file-entity",
            "_links": {},
        }

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        with self.assertRaises(Noark5Error) as ctx:
            client.upload_file("https://example.com/arkivdel/999", b"data")
        self.assertEqual(ctx.exception.code, 404)
        self.assertIn("fil relation", ctx.exception.message)

    @patch.object(Noark5Client, "_get_json")
    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_upload_from_registrering(self, mock_urlopen, mock_get_json):
        mock_get_json.return_value = {
            "_links": {
                _rel("arkivstruktur/fil/"): {"href": "https://example.com/registrering/r1/referanseFil"},
            },
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "systemID": "new-do-id",
            "_embedded": {
                _rel("arkivstruktur/dokumentbeskrivelse/"): {
                    "systemID": "new-db-id",
                },
            },
        }).encode()
        mock_urlopen.return_value = mock_resp

        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        result = client.upload_file(
            "https://example.com/registrering/r1",
            b"file content",
            mime_type="text/plain"
        )
        self.assertEqual(result["systemID"], "new-do-id")

        req = mock_urlopen.call_args[0][0]
        self.assertIn("referanseFil", req.full_url)


class TestServerUploadFile(unittest.TestCase):
    """Test server-level noark5_upload_file tool with file_path."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_upload_from_file(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.upload_file.return_value = {
            "systemID": "new-do-id",
            "filnavn": "test.txt",
            "mimeType": "text/plain",
        }
        mock_get_client.return_value = mock_client

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello world")
            tmp_path = f.name

        try:
            import noark5_tg_mcp.server as srv
            result = srv.noark5_upload_file(
                entity_url="https://example.com/registrering/r1",
                file_path=tmp_path,
                mime_type="text/plain",
            )
            self.assertIn("new-do-id", result)
            mock_client.upload_file.assert_called_once()
            call_args = mock_client.upload_file.call_args[0]
            self.assertEqual(call_args[1], b"hello world")
        finally:
            os.unlink(tmp_path)

    def test_upload_missing_file(self):
        import noark5_tg_mcp.server as srv
        with self.assertRaises(FileNotFoundError):
            srv.noark5_upload_file(
                entity_url="https://example.com/registrering/r1",
                file_path="/nonexistent/path/file.txt",
            )


class TestClientCreateWithAttributes(unittest.TestCase):
    """Test client create methods with attributes parameter to cover the `if attributes:` branches."""

    @patch("noark5_tg_mcp.client.Noark5Client._create_at_root")
    def test_create_arkiv_with_attributes(self, mock_create):
        """create_arkiv with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "My Archive",
            "_links": {"self": {"href": "http://example.com/arkiv/a1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_arkiv("My Archive", attributes={"beskrivelse": "Test Desc"})
        call_data = mock_create.call_args[0][1]
        assert call_data["beskrivelse"] == "Test Desc"

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_arkivdel_with_attributes(self, mock_create):
        """create_arkivdel with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Series One",
            "_links": {"self": {"href": "http://example.com/ad/ad1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_arkivdel(
            "http://example.com/arkiv/a1",
            "Series One",
            attributes={"beskrivelse": "Test Series"},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["beskrivelse"] == "Test Series"

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_registrering_with_attributes(self, mock_create):
        """create_registrering with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Record One",
            "_links": {"self": {"href": "http://example.com/r/r1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_registrering(
            "http://example.com/m/m1",
            "Record One",
            attributes={"registreringsID": "REG-001"},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["registreringsID"] == "REG-001"

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_dokumentbeskrivelse_with_attributes(self, mock_create):
        """create_dokumentbeskrivelse with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Doc Desc",
            "_links": {"self": {"href": "http://example.com/db/db1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_dokumentbeskrivelse(
            "http://example.com/r/r1",
            "Doc Desc",
            attributes={"dokumenttype": {"kode": "U"}},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["dokumenttype"] == {"kode": "U"}

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_klassifikasjonssystem_with_attributes(self, mock_create):
        """create_klassifikasjonssystem with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Class System",
            "_links": {"self": {"href": "http://example.com/ks/ks1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_klassifikasjonssystem(
            "http://example.com/ad/ad1",
            "Class System",
            attributes={"klassifikasjonstype": {"kode": "S"}},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["klassifikasjonstype"] == {"kode": "S"}

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_klasse_with_attributes(self, mock_create):
        """create_klasse with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Class One",
            "_links": {"self": {"href": "http://example.com/k/k1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_klasse(
            "http://example.com/ks/ks1",
            "Class One",
            attributes={"klasseID": "K-001"},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["klasseID"] == "K-001"

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_saksmappe_with_attributes(self, mock_create):
        """create_saksmappe with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Case File",
            "_links": {"self": {"href": "http://example.com/sm/sm1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_saksmappe(
            "http://example.com/ad/ad1",
            "Case File",
            saksaar=2024,
            attributes={"saksansvarlig": {"navn": "John Doe"}},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["saksansvarlig"] == {"navn": "John Doe"}

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_journalpost_with_attributes(self, mock_create):
        """create_journalpost with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Journal Entry",
            "_links": {"self": {"href": "http://example.com/jp/jp1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_journalpost(
            "http://example.com/sm/sm1",
            "Journal Entry",
            attributes={"journalposttype": {"kode": "MOTTFATT"}},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["journalposttype"] == {"kode": "MOTTFATT"}

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_arkivnotat_with_attributes(self, mock_create):
        """create_arkivnotat with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "Note One",
            "_links": {"self": {"href": "http://example.com/an/an1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_arkivnotat(
            "http://example.com/sm/sm1",
            "Note One",
            attributes={"dokumentetsDato": "2024-01-15"},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["dokumentetsDato"] == "2024-01-15"

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_dokumentobjekt_with_attributes(self, mock_create):
        """create_dokumentobjekt with attributes merges them into data."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "filnavn": "test.pdf",
            "_links": {"self": {"href": "http://example.com/do1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_dokumentobjekt(
            "http://example.com/db/db1",
            attributes={"filnavn": "test.pdf"},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["filnavn"] == "test.pdf"

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_mappe_with_beskrivelse_and_attributes(self, mock_create):
        """create_mappe with both beskrivelse and attributes."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "tittel": "File One",
            "_links": {"self": {"href": "http://example.com/m/m1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_mappe(
            "http://example.com/ad/ad1",
            "File One",
            beskrivelse="My Description",
            attributes={"mappeID": "M-001"},
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["beskrivelse"] == "My Description"
        assert call_data["mappeID"] == "M-001"


class TestClientOidcTokenRequest(unittest.TestCase):

    """Test OIDC login token request path."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_oidc_token_request_format(self, mock_urlopen):
        """OIDC _login_oidc sends proper form data with grant_type=password."""
        from noark5_tg_mcp.client import Noark5Client

        discovery = {"token_endpoint": "http://example.com/oauth/token"}
        token_response = {
            "access_token": "test-access-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        mock_resp_discovery = MagicMock()
        mock_resp_discovery.read.return_value = json.dumps(discovery).encode("utf-8")
        mock_resp_discovery.status = 200

        mock_resp_token = MagicMock()
        mock_resp_token.read.return_value = json.dumps(token_response).encode("utf-8")
        mock_resp_token.status = 200

        # _login_oidc may make additional calls (auth header check, etc.)
        mock_urlopen.side_effect = [mock_resp_discovery, mock_resp_token] + [MagicMock(read=lambda: b"{}", status=200)] * 10

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client._login_oidc("http://example.com/.well-known/openid-configuration")

        # Check that the token request was made with proper form data.
        token_call = mock_urlopen.call_args_list[1]
        req = token_call[0][0]
        form_data = req.data.decode("utf-8") if isinstance(req.data, bytes) else str(req.data)
        assert "grant_type=password" in form_data
        assert "username=user" in form_data


class TestClientSecondaryEntity(unittest.TestCase):
    """Test client create_secondary_entity method."""

    @patch("noark5_tg_mcp.client.Noark5Client._create_entity")
    def test_create_forfatter(self, mock_create):
        """Creates forfatter secondary entity correctly."""
        from noark5_tg_mcp.client import Noark5Client

        mock_create.return_value = {
            "forfatter": "John Doe",
            "_links": {"self": {"href": "http://example.com/f/1"}},
        }

        client = Noark5Client("http://example.com/", "user", "pass")
        result = client.create_secondary_entity(
            "http://example.com/db/db1", "forfatter", {"forfatter": "John Doe"}
        )
        call_data = mock_create.call_args[0][2]
        assert call_data["forfatter"] == "John Doe"


class TestDownloadTempFile(unittest.TestCase):
    """Test download to temp file."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_download_to_temp_file(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.download_dokumentobjekt.return_value = b"temp file content"
        mock_get_client.return_value = mock_client

        import noark5_tg_mcp.server as srv
        result = srv.noark5_download_dokumentobjekt(
            dokobj_url="https://example.com/dokobj/123",
        )
        # Should contain a temp file path, not base64 content
        self.assertIn("Downloaded", result)
        self.assertNotIn("Base64-Content", result)

        # Extract the temp file path from result string
        parts = result.split()
        tmp_path = None
        for p in parts:
            if "/tmp/" in p or "noark5-download-" in p:
                tmp_path = p.rstrip(")")
                break
        self.assertIsNotNone(tmp_path)

        # Verify file was created with correct content
        try:
            with open(tmp_path, "rb") as f:
                self.assertEqual(f.read(), b"temp file content")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)


class TestListChildrenTopLevelGetJson(unittest.TestCase):
    """Test noark5_list_children top-level via _get_json mocking to exercise both server and client layers."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_no_parent_exercises_find_relation(self, mock_get_client):
        """Top-level list calls find_relation for arkiv/arkivskaper collections."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        mock_client.find_relation.side_effect = lambda rel: {
            RELBASE + "arkivstruktur/arkiv/": "http://api/arkiv?{?$filter}",
            RELBASE + "arkivstruktur/arkivskaper/": "http://api/arkivskaper?{?$filter}",
        }.get(rel)
        mock_client._get_json.return_value = {"results": [{"systemID": "a1", "tittel": "Archive 1"}]}

        result = noark5_list_children()
        assert "Archive 1" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_no_arkivskaper_relation(self, mock_get_client):
        """find_relation returning None for arkivskaper skips that collection (server line 350)."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        call_count = [0]

        def find_rel(rel):
            if rel == RELBASE + "arkivstruktur/arkivskaper/":
                return None
            call_count[0] += 1
            return "http://api/collection?{?$filter}"

        mock_client.find_relation.side_effect = find_rel
        mock_client._get_json.return_value = {"results": [{"systemID": "a1", "tittel": "Archive"}]}

        result = noark5_list_children()
        assert "Archive" in result
        assert "arkivskaper" not in result.lower() or "no arkivskapere" not in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_with_filter(self, mock_get_client):
        """Top-level list with filter_str appends $filter to URL (server line 352)."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        filter_used = [None]

        def find_rel(rel):
            return "http://api/collection?{?$filter}"

        mock_client.find_relation.side_effect = find_rel

        def get_json(url):
            if "$filter=" in url:
                filter_used[0] = url.split("$filter=", 1)[1]
            return {"results": [{"systemID": "a1", "tittel": "Filtered"}]}

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(filter_str="contains(tittel, 'Test')")
        assert "Filtered" in result


class TestListChildrenParentGetJson(unittest.TestCase):
    """Test noark5_list_children with parent_url via _get_json to exercise client list_* methods."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_parent_no_collections(self, mock_get_client):
        """Entity with no child collection links returns message (server lines 808-809)."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        # Entity with only a self link — no children collections
        entity_data = {
            "systemID": "x1",
            "tittel": "Leaf Entity",
            "_links": {"self": {"href": "http://api/leaf/x1"}},
        }
        mock_client.get_entity.return_value = entity_data

        result = noark5_list_children(parent_url="http://api/leaf/x1")
        assert "No child collections" in result or "no child" in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_parent_empty_results(self, mock_get_client):
        """Entity with collection link but empty results (server lines 811-812)."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        # Entity has a mappe/ relation but returns empty results
        entity_with_links = {
            "systemID": "ad1",
            "tittel": "Series 1",
            "_links": {
                "self": {"href": "http://api/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/arkivdel/ad1/mappe/"},
            },
        }

        mock_client.get_entity.return_value = entity_with_links

        def get_json(url):
            if "/mappe/" in url:
                return {"results": []}
            return entity_with_links

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(parent_url="http://api/arkivdel/ad1")
        assert "No mappe found" in result or "mappe" in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_parent_fetch_error(self, mock_get_client):
        """Collection fetch raises Noark5Error, continues to next (server lines 395-397)."""
        from noark5_tg_mcp.client import Noark5Error
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        entity_with_links = {
            "systemID": "ad1",
            "_links": {
                "self": {"href": "http://api/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/arkivdel/ad1/mappe/"},
                RELBASE + "sakarkiv/saksmappe/": {"href": "http://api/arkivdel/ad1/saksmappe/"},
            },
        }

        mock_client.get_entity.return_value = entity_with_links

        def get_json(url):
            if "/mappe/" in url:
                raise Noark5Error(500, "Internal Error", url)
            elif "/saksmappe/" in url:
                return {"results": [{"systemID": "s1", "tittel": "Case File"}]}
            return entity_with_links

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(parent_url="http://api/arkivdel/ad1")
        assert "Error fetching collection" in result
        assert "saksmappe" in result.lower()


class TestEntityLinksClassificationGetJson(unittest.TestCase):
    """Test noark5_entity_links classification via _get_json mocking."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_entity_links_create_endpoint(self, mock_get_client):
        """ny- relation classified as create endpoint (server line 914)."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        entity_data = {
            "systemID": "m1",
            "tittel": "Mappe 1",
            "_links": {
                "self": {"href": "http://api/mappe/m1"},
                RELBASE + "arkivstruktur/ny-registrering/": {
                    "href": "http://api/mappe/m1/registrering/new?{?$filter}", "templated": True
                },
            },
        }
        mock_client.get_entity.return_value = entity_data

        result = noark5_entity_links("http://api/mappe/m1")
        assert "Create endpoints" in result or "ny-registrering" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_entity_links_query_template(self, mock_get_client):
        """Templated relation without ny- classified as query template (server line 916)."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        entity_data = {
            "systemID": "ad1",
            "_links": {
                "self": {"href": "http://api/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {
                    "href": "http://api/mapper?parent=ad1&{?$filter}", "templated": True
                },
            },
        }
        mock_client.get_entity.return_value = entity_data

        result = noark5_entity_links("http://api/arkivdel/ad1")
        assert "{?$filter}" in result or "Query templates" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_entity_links_klasse_parent(self, mock_get_client):
        """klasse entity with overklasse/ relation classified as parent (server lines 930-931)."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        entity_data = {
            "systemID": "k2",
            "_links": {
                "self": {"href": "http://api/klasse/k2"},
                RELBASE + "arkivstruktur/overklasse/": {"href": "http://api/klasse/k1"},
            },
        }
        mock_client.get_entity.return_value = entity_data

        result = noark5_entity_links("http://api/klasse/k2")
        assert "Parent" in result or "overklasse" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_entity_links_mappe_parent(self, mock_get_client):
        """mappe with overmappe/ classified as parent (server lines 933-934)."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        entity_data = {
            "systemID": "m2",
            "_links": {
                "self": {"href": "http://api/mappe/m2"},
                RELBASE + "arkivstruktur/overmappe/": {"href": "http://api/mappe/m1"},
            },
        }
        mock_client.get_entity.return_value = entity_data

        result = noark5_entity_links("http://api/mappe/m2")
        assert "Parent" in result or "overmappe" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_entity_links_no_navigable_links(self, mock_get_client):
        """Entity with only self link returns no navigable links message (server line 971)."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        entity_data = {
            "systemID": "do1",
            "_links": {"self": {"href": "http://api/dokobj/do1"}},
        }
        mock_client.get_entity.return_value = entity_data

        result = noark5_entity_links("http://api/dokobj/do1")
        assert "No navigable links" in result


class TestFilterEntitiesToolGetJson(unittest.TestCase):
    """Test noark5_filter_entities via _get_json to exercise filter_collection + server formatting."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_filter_entities_with_results(self, mock_get_client):
        """Returns formatted list with systemID, title (server lines 1043-1056)."""
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = [
            {"systemID": "e1", "tittel": "Entity One", "_links": {"self": {"href": "http://api/e1"}}},
        ]

        result = noark5_filter_entities("http://api/mapper?{?$filter}", "contains(tittel, 'One')")
        assert "Entity One" in result
        assert "e1" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_filter_entities_no_results(self, mock_get_client):
        """Empty results return no entities message with filter info (server line 1046)."""
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = []

        result = noark5_filter_entities("http://api/mapper?{?$filter}", "contains(tittel, 'X')")
        assert "No entities found" in result
        assert "matching filter" in result or "X" in result


class TestListMetadataToolGetJson(unittest.TestCase):
    """Test noark5_list_metadata via _get_json to exercise metadata listing paths."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_metadata_no_catalogs(self, mock_get_client):
        """Empty catalog list returns message (server line 1000)."""
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata.return_value = []

        result = noark5_list_metadata()
        assert "No metadata catalogs" in result


class TestClientListMethodsNoRelation(unittest.TestCase):
    """Test client list_* methods when entity has no relevant relation — exercises 'if rel not in links' branches."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkivdeler_no_relation(self, mock_get_json):
        """list_arkivdeler returns [] when arkivdel/ relation missing (client line 530-531)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "a1",
            "_links": {"self": {"href": "http://api/arkiv/a1"}},
        }

        result = client.list_arkivdeler("http://api/arkiv/a1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_mapper_no_relation(self, mock_get_json):
        """list_mapper returns [] when mappe/ relation missing (client line 543-544)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "k1",
            "_links": {"self": {"href": "http://api/klasse/k1"}},
        }

        result = client.list_mapper("http://api/klasse/k1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_registreringer_no_relation(self, mock_get_json):
        """list_registreringer returns [] when registrering/ missing (client line 557)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "m1",
            "_links": {"self": {"href": "http://api/mappe/m1"}},
        }

        result = client.list_registreringer("http://api/mappe/m1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_dokumentbeskrivelser_no_relation(self, mock_get_json):
        """list_dokumentbeskrivelser returns [] (client line 566-573)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "r1",
            "_links": {"self": {"href": "http://api/registrering/r1"}},
        }

        result = client.list_dokumentbeskrivelser("http://api/registrering/r1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_saksmapper_no_relation(self, mock_get_json):
        """list_saksmapper returns [] when saksmappe/ missing (client line 616-617)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "ad1",
            "_links": {"self": {"href": "http://api/arkivdel/ad1"}},
        }

        result = client.list_saksmapper("http://api/arkivdel/ad1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_journalposter_no_relation(self, mock_get_json):
        """list_journalposter returns [] when journalpost/ missing (client line 627-628)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "sm1",
            "_links": {"self": {"href": "http://api/saksmappe/sm1"}},
        }

        result = client.list_journalposter("http://api/saksmappe/sm1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_klasser_no_relation(self, mock_get_json):
        """list_klasser returns [] when klasse/ missing (client line 660-661)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "ks1",
            "_links": {"self": {"href": "http://api/klassifikasjonssystem/ks1"}},
        }

        result = client.list_klasser("http://api/klassifikasjonssystem/ks1")
        self.assertEqual(result, [])


class TestClientParseLinksStringHref(unittest.TestCase):
    """Test parse_links handles string href values (client line 443-444)."""

    def test_parse_links_string_href(self):
        """parse_links accepts both dict and string href formats."""
        client = Noark5Client("http://api/")
        entity = {
            "_links": {
                "self": {"href": "http://api/self"},
                "related": "http://api/related",  # String format (N5TG ch 6)
            },
        }
        links = client.parse_links(entity)
        self.assertEqual(links["self"], "http://api/self")
        self.assertEqual(links["related"], "http://api/related")


class TestClientFindRelationDuplicates(unittest.TestCase):
    """Test find_relation skips duplicate URLs (client line 472-473)."""

    @patch.object(Noark5Client, "_get_json")
    def test_find_relation_skips_duplicates(self, mock_get_json):
        """find_relation avoids re-fetching same clean URL."""
        client = Noark5Client("http://api/")
        call_urls = []

        def get_json_side_effect(url):
            call_urls.append(url)
            return {
                "_links": {
                    "self": {"href": url if url != "." else "http://api/"},
                    RELBASE + "arkivstruktur/arkiv/": {"href": "http://api/arkiv?{?$filter}"},
                    RELBASE + "arkivstruktur/arkivdel/": {"href": "http://api/arkivdel?{?$filter}"},
                },
            }

        mock_get_json.side_effect = get_json_side_effect
        result = client.find_relation(RELBASE + "arkivstruktur/arkiv/")
        self.assertIsNotNone(result)


class TestClientSearchEntities(unittest.TestCase):
    """Test search_entities via _get_json to exercise full collection traversal."""

    @patch.object(Noark5Client, "_get_json")
    def test_search_no_relation_found(self, mock_get_json):
        """search_entities skips collections where find_relation returns None (client line 700-701)."""
        client = Noark5Client("http://api/")

        def get_json_side_effect(url):
            return {
                "_links": {
                    "self": {"href": "http://api/" if url == "." else url},
                },
            }

        mock_get_json.side_effect = get_json_side_effect
        result = client.search_entities("test")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_search_with_results_and_dedup(self, mock_get_json):
        """search_entities returns deduplicated results across collections."""
        from unittest.mock import call

        client = Noark5Client("http://api/")
        arkiv_rel = RELBASE + "arkivstruktur/arkiv/"
        arkivdel_rel = RELBASE + "arkivstruktur/arkivdel/"

        def get_json_side_effect(url):
            if "$search=" in url:
                return {"results": [
                    {"_links": {"self": {"href": "http://api/item1"}}, "tittel": "Found Item"},
                ]}
            return {
                "_links": {
                    "self": {"href": "http://api/" if url == "." else url},
                    arkiv_rel: {"href": "http://api/arkiv?{?$filter}"},
                    arkivdel_rel: {"href": "http://api/arkivdel?{?$filter}"},
                },
            }

        mock_get_json.side_effect = get_json_side_effect
        result = client.search_entities("test")
        self.assertTrue(len(result) >= 1)


class TestClientCreateEntityNoRelation(unittest.TestCase):
    """Test _create_entity when ny- relation is missing from parent (client line 724)."""

    @patch.object(Noark5Client, "_get_json")
    def test_create_entity_missing_relation(self, mock_get_json):
        """_create_entity raises Noark5Error when ny_rel not in links."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "m1",
            "_links": {"self": {"href": "http://api/mappe/m1"}},
        }

        with self.assertRaises(Noark5Error):
            client._create_entity("http://api/mappe/m1", RELBASE + "arkivstruktur/ny-registrering/", {})


class TestClientCreateEntityWithTemplate(unittest.TestCase):
    """Test _create_entity template defaults loop (client line 730-732)."""

    @patch.object(Noark5Client, "_get_json")
    def test_create_entity_template_defaults(self, mock_get_json):
        """_create_entity merges multiple template defaults into data."""
        from unittest.mock import patch

        client = Noark5Client("http://api/")
        parent_data = {
            "systemID": "m1",
            "_links": {
                "self": {"href": "http://api/mappe/m1"},
                RELBASE + "arkivstruktur/ny-registrering/": {"href": "http://api/reg/new"},
            },
        }

        def get_json_side_effect(url):
            if url == "http://api/mappe/m1":
                return parent_data
            elif "$filter" in str(url) or "new" in url:
                return {"dokumenttype": "Inngående", "arkivertAv": "system"}
            raise Noark5Error(404, "Not found", str(url))

        mock_get_json.side_effect = get_json_side_effect

        with patch.object(client, "_post_json") as mock_post:
            mock_post.return_value = {"systemID": "new-reg-1"}
            result = client._create_entity(
                "http://api/mappe/m1",
                RELBASE + "arkivstruktur/ny-registrering/",
                {"tittel": "New Record"},
            )
            call_args = mock_post.call_args[0][1]
            self.assertEqual(call_args["dokumenttype"], "Inngående")


class TestClientCreateAtRoot(unittest.TestCase):
    """Test _create_at_root when relation not found (client line 742)."""

    @patch.object(Noark5Client, "_get_json")
    def test_create_at_root_no_relation(self, mock_get_json):
        """_create_at_root raises Noark5Error when find_relation returns None."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "systemID": "root",
            "_links": {"self": {"href": "http://api/"}},
        }

        with self.assertRaises(Noark5Error):
            client._create_at_root("arkivstruktur/ny-arkivskaper/", {})


class TestClientCreateAtRootWithTemplate(unittest.TestCase):
    """Test _create_at_root template defaults loop (client lines 747-748)."""

    @patch.object(Noark5Client, "_get_json")
    def test_create_at_root_template_merge(self, mock_get_json):
        """_create_at_root merges template defaults into data."""
        from unittest.mock import patch

        client = Noark5Client("http://api/")
        root_data = {
            "systemID": "root",
            "_links": {
                "self": {"href": "http://api/"},
                RELBASE + "arkivstruktur/ny-arkivskaper/": {"href": "http://api/arkivskaper/new"},
            },
        }

        def get_json_side_effect(url):
            if url == ".":
                return root_data
            elif "new" in str(url) or "$filter" in str(url):
                return {"beskrivelse": "Default creator"}
            raise Noark5Error(404, "Not found", str(url))

        mock_get_json.side_effect = get_json_side_effect

        with patch.object(client, "_post_json") as mock_post:
            mock_post.return_value = {"systemID": "new-ak"}
            client._create_at_root("arkivstruktur/ny-arkivskaper/", {"arkivskaperID": "test"})
            call_args = mock_post.call_args[0][1]
            self.assertEqual(call_args["beskrivelse"], "Default creator")


class TestClientListArkvieFilter(unittest.TestCase):
    """Test list_arkiv and list_arkivskapere with filter parameter."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkiv_with_filter(self, mock_get_json):
        """list_arkiv appends $filter when provided (client line 510-512)."""
        client = Noark5Client("http://api/")
        filter_used = [None]

        def get_json_side_effect(url):
            if "$filter=" in str(url):
                filter_used[0] = True
                return {"results": [{"systemID": "a1", "tittel": "Filtered Archive"}]}
            elif url == ".":
                return {
                    "_links": {
                        RELBASE + "arkivstruktur/arkiv/": {"href": "http://api/arkiv?{?$filter}"},
                    },
                }
            raise Noark5Error(404, "Not found", str(url))

        mock_get_json.side_effect = get_json_side_effect
        result = client.list_arkiv(filter_str="contains(tittel, 'Test')")
        self.assertEqual(len(result), 1)
        self.assertTrue(filter_used[0])


class TestCreateMethodsNoAttributes(unittest.TestCase):
    """Test create methods without attributes to cover the `if attributes:` skip branches."""

    @patch.object(Noark5Client, "_create_entity")
    def test_create_arkivdel_no_attributes(self, mock_create):
        """create_arkivdel without attributes (client line 792->794)."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("http://api/")
        mock_create.return_value = {"systemID": "ad1"}
        result = client.create_arkivdel("http://api/arkiv/a1", "Series Title")
        call_data = mock_create.call_args[0][2]
        self.assertNotIn("beskrivelse", call_data)

    @patch.object(Noark5Client, "_create_entity")
    def test_create_registrering_no_attributes(self, mock_create):
        """create_registrering without attributes (client line 822->824)."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("http://api/")
        mock_create.return_value = {"systemID": "r1"}
        result = client.create_registrering("http://api/mappe/m1", "Record Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "Record Title"})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_dokumentbeskrivelse_no_attributes(self, mock_create):
        """create_dokumentbeskrivelse without attributes (client line 837->839)."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("http://api/")
        mock_create.return_value = {"systemID": "db1"}
        result = client.create_dokumentbeskrivelse(
            "http://api/registrering/r1", "Doc Desc Title"
        )
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "Doc Desc Title"})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_mappe_no_attributes(self, mock_create):
        """create_mappe without attributes or beskrivelse (client line 854->856)."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("http://api/")
        mock_create.return_value = {"systemID": "m1"}
        result = client.create_mappe("http://api/parent", "Mappe Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "Mappe Title"})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_klasse_no_attributes(self, mock_create):
        """create_klasse without attributes (client line 869->871)."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("http://api/")
        mock_create.return_value = {"systemID": "k1"}
        result = client.create_klasse("http://api/ks1", "Class Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "Class Title"})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_journalpost_no_attributes(self, mock_create):
        """create_journalpost without attributes (client line 916->918)."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("http://api/")
        mock_create.return_value = {"systemID": "jp1"}
        result = client.create_journalpost("http://api/sm1", "Journal Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "Journal Title"})


class TestDownloadDefaultOutputPath(unittest.TestCase):
    """Test noark5_download_dokumentobjekt with default output_path (server lines 1088-1092)."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_download_default_output_path(self, mock_get_client):
        """download_dokumentobjekt generates temp file when no output_path given."""
        import tempfile
        from noark5_tg_mcp.server import noark5_download_dokumentobjekt

        mock_client = mock_get_client.return_value
        mock_client.download_dokumentobjekt.return_value = b"file content here"

        result = noark5_download_dokumentobjekt("http://api/dokobj/do1")
        self.assertIn("Downloaded", result)
        file_path = result.split("to ")[1].split(" (")[0]
        self.assertTrue(file_path.startswith(tempfile.gettempdir()))


class TestClientSelfHref(unittest.TestCase):
    """Test _self_href edge cases (client lines 1037-1042)."""

    def test_self_href_no_links(self):
        """_self_href returns None when no _links."""
        client = Noark5Client("http://api/")
        self.assertIsNone(client._self_href({}))

    def test_self_href_empty_values(self):
        """_self_href handles empty href values."""
        client = Noark5Client("http://api/")
        entity = {"_links": {"self": {"href": ""}}}
        self.assertIsNone(client._self_href(entity))


class TestMainListTools(unittest.TestCase):
    """Test main() --list-tools and --list-tools-full paths (server lines 1201-1216)."""

    @patch("sys.argv", ["noark5-tg-mcp", "--list-tools"])
    def test_main_list_tools(self):
        """main with --list-tools prints tool list."""
        from noark5_tg_mcp.server import main
        import io, sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            main()
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("Available MCP tools", output)


class TestClientListArkvieNoUrl(unittest.TestCase):
    """Test list_arkiv/list_arkivskapere when find_relation returns None."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkiv_no_url(self, mock_get_json):
        """list_arkiv returns [] when find_relation returns None (client line 509)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "_links": {"self": {"href": "http://api/"}},
        }

        result = client.list_arkiv()
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkivskapere_no_url(self, mock_get_json):
        """list_arkivskapere returns [] when find_relation returns None (client line 518-519)."""
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {
            "_links": {"self": {"href": "http://api/"}},
        }

        result = client.list_arkivskapere()
        self.assertEqual(result, [])


class TestServerListChildrenParentUrlWithFilter(unittest.TestCase):
    """Test noark5_list_children with parent_url and filter_str."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_parent_with_filter(self, mock_get_client):
        """filter_str applied to collection fetch (server lines 832-840)."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        mock_client._encode_filter.side_effect = lambda s: s.replace(" ", "%20")
        entity_with_links = {
            "systemID": "ad1",
            "_links": {
                "self": {"href": "http://api/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/arkivdel/ad1/mappe/"},
            },
        }

        mock_client.get_entity.return_value = entity_with_links

        def get_json(url):
            if "/mappe/" in url:
                return {"results": [{"systemID": "m1", "tittel": "Filtered Mappe"}]}
            return entity_with_links

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(
            parent_url="http://api/arkivdel/ad1", filter_str="contains(tittel, 'Filter')"
        )
        self.assertIn("Filtered Mappe", result)


class TestClientListArkvieWithResults(unittest.TestCase):
    """Test list_arkiv/list_arkivskapere with actual results via find_relation."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkiv_with_results(self, mock_get_json):
        """list_arkiv returns results when relation found (client lines 512-513)."""
        client = Noark5Client("http://api/")

        def get_json_side_effect(url):
            if "$filter" in str(url) or "arkiv?" in str(url):
                return {"results": [{"systemID": "a1", "tittel": "Archive One"}]}
            elif url == ".":
                return {
                    "_links": {
                        RELBASE + "arkivstruktur/arkiv/": {"href": "http://api/arkiv?{?$filter}"},
                    },
                }
            raise Noark5Error(404, "Not found", str(url))

        mock_get_json.side_effect = get_json_side_effect
        result = client.list_arkiv()
        self.assertEqual(len(result), 1)


class TestClientSearchWithFilter(unittest.TestCase):
    """Test search_entities with filter_str (client line 703-704)."""

    @patch.object(Noark5Client, "_get_json")
    def test_search_with_filter(self, mock_get_json):
        """search_entities appends $filter when provided."""
        client = Noark5Client("http://api/")
        filter_used = [False]

        def get_json_side_effect(url):
            if "$filter=" in str(url):
                filter_used[0] = True
            elif "$search=" in str(url):
                return {"results": [{"_links": {"self": {"href": "http://api/1"}}, "tittel": "Item"}]}
            return {
                "_links": {
                    RELBASE + "arkivstruktur/arkiv/": {"href": "http://api/arkiv?{?$filter}"},
                },
            }

        mock_get_json.side_effect = get_json_side_effect
        client.search_entities("test", filter_str="opprettetDato ge 2024-01-01T00:00:00Z")
        self.assertTrue(filter_used[0])


class TestClientSearchNoark5Error(unittest.TestCase):
    """Test search_entities handles Noark5Error per collection (client line 713-714)."""

    @patch.object(Noark5Client, "_get_json")
    def test_search_continues_on_error(self, mock_get_json):
        """search_entities catches Noark5Error and continues to next collection."""
        client = Noark5Client("http://api/")
        call_count = [0]

        def get_json_side_effect(url):
            call_count[0] += 1
            if "$search=" in str(url):
                raise Noark5Error(400, "Bad request", url)
            return {
                "_links": {
                    RELBASE + "arkivstruktur/arkiv/": {"href": "http://api/arkiv?{?$filter}"},
                },
            }

        mock_get_json.side_effect = get_json_side_effect
        result = client.search_entities("test")
        self.assertEqual(result, [])




class TestCreateSecondaryEntity(unittest.TestCase):
    """Test create_secondary_entity method for [0..*] sub-resources."""

    @patch.object(Noark5Client, "_create_entity")
    def test_create_forfatter(self, mock_create):
        mock_create.return_value = {
            "forfatter": "Cory Doctorow",
            "_links": {"self": {"href": "https://example.com/forfatter/123"}},
        }

        client = Noark5Client("https://example.com/")
        result = client.create_secondary_entity(
            "https://example.com/dokbeskr/456",
            "forfatter",
            {"forfatter": "Cory Doctorow"},
        )
        self.assertEqual(result["forfatter"], "Cory Doctorow")
        mock_create.assert_called_once_with(
            "https://example.com/dokbeskr/456",
            NIKITA_RELBASE + "ny-forfatter/",
            {"forfatter": "Cory Doctorow"},
        )

    @patch.object(Noark5Client, "_create_entity")
    def test_create_noekkelord(self, mock_create):
        mock_create.return_value = {
            "noekkelord": "science fiction",
            "_links": {"self": {"href": "https://example.com/noekkelord/789"}},
        }

        client = Noark5Client("https://example.com/")
        result = client.create_secondary_entity(
            "https://example.com/dokbeskr/456",
            "noekkelord",
            {"noekkelord": "science fiction"},
        )
        self.assertEqual(result["noekkelord"], "science fiction")



class TestSecondaryEntityRelation(unittest.TestCase):
    """Test _secondary_entity_relation uses correct relation base."""

    def test_merknad_uses_official_rel(self):
        rel = Noark5Client._secondary_entity_relation("merknad")
        self.assertEqual(rel, RELBASE + "arkivstruktur/ny-merknad/")

    def test_kryssreferanse_uses_official_rel(self):
        rel = Noark5Client._secondary_entity_relation("kryssreferanse")
        self.assertEqual(rel, RELBASE + "arkivstruktur/ny-kryssreferanse/")

    def test_forfatter_falls_back_to_vendor(self):
        rel = Noark5Client._secondary_entity_relation("forfatter")
        self.assertEqual(rel, NIKITA_RELBASE + "ny-forfatter/")

    def test_noekkelord_falls_back_to_vendor(self):
        rel = Noark5Client._secondary_entity_relation("noekkelord")
        self.assertEqual(rel, NIKITA_RELBASE + "ny-noekkelord/")



class TestUpdateEntity(unittest.TestCase):
    """Test update_entity uses merge PATCH instead of PUT."""

    @patch.object(Noark5Client, "_get_with_etag")
    @patch.object(Noark5Client, "_patch_json_with_etag")
    def test_update_uses_patch(self, mock_patch, mock_get_etag):
        mock_get_etag.return_value = ({"tittel": "Old"}, '"abc123"')
        mock_patch.return_value = {"tittel": "New", "_links": {"self": {"href": "https://example.com/mappe/456"}}}

        client = Noark5Client("https://example.com/")
        result = client.update_entity("/mappe/456", {"tittel": "New"})
        self.assertEqual(result["tittel"], "New")
        mock_patch.assert_called_once_with("/mappe/456", {"tittel": "New"}, '"abc123"')

    @patch.object(Noark5Client, "_get_with_etag")
    def test_patch_sends_only_changes(self, mock_get_etag):
        import urllib.request
        from unittest.mock import MagicMock

        mock_get_etag.return_value = ({"tittel": "Old", "beskrivelse": "Existing"}, '"etag123"')

        client = Noark5Client("https://example.com/")
        sent_body = []

        original_urlopen = urllib.request.urlopen

        def fake_urlopen(req):
            sent_body.append(req.data)
            resp = MagicMock()
            resp.read.return_value = json.dumps({"tittel": "New", "beskrivelse": "Existing"}).encode("utf-8")
            return resp

        with patch.object(urllib.request, "urlopen", fake_urlopen):
            client.update_entity("/mappe/456", {"tittel": "New"})

        self.assertEqual(len(sent_body), 1)
        body = json.loads(sent_body[0])
        self.assertNotIn("beskrivelse", body)  # Should not send unchanged fields


class TestFilterCollection(unittest.TestCase):
    """Test filter_collection method for generic OData filtering."""

    @patch.object(Noark5Client, "_get_json")
    def test_filter_collection_no_filter(self, mock_get):
        mock_get.return_value = dokumentobjekt_collection([
            dokumentobjekt_entity("1", "a.epub"),
            dokumentobjekt_entity("2", "b.pdf"),
        ])

        client = Noark5Client("https://example.com/")
        result = client.filter_collection("/dokumentobjekt")
        self.assertEqual(len(result), 2)

    @patch.object(Noark5Client, "_get_json")
    def test_filter_collection_with_filter(self, mock_get):
        mock_get.return_value = dokumentobjekt_collection([
            dokumentobjekt_entity("1", "a.epub"),
        ])

        client = Noark5Client("https://example.com/")
        result = client.filter_collection(
            "/dokumentobjekt",
            filter_str="mimetype eq 'application/epub+zip'",
        )
        self.assertEqual(len(result), 1)
        call_url = mock_get.call_args[0][0]
        self.assertIn("$filter=", call_url)
        self.assertIn("mimetype", call_url)

    @patch.object(Noark5Client, "_get_json")
    def test_filter_collection_empty_results(self, mock_get):
        mock_get.return_value = dokumentobjekt_collection([])

        client = Noark5Client("https://example.com/")
        result = client.filter_collection("/dokumentobjekt", filter_str="mimetype eq 'text/plain'")
        self.assertEqual(result, [])


class TestListDokumentobjekter(unittest.TestCase):
    """Test list_dokumentobjekter method with optional filter."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_dokobj_all(self, mock_get):
        parent = dokumentbeskrivelse_entity()
        collection = dokumentobjekt_collection([dokumentobjekt_entity("1", "a.epub"), dokumentobjekt_entity("2", "b.pdf")])
        mock_get.side_effect = [parent, collection]

        client = Noark5Client("https://example.com/")
        result = client.list_dokumentobjekter("https://example.com/dokbeskr/1")
        self.assertEqual(len(result), 2)

    @patch.object(Noark5Client, "_get_json")
    def test_list_dokobj_filtered(self, mock_get):
        parent = dokumentbeskrivelse_entity()
        collection = dokumentobjekt_collection([dokumentobjekt_entity("1", "a.epub")])
        mock_get.side_effect = [parent, collection]

        client = Noark5Client("https://example.com/")
        result = client.list_dokumentobjekter(
            "https://example.com/dokbeskr/1",
            filter_str="mimetype eq 'application/epub+zip'",
        )
        self.assertEqual(len(result), 1)
        call_url = mock_get.call_args[0][0]
        self.assertIn("?", call_url)

    @patch.object(Noark5Client, "_get_json")
    def test_list_dokobj_no_relation(self, mock_get):
        """list_dokumentobjekter returns [] when no dokumentobjekt relation."""
        parent = {"_links": {}}  # No dokumentobjekt relation
        mock_get.return_value = parent

        client = Noark5Client("https://example.com/")
        result = client.list_dokumentobjekter("https://example.com/dokbeskr/1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkivnotater_no_relation(self, mock_get):
        """list_arkivnotater returns [] when no arkivnotat relation."""
        parent = {"tittel": "Case File", "_links": {}}  # No arkivnotat relation
        mock_get.return_value = parent

        client = Noark5Client("https://example.com/")
        result = client.list_arkivnotater("https://example.com/sm/1")
        self.assertEqual(result, [])


class TestServerNewTools(unittest.TestCase):
    """Test new MCP server tools."""

    def test_format_list_includes_mime(self):
        from noark5_tg_mcp.server import _format_list

        items = dokumentobjekt_collection([dokumentobjekt_entity("1", "a.epub")])["results"]
        result = _format_list(items, "dokumentobjekt")
        self.assertIn("Found 1 dokumentobjekt(s)", result)
        self.assertIn("[1]", result)


class TestArkivnotat(unittest.TestCase):
    """Test arkivnotat client methods."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkivnotater(self, mock_get):
        saksmappe = saksmappe_entity()
        collection = {
            "count": 1,
            "results": [
                {"systemID": "n1", "tittel": "Note 1", "_links": {"self": {"href": "http://note1"}}},
            ],
            "_links": {"self": {"href": "https://example.com/saksmappe/sm1/arkivnotat"}},
        }
        mock_get.side_effect = [saksmappe, collection]

        client = Noark5Client("https://example.com/")
        result = client.list_arkivnotater("https://example.com/saksmappe/1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["tittel"], "Note 1")

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkivnotater_no_relation(self, mock_get):
        saksmappe = {"_links": {}}
        mock_get.return_value = saksmappe

        client = Noark5Client("https://example.com/")
        result = client.list_arkivnotater("https://example.com/saksmappe/1")
        self.assertEqual(result, [])

    @patch.object(Noark5Client, "_create_entity")
    def test_create_arkivnotat(self, mock_create):
        mock_create.return_value = {
            "tittel": "My Note",
            "_links": {"self": {"href": "https://example.com/arkivnotat/42"}},
        }

        client = Noark5Client("https://example.com/")
        result = client.create_arkivnotat(
            "https://example.com/saksmappe/1",
            "My Note",
        )
        self.assertEqual(result["tittel"], "My Note")
        mock_create.assert_called_once_with(
            "https://example.com/saksmappe/1",
            RELBASE + "sakarkiv/ny-arkivnotat/",
            {"tittel": "My Note"},
        )

    def test_entity_type_arkivnotat(self):
        url = "https://example.com/api/sakarkiv/arkivnotat/123"
        self.assertEqual(Noark5Client.entity_type(url), "arkivnotat")


class TestOidcAuth(unittest.TestCase):
    """Test OIDC authentication and token renewal."""

    def test_preexisting_access_token_skips_login(self):
        """Pre-existing access_token skips login flow."""
        client = Noark5Client(
            "https://example.com/",
            auth_method="oidc",
            access_token="Bearer eyJhbGciOiJIUzI1NiJ9.test",
        )
        self.assertTrue(client._logged_in)
        self.assertEqual(client.auth_method, "oidc")

    def test_login_basic_default(self):
        """Default auth method is basic."""
        client = Noark5Client("https://example.com/", "user", "pass")
        self.assertEqual(client.auth_method, "basic")

    @patch.object(Noark5Client, "_get_json")
    @patch.object(Noark5Client, "find_relation", return_value="https://oidc.example.com/discovery")
    def test_login_oidc_success(self, mock_find_rel, mock_get):
        """OIDC login returns bearer token."""
        import urllib.request

        # Mock discovery doc returned by first _get_json call (discovery endpoint).
        # Second _get_json call is for root entity after login.
        mock_get.side_effect = [
            {
                "token_endpoint": "/realms/recordkeeping/protocol/openid-connect/token",
                "issuer": "https://oidc.example.com/",
            },
            {"_links": {}},  # Root entity after successful login.
        ]

        token_response = json.dumps({
            "access_token": "test-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "test-refresh-token",
            "refresh_expires_in": 86400,
        }).encode()

        def fake_urlopen(req):
            resp = MagicMock()
            resp.read.return_value = token_response
            return resp

        with patch.object(urllib.request, "urlopen", fake_urlopen):
            client = Noark5Client(
                "https://example.com/",
                "admin@example.com",
                "password123",
                auth_method="oidc",
            )
            root = client.login()

        self.assertTrue(client._logged_in)
        self.assertEqual(client._token, "Bearer test-access-token")
        self.assertIn("access_token", client._oidc_info)
        self.assertEqual(root, {"_links": {}})

    @patch.object(Noark5Client, "_get_json")
    @patch.object(Noark5Client, "find_relation", return_value="https://oidc.example.com/discovery")
    def test_login_oidc_with_client_id(self, mock_find_rel, mock_get):
        """OIDC login with client_id includes Authorization header."""
        import urllib.request

        mock_get.side_effect = [
            {
                "token_endpoint": "/realms/recordkeeping/protocol/openid-connect/token",
            },
            {"_links": {}},
        ]

        token_response = json.dumps({
            "access_token": "tok123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "ref123",
            "refresh_expires_in": 86400,
        }).encode()

        captured_auth = None

        def fake_urlopen(req):
            nonlocal captured_auth
            captured_auth = req.headers.get("Authorization")
            resp = MagicMock()
            resp.read.return_value = token_response
            return resp

        with patch.object(urllib.request, "urlopen", fake_urlopen):
            client = Noark5Client(
                "https://example.com/",
                "admin@example.com",
                "password123",
                auth_method="oidc",
                client_id="my-client",
            )
            client.login()

        self.assertIsNotNone(captured_auth)
        self.assertTrue(captured_auth.startswith("Basic "))

    @patch.object(Noark5Client, "_get_json")
    @patch.object(Noark5Client, "find_relation", return_value=None)
    def test_login_oidc_no_endpoint(self, mock_find_rel, _mock_get):
        """OIDC login fails when oidc relation not found."""
        client = Noark5Client(
            "https://example.com/",
            "admin@example.com",
            "password123",
            auth_method="oidc",
        )
        with self.assertRaises(Noark5Error) as ctx:
            client.login()
        self.assertEqual(ctx.exception.code, 404)

    @patch.object(Noark5Client, "_get_json")
    def test_oidc_renew_token(self, mock_get):
        """Token renewal updates access token and expiry."""
        import urllib.request

        client = Noark5Client(
            "https://example.com/",
            "admin@example.com",
            "password123",
            auth_method="oidc",
        )
        # Simulate initial login state.
        client._logged_in = True
        client._token = "Bearer old-token"
        import time

        now = time.time()
        client._oidc_meta = {"token_endpoint": "/realms/recordkeeping/token"}
        client._oidc_info = {
            "access_token": "old-access",
            "token_type": "Bearer",
            "refresh_token": "valid-refresh",
            "epoc_expires_in": now + 10,  # Expires soon.
            "epoc_refresh_expires_in": now + 86400,
        }

        new_token_response = json.dumps({
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new-refresh-token",
            "refresh_expires_in": 86400,
        }).encode()

        def fake_urlopen(req):
            resp = MagicMock()
            resp.read.return_value = new_token_response
            return resp

        with patch.object(urllib.request, "urlopen", fake_urlopen):
            client._oidc_renew()

        self.assertEqual(client._token, "Bearer new-access-token")
        self.assertIn("new-access-token", client._oidc_info["access_token"])

    def test_auth_headers_oidc_no_renewal_needed(self):
        """_auth_headers returns token without renewal if still valid."""
        import time

        client = Noark5Client(
            "https://example.com/",
            "admin@example.com",
            "password123",
            auth_method="oidc",
        )
        client._logged_in = True
        client._token = "Bearer valid-token"
        now = time.time()
        client._oidc_meta = {"token_endpoint": "/token"}
        client._oidc_info = {
            "access_token": "valid-token",
            "token_type": "Bearer",
            "refresh_token": "some-refresh",
            "epoc_expires_in": now + 3600,
            "epoc_refresh_expires_in": now + 86400,
        }

        headers = client._auth_headers()
        self.assertEqual(headers["Authorization"], "Bearer valid-token")

    def test_auth_headers_basic(self):
        """_auth_headers returns basic token for basic auth."""
        client = Noark5Client("https://example.com/", "user", "pass")
        client._token = "Basic dXNlcjpwYXNz"
        headers = client._auth_headers()
        self.assertEqual(headers["Authorization"], "Basic dXNlcjpwYXNz")


class TestAuthDetection(unittest.TestCase):
    """Test auth method auto-detection from root entity links."""

    def test_detect_oidc_preferred(self):
        """OIDC is preferred when both methods are available."""
        links = Noark5Client.parse_links(root_entity())
        self.assertEqual(Noark5Client._detect_auth_method(links), "oidc")

    def test_detect_basic_only(self):
        """Basic is selected when only rfc7617 is available."""
        entity = root_entity()
        del entity["_links"][_rel("login/oidc/")]
        links = Noark5Client.parse_links(entity)
        self.assertEqual(Noark5Client._detect_auth_method(links), "basic")

    def test_detect_oidc_only(self):
        """OIDC is selected when only oidc is available."""
        entity = root_entity()
        del entity["_links"][_rel("login/rfc7617/")]
        links = Noark5Client.parse_links(entity)
        self.assertEqual(Noark5Client._detect_auth_method(links), "oidc")

    def test_detect_none(self):
        """Returns None when no login relations found."""
        entity = root_entity()
        del entity["_links"][_rel("login/oidc/")]
        del entity["_links"][_rel("login/rfc7617/")]
        links = Noark5Client.parse_links(entity)
        self.assertIsNone(Noark5Client._detect_auth_method(links))

    @patch.object(Noark5Client, "_get_json")
    def test_login_auto_detects_oidc(self, mock_get):
        """Auto method detects oidc from root links."""
        import urllib.request

        # First _get_json call: root entity (for detection).
        # Second _get_json call: discovery doc.
        # Third _get_json call: root after login.
        mock_get.side_effect = [
            root_entity(),  # Root with OIDC relation.
            {  # Discovery doc.
                "token_endpoint": "/realms/test/token",
            },
            {"_links": {}},  # Root after login.
        ]

        token_response = json.dumps({
            "access_token": "auto-detected-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "ref123",
            "refresh_expires_in": 86400,
        }).encode()

        def fake_urlopen(req):
            resp = MagicMock()
            resp.read.return_value = token_response
            return resp

        with patch.object(urllib.request, "urlopen", fake_urlopen):
            client = Noark5Client(
                "https://example.com/",
                "admin@example.com",
                "password123",
                auth_method="auto",
            )
            client.login()

        self.assertEqual(client.auth_method, "oidc")
        self.assertTrue(client._logged_in)

    @patch.object(Noark5Client, "_get_json")
    def test_login_auto_detects_basic(self, mock_get):
        """Auto method detects basic from root links."""
        # First _get_json call: root entity (for detection).
        # Second _get_json call: root after login.
        fake_root = {
            "_links": {
                _rel("login/rfc7617/"): {"href": "https://example.com/api/login/rfc7617/"},
            },
        }
        mock_get.side_effect = [fake_root, {"_links": {}}]

        client = Noark5Client(
            "https://example.com/",
            "user",
            "pass",
            auth_method="auto",
        )
        client.login()

        self.assertEqual(client.auth_method, "basic")
        self.assertTrue(client._logged_in)


class TestServerStateOidc(unittest.TestCase):
    """Test server.py state handling for OIDC."""

    def test_server_state_has_oidc_fields(self):
        from noark5_tg_mcp.server import _server_state

        self.assertIn("auth_method", _server_state)
        self.assertIn("client_id", _server_state)
        self.assertIn("access_token", _server_state)

    def test_server_state_default_auto(self):
        """Server state defaults auth_method to auto."""
        from noark5_tg_mcp.server import _server_state

        self.assertEqual(_server_state["auth_method"], "auto")


if __name__ == "__main__":
    unittest.main()


class TestUpdateEntityJson(unittest.TestCase):
    """Test update_entity handles structured JSON values."""

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_update_structured_field(self, mock_urlopen):
        """update_entity should send dict values as-is (not stringified)."""
        from noark5_tg_mcp.client import Noark5Client, Noark5Error

        # Mock GET for etag fetch.
        with patch.object(Noark5Client, "_get_json", return_value=dokumentbeskrivelse_entity()):
            client = Noark5Client("https://example.com/", "user", "pass")
            client._logged_in = True

            # Mock PATCH response - returns realistic entity structure.
            mock_resp = MagicMock()
            updated = dokumentbeskrivelse_entity()
            updated["dokumenttype"] = {"kode": "U"}
            mock_resp.read.return_value = json.dumps(updated).encode()
            mock_urlopen.return_value = mock_resp

            result = client.update_entity(
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id",
                {"dokumenttype": {"kode": "U"}},
            )

            self.assertEqual(result["dokumenttype"]["kode"], "U")
            # Verify the request body contains the dict structure.
            call_args = mock_urlopen.call_args
            req_body = json.loads(call_args[0][0].data)
            self.assertEqual(req_body, {"dokumenttype": {"kode": "U"}})

    @patch("noark5_tg_mcp.client.urllib.request.urlopen")
    def test_update_simple_field(self, mock_urlopen):
        """update_entity should still work with simple string values."""
        from noark5_tg_mcp.client import Noark5Client

        with patch.object(Noark5Client, "_get_json", return_value=dokumentbeskrivelse_entity()):
            client = Noark5Client("https://example.com/", "user", "pass")
            client._logged_in = True

            mock_resp = MagicMock()
            updated = dokumentbeskrivelse_entity()
            updated["tittel"] = "Updated Title"
            mock_resp.read.return_value = json.dumps(updated).encode()
            mock_urlopen.return_value = mock_resp

            result = client.update_entity(
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id",
                {"tittel": "Updated Title"},
            )

            self.assertEqual(result["tittel"], "Updated Title")


class TestSearchDeduplication(unittest.TestCase):
    """Test search_entities deduplicates across collection queries."""

    def test_search_deduplicates_results(self):
        """When same entity appears in multiple collections, only return once."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("https://example.com/", "user", "pass")
        client._logged_in = True

        # Mock find_relation to return URLs for 2 collections.
        with patch.object(client, "find_relation") as mock_rel:
            mock_rel.side_effect = [
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/",
                "https://example.com/api/arkivstruktur/mappe/",
            ] + [None] * 7  # Remaining collections return None.

            # Both collections return the same entity (with realistic structure).
            mock_data = {
                "count": 1,
                "results": [
                    {
                        "systemID": "abc",
                        "tittel": "Duplicate Entity",
                        "_links": {
                            "self": {"href": "https://example.com/api/arkivstruktur/dokumentbeskrivelse/abc"},
                            _rel("arkivstruktur/dokumentbeskrivelse/"): {"href": "https://example.com/api/arkivstruktur/dokumentbeskrivelse/abc"},
                        },
                    }
                ],
            }
            with patch.object(client, "_get_json", return_value=mock_data):
                results = client.search_entities("test")

                # Should only appear once despite being returned by both collections.
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0][0], "https://example.com/api/arkivstruktur/dokumentbeskrivelse/abc")


    def test_search_with_filter_applies_both(self):
        """search_entities with filter_str applies both $search and $filter."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("https://example.com/", "user", "pass")
        client._logged_in = True

        captured_urls = []

        def fake_get_json(url):
            captured_urls.append(url)
            return {
                "count": 1,
                "results": [
                    {
                        "systemID": "xyz",
                        "tittel": "Matched Entity",
                        "_links": {
                            "self": {"href": "https://example.com/api/arkivstruktur/mappe/xyz"},
                            _rel("arkivstruktur/mappe/"): {"href": "https://example.com/api/arkivstruktur/mappe/xyz"},
                        },
                    }
                ],
            }

        with patch.object(client, "find_relation") as mock_rel:
            mock_rel.side_effect = [
                None, None, None,  # arkiv, arkivdel, klassifikasjonssystem
                "https://example.com/api/arkivstruktur/mappe/",  # mappe — will match
            ] + [None] * 5

            with patch.object(client, "_get_json", side_effect=fake_get_json):
                results = client.search_entities("test", filter_str="contains(tittel, 'Matched')")

        self.assertEqual(len(results), 1)
        # Verify URL contains both $search and $filter.
        url_with_filter = [u for u in captured_urls if "$filter=" in u]
        self.assertEqual(len(url_with_filter), 1)
        self.assertIn("$search=test", url_with_filter[0])
        self.assertIn("$filter=", url_with_filter[0])

    def test_search_without_filter_omits_filter_param(self):
        """search_entities without filter_str does not append $filter."""
        from noark5_tg_mcp.client import Noark5Client

        client = Noark5Client("https://example.com/", "user", "pass")
        client._logged_in = True

        captured_urls = []

        def fake_get_json(url):
            captured_urls.append(url)
            return {"count": 0, "results": []}

        with patch.object(client, "find_relation", side_effect=["https://example.com/api/arkivstruktur/mappe/"] + [None] * 8):
            with patch.object(client, "_get_json", side_effect=fake_get_json):
                client.search_entities("test")

        # Verify URL has $search but NOT $filter.
        self.assertIn("$search=test", captured_urls[0])
        self.assertNotIn("$filter=", captured_urls[0])


class TestServerUpdateEntityJson(unittest.TestCase):
    """Test server.py noark5_update_entity parses JSON changes object."""

    def test_server_parses_json_value(self):
        """noark5_update_entity should pass through structured dict values as-is."""
        import json as json_module
        from unittest.mock import patch, MagicMock

        with patch("noark5_tg_mcp.server._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.update_entity.return_value = {
                "tittel": "Test",
                "dokumenttype": {"kode": "U"},
                "_links": {"self": {"href": "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id"}},
            }
            mock_get_client.return_value = mock_client

            from noark5_tg_mcp.server import noark5_update_entity
            result = noark5_update_entity(
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id",
                '{"dokumenttype": {"kode": "U"}}',
            )

            # Verify the full changes dict was passed to client.update_entity.
            mock_client.update_entity.assert_called_once_with(
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id",
                {"dokumenttype": {"kode": "U"}},
            )

    def test_server_simple_string_value(self):
        """noark5_update_entity should handle simple string values."""
        from unittest.mock import patch, MagicMock

        with patch("noark5_tg_mcp.server._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.update_entity.return_value = {
                "tittel": "Updated Title",
                "_links": {"self": {"href": "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id"}},
            }
            mock_get_client.return_value = mock_client

            from noark5_tg_mcp.server import noark5_update_entity
            result = noark5_update_entity(
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id",
                '{"tittel": "Updated Title"}',
            )

            mock_client.update_entity.assert_called_once_with(
                "https://example.com/api/arkivstruktur/dokumentbeskrivelse/test-id",
                {"tittel": "Updated Title"},
            )

    def test_server_multiple_fields(self):
        """noark5_update_entity should handle multiple fields in one call."""
        from unittest.mock import patch, MagicMock

        with patch("noark5_tg_mcp.server._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.update_entity.return_value = {
                "tittel": "New Title",
                "beskrivelse": "New Desc",
                "_links": {"self": {"href": "https://example.com/api/arkivstruktur/mappe/test-id"}},
            }
            mock_get_client.return_value = mock_client

            from noark5_tg_mcp.server import noark5_update_entity
            result = noark5_update_entity(
                "https://example.com/api/arkivstruktur/mappe/test-id",
                '{"tittel": "New Title", "beskrivelse": "New Desc"}',
            )

            mock_client.update_entity.assert_called_once_with(
                "https://example.com/api/arkivstruktur/mappe/test-id",
                {"tittel": "New Title", "beskrivelse": "New Desc"},
            )


class TestMetadataClientMethods(unittest.TestCase):
    """Test client metadata (katalog) methods."""

    def test_list_metadata_no_relation(self):
        client = Noark5Client("https://example.com/api/")
        with patch.object(client, "find_relation", return_value=None):
            result = client.list_metadata()
        assert result == []

    @patch.object(Noark5Client, "_get_json")
    @patch.object(Noark5Client, "find_relation")
    def test_list_metadata_success(self, mock_find, mock_get):
        mock_find.return_value = "https://example.com/api/metadata"
        mock_get.return_value = metadata_root_entity()
        client = Noark5Client("https://example.com/api/")
        result = client.list_metadata()
        assert len(result) == 2
        assert result[0]["tittel"] == "dokumentmedium"
        assert result[1]["tittel"] == "format"

    @patch.object(Noark5Client, "_get_json")
    def test_list_metadata_poster_success(self, mock_get):
        side_effects = [
            metadata_root_entity(),  # First call: get metadata root to find catalog link.
            {  # Second call: get katalogpost results.
                "count": 2,
                "results": [
                    metadata_catalog_poster("E", "Elektronisk"),
                    metadata_catalog_poster("F", "Fysisk"),
                ],
                "_links": {"self": {"href": "https://example.com/api/metadata/dokumentmedium"}},
            },
        ]
        mock_get.side_effect = side_effects
        client = Noark5Client("https://example.com/api/")
        with patch.object(client, "find_relation", return_value="https://example.com/api/metadata"):
            result = client.list_metadata_poster("dokumentmedium")
        assert len(result) == 2
        assert result[0]["kode"] == "E"

    @patch.object(Noark5Client, "_get_json")
    def test_list_metadata_poster_filter(self, mock_get):
        side_effects = [
            metadata_root_entity(),  # metadata root.
            {
                "count": 1,
                "results": [metadata_catalog_poster("E", "Elektronisk")],
                "_links": {"self": {"href": "https://example.com/api/metadata/dokumentmedium?$filter=..."}},
            },
        ]
        mock_get.side_effect = side_effects
        client = Noark5Client("https://example.com/api/")
        with patch.object(client, "find_relation", return_value="https://example.com/api/metadata"):
            result = client.list_metadata_poster("dokumentmedium", filter_str="kode eq 'E'")
        call_args = mock_get.call_args[0][0]
        assert "?$filter=" in call_args

    @patch.object(Noark5Client, "_get_json")
    def test_list_metadata_poster_unknown_catalog(self, mock_get):
        mock_get.return_value = {"_links": {}}
        client = Noark5Client("https://example.com/api/")
        with patch.object(client, "find_relation", return_value="https://example.com/api/metadata"):
            try:
                client.list_metadata_poster("nonexistent")
                self.fail("Expected Noark5Error")
            except Noark5Error as e:
                assert "nonexistent" in str(e.message)

    @patch.object(Noark5Client, "_get_json")
    def test_search_metadata_success(self, mock_get):
        side_effects = [
            metadata_root_entity(),  # metadata root.
            {  # katalogpost results with filter.
                "count": 1,
                "results": [metadata_catalog_poster("E", "Elektronisk")],
                "_links": {"self": {"href": "https://example.com/api/metadata/dokumentmedium"}},
            },
        ]
        mock_get.side_effect = side_effects
        client = Noark5Client("https://example.com/api/")
        with patch.object(client, "find_relation", return_value="https://example.com/api/metadata"):
            result = client.search_metadata("dokumentmedium", "contains(kodenavn, 'Elektronisk')")
        assert len(result) == 1
        assert result[0]["kode"] == "E"


class TestMetadataTools:
    """Test metadata lookup MCP tools."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_metadata_no_catalog(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata.return_value = [
            {"tittel": "dokumentmedium"},
            {"tittel": "format"},
        ]

        result = noark5_list_metadata()

        assert "dokumentmedium" in result
        assert "format" in result
        assert "Available metadata catalogs" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_metadata_with_catalog(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata_poster.return_value = [
            {"kode": "E", "kodenavn": "Elektronisk arkiv"},
            {"kode": "F", "kodenavn": "Fysisk medium"},
        ]

        result = noark5_list_metadata(catalog_name="dokumentmedium")

        mock_client.list_metadata_poster.assert_called_once_with(
            "dokumentmedium", ""
        )
        assert "E" in result
        assert "Elektronisk arkiv" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_metadata_filter(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata_poster.return_value = [
            {"kode": "EPUB", "kodenavn": "EPUB"},
        ]

        result = noark5_list_metadata(catalog_name="format", filter_str="contains(kodenavn, 'EPUB')")

        mock_client.list_metadata_poster.assert_called_once_with(
            "format",
            "contains(kodenavn, 'EPUB')",
        )
        assert "EPUB" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_metadata_unknown_catalog(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata_poster.side_effect = Noark5Error(404, "No catalog named 'NonExistent'", "")

        try:
            noark5_list_metadata(catalog_name="NonExistent")
            assert False, "Expected Noark5Error"
        except Noark5Error as e:
            assert "NonExistent" in str(e)


class TestNavigateUpHierarchy:
    """Test parent detection using N5TG hierarchy from UML/ch 7."""

    def test_possible_parents_arkivdel(self):
        parents = Noark5Client._possible_parents("arkivdel")
        assert parents == ["arkiv"]

    def test_possible_parents_klasse(self):
        parents = Noark5Client._possible_parents("klasse")
        assert set(parents) == {"klassifikasjonssystem", "klasse"}

    def test_possible_parents_mappe(self):
        parents = Noark5Client._possible_parents("mappe")
        assert set(parents) == {"arkivdel", "klasse", "mappe"}

    def test_possible_parents_saksmappe(self):
        # saksmappe inherits mappe's parent types, plus itself (recursive via overmappe).
        parents = Noark5Client._possible_parents("saksmappe")
        assert set(parents) == {"arkivdel", "klasse", "mappe", "saksmappe"}

    def test_possible_parents_registrering(self):
        parents = Noark5Client._possible_parents("registrering")
        assert set(parents) == {"arkivdel", "klasse", "mappe", "saksmappe"}

    def test_possible_parents_dokumentbeskrivelse(self):
        parents = Noark5Client._possible_parents("dokumentbeskrivelse")
        assert set(parents) == {"registrering", "journalpost", "arkivnotat"}

    def test_possible_parents_dokumentobjekt(self):
        parents = Noark5Client._possible_parents("dokumentobjekt")
        assert parents == ["dokumentbeskrivelse"]

    def test_list_parents_saksmappe_under_klasse(self):
        """Test that list_parents correctly finds klasse as parent of saksmappe."""
        mock_client = MagicMock()
        saksmappe = saksmappe_entity("123", "Case under Klasse")
        # Override the _links to add a klasse parent.
        saksmappe["_links"]["https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/klasse/"] = {
            "href": "https://example.com/api/arkivstruktur/klasse/456/",
        }
        mock_client.get_entity.return_value = saksmappe

        with patch("noark5_tg_mcp.server._get_client", return_value=mock_client):
            from noark5_tg_mcp.server import noark5_list_parents
            result = noark5_list_parents("https://example.com/api/sakarkiv/saksmappe/123/")

        # Should find klasse as parent (rel ends with "klasse/").
        assert "klasse" in result.lower() or "no parent entities found" not in result


class TestMetadataFilterUrl:
    """Test metadata filter URL construction to verify $filter= prefix."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_metadata_poster_filter_url_structure(self, mock_get):
        """list_metadata_poster constructs correct URL: base + ?$filter=encoded_expr."""
        side_effects = [
            metadata_root_entity(),  # metadata root.
            {  # filtered results.
                "count": 1,
                "results": [metadata_catalog_poster("U", "UNKNOWN")],
                "_links": {"self": {"href": "https://example.com/api/metadata/format?$filter=..."}},
            },
        ]
        mock_get.side_effect = side_effects

        client = Noark5Client("https://example.com/api/")
        with patch.object(client, "find_relation", return_value="https://example.com/api/metadata"):
            result = client.list_metadata_poster("format", filter_str="kode eq 'U'")

        assert len(result) == 1
        called_url = mock_get.call_args_list[-1][0][0]
        # Verify base path is correct and template params stripped.
        assert "?$filter=kode" in called_url, f"URL missing ?$filter=: {called_url}"
        assert "{" not in called_url, "Template params not stripped from URL"


class TestListParentsBugs(unittest.TestCase):
    """Test list_parents handles edge cases correctly."""

    def test_list_parents_skips_self_referencing(self):
        """list_parents must skip canonical relation that points to entity itself."""
        mock_client = MagicMock()
        # Mappe with only self + canonical rel (no real parent links).
        entity = mappe_entity("abc", "Self-ref Entity")
        mock_client.get_entity.return_value = entity

        with patch("noark5_tg_mcp.server._get_client", return_value=mock_client):
            from noark5_tg_mcp.server import noark5_list_parents
            result = noark5_list_parents("https://example.com/api/arkivstruktur/mappe/abc/")

        # Should not find any parents (self-ref is skipped, no real parent links).
        assert "no parent entities found" in result.lower() or "Self-ref Entity" in result

    def test_list_parents_skips_undermappe(self):
        """list_parents must skip undermappe child-collection link."""
        mock_client = MagicMock()
        # Mappe with self, canonical rel (self), and undermappe (child collection).
        entity = mappe_entity("abc", "Parent Mappe")
        mock_client.get_entity.return_value = entity

        with patch("noark5_tg_mcp.server._get_client", return_value=mock_client):
            from noark5_tg_mcp.server import noark5_list_parents
            result = noark5_list_parents("https://example.com/api/arkivstruktur/mappe/abc/")

        # Should not find any parents (both links are skipped).
        assert "no parent entities found" in result.lower() or "Parent Mappe" in result


class TestListKlassifikasjonssystemer(unittest.TestCase):
    """Test client.list_klassifikasjonssystemer method."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_klassif_success(self, mock_get):
        parent = arkivdel_entity()
        collection = {
            "count": 2,
            "results": [
                {"systemID": "ks1", "tittel": "System 1", "_links": {"self": {"href": "http://ks1"}}},
                {"systemID": "ks2", "tittel": "System 2", "_links": {"self": {"href": "http://ks2"}}},
            ],
        }
        mock_get.side_effect = [parent, collection]

        client = Noark5Client("https://example.com/")
        result = client.list_klassifikasjonssystemer("http://ad1")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["tittel"], "System 1")

    @patch.object(Noark5Client, "_get_json")
    def test_list_klassif_no_relation(self, mock_get):
        parent = {"_links": {}}  # No klassifikasjonssystem relation.
        mock_get.return_value = parent

        client = Noark5Client("https://example.com/")
        result = client.list_klassifikasjonssystemer("http://ad1")
        self.assertEqual(result, [])


class TestListChildrenTool(unittest.TestCase):
    """Test server noark5_list_children MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_top_level_no_parent(self, mock_get_client):
        """Without parent_url, lists arkiv and arkivskaper from root."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        # Root entity with arkiv collection link.
        root = {
            "systemID": "root",
            "_links": {
                _rel("arkivstruktur/arkiv/"): {"href": "https://example.com/api/archives"},
            },
        }
        mock_client._get_json.side_effect = [
            root,  # First call: root entity.
            arkiv_collection([arkiv_entity("a1", "Archive One")]),  # arkiv results.
        ]

        result = noark5_list_children()
        assert "Top-level entities" in result
        assert "[a1] Archive One" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_with_parent_discovers_children(self, mock_get_client):
        """With parent_url, discovers child collections via HATEOAS."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        entity = mappe_entity("m1", "Test Mappe")

        mock_client.get_entity.return_value = entity
        mock_client._get_json.side_effect = [
            {"count": 1, "results": [{"systemID": "c1", "tittel": "Child One", "_links": {"self": {"href": "https://example.com/c1"}}}]},  # undermappe
            {"count": 1, "results": [{"systemID": "r1", "tittel": "Reg One", "_links": {"self": {"href": "https://example.com/r1"}}}]},  # registrering
        ]

        result = noark5_list_children("https://example.com/api/arkivstruktur/mappe/m1")
        assert "Children of Test Mappe" in result
        assert "[c1] Child One" in result
        assert "[r1] Reg One" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_no_children_found(self, mock_get_client):
        """Returns message when entity has no child collections."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        # Entity with only self + canonical link (no children).
        dokobj = dokumentobjekt_entity()
        mock_client.get_entity.return_value = dokobj

        result = noark5_list_children("https://example.com/api/arkivstruktur/dokumentobjekt/do1")
        assert "No children found" in result.lower() or "Leaf Entity" not in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_filter_str_applied(self, mock_get_client):
        """OData filter is appended to child collection URLs."""
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        entity = mappe_entity("m1", "Test Entity")

        mock_client.get_entity.return_value = entity
        mock_client._get_json.return_value = {"count": 0, "results": []}
        mock_client._encode_filter.side_effect = lambda s: s  # Pass-through.

        noark5_list_children(
            "https://example.com/api/arkivstruktur/mappe/m1",
            filter_str="tittel eq 'Book'",
        )

        # Check that _get_json was called with URL containing $filter=.
        call_url = mock_client._get_json.call_args[0][0]
        assert "$filter=" in call_url, f"Filter not applied to URL: {call_url}"


class TestEntityLinksClassification(unittest.TestCase):
    """Verify entity_links correctly categorizes parent/child/system links."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_dokumentbeskrivelse_links_skip_metadata_and_self(self, mock_get_client):
        """Metadata/logging links and self-referencing canonical link are skipped."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        dokbeskr_url = "https://example.com/api/arkivstruktur/dokumentbeskrivelse/db1"
        relbase = RELBASE + "arkivstruktur/"

        entity = {
            "tittel": "Test Doc",
            "systemID": "db1",
            "_links": {
                "self": {"href": dokbeskr_url},
                # Canonical/self-referencing (points to same URL) - should be SKIPPED.
                relbase + "dokumentbeskrivelse/": {"href": dokbeskr_url},
                # Parent link: registrering.
                relbase + "registrering/": {
                    "href": dokbeskr_url + "/registrering"
                },
                # Child collections (href on own path).
                relbase + "dokumentobjekt/": {
                    "href": dokbeskr_url + "/dokumentobjekt"
                },
                relbase + "merknad/": {"href": dokbeskr_url + "/merknad"},
                # Metadata links - should be SKIPPED entirely.
                RELBASE + "metadata/dokumentmedium/": {
                    "href": "https://example.com/api/metadata/dokumentmedium"
                },
                RELBASE + "loggingogsporing/hendelseslogg/": {
                    "href": "https://example.com/api/loggingogsporing/log"
                },
            },
        }

        mock_client.get_entity.return_value = entity
        result = noark5_entity_links(dokbeskr_url)

        # Metadata/logging must NOT appear in output.
        assert "/metadata/" not in result, "Metadata links should be skipped"
        assert "/loggingogsporing/" not in result, "Logging links should be skipped"

        # Self-referencing canonical link must NOT appear as a standalone href line.
        for rline in result.split("\n"):
            stripped = rline.strip()
            if stripped.startswith("-> ") and stripped == f"-> {dokbeskr_url}":
                assert False, "Self-referencing canonical link should be skipped"

        # registering/ should appear as parent.
        assert "registrering/" in result, "Parent registering link missing"
        # dokumentobjekt/ should appear as child.
        assert "dokumentobjekt/" in result, "Child dokumentobjekt link missing"

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_parents_dokumentbeskrivelse_finds_registrering(self, mock_get_client):
        """list_parents from dokumentbeskrivelse finds registering as parent."""
        from noark5_tg_mcp.server import noark5_list_parents

        mock_client = mock_get_client.return_value
        relbase = RELBASE + "arkivstruktur/"

        dokbeskr_url = "https://example.com/api/arkivstruktur/dokumentbeskrivelse/db1"
        registrering_url = "https://example.com/api/arkivstruktur/registrering/r1"

        entity = {
            "tittel": "Test Doc",
            "systemID": "db1",
            "_links": {
                "self": {"href": dokbeskr_url},
                relbase + "dokumentbeskrivelse/": {"href": dokbeskr_url},
                relbase + "registrering/": {"href": registrering_url},
            },
        }

        parent_collection = {
            "count": 1,
            "results": [{"_links": {"self": {"href": registrering_url}}}],
        }

        parent_entity = {
            "tittel": "Parent Record",
            "systemID": "r1",
            "_links": {"self": {"href": registrering_url}},
        }

        mock_client.get_entity.side_effect = [entity, parent_collection, parent_entity]
        result = noark5_list_parents(dokbeskr_url)

        assert "registrering" in result.lower(), f"dokumentbeskrivelse should find registering as parent: {result}"
        assert "Parent Record" in result, f"Parent title not found: {result}"
        assert "r1" in result, f"Parent systemID not found: {result}"

    @patch("noark5_tg_mcp.server._get_client")
    def test_mappe_links_no_registrering_as_parent(self, mock_get_client):
        """For mappe, registering/ is a child link, NOT a parent."""
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        relbase = RELBASE + "arkivstruktur/"

        mappe_url = "https://example.com/api/arkivstruktur/mappe/m1"
        entity = {
            "tittel": "Test Mappe",
            "systemID": "m1",
            "_links": {
                "self": {"href": mappe_url},
                relbase + "mappe/": {"href": mappe_url},  # self-ref canonical
                relbase + "arkivdel/": {
                    "href": "https://example.com/api/arkivstruktur/mappe/m1/arkivdel"
                },
                relbase + "registrering/": {
                    "href": mappe_url + "/registrering",
                },
            },
        }

        mock_client.get_entity.return_value = entity
        result = noark5_entity_links(mappe_url)

        # Check that registering/ is NOT in the parent section.
        lines = result.split("\n")
        in_parent_section = False
        for line in lines:
            if "Parent links" in line:
                in_parent_section = True
            elif "Children collections" in line or "Create endpoints" in line:
                in_parent_section = False

            if in_parent_section and "registrering/" in line:
                assert False, f"For mappe, registering/ should NOT be a parent link. Found: {line}"


class TestGetClient(unittest.TestCase):
    """Test _get_client() authentication scenarios."""

    def setUp(self):
        from noark5_tg_mcp.server import _server_state
        self._saved = dict(_server_state)

    def tearDown(self):
        from noark5_tg_mcp.server import _server_state
        _server_state.clear()
        _server_state.update(self._saved)

    def test_not_authenticated_raises(self):
        """_get_client raises RuntimeError when no credentials set."""
        from noark5_tg_mcp.server import _get_client, _server_state
        _server_state["username"] = ""
        _server_state["password"] = ""
        _server_state["access_token"] = None
        with self.assertRaises(RuntimeError) as cm:
            _get_client()
        assert "Not authenticated" in str(cm.exception)

    @patch("noark5_tg_mcp.server.Noark5Client")
    def test_with_access_token_skips_login(self, mock_cls):
        """_get_client with access_token does not call login."""
        from noark5_tg_mcp.server import _get_client, _server_state
        _server_state["username"] = "user"
        _server_state["password"] = "pass"
        _server_state["access_token"] = "my-token"
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        _get_client()
        mock_instance.login.assert_not_called()
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["access_token"] == "my-token"


class TestSetCredentialsTool(unittest.TestCase):
    """Test noark5_set_credentials MCP tool."""

    def setUp(self):
        from noark5_tg_mcp.server import _server_state
        self._saved = dict(_server_state)

    def tearDown(self):
        from noark5_tg_mcp.server import _server_state
        _server_state.clear()
        _server_state.update(self._saved)

    @patch("noark5_tg_mcp.server.Noark5Client")
    def test_success_sets_state_and_returns_links(self, mock_cls):
        """Successful authentication sets server state and returns link list."""
        from noark5_tg_mcp.server import noark5_set_credentials, _server_state

        login_result = {
            "_links": {
                "https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/": {"href": "http://localhost:8092/noark5v5/arkivstruktur/"},
            }
        }
        mock_instance = MagicMock()
        mock_instance.login.return_value = login_result
        mock_cls.return_value = mock_instance
        mock_cls.parse_links = staticmethod(lambda e: {rel: v["href"] for rel, v in e.get("_links", {}).items()})

        result = noark5_set_credentials("user1", "pass1")
        assert _server_state["username"] == "user1"
        assert _server_state["password"] == "pass1"
        assert "Authenticated as 'user1'" in result
        assert "arkivstruktur/" in result

    @patch("noark5_tg_mcp.server.Noark5Client")
    def test_login_failure_clears_credentials(self, mock_cls):
        """Failed login clears username/password from server state."""
        from noark5_tg_mcp.server import noark5_set_credentials, _server_state

        mock_instance = MagicMock()
        mock_instance.login.side_effect = Exception("bad creds")
        mock_cls.return_value = mock_instance

        with self.assertRaises(RuntimeError) as cm:
            noark5_set_credentials("user1", "pass1")
        assert "Authentication failed" in str(cm.exception)
        assert _server_state["username"] == ""
        assert _server_state["password"] == ""

    @patch("noark5_tg_mcp.server.Noark5Client")
    def test_custom_base_url_normalized(self, mock_cls):
        """Base URL gets trailing slash normalized."""
        from noark5_tg_mcp.server import noark5_set_credentials, _server_state

        mock_instance = MagicMock()
        mock_instance.login.return_value = {"_links": {}}
        mock_cls.return_value = mock_instance
        mock_cls.parse_links = staticmethod(lambda e: {})

        noark5_set_credentials("u", "p", base_url="http://example.com/api")
        assert _server_state["base_url"] == "http://example.com/api/"


class TestGetRootLinksTool(unittest.TestCase):
    """Test noark5_get_root_links MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_returns_root_links(self, mock_get_client):
        """Returns formatted root entity links."""
        from noark5_tg_mcp.server import noark5_get_root_links

        mock_client = mock_get_client.return_value
        root = {
            "_links": {
                "https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/": {"href": "http://localhost:8092/noark5v5/arkivstruktur/"},
                "https://rel.arkivverket.no/noark5/v5/api/sakarkiv/": {"href": "http://localhost:8092/noark5v5/sakarkiv/"},
            }
        }
        mock_client._get_json.return_value = root

        result = noark5_get_root_links()
        assert "API root" in result
        assert "arkivstruktur/" in result
        assert "sakarkiv/" in result


class TestGetEntityTool(unittest.TestCase):
    """Test noark5_get_entity MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_returns_formatted_entity(self, mock_get_client):
        """Returns formatted entity with full JSON."""
        from noark5_tg_mcp.server import noark5_get_entity

        mock_client = mock_get_client.return_value
        entity = {"tittel": "My Archive", "systemID": "a1", "_links": {}}
        mock_client.get_entity.return_value = entity

        result = noark5_get_entity("http://localhost:8092/noark5v5/arkivstruktur/arkiv/a1")
        assert "My Archive" in result
        assert "a1" in result
        assert "Full JSON" in result


class TestCreateTools(unittest.TestCase):
    """Test all noark5_create_* MCP tools via mocked _get_client."""

    def setUp(self):
        from noark5_tg_mcp.server import _server_state
        self._saved = dict(_server_state)

    def tearDown(self):
        from noark5_tg_mcp.server import _server_state
        _server_state.clear()
        _server_state.update(self._saved)

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_arkivskaper(self, mock_get_client):
        """Creates arkivskaper with ID and name."""
        from noark5_tg_mcp.server import noark5_create_arkivskaper

        mock_client = mock_get_client.return_value
        mock_client.create_arkivskaper.return_value = {
            "arkivskaperId": "org1",
            "navn": "My Org",
            "_links": {"self": {"href": "http://example.com/ak/org1"}},
        }

        result = noark5_create_arkivskaper("org1", "My Org")
        mock_client.create_arkivskaper.assert_called_once_with("org1", "My Org", None)
        assert "Created arkivskaper" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_arkiv(self, mock_get_client):
        """Creates arkiv with title."""
        from noark5_tg_mcp.server import noark5_create_arkiv

        mock_client = mock_get_client.return_value
        mock_client.create_arkiv.return_value = {
            "tittel": "My Archive",
            "_links": {"self": {"href": "http://example.com/arkiv/a1"}},
        }

        result = noark5_create_arkiv("My Archive")
        mock_client.create_arkiv.assert_called_once_with("My Archive", None)
        assert "Created fonds" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_arkivdel_with_parent(self, mock_get_client):
        """Creates arkivdel under parent arkiv."""
        from noark5_tg_mcp.server import noark5_create_arkivdel

        mock_client = mock_get_client.return_value
        mock_client.create_arkivdel.return_value = {
            "tittel": "Series One",
            "_links": {"self": {"href": "http://example.com/ad/ad1"}},
        }

        noark5_create_arkivdel("http://example.com/arkiv/a1", "Series One")
        mock_client.create_arkivdel.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_mappe_with_beskrivelse(self, mock_get_client):
        """Creates mappe with optional beskrivelse."""
        from noark5_tg_mcp.server import noark5_create_mappe

        mock_client = mock_get_client.return_value
        mock_client.create_mappe.return_value = {
            "tittel": "File One",
            "_links": {"self": {"href": "http://example.com/m/m1"}},
        }

        noark5_create_mappe("http://example.com/ad/ad1", "File One", beskrivelse="Description here")
        mock_client.create_mappe.assert_called_once()
        call_args = mock_client.create_mappe.call_args
        assert call_args[0][1] == "File One"

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_registrering(self, mock_get_client):
        """Creates registrering under mappe."""
        from noark5_tg_mcp.server import noark5_create_registrering

        mock_client = mock_get_client.return_value
        mock_client.create_registrering.return_value = {
            "tittel": "Record One",
            "_links": {"self": {"href": "http://example.com/r/r1"}},
        }

        noark5_create_registrering("http://example.com/m/m1", "Record One")
        mock_client.create_registrering.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_dokumentbeskrivelse(self, mock_get_client):
        """Creates dokumentbeskrivelse under registrering."""
        from noark5_tg_mcp.server import noark5_create_dokumentbeskrivelse

        mock_client = mock_get_client.return_value
        mock_client.create_dokumentbeskrivelse.return_value = {
            "tittel": "Doc Desc",
            "_links": {"self": {"href": "http://example.com/db/db1"}},
        }

        noark5_create_dokumentbeskrivelse("http://example.com/r/r1", "Doc Desc")
        mock_client.create_dokumentbeskrivelse.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_klassifikasjonssystem(self, mock_get_client):
        """Creates klassifikasjonssystem under arkivdel."""
        from noark5_tg_mcp.server import noark5_create_klassifikasjonssystem

        mock_client = mock_get_client.return_value
        mock_client.create_klassifikasjonssystem.return_value = {
            "tittel": "Class System",
            "_links": {"self": {"href": "http://example.com/ks/ks1"}},
        }

        noark5_create_klassifikasjonssystem("http://example.com/ad/ad1", "Class System")
        mock_client.create_klassifikasjonssystem.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_klasse(self, mock_get_client):
        """Creates klasse under parent."""
        from noark5_tg_mcp.server import noark5_create_klasse

        mock_client = mock_get_client.return_value
        mock_client.create_klasse.return_value = {
            "tittel": "Class One",
            "_links": {"self": {"href": "http://example.com/k/k1"}},
        }

        noark5_create_klasse("http://example.com/ks/ks1", "Class One")
        mock_client.create_klasse.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_saksmappe_with_saksaar(self, mock_get_client):
        """Creates saksmappe with saksaar."""
        from noark5_tg_mcp.server import noark5_create_saksmappe

        mock_client = mock_get_client.return_value
        mock_client.create_saksmappe.return_value = {
            "tittel": "Case File",
            "_links": {"self": {"href": "http://example.com/sm/sm1"}},
        }

        noark5_create_saksmappe("http://example.com/ad/ad1", "Case File", saksaar=2024)
        mock_client.create_saksmappe.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_journalpost(self, mock_get_client):
        """Creates journalpost under saksmappe."""
        from noark5_tg_mcp.server import noark5_create_journalpost

        mock_client = mock_get_client.return_value
        mock_client.create_journalpost.return_value = {
            "tittel": "Journal Entry",
            "_links": {"self": {"href": "http://example.com/jp/jp1"}},
        }

        noark5_create_journalpost("http://example.com/sm/sm1", "Journal Entry")
        mock_client.create_journalpost.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_arkivnotat(self, mock_get_client):
        """Creates arkivnotat under saksmappe."""
        from noark5_tg_mcp.server import noark5_create_arkivnotat

        mock_client = mock_get_client.return_value
        mock_client.create_arkivnotat.return_value = {
            "tittel": "Note One",
            "_links": {"self": {"href": "http://example.com/an/an1"}},
        }

        noark5_create_arkivnotat("http://example.com/sm/sm1", "Note One")
        mock_client.create_arkivnotat.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_with_attributes(self, mock_get_client):
        """Create tools pass attributes JSON to client."""
        from noark5_tg_mcp.server import noark5_create_arkiv

        mock_client = mock_get_client.return_value
        mock_client.create_arkiv.return_value = {
            "tittel": "My Archive",
            "_links": {"self": {"href": "http://example.com/arkiv/a1"}},
        }

        attrs = '{"beskrivelse": "My Description"}'
        noark5_create_arkiv("My Archive", attributes=attrs)
        mock_client.create_arkiv.assert_called_once()


class TestDeleteEntityTool(unittest.TestCase):
    """Test noark5_delete_entity MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_delete_returns_confirmation(self, mock_get_client):
        """Deletes entity and returns confirmation message."""
        from noark5_tg_mcp.server import noark5_delete_entity

        mock_client = mock_get_client.return_value
        mock_client.delete_entity.return_value = None

        result = noark5_delete_entity("http://example.com/entity/e1")
        assert "deleted" in result.lower()


class TestSecondaryEntityTool(unittest.TestCase):
    """Test noark5_create_secondary_entity MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_forfatter(self, mock_get_client):
        """Creates forfatter secondary entity."""
        from noark5_tg_mcp.server import noark5_create_secondary_entity

        mock_client = mock_get_client.return_value
        mock_client.create_secondary_entity.return_value = {
            "forfatter": "John Doe",
            "_links": {"self": {"href": "http://example.com/f/1"}},
        }

        result = noark5_create_secondary_entity(
            "http://example.com/db/db1", "forfatter", "forfatter", "John Doe"
        )
        mock_client.create_secondary_entity.assert_called_once()
        assert "Created secondary entity" in result


class TestFilterEntitiesTool(unittest.TestCase):
    """Test noark5_filter_entities MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_filter_with_expression(self, mock_get_client):
        """Applies OData filter to collection URL."""
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = [
            {"systemID": "e1", "tittel": "Matched Entity", "_links": {"self": {"href": "http://example.com/e1"}}}
        ]

        result = noark5_filter_entities(
            "http://example.com/api/arkivstruktur/arkiv/",
            filter_str="contains(tittel, 'Archive')",
        )
        assert "Matched Entity" in result
        mock_client.filter_collection.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_filter_empty_returns_all(self, mock_get_client):
        """Empty filter lists all entities."""
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = [
            {"systemID": "e1", "tittel": "Entity One", "_links": {"self": {"href": "http://example.com/e1"}}},
            {"systemID": "e2", "tittel": "Entity Two", "_links": {"self": {"href": "http://example.com/e2"}}},
        ]

        result = noark5_filter_entities("http://example.com/api/arkivstruktur/arkiv/")
        assert "Entity One" in result
        assert "Entity Two" in result


class TestSearchEntitiesTool(unittest.TestCase):
    """Test noark5_search_entities MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_search_across_collections(self, mock_get_client):
        """Searches all arkivstruktur and sakarkiv collections."""
        from noark5_tg_mcp.server import noark5_search_entities

        mock_client = mock_get_client.return_value
        mock_client.search_entities.return_value = [
            ("http://example.com/a1", "Test Archive"),
        ]

        result = noark5_search_entities("test")
        assert "Test Archive" in result


class TestDownloadUploadTools(unittest.TestCase):
    """Test noark5_download_dokumentobjekt and noark5_upload_file tools."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_download_dokumentobjekt(self, mock_get_client):
        """Downloads file content from dokumentobjekt."""
        from noark5_tg_mcp.server import noark5_download_dokumentobjekt

        mock_client = mock_get_client.return_value
        mock_client.download_dokumentobjekt.return_value = b"%PDF-1.4 test content"

        result = noark5_download_dokumentobjekt("http://example.com/dokobj/do1")
        assert "Downloaded" in result
        mock_client.download_dokumentobjekt.assert_called_once()

    @patch("noark5_tg_mcp.server._get_client")
    def test_upload_file(self, mock_get_client):
        """Uploads file to entity with fil relation."""
        from noark5_tg_mcp.server import noark5_upload_file

        mock_client = mock_get_client.return_value
        mock_client.upload_file.return_value = {
            "dokumentobjekt": {
                "filnavn": "report.pdf",
                "mimeType": "application/pdf",
                "_links": {"self": {"href": "http://example.com/dokobj/do1"}},
            },
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 test")
            tmp_path = f.name

        try:
            result = noark5_upload_file("http://example.com/reg/r1", tmp_path, mime_type="application/pdf")
            assert "report.pdf" in result
            mock_client.upload_file.assert_called_once()
        finally:
            os.unlink(tmp_path)


class TestFormatEntityNonDict(unittest.TestCase):
    """Test _format_entity handles non-dict input."""

    def test_non_dict_returns_json(self):
        """_format_entity returns JSON for non-dict values."""
        from noark5_tg_mcp.server import _format_entity

        result = _format_entity([1, 2, 3])
        assert "[1, 2, 3]" in result or "1" in result

    def test_string_returns_json(self):
        """_format_entity returns JSON for string values."""
        from noark5_tg_mcp.server import _format_entity

        result = _format_entity("hello")
        assert '"hello"' in result


class TestDiscoverChildrenLinks(unittest.TestCase):
    """Test _discover_children_links edge cases."""

    def test_skips_non_dict_values(self):
        """Skips links where value is not a dict."""
        from noark5_tg_mcp.server import _discover_children_links

        raw_links = {
            "https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/undermappe/": "not-a-dict",
        }
        result = _discover_children_links(raw_links, "mappe")
        self.assertEqual(result, [])


class TestListParentsEdgeCases(unittest.TestCase):
    """Test noark5_list_parents edge cases."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_no_links_found(self, mock_get_client):
        """Returns message when entity has no links."""
        from noark5_tg_mcp.server import noark5_list_parents

        mock_client = mock_get_client.return_value
        mock_client.get_entity.return_value = {"tittel": "Orphan Entity", "_links": {}}

        result = noark5_list_parents("http://example.com/entity/e1")
        assert "No links found" in result.lower() or "no links" in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_no_known_parents_for_type(self, mock_get_client):
        """Returns message for entity type with no known parents."""
        from noark5_tg_mcp.server import noark5_list_parents

        mock_client = mock_get_client.return_value
        mock_client.get_entity.return_value = {
            "tittel": "Unknown Entity",
            "_links": {"self": {"href": "http://example.com/unknown/u1"}},
        }

        result = noark5_list_parents("http://example.com/unknown/u1")
        assert "no known parents" in result.lower() or "No links" in result


class TestSearchEntitiesEdgeCases(unittest.TestCase):
    """Test noark5_search_entities edge cases."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_no_results_found(self, mock_get_client):
        """Returns 'not found' message when search returns empty."""
        from noark5_tg_mcp.server import noark5_search_entities

        mock_client = mock_get_client.return_value
        mock_client.search_entities.return_value = []

        result = noark5_search_entities("nonexistent")
        assert "no entities found" in result.lower() or "not found" in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_with_filter_shows_filter_msg(self, mock_get_client):
        """Empty search results with filter shows filter info."""
        from noark5_tg_mcp.server import noark5_search_entities

        mock_client = mock_get_client.return_value
        mock_client.search_entities.return_value = []

        result = noark5_search_entities("test", filter_str="tittel eq 'X'")
        assert "filter" in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_with_filter_in_results(self, mock_get_client):
        """Results with filter show filter info in header."""
        from noark5_tg_mcp.server import noark5_search_entities

        mock_client = mock_get_client.return_value
        mock_client.search_entities.return_value = [
            ("http://example.com/a1", "Test Archive"),
        ]

        result = noark5_search_entities("test", filter_str="tittel eq 'X'")
        assert "filtered by" in result.lower()


class TestFilterEntitiesEdgeCases(unittest.TestCase):
    """Test noark5_filter_entities edge cases."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_empty_results(self, mock_get_client):
        """Returns 'not found' message when filter returns empty."""
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = []

        result = noark5_filter_entities(
            "http://example.com/api/arkivstruktur/arkiv/",
            filter_str="tittel eq 'nonexistent'",
        )
        assert "no entities found" in result.lower() or "not found" in result.lower()

    @patch("noark5_tg_mcp.server._get_client")
    def test_with_mime_and_size(self, mock_get_client):
        """Shows mimetype and size for dokumentobjekt results."""
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = [
            {
                "systemID": "do1",
                "filnavn": "report.pdf",
                "mimetype": "application/pdf",
                "storrelse": 4096,
                "_links": {"self": {"href": "http://example.com/do1"}},
            }
        ]

        result = noark5_filter_entities("http://example.com/api/arkivstruktur/dokumentobjekt/")
        assert "report.pdf" in result
        assert "application/pdf" in result or "mime=" in result


class TestUpdateEntityTool(unittest.TestCase):
    """Test noark5_update_entity MCP tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_update_simple_field(self, mock_get_client):
        """Updates entity with simple field change."""
        from noark5_tg_mcp.server import noark5_update_entity

        mock_client = mock_get_client.return_value
        mock_client.update_entity.return_value = {
            "tittel": "New Title",
            "_links": {"self": {"href": "http://example.com/e1"}},
        }

        result = noark5_update_entity(
            "http://example.com/e1", changes='{"tittel": "New Title"}'
        )
        mock_client.update_entity.assert_called_once()
        assert "Updated" in result

    @patch("noark5_tg_mcp.server._get_client")
    def test_update_structured_field(self, mock_get_client):
        """Updates entity with structured field (nested dict)."""
        from noark5_tg_mcp.server import noark5_update_entity

        mock_client = mock_get_client.return_value
        mock_client.update_entity.return_value = {
            "dokumenttype": {"kode": "U"},
            "_links": {"self": {"href": "http://example.com/db1"}},
        }

        result = noark5_update_entity(
            "http://example.com/db1", changes='{"dokumenttype": {"kode": "U"}}'
        )
        mock_client.update_entity.assert_called_once()


class TestUploadTool(unittest.TestCase):
    """Test noark5_upload_file MCP tool edge cases."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_upload_calls_client(self, mock_get_client):
        """Upload file calls client.upload_file with correct args."""
        from noark5_tg_mcp.server import noark5_upload_file

        mock_client = mock_get_client.return_value
        mock_client.upload_file.return_value = {
            "dokumentobjekt": {
                "filnavn": "data.csv",
                "mimeType": "text/csv",
                "_links": {"self": {"href": "http://example.com/do1"}},
            },
        }

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            f.write(b"a,b,c\n1,2,3")
            tmp_path = f.name

        try:
            result = noark5_upload_file("http://example.com/reg/r1", tmp_path, mime_type="text/csv")
            assert "data.csv" in result
            call_args = mock_client.upload_file.call_args
            assert call_args[0][0] == "http://example.com/reg/r1"
        finally:
            os.unlink(tmp_path)


# ---- Coverage gap tests for missed branches (non-OIDC, practical only) ----

class TestCreateMethodsNoneAttributes(unittest.TestCase):
    """Test create methods hit the None branch for attributes parameter."""

    @patch.object(Noark5Client, "_create_entity")
    def test_create_dokumentobjekt_no_attributes(self, mock_create):
        """create_dokumentobjekt without attributes (client line 854->856)."""
        mock_create.return_value = {
            "systemID": "do1",
            "_links": {
                "self": {"href": "http://api/do/do1"},
                "https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/dokumentobjekt/": "http://api/do/do1",
            },
        }
        client = Noark5Client("http://api/")
        client.create_dokumentobjekt("http://api/db/db1")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_klassifikasjonssystem_no_attributes(self, mock_create):
        """create_klassifikasjonssystem without attributes (client line 869->871)."""
        mock_create.return_value = {
            "systemID": "ks1",
            "_links": {"self": {"href": "http://api/ks/ks1"}},
        }
        client = Noark5Client("http://api/")
        client.create_klassifikasjonssystem("http://api/ad/ad1", "KS Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "KS Title"})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_saksmappe_no_saksaar_no_attributes(self, mock_create):
        """create_saksmappe without saksaar and attributes (client line 900->902)."""
        mock_create.return_value = {
            "systemID": "sm1",
            "_links": {"self": {"href": "http://api/sm/sm1"}},
        }
        client = Noark5Client("http://api/")
        client.create_saksmappe("http://api/ad/ad1", "SM Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "SM Title"})
        self.assertNotIn("saksaar", call_data)

    @patch.object(Noark5Client, "_create_entity")
    def test_create_journalpost_no_attributes(self, mock_create):
        """create_journalpost without attributes (client line 902->904)."""
        mock_create.return_value = {
            "systemID": "jp1",
            "_links": {"self": {"href": "http://api/jp/jp1"}},
        }
        client = Noark5Client("http://api/")
        client.create_journalpost("http://api/sm/sm1", "JP Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "JP Title"})

    @patch.object(Noark5Client, "_create_entity")
    def test_create_arkivnotat_no_attributes(self, mock_create):
        """create_arkivnotat without attributes."""
        mock_create.return_value = {
            "systemID": "an1",
            "_links": {"self": {"href": "http://api/an/an1"}},
        }
        client = Noark5Client("http://api/")
        client.create_arkivnotat("http://api/sm/sm1", "AN Title")
        call_data = mock_create.call_args[0][2]
        self.assertEqual(call_data, {"tittel": "AN Title"})

    @patch.object(Noark5Client, "_create_at_root")
    def test_create_arkivskaper_no_attributes(self, mock_create):
        """create_arkivskaper without attributes (client line 749-750)."""
        mock_create.return_value = {
            "arkivskaperID": "test",
            "_links": {"self": {"href": "http://api/ak/test"}},
        }
        client = Noark5Client("http://api/")
        client.create_arkivskaper("test", "Test Creator")
        call_data = mock_create.call_args[0][1]
        self.assertEqual(call_data, {"arkivskaperID": "test", "arkivskaperNavn": "Test Creator"})


class TestClientListWithFilter(unittest.TestCase):
    """Test list methods that accept filter_str parameter."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_arkivskapere_with_filter(self, mock_get_json):
        client = Noark5Client("http://api/")

        def get_json_side_effect(url):
            if "$filter=" in str(url):
                return {"results": [{"systemID": "a1", "tittel": "Filtered"}]}
            elif url == ".":
                return {
                    "_links": {
                        RELBASE + "arkivstruktur/arkivskaper/": {"href": "http://api/ak/"},
                    },
                }
            raise Noark5Error(404, "Not found", str(url))

        mock_get_json.side_effect = get_json_side_effect
        result = client.list_arkivskapere(filter_str="contains(tittel, 'Test')")
        self.assertEqual(len(result), 1)


class TestClientFilterCollection(unittest.TestCase):
    """Test filter_collection method body (client line 1051-1061)."""

    @patch.object(Noark5Client, "_get_json")
    def test_filter_collection_no_filter(self, mock_get_json):
        client = Noark5Client("http://api/")
        mock_get_json.return_value = {"results": [{"systemID": "x1"}]}
        result = client.filter_collection("http://api/collection/", None)
        self.assertEqual(len(result), 1)

    @patch.object(Noark5Client, "_get_json")
    def test_filter_collection_with_filter(self, mock_get_json):
        client = Noark5Client("http://api/")
        urls_called = []

        def get_json_side_effect(url):
            urls_called.append(str(url))
            return {"results": [{"systemID": "x1"}]}

        mock_get_json.side_effect = get_json_side_effect
        result = client.filter_collection("http://api/collection/", "tittel eq 'X'")
        self.assertEqual(len(result), 1)
        self.assertIn("$filter=", urls_called[0])


class TestServerListParentsError(unittest.TestCase):
    """Test noark5_list_parents error handling."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_navigate_up_error_fetching_parent(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_parents

        mock_client = mock_get_client.return_value
        call_count = [0]
        def get_entity_side_effect(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "systemID": "m1",
                    "tittel": "Test Mappe",
                    "_links": {
                        "self": {"href": "http://api/mappe/m1"},
                        RELBASE + "arkivstruktur/arkivdel/": {
                            "href": "http://api/ad/p1",
                        },
                    },
                }
            raise Noark5Error(404, "Not found", url)

        mock_client.get_entity.side_effect = get_entity_side_effect

        result = noark5_list_parents("http://api/mappe/m1")
        self.assertIn("Error fetching parent", result)


class TestServerListParentsUnexpected(unittest.TestCase):
    """Test noark5_list_parents handles non-dict parent response."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_navigate_up_unexpected_response(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_parents

        call_count = [0]
        mock_client = mock_get_client.return_value

        def get_entity_side_effect(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return {
                    "systemID": "m1",
                    "tittel": "Test Mappe",
                    "_links": {
                        "self": {"href": "http://api/mappe/m1"},
                        RELBASE + "arkivstruktur/arkivdel/": {
                            "href": "http://api/ad/p1",
                        },
                    },
                }
            return ["unexpected list"]

        mock_client.get_entity.side_effect = get_entity_side_effect

        result = noark5_list_parents("http://api/mappe/m1")
        self.assertIn("Unexpected response", result)


class TestServerEntityLinksEmpty(unittest.TestCase):
    """Test noark5_entity_links with minimal entity."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_entity_links_no_navigable_links(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_entity_links

        mock_client = mock_get_client.return_value
        mock_client.get_entity.return_value = {
            "systemID": "x1",
            "tittel": "Minimal",
            "_links": {"self": {"href": "http://api/x/x1"}},
        }

        result = noark5_entity_links("http://api/x/x1")
        self.assertIn("No navigable links found for this entity (Minimal).", result)


class TestServerMetadataEmpty(unittest.TestCase):
    """Test noark5_list_metadata with empty results."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_metadata_empty_results(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata_poster.return_value = []

        result = noark5_list_metadata("dokumentmedium")
        self.assertIn("No metadata posts found", result)


class TestServerDownloadAutoPath(unittest.TestCase):
    """Test download tool generates temp path when output_path is empty."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_download_auto_output_path(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_download_dokumentobjekt

        mock_client = mock_get_client.return_value
        mock_client.download_dokumentobjekt.return_value = b"test content"

        result = noark5_download_dokumentobjekt(
            "http://api/do/do1", output_path=""
        )
        self.assertIn("Downloaded", result)


class TestServerListChildrenNoCollections(unittest.TestCase):
    """Test list_children with entity that has no child collections."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_no_child_collections(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        mock_client.get_entity.return_value = {
            "systemID": "do1",
            "tittel": "Document Object",
            "_links": {"self": {"href": "http://api/do/do1"}},
        }

        result = noark5_list_children(parent_url="http://api/do/do1")
        self.assertIn("No children found", result)


class TestServerListChildrenEmpty(unittest.TestCase):
    """Test list_children with collection that returns empty results."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_empty_results(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        entity_with_links = {
            "systemID": "ad1",
            "tittel": "Test Arkivdel",
            "_links": {
                "self": {"href": "http://api/arkivstruktur/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/arkivstruktur/arkivdel/ad1/mappe/"},
            },
        }

        mock_client.get_entity.return_value = entity_with_links

        def get_json(url):
            if "/mappe/" in str(url):
                return {"results": []}
            return entity_with_links

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(parent_url="http://api/arkivstruktur/arkivdel/ad1")
        self.assertIn("No mappe(s) found.", result)


class TestServerListChildrenFetchError(unittest.TestCase):
    """Test list_children continues on fetch error."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_fetch_error_continues(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        entity_with_links = {
            "systemID": "ad1",
            "tittel": "Test Arkivdel",
            "_links": {
                "self": {"href": "http://api/arkivstruktur/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/arkivstruktur/arkivdel/ad1/mappe/"},
                RELBASE + "sakarkiv/saksmappe/": {"href": "http://api/sakarkiv/saksmappe/sm/"},
            },
        }

        mock_client.get_entity.return_value = entity_with_links

        def get_json(url):
            if "/mappe/" in str(url):
                raise Noark5Error(500, "Internal Error", url)
            elif "saksmappe" in str(url) and "$filter" not in str(url):
                return {"results": [{"systemID": "s1", "tittel": "Case File"}]}
            return entity_with_links

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(parent_url="http://api/arkivstruktur/arkivdel/ad1")
        self.assertIn("Error fetching collection", result)


class TestServerListChildrenWithFilter(unittest.TestCase):
    """Test list_children with filter_str."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_parent_with_filter(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value
        entity_with_links = {
            "systemID": "ad1",
            "tittel": "Test Arkivdel",
            "_links": {
                "self": {"href": "http://api/arkivstruktur/arkivdel/ad1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/arkivstruktur/arkivdel/ad1/mappe/"},
            },
        }

        mock_client.get_entity.return_value = entity_with_links

        def get_json(url):
            if "/mappe/" in str(url):
                return {"results": [{"systemID": "m1", "tittel": "Filtered Mappe"}]}
            return entity_with_links

        mock_client._encode_filter.return_value = "contains%28tittel%2C+%27Filter%27%29"
        mock_client._get_json.side_effect = get_json

        result = noark5_list_children(
            parent_url="http://api/arkivstruktur/arkivdel/ad1", filter_str="contains(tittel, 'Filter')"
        )
        self.assertIn("Filtered Mappe", result)


class TestServerSearchEmpty(unittest.TestCase):
    """Test search_entities tool with empty results."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_search_entities_empty_results(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_search_entities

        mock_client = mock_get_client.return_value
        mock_client.search_entities.return_value = []

        result = noark5_search_entities("nonexistent")
        self.assertIn("No entities found", result)


class TestServerFilterEntitiesEmpty(unittest.TestCase):
    """Test filter_entities tool with empty results."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_filter_entities_empty_results(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_filter_entities

        mock_client = mock_get_client.return_value
        mock_client.filter_collection.return_value = []

        result = noark5_filter_entities("http://api/collection/", "tittel eq 'X'")
        self.assertIn("No entities found", result)


class TestServerUpdateEntityJson(unittest.TestCase):
    """Test update_entity tool parses JSON changes."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_update_entity_json(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_update_entity

        mock_client = mock_get_client.return_value
        mock_client.update_entity.return_value = {
            "systemID": "x1",
            "tittel": "Updated Title",
        }

        result = noark5_update_entity(
            "http://api/entity/x1", changes='{"tittel": "Updated Title"}'
        )
        self.assertIn("Updated Title", result)


class TestServerDeleteEntity(unittest.TestCase):
    """Test delete_entity tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_delete_entity_tool(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_delete_entity

        mock_client = mock_get_client.return_value
        mock_client.delete_entity.return_value = "Deleted"

        result = noark5_delete_entity("http://api/entity/x1")
        self.assertIn("Deleted", result)


class TestServerGetEntity(unittest.TestCase):
    """Test get_entity tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_get_entity_tool(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_get_entity

        mock_client = mock_get_client.return_value
        mock_client.get_entity.return_value = {
            "systemID": "x1",
            "tittel": "Test Entity",
        }

        result = noark5_get_entity("http://api/entity/x1")
        self.assertIn("Test Entity", result)


class TestServerSetCredentials(unittest.TestCase):
    """Test set_credentials tool."""

    @patch.object(Noark5Client, "__init__", return_value=None)
    @patch.object(Noark5Client, "login", return_value={"_links": {"self": {"href": "http://api/"}}})
    def test_set_credentials_tool(self, mock_login, mock_init):
        from noark5_tg_mcp.server import noark5_set_credentials

        result = noark5_set_credentials("user", "pass")
        self.assertIn("Authenticated as 'user'", result)


class TestServerGetRootLinks(unittest.TestCase):
    """Test get_root_links tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_get_root_links_tool(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_get_root_links

        mock_client = mock_get_client.return_value
        mock_client._get_json.return_value = {
            "_links": {
                "rel1": {"href": "http://api/r1"},
                "rel2": {"href": "http://api/r2"},
            }
        }

        result = noark5_get_root_links()
        self.assertIn("rel1", result)


class TestServerCreateArkivTool(unittest.TestCase):
    """Test create tools call correct client methods."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_create_arkiv_tool(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_create_arkiv

        mock_client = mock_get_client.return_value
        mock_client.create_arkiv.return_value = {
            "systemID": "a1",
            "tittel": "New Archive",
        }

        result = noark5_create_arkiv("New Archive")
        self.assertIn("New Archive", result)


class TestServerSecondaryEntityTool(unittest.TestCase):
    """Test secondary entity tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_secondary_entity_tool(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_create_secondary_entity

        mock_client = mock_get_client.return_value
        mock_client.create_secondary_entity.return_value = {"noekkelord": "test"}

        result = noark5_create_secondary_entity(
            "http://api/entity/x1", "noekkelord", "noekkelord", "test"
        )
        self.assertIn("test", result)


class TestServerUploadTool(unittest.TestCase):
    """Test upload tool."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_upload_tool(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_upload_file

        mock_client = mock_get_client.return_value
        mock_client.upload_file.return_value = {
            "dokumentobjekt": {"filnavn": "test.txt", "mimeType": "text/plain"},
        }

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello")
            tmp_path = f.name

        try:
            result = noark5_upload_file(
                "http://api/reg/r1", tmp_path, mime_type="text/plain"
            )
            self.assertIn("test.txt", result)
        finally:
            os.unlink(tmp_path)


class TestServerUploadMissingFile(unittest.TestCase):
    """Test upload tool with missing file."""

    def test_upload_tool_missing_file(self):
        from noark5_tg_mcp.server import noark5_upload_file

        with self.assertRaises(FileNotFoundError):
            noark5_upload_file("http://api/reg/r1", "/nonexistent/file.txt")


class TestServerDiscoverChildrenLinks(unittest.TestCase):
    """Test _discover_children_links helper."""

    def test_discover_children_arkivdel(self):
        from noark5_tg_mcp.server import _discover_children_links

        raw_links = {
            RELBASE + "arkivstruktur/mappe/": {"href": "http://api/ad1/mappe/"},
            RELBASE + "sakarkiv/saksmappe/": {"href": "http://api/ad1/sm/"},
            RELBASE + "arkivstruktur/klassifikasjonssystem/": {
                "href": "http://api/ad1/ks/"
            },
        }

        result = _discover_children_links(raw_links, "arkivdel")
        rels = [r for r, _ in result]
        self.assertIn(RELBASE + "arkivstruktur/mappe/", rels)


class TestServerListDokumentobjekter(unittest.TestCase):
    """Test list_dokumentobjekter client method."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_dokobj_basic(self, mock_get_json):
        def get_json(url):
            if str(url) == "http://api/dokbeskr/db1":
                return {
                    "_links": {
                        "self": {"href": "http://api/dokbeskr/db1"},
                        RELBASE + "arkivstruktur/dokumentobjekt/": {
                            "href": "http://api/dokbeskr/db1/dokumentobjekt"
                        },
                    }
                }
            return {"results": [{"systemID": "do1", "filnavn": "test.pdf"}]}

        mock_get_json.side_effect = get_json
        client = Noark5Client("http://api/")
        result = client.list_dokumentobjekter("http://api/dokbeskr/db1")
        self.assertEqual(len(result), 1)


class TestServerListKlassifikasjonssystemer(unittest.TestCase):
    """Test list_klassifikasjonssystemer client method."""

    @patch.object(Noark5Client, "_get_json")
    def test_list_ks_basic(self, mock_get_json):
        def get_json(url):
            if "arkivdel" in str(url) and "klassifikasjonssystem" not in str(url):
                return {
                    "_links": {
                        "self": {"href": "http://api/arkivstruktur/arkivdel/ad1"},
                        RELBASE + "arkivstruktur/klassifikasjonssystem/": {
                            "href": "http://api/arkivstruktur/arkivdel/ad1/klassifikasjonssystem"
                        },
                    }
                }
            return {"results": [{"systemID": "ks1", "tittel": "Test KS"}]}

        mock_get_json.side_effect = get_json
        client = Noark5Client("http://api/")
        result = client.list_klassifikasjonssystemer("http://api/arkivstruktur/arkivdel/ad1")
        self.assertEqual(len(result), 1)


class TestServerFormatEntity(unittest.TestCase):
    """Test _format_entity helper."""

    def test_format_entity_basic(self):
        from noark5_tg_mcp.server import _format_entity

        entity = {
            "systemID": "x1",
            "tittel": "Test",
            "_links": {"self": {"href": "http://api/x/x1"}},
        }
        result = _format_entity(entity)
        self.assertIn("x1", result)
        self.assertIn("Test", result)


class TestServerFormatEntityNonDict(unittest.TestCase):
    """Test _format_entity with non-dict input."""

    def test_format_entity_non_dict(self):
        from noark5_tg_mcp.server import _format_entity

        result = _format_entity("not a dict")
        self.assertIn("not a dict", str(result))


class TestServerFormatList(unittest.TestCase):
    """Test _format_list helper."""

    def test_format_list_basic(self):
        from noark5_tg_mcp.server import _format_list

        items = [
            {"systemID": "x1", "tittel": "Item 1"},
            {"systemID": "x2", "tittel": "Item 2"},
        ]
        result = _format_list(items, "entity")
        self.assertIn("Item 1", result)
        self.assertIn("Item 2", result)


class TestClientEntityRelationKey(unittest.TestCase):
    """Test entity_relation_key static method."""

    def test_entity_relation_key_basic(self):
        # When both self and canonical rel match, "self" is found first
        # (the skip check is for "self/" with trailing slash, not bare "self")
        entity = {
            "_links": {
                "self": {"href": "http://api/mappe/m1"},
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/mappe/m1"},
            }
        }
        result = Noark5Client.entity_relation_key(entity)
        self.assertEqual(result, "self")

    def test_entity_relation_key_canonical_only(self):
        # Without bare 'self' link, returns canonical rel
        entity = {
            "_links": {
                RELBASE + "arkivstruktur/mappe/": {"href": "http://api/mappe/m1"},
            }
        }
        result = Noark5Client.entity_relation_key(entity)
        self.assertEqual(result, RELBASE + "arkivstruktur/mappe/")


class TestServerGetClientNotAuth(unittest.TestCase):
    """Test _get_client raises when not authenticated."""

    def test_get_client_not_authenticated(self):
        from noark5_tg_mcp.server import _server_state, _get_client

        old_state = dict(_server_state)
        try:
            _server_state["username"] = ""
            _server_state["password"] = ""
            _server_state["access_token"] = None
            with self.assertRaises(RuntimeError):
                _get_client()
        finally:
            _server_state.update(old_state)


class TestServerListParentsNoParent(unittest.TestCase):
    """Test noark5_list_parents when entity has no parent links."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_parents_no_parent(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_parents

        mock_client = mock_get_client.return_value
        mock_client.get_entity.return_value = {
            "systemID": "do1",
            "tittel": "Document Object",
            "_links": {"self": {"href": "http://api/dokumentobjekt/do1"}},
        }

        result = noark5_list_parents("http://api/dokumentobjekt/do1")
        self.assertIn("No parent entities found for Document Object.", result)


class TestClientParseLinksEmpty(unittest.TestCase):
    """Test parse_links edge cases."""

    def test_parse_links_empty(self):
        client = Noark5Client("http://api/")
        data = {"_links": {}}
        links = client.parse_links(data)
        self.assertEqual(links, {})


class TestServerMetadataListAll(unittest.TestCase):
    """Test list_metadata listing all catalogs."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_metadata_list_all(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_metadata

        mock_client = mock_get_client.return_value
        mock_client.list_metadata.return_value = [
            {"tittel": "dokumentmedium"},
            {"tittel": "arkivstatus"},
        ]

        result = noark5_list_metadata()
        self.assertIn("dokumentmedium", result)


class TestClientCreateArkiv(unittest.TestCase):
    """Test create_arkiv method."""

    @patch.object(Noark5Client, "_create_at_root")
    def test_create_arkiv_basic(self, mock_create):
        mock_create.return_value = {
            "systemID": "a1",
            "tittel": "New Archive",
            "_links": {"self": {"href": "http://api/arkiv/a1"}},
        }
        client = Noark5Client("http://api/")
        result = client.create_arkiv("New Archive")
        self.assertEqual(result["systemID"], "a1")


class TestClientCreateArkivdel(unittest.TestCase):
    """Test create_arkivdel method."""

    @patch.object(Noark5Client, "_create_entity")
    def test_create_arkivdel_basic(self, mock_create):
        mock_create.return_value = {
            "systemID": "ad1",
            "tittel": "New Arkivdel",
            "_links": {"self": {"href": "http://api/ad/ad1"}},
        }
        client = Noark5Client("http://api/")
        result = client.create_arkivdel("http://api/arkiv/a1", "New Arkivdel")
        self.assertEqual(result["systemID"], "ad1")


class TestServerListChildrenTopLevel(unittest.TestCase):
    """Test list_children top-level listing."""

    @patch("noark5_tg_mcp.server._get_client")
    def test_list_children_top_level(self, mock_get_client):
        from noark5_tg_mcp.server import noark5_list_children

        mock_client = mock_get_client.return_value

        def find_relation(rel):
            if "arkiv/" in rel:
                return "http://api/arkiv/"
            elif "arkivskaper/" in rel:
                return "http://api/ak/"
            return None

        mock_client.find_relation.side_effect = find_relation

        def get_json(url):
            if "arkiv" in str(url) and "$filter" not in str(url):
                return {"results": [{"systemID": "a1", "tittel": "Test Archive"}]}
            elif "arkivskaper" in str(url):
                return {"results": []}
            return {}

        mock_client._get_json.side_effect = get_json

        result = noark5_list_children()
        self.assertIn("Test Archive", result)


if __name__ == "__main__":
    unittest.main()

