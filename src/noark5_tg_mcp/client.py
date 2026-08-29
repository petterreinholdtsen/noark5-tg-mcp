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

"""HTTP client for Noark 5 tjenestegrensesnitt (N5TG) API.

Handles authentication, HATEOAS link navigation, and CRUD operations.
Based on the patterns from noark5-tester/lib/n5core/endpoint.py and lib/n5tui/api.py.
"""

import base64
import json
import time
import urllib.request
from urllib.parse import quote, urlencode, urljoin, urlparse


RELBASE = "https://rel.arkivverket.no/noark5/v5/api/"
NIKITA_RELBASE = "https://nikita.arkivlab.no/noark5/v5/"

# OIDC token renewal safety margin (seconds) — renew if expires within this window.
OIDC_RENEW_MARGIN = 30


class Noark5Error(Exception):
    """Base exception for Noark 5 API errors."""

    def __init__(self, code: int, message: str, url: str = ""):
        self.code = code
        self.message = message
        self.url = url
        super().__init__(f"HTTP {code}: {message} ({url})")


class Noark5Client:
    """Client for the Noark 5 tjenestegrensesnitt REST API.

    Supports two authentication methods:
      - Basic auth (RFC 7617): default, username/password encoded as Base64
      - OIDC / OAuth2 password grant: auto-discovers token endpoint via login/oidc/,
        with automatic token renewal via refresh_token

    Usage:
        client = Noark5Client("http://localhost:8092/noark5v5/", "admin", "password")
        client.login()  # Basic auth by default
            result = client.list_arkiv()

        # OIDC login with auto-renewal:
        client = Noark5Client(
            "https://example.com/noark5v5/",
            "admin@example.com",
            "password",
            auth_method="oidc",
            client_id="my-client",
            client_secret="client-secret",
        )
        client.login()

    Environment variables (read by server.py, not this module):
        NOARK5_AUTH_METHOD  - "basic" or "oidc" (default: "basic")
        NOARK5_USERNAME     - Auth username
        NOARK5_PASSWORD     - Auth password
        NOARK5_CLIENT_ID    - OIDC client_id (optional)
        NOARK5_CLIENT_SECRET - OIDC client_secret (optional, used with client_id)
        NOARK5_ACCESS_TOKEN - Pre-existing Bearer token; skip login flow entirely.
    """

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        auth_method: str | None = None,
        client_id: str = "",
        client_secret: str = "",
        access_token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.auth_method = auth_method or "basic"
        self.client_id = client_id
        self._client_secret = client_secret
        self._token: str | None = access_token  # Pre-existing token, skips login.
        self._logged_in = bool(access_token)

        # OIDC state (populated during oidc login)
        self._oidc_meta: dict[str, str] = {}
        self._oidc_info: dict[str, object] = {}

    # ---- Authentication ----

    def _login_basic(self) -> dict:
        """Authenticate using Basic auth (RFC 7617)."""
        if not self.username or not self.password:
            raise ValueError("Username and password are required for login")

        credentials = f"{self.username}:{self.password}"
        self._token = "Basic " + base64.b64encode(credentials.encode()).decode()
        root = self._get_json(".")
        self._logged_in = True
        return root

    def _login_oidc(self, oidc_url: str | None = None) -> dict:
        """Authenticate using OIDC password grant with auto-renewal support.

        Flow (per N5TG ch 4 / OIDC service provider):
          1. GET {base}/login/oidc/ → discovery document with token_endpoint
          2. POST to token_endpoint with form-encoded credentials
          3. Store access_token, refresh_token, expiry info for auto-renewal

        Args:
            oidc_url: Pre-discovered OIDC endpoint URL (from auto-detect). If None,
                      discovers via find_relation().
        """
        if not self.username or not self.password:
            raise ValueError("Username and password are required for OIDC login")

        # Step 1: Discover token endpoint via OIDC relation.
        if oidc_url is None:
            oidc_url = self.find_relation(RELBASE + "login/oidc/")
            if not oidc_url:
                raise Noark5Error(404, "OIDC login endpoint not found", self.base_url)

        discovery = self._get_json(oidc_url)
        token_endpoint = discovery.get("token_endpoint")
        if not token_endpoint:
            raise Noark5Error(404, "No token_endpoint in OIDC discovery document", oidc_url)

        # Step 2: POST credentials to token endpoint.
        self._oidc_meta = discovery
        form_data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
        }
        if self.client_id:
            form_data["client_id"] = self.client_id

        encoded = urlencode(form_data).encode("utf-8")
        token_url = self._expand_url(token_endpoint)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        # If client_id is set, authenticate the client on the token request.
        if self.client_id:
            cred = f"{self.client_id}:{self._client_secret}"
            headers["Authorization"] = "Basic " + base64.b64encode(cred.encode()).decode()

        req = urllib.request.Request(token_url, data=encoded, headers=headers)
        req.get_method = lambda: "POST"

        try:
            res = urllib.request.urlopen(req)
            token_data = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            raise Noark5Error(e.code, body.decode(errors="replace"), token_url)

        # Step 3: Store token info for auto-renewal.
        now = time.time()
        self._oidc_info = {
            "access_token": token_data["access_token"],
            "token_type": token_data.get("token_type", "Bearer"),
            "refresh_token": token_data.get("refresh_token", ""),
            "epoc_expires_in": now + token_data.get("expires_in", 3600),
            "epoc_refresh_expires_in": now + token_data.get("refresh_expires_in", 86400),
        }
        if self.client_id:
            self._oidc_info["client_id"] = self.client_id

        # Set initial bearer token.
        self._token = f"{self._oidc_info['token_type']} {self._oidc_info['access_token']}"
        root = self._get_json(".")
        self._logged_in = True
        return root

    @staticmethod
    def _detect_auth_method(root_links: dict[str, str]) -> str | None:
        """Detect available auth method from root entity links.

        Returns "oidc" if login/oidc/ relation found, "basic" if login/rfc7617/,
        or None if neither is present. OIDC takes precedence when both are available.
        """
        oidc_rel = RELBASE + "login/oidc/"
        basic_rel = RELBASE + "login/rfc7617/"

        if oidc_rel in root_links:
            return "oidc"
        if basic_rel in root_links:
            return "basic"
        return None

    def login(self) -> dict:
        """Authenticate using the configured auth method.

        If auth_method is "auto", fetches the root entity first to detect which
        login endpoints are available (OIDC preferred over Basic). Otherwise dispatches
        directly based on self.auth_method.

        If a pre-existing access_token was provided at construction, this is a no-op.
        Returns the root entity JSON with _links.
        Raises Noark5Error on failure.
        """
        if self._logged_in:
            return self._get_json(".")

        # Auto-detect method from server's advertised login relations.
        oidc_url = None
        if self.auth_method == "auto":
            try:
                root = self._get_json(".")
                links = self.parse_links(root)
                detected = self._detect_auth_method(links)
                if detected:
                    self.auth_method = detected
                    # Reuse discovered OIDC URL to avoid re-traversal.
                    oidc_rel = RELBASE + "login/oidc/"
                    if detected == "oidc" and oidc_rel in links:
                        oidc_url = links[oidc_rel]
            except Noark5Error:
                # Server requires auth for root — fall back to basic.
                pass

        if self.auth_method == "oidc":
            return self._login_oidc(oidc_url)
        return self._login_basic()

    def _oidc_renew(self) -> None:
        """Renew OIDC access token using refresh_token."""
        if not self._oidc_info.get("refresh_token"):
            raise Noark5Error(401, "No refresh_token available for renewal", "")

        url = self._expand_url(self._oidc_meta["token_endpoint"])
        form_data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": self._oidc_info["refresh_token"],
        }
        if "client_id" in self._oidc_info:
            form_data["client_id"] = self._oidc_info["client_id"]

        encoded = urlencode(form_data).encode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, data=encoded, headers=headers)
        req.get_method = lambda: "POST"

        try:
            res = urllib.request.urlopen(req)
            token_data = json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            raise Noark5Error(e.code, body.decode(errors="replace"), url)

        now = time.time()
        self._oidc_info["access_token"] = token_data["access_token"]
        if "refresh_token" in token_data:
            self._oidc_info["refresh_token"] = token_data["refresh_token"]
        self._oidc_info["epoc_expires_in"] = now + token_data.get("expires_in", 3600)
        self._oidc_info["epoc_refresh_expires_in"] = now + token_data.get(
            "refresh_expires_in", 86400
        )

        self._token = f"{self._oidc_info['token_type']} {self._oidc_info['access_token']}"

    def _auth_headers(self) -> dict[str, str]:
        """Return headers with authentication if logged in.

        For OIDC auth, transparently renews the access token if it is about to expire.
        """
        headers: dict[str, str] = {}
        if self.auth_method == "oidc" and self._logged_in:
            now = time.time()
            expires_at = self._oidc_info.get("epoc_expires_in", 0)
            refresh_expires_at = self._oidc_info.get("epoc_refresh_expires_in", 0)

            # Renew if access token expires within margin or refresh token is expiring.
            if (now >= expires_at - OIDC_RENEW_MARGIN or now >= refresh_expires_at - OIDC_RENEW_MARGIN):
                if now < refresh_expires_at:
                    self._oidc_renew()
                else:
                    raise Noark5Error(401, "OIDC refresh token expired; re-login required", "")

        if self._token:
            headers["Authorization"] = self._token
        return headers

    # ---- Low-level HTTP methods ----

    def _expand_url(self, path: str) -> str:
        """Expand a relative or absolute path to a full URL."""
        if not path:
            raise ValueError("Empty path")
        if path.startswith("http"):
            return path
        return urljoin(self.base_url, path)

    def _request(
        self, method: str, path: str, data: bytes | None = None, content_type: str | None = None
    ) -> tuple[bytes, "http.client.HTTPResponse"]:
        """Make an HTTP request and return (content_bytes, response)."""
        url = self._expand_url(path)
        headers = {
            "Accept": "application/vnd.noark5+json, application/json",
        }
        headers.update(self._auth_headers())

        if content_type:
            headers["Content-Type"] = content_type
        if data is not None:
            headers["Content-Length"] = str(len(data))

        req = urllib.request.Request(url, data=data, headers=headers)
        req.get_method = lambda: method

        try:
            response = urllib.request.urlopen(req)
            return response.read(), response
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            try:
                err = json.loads(body)
                msg = err.get("feil", {}).get("beskrivelse", body.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                msg = body.decode(errors="replace")
            raise Noark5Error(e.code, msg, url)

    def _get_json(self, path: str) -> dict | list:
        """GET a JSON resource."""
        content, _res = self._request("GET", path)
        return json.loads(content.decode("utf-8"))

    def download_file(self, path: str) -> bytes:
        """GET raw binary content from a dokumentobjekt's referanseFil link."""
        url = self._expand_url(path)
        headers = {"Accept": "*/*"}
        headers.update(self._auth_headers())
        req = urllib.request.Request(url, headers=headers)
        req.get_method = lambda: "GET"
        try:
            res = urllib.request.urlopen(req)
            return res.read()
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            raise Noark5Error(e.code, body.decode(errors="replace"), url)

    def download_dokumentobjekt(self, dokobj_url: str) -> bytes:
        """Download file content from a dokumentobjekt.

        Resolves the referanseFil HATEOAS link on the given dokumentobjekt
        and downloads the binary content (per N5TG chapter 6).

        Args:
            dokobj_url: The self-href URL of the dokumentobjekt to download.

        Returns:
            Raw file bytes.

        Raises:
            Noark5Error: If no referanseFil link is found on the dokumentobjekt.
        """
        obj = self._get_json(dokobj_url)
        obj_links = self.parse_links(obj)
        fil_rel = RELBASE + "arkivstruktur/fil/"
        if fil_rel not in obj_links:
            raise Noark5Error(404, "No referanseFil link on dokumentobjekt", dokobj_url)

        fil_url = self.clean_url(obj_links[fil_rel])
        return self.download_file(fil_url)

    def _post_json(self, path: str, data: dict) -> dict:
        """POST JSON data and return the response as dict."""
        body = json.dumps(data).encode("utf-8")
        content, _res = self._request(
            "POST", path, data=body, content_type="application/vnd.noark5+json"
        )
        return json.loads(content.decode("utf-8"))

    def upload_file(self, entity_url: str, file_data: bytes, mime_type: str = "application/octet-stream") -> dict:
        """Upload a file to an entity that has a fil relation key.

        Resolves the href of the fil relation (arkivstruktur/fil/) from the entity's _links
        per N5TG chapter 6, then POSTs raw binary content to that URL. Returns JSON with
        created dokumentobjekt and optionally embedded entities.
        """
        entity_url = self._expand_url(entity_url)
        obj = self._get_json(entity_url)
        obj_links = self.parse_links(obj)
        fil_rel = RELBASE + "arkivstruktur/fil/"
        if fil_rel not in obj_links:
            raise Noark5Error(404, f"No fil relation on entity", entity_url)

        url = self.clean_url(obj_links[fil_rel])
        headers = {
            "Content-Type": mime_type,
            "Accept": "application/vnd.noark5+json, application/json",
            "Content-Length": str(len(file_data)),
        }
        headers.update(self._auth_headers())
        req = urllib.request.Request(url, data=file_data, headers=headers)
        req.get_method = lambda: "POST"
        try:
            res = urllib.request.urlopen(req)
            return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            raise Noark5Error(e.code, body.decode(errors="replace"), url)

    # ---- HATEOAS navigation helpers ----

    @staticmethod
    def _encode_filter(filter_str: str) -> str:
        """Percent-encode an OData $filter expression for safe URL inclusion."""
        return quote(filter_str, safe="")

    @staticmethod
    def parse_links(entity: dict) -> dict[str, str]:
        """Extract href values from _links dict.

        Handles both formats:
          - Dict with "href" key: {"href": "https://..."}
          - Plain string URL: "https://..."
        """
        links = {}
        for rel, val in entity.get("_links", {}).items():
            if isinstance(val, dict) and "href" in val:
                links[rel] = val["href"]
            elif isinstance(val, str):
                links[rel] = val
        return links

    @staticmethod
    def clean_url(url: str) -> str:
        """Remove OData template parameters (e.g., {?$filter})."""
        idx = url.find("{")
        if idx >= 0:
            return url[:idx]
        return url

    def find_relation(self, rel_key: str) -> str | None:
        """Recursively walk _links from root to find a relation by key.

        Returns the href URL or None if not found.
        """
        urls_left = ["."]
        seen = set()

        while urls_left:
            url = urls_left.pop(0)
            clean = self.clean_url(url).rstrip("/")
            if clean in seen:
                continue
            seen.add(clean)

            try:
                entity = self._get_json(url)
            except Noark5Error:
                continue

            for r, href in self.parse_links(entity).items():
                if r == rel_key:
                    return self.clean_url(href)
                child = self.clean_url(href).rstrip("/")
                if child not in seen:
                    urls_left.append(href)
        return None

    # ---- Entity operations ----

    def get_entity(self, path: str) -> dict:
        """GET an entity at the given URL or path."""
        return self._get_json(path)

    def delete_entity(self, path: str) -> str:
        """DELETE an entity. Returns response text."""
        url = self._expand_url(path)
        headers = {"Accept": "application/vnd.noark5+json"}
        headers.update(self._auth_headers())
        req = urllib.request.Request(url, headers=headers)
        req.get_method = lambda: "DELETE"
        try:
            res = urllib.request.urlopen(req)
            return res.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read() or b""
            raise Noark5Error(e.code, body.decode(errors="replace"), url)

    # ---- List operations ----

    def list_arkiv(self, filter_str: str | None = None) -> list[dict]:
        """List all top-level archives (arkiv)."""
        url = self.find_relation(RELBASE + "arkivstruktur/arkiv/")
        if not url:
            return []
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def list_arkivskapere(self, filter_str: str | None = None) -> list[dict]:
        """List all archive creators (arkivskaper)."""
        url = self.find_relation(RELBASE + "arkivstruktur/arkivskaper/")
        if not url:
            return []
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def list_arkivdeler(self, arkiv_url: str, filter_str: str | None = None) -> list[dict]:
        """List arkivdel under a specific archive."""
        entity = self._get_json(arkiv_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/arkivdel/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def list_mapper(self, parent_url: str, filter_str: str | None = None) -> list[dict]:
        """List mapper under a parent (arkivdel, klasse, or mappe)."""
        entity = self._get_json(parent_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/mappe/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def list_registreringer(self, mappe_url: str, filter_str: str | None = None) -> list[dict]:
        """List registrerings under a mappe."""
        entity = self._get_json(mappe_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/registrering/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def list_dokumentbeskrivelser(self, registrering_url: str) -> list[dict]:
        """List dokumentbeskrivelser under a registrering."""
        entity = self._get_json(registrering_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/dokumentbeskrivelse/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        data = self._get_json(url)
        return data.get("results", [])

    def list_dokumentobjekter(
        self, dokbeskr_url: str, filter_str: str | None = None
    ) -> list[dict]:
        """List dokumentobjekter under a dokumentbeskrivelse.

        Args:
            dokbeskr_url: Self-href URL of the dokumentbeskrivelse.
            filter_str: Optional OData $filter expression (e.g., 'mimetype eq ''application/epub+zip''').
                        Leave empty to list all.
        """
        entity = self._get_json(dokbeskr_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/dokumentobjekt/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def filter_collection(self, collection_url: str, filter_str: str | None = None) -> list[dict]:
        """List entities in any OData collection with optional filter.

        Args:
            collection_url: The URL of the collection endpoint (without query params).
            filter_str: Optional OData $filter expression (e.g., 'mimetype eq ''application/epub+zip''').

        Returns list of entity dicts from the results array.
        """
        url = self.clean_url(self._expand_url(collection_url))
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        data = self._get_json(url)
        return data.get("results", [])

    def list_saksmapper(self, parent_url: str) -> list[dict]:
        """List saksmapper under an arkivdel."""
        entity = self._get_json(parent_url)
        links = self.parse_links(entity)
        rel = RELBASE + "sakarkiv/saksmappe/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        data = self._get_json(url)
        return data.get("results", [])

    def list_journalposter(self, saksmappe_url: str) -> list[dict]:
        """List journalposter under a saksmappe."""
        entity = self._get_json(saksmappe_url)
        links = self.parse_links(entity)
        rel = RELBASE + "sakarkiv/journalpost/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        data = self._get_json(url)
        return data.get("results", [])

    def list_arkivnotater(self, saksmappe_url: str) -> list[dict]:
        """List arkivnotater under a saksmappe."""
        entity = self._get_json(saksmappe_url)
        links = self.parse_links(entity)
        rel = RELBASE + "sakarkiv/arkivnotat/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        data = self._get_json(url)
        return data.get("results", [])

    def list_klassifikasjonssystemer(self, arkivdel_url: str) -> list[dict]:
        """List klassifikasjonssystemer under an arkivdel."""
        entity = self._get_json(arkivdel_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/klassifikasjonssystem/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        data = self._get_json(url)
        return data.get("results", [])

    def list_klasser(self, parent_url: str) -> list[dict]:
        """List klasser under a klassifikasjonssystem or klasse."""
        entity = self._get_json(parent_url)
        links = self.parse_links(entity)
        rel = RELBASE + "arkivstruktur/klasse/"
        if rel not in links:
            return []
        url = self.clean_url(links[rel])
        data = self._get_json(url)
        return data.get("results", [])

    # ---- Search operations ----

    def search_entities(self, query: str, filter_str: str | None = None) -> list[tuple[str, str]]:
        """Search entities by title across all global collections.

        Uses OData $search for full-text title matching, optionally combined
        with a $filter expression to further narrow results (AND semantics).

        Args:
            query: The search term to match against entity titles.
            filter_str: Optional OData $filter expression applied in addition
                        to the $search term (e.g., 'opprettetDato ge 2026-01-01T00:00:00Z').

        Returns list of (self_href, tittel) tuples.
        """
        from urllib.parse import quote_plus

        encoded_query = quote_plus(query)
        collection_rels = [
            RELBASE + "arkivstruktur/arkiv/",
            RELBASE + "arkivstruktur/arkivdel/",
            RELBASE + "arkivstruktur/klassifikasjonssystem/",
            RELBASE + "arkivstruktur/mappe/",
            RELBASE + "arkivstruktur/registrering/",
            RELBASE + "arkivstruktur/dokumentbeskrivelse/",
            RELBASE + "sakarkiv/saksmappe/",
            RELBASE + "sakarkiv/journalpost/",
            RELBASE + "sakarkiv/arkivnotat/",
        ]

        results: list[tuple[str, str]] = []
        seen_urls: set[str] = set()  # Deduplicate across collection queries.
        for rel in collection_rels:
            url = self.find_relation(rel)
            if not url:
                continue
            search_url = self.clean_url(url) + f"?$search={encoded_query}"
            if filter_str:
                search_url += "&$filter=" + self._encode_filter(filter_str)
            try:
                data = self._get_json(search_url)
                for item in data.get("results", []):
                    href = item.get("_links", {}).get("self", {}).get("href", "")
                    tittel = item.get("tittel", "?")
                    if href and href not in seen_urls:
                        results.append((href, tittel))
                        seen_urls.add(href)
            except Noark5Error:
                continue
        return results

    # ---- Create operations ----

    def _create_entity(self, parent_url: str, ny_rel: str, data: dict) -> dict:
        """Create an entity under a parent using the 'ny-*' relation."""
        parent = self._get_json(parent_url)
        links = self.parse_links(parent)
        if ny_rel not in links:
            raise Noark5Error(404, f"No {ny_rel} relation found on parent", parent_url)

        create_url = links[ny_rel]
        # Try to get template defaults
        try:
            default = self._get_json(create_url)
            for k, v in default.items():
                if k != "_links" and k not in data:
                    data[k] = v
        except Noark5Error:
            pass  # Template unavailable, proceed with minimal data

        return self._post_json(create_url, data)

    def _create_at_root(self, ny_rel_suffix: str, data: dict) -> dict:
        """Create an entity at root level (e.g., arkivskaper, arkiv)."""
        url = self.find_relation(RELBASE + ny_rel_suffix)
        if not url:
            raise Noark5Error(404, f"No {ny_rel_suffix} relation found at root", self.base_url)

        try:
            default = self._get_json(url)
            for k, v in default.items():
                if k != "_links" and k not in data:
                    data[k] = v
        except Noark5Error:
            pass

        return self._post_json(url, data)

    def create_arkivskaper(
        self, arkivskaper_id: str, navn: str, attributes: dict | None = None
    ) -> dict:
        """Create an archive creator.

        Optional fields: beskrivelse.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data: dict[str, str] = {
            "arkivskaperID": arkivskaper_id,
            "arkivskaperNavn": navn,
        }
        if attributes:
            data.update(attributes)
        return self._create_at_root("arkivstruktur/ny-arkivskaper/", data)

    def create_arkiv(
        self, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create a top-level archive (fonds).

        Optional fields: beskrivelse, arkivstatus, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_at_root("arkivstruktur/ny-arkiv/", data)

    def create_arkivdel(
        self, arkiv_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create an arkivdel (series) under an archive.

        Optional fields: beskrivelse, arkivdelstatus, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv, arkivperiodeStartDato, arkivperiodeSluttDato, referanseForloeper, referanseArvtaker.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            arkiv_url, RELBASE + "arkivstruktur/ny-arkivdel/", data
        )

    def create_mappe(
        self, parent_url: str, tittel: str, beskrivelse: str | None = None, attributes: dict | None = None
    ) -> dict:
        """Create a mappe (file) under a parent.

        Optional fields: mappeID, offentligTittel, noekkelord, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if beskrivelse:
            data["beskrivelse"] = beskrivelse
        if attributes:
            data.update(attributes)
        return self._create_entity(parent_url, RELBASE + "arkivstruktur/ny-mappe/", data)

    def create_registrering(
        self, mappe_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create a registrering (record) under a mappe.

        Optional fields: arkivertDato, arkivertAv, referanseArkivertAv, registreringsID, offentligTittel, beskrivelse, noekkelord, forfatter, dokumentmedium, oppbevaringssted.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            mappe_url, RELBASE + "arkivstruktur/ny-registrering/", data
        )

    def create_dokumentbeskrivelse(
        self, registrering_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create a dokumentbeskrivelse (document description) under a registrering.

        Optional fields: dokumenttype, dokumentstatus, beskrivelse, forfatter, dokumentmedium, oppbevaringssted, tilknyttetRegistreringSom, dokumentnummer, tilknyttetDato, tilknyttetAv, referanseTilknyttetAv, eksternReferanse.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            registrering_url,
            RELBASE + "arkivstruktur/ny-dokumentbeskrivelse/",
            data,
        )

    def create_dokumentobjekt(
        self, dokbeskr_url: str, attributes: dict | None = None
    ) -> dict:
        """Create a dokumentobjekt (document object) under a dokumentbeskrivelse.

        Optional fields: versjonsnummer, variantformat, format, formatDetaljer, referanseDokumentfil, filnavn, sjekksum, mimeType, sjekksumAlgoritme, filstoerrelse.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            dokbeskr_url, RELBASE + "arkivstruktur/ny-dokumentobjekt/", data
        )

    def create_klassifikasjonssystem(
        self, arkivdel_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create a klassifikasjonssystem (classification system) under an arkivdel.

        Optional fields: klassifikasjonstype, beskrivelse, avsluttetDato, avsluttetAv, referanseAvsluttetAv.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            arkivdel_url, RELBASE + "arkivstruktur/ny-klassifikasjonssystem/", data
        )

    def create_klasse(
        self, parent_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create a klasse (class) under a klassifikasjonssystem or another klasse.

        Optional fields: klasseID, beskrivelse, noekkelord, avsluttetDato, avsluttetAv, referanseAvsluttetAv.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            parent_url, RELBASE + "arkivstruktur/ny-klasse/", data
        )

    def create_saksmappe(
        self, parent_url: str, tittel: str, saksaar: int | None = None, attributes: dict | None = None
    ) -> dict:
        """Create a saksmappe (case file) under an arkivdel.

        Optional fields: sakssekvensnummer, saksdato, administrativEnhet, referanseAdministrativEnhet, saksansvarlig, referanseSaksansvarlig, journalenhet, saksstatus, utlaantDato, utlaantTil, referanseUtlaantTil.
        Also inherits from Mappe: mappeID, offentligTittel, beskrivelse, noekkelord, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if saksaar is not None:
            data["saksaar"] = saksaar
        if attributes:
            data.update(attributes)
        return self._create_entity(parent_url, RELBASE + "sakarkiv/ny-saksmappe/", data)

    def create_journalpost(
        self, saksmappe_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create a journalpost (registry entry) under a saksmappe.

        Optional fields: journalaar, journalsekvensnummer, journalpostnummer, journalposttype, journalstatus, journaldato, dokumentetsDato, mottattDato, sendtDato, forfallsdato, offentlighetsvurdertDato, antallVedlegg, utlaantDato, utlaantTil, referanseUtlaantTil, journalenhet.
        Also inherits from Registrering: arkivertDato, arkivertAv, referanseArkivertAv, registreringsID, offentligTittel, beskrivelse, noekkelord, forfatter, dokumentmedium, oppbevaringssted.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            saksmappe_url, RELBASE + "sakarkiv/ny-journalpost/", data
        )

    def create_arkivnotat(
        self, saksmappe_url: str, tittel: str, attributes: dict | None = None
    ) -> dict:
        """Create an arkivnotat (record note) under a saksmappe.

        Optional fields: dokumentetsDato, mottattDato, sendtDato, forfallsdato, offentlighetsvurdertDato, antallVedlegg, utlaantDato, utlaantTil, referanseUtlaantTil.
        Also inherits from Registrering: arkivertDato, arkivertAv, referanseArkivertAv, registreringsID, offentligTittel, beskrivelse, noekkelord, forfatter, dokumentmedium, oppbevaringssted.
        Inherits Arkivenhet (auto-populated): systemID, opprettetDato, opprettetAv, endretDato, endretAv.
        """
        data = {"tittel": tittel}
        if attributes:
            data.update(attributes)
        return self._create_entity(
            saksmappe_url, RELBASE + "sakarkiv/ny-arkivnotat/", data
        )

    # ---- Update operations ----

    def _get_with_etag(self, path: str) -> tuple[dict | list, str]:
        """GET a JSON resource and return (data, etag)."""
        content, res = self._request("GET", path)
        data = json.loads(content.decode("utf-8"))
        etag = res.getheader("ETag") or ""
        # Strip surrounding quotes if present
        if etag.startswith('"') and etag.endswith('"'):
            etag = etag[1:-1]
        return data, etag

    def _patch_json_with_etag(self, path: str, changes: dict, etag: str | None = None) -> dict:
        """PATCH JSON data with merge semantics and If-Match ETag header."""
        body = json.dumps(changes).encode("utf-8")
        url = self._expand_url(path)
        headers = {
            "Accept": "application/vnd.noark5+json, application/json",
            "Content-Type": "application/merge-patch+json",
            "If-Match": etag if etag else "*",
        }
        headers.update(self._auth_headers())
        req = urllib.request.Request(url, data=body, headers=headers)
        req.get_method = lambda: "PATCH"
        try:
            res = urllib.request.urlopen(req)
            return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_resp = e.read() or b""
            raise Noark5Error(e.code, body_resp.decode(errors="replace"), url)

    def update_entity(self, entity_path: str, changes: dict) -> dict:
        """Update an entity with field changes using merge PATCH."""
        _, etag = self._get_with_etag(entity_path)
        return self._patch_json_with_etag(entity_path, changes, etag)

    def create_secondary_entity(self, parent_url: str, entity_type: str, data: dict) -> dict:
        """Create a secondary entity (forfatter, noekkelord, etc.) under a parent.

        The N5TG API models [0..*] and [1..*] fields like 'forfatter' and 'noekkelord' as
        separate entities with their own endpoints rather than direct fields on the
        parent entity. They are created via ny-{entity_type} POST endpoints.

        Common secondary entity types and their field names:
            - merknad: {"tekst": "note text"} (official N5TG relation)
            - kryssreferanse: {"kryssreferanse": "reference text"} (official N5TG relation)
            - forfatter: {"forfatter": "Name"} (Nikita vendor extension)
            - noekkelord: {"noekkelord": "keyword"} (Nikita vendor extension)

        Args:
            parent_url: The self-href URL of the parent entity (e.g., dokumentbeskrivelse).
            entity_type: The type of secondary entity ('merknad', 'kryssreferanse', etc.).
            data: Dict with field values for the new entity.

        Returns:
            The created secondary entity JSON.
        """
        vendor_rel = self._secondary_entity_relation(entity_type)
        return self._create_entity(parent_url, vendor_rel, data)

    @staticmethod
    def _secondary_entity_relation(entity_type: str) -> str:
        """Return the ny-{entity_type} relation URL for a secondary entity type.

        Uses official arkivverket relations when available (N5TG spec), falling back
        to Nikita vendor-specific relations otherwise.

        Official N5TG relations (RELBASE + 'arkivstruktur/ny-*'):
            kryssreferanse, merknad

        Vendor extensions (NIKITA_RELBASE + 'ny-*'):
            forfatter, noekkelord
        """
        # Entity types with official arkivverket relations per N5TG chapter 7.
        official = {"kryssreferanse", "merknad"}
        if entity_type in official:
            return RELBASE + f"arkivstruktur/ny-{entity_type}/"
        # Vendor-specific fallback (Nikita).
        return NIKITA_RELBASE + f"ny-{entity_type}/"

    # ---- Entity type detection ----

    @staticmethod
    def entity_type(url: str) -> str:
        """Detect entity type from URL path. Returns e.g., 'arkiv', 'mappe', etc."""
        known = {
            "klassifikasjonssystem", "dokumentbeskrivelse", "dokumentobjekt",
            "saksmappe", "arkivskaper", "arkivdel", "registrering",
            "journalpost", "arkivnotat", "klasse", "mappe", "arkiv",
        }
        # Check all path segments, rightmost match wins (handles .../klassifikasjon-system/{id}/).
        for segment in reversed(url.rstrip("/").split("/")):
            if segment in known:
                return segment
        return "unknown"

    @staticmethod
    def _self_href(entity: dict) -> str | None:
        """Extract the 'self' href from an entity's _links."""
        for val in entity.get("_links", {}).values():
            if isinstance(val, dict):
                href = Noark5Client.clean_url(val.get("href", ""))
                if href:
                    return href
        return None

    @staticmethod
    def entity_relation_key(entity: dict) -> str | None:
        """Determine the canonical relation key for an entity from its _links.

        Per N5TG ch 6 "Identifisere entitetstype": find self-href, then locate which
        other rel has the same href value — that is the entity's type identifier.
        """
        self_href = Noark5Client._self_href(entity)
        if not self_href:
            return None

        for rel, val in entity.get("_links", {}).items():
            if isinstance(val, dict):
                href = Noark5Client.clean_url(val.get("href", ""))
                if href and (href == self_href or self_href.endswith(href)):
                    if not rel.startswith(("self/", "metadata/", "loggingogsporing/")):
                        return rel
        return None

    @staticmethod
    def _possible_parents(entity_type: str) -> list[str]:
        """Return the possible parent entity types for a given entity type.

        Derived from uml-complete.puml and N5TG ch 7 association directions.
        Inherited types behave like their parents (e.g., saksmappe inherits mappe's parents).
        """
        # Map: child_type -> list of possible parent types
        hierarchy = {
            "arkiv": ["arkiv"],
            "arkivdel": ["arkiv"],
            "klassifikasjonssystem": ["arkivdel"],
            "klasse": ["klassifikasjonssystem", "klasse"],
            "mappe": ["arkivdel", "klasse", "mappe"],
            "saksmappe": ["arkivdel", "klasse", "mappe", "saksmappe"],
            "registrering": ["arkivdel", "klasse", "mappe", "saksmappe"],
            "journalpost": ["arkivdel", "klasse", "mappe", "saksmappe"],
            "arkivnotat": ["arkivdel", "klasse", "mappe", "saksmappe"],
            "dokumentbeskrivelse": ["registrering", "journalpost", "arkivnotat"],
            "dokumentobjekt": ["dokumentbeskrivelse"],
        }
        return hierarchy.get(entity_type, [])

    # ---- Metadata (katalog) operations ----

    def list_metadata(self, filter_str: str | None = None) -> list[dict]:
        """List all metadata catalogs."""
        meta_root_url = self.find_relation(RELBASE + "metadata/")
        if not meta_root_url:
            return []
        data = self._get_json(meta_root_url)
        raw_links = data.get("_links", {})
        catalogs = []
        for rel, val in raw_links.items():
            # Skip ny-* (create) links.
            if "/ny-" in rel or not isinstance(val, dict):
                continue
            href = val.get("href", "")
            templated = val.get("templated", False)
            # Only catalog collection links are templated (OData query params).
            if not templated:
                continue
            clean = self.clean_url(href)
            cat_name = rel.rstrip("/").split("/")[-1]  # e.g. "dokumentmedium"
            catalogs.append({
                "tittel": cat_name,
                "_links": {"self": {"href": clean}},
            })
        if filter_str:
            encoded = self._encode_filter(filter_str)
            return [c for c in catalogs if encoded.lower() in c["tittel"].lower()]
        return catalogs

    def list_metadata_poster(self, catalog_name: str, filter_str: str | None = None) -> list[dict]:
        """List metadata posts (katalogpost) within a specific catalog.

        Args:
            catalog_name: Name of the katalog (e.g., "dokumentmedium", "format").
            filter_str: Optional OData $filter expression.
        """
        meta_root_url = self.find_relation(RELBASE + "metadata/")
        if not meta_root_url:
            return []
        data = self._get_json(meta_root_url)
        raw_links = data.get("_links", {})
        rel = RELBASE + f"metadata/{catalog_name}/"
        val = raw_links.get(rel)
        if not val or not isinstance(val, dict):
            raise Noark5Error(404, f"No catalog named '{catalog_name}'", meta_root_url)
        href = val.get("href", "")
        # Strip OData template params like {?$filter&$orderby&$top&$skip}
        url = self.clean_url(href.split("{")[0])
        if filter_str:
            url += "?$filter=" + self._encode_filter(filter_str)
        result_data = self._get_json(url)
        return result_data.get("results", [])

    def search_metadata(self, catalog_name: str, filter_str: str) -> list[dict]:
        """Search metadata posts within a specific catalog using OData $filter.

        Args:
            catalog_name: Name of the katalog (e.g., "dokumentmedium").
            filter_str: OData $filter expression.

        Returns list of matching katalogpost dicts with kode, kodenavn.
        """
        return self.list_metadata_poster(catalog_name, filter_str)
