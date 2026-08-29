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

"""MCP server for Noark 5 tjenestegrensesnitt (N5TG) API.

Provides tools for browsing, searching, and managing archive entities through the Model Context Protocol.

Supports two authentication methods:
    - Basic auth (RFC 7617): default, username/password encoded as Base64
    - OIDC / OAuth2 password grant: auto-discovers token endpoint via login/oidc/,
      with automatic token renewal via refresh_token

Configuration via environment variables:
    NOARK5_BASE_URL     - API base URL (default: http://localhost:8092/noark5v5/)
    NOARK5_AUTH_METHOD  - Auth method: "basic" or "oidc" (default: "basic")
    NOARK5_USERNAME     - Auth username
    NOARK5_PASSWORD     - Auth password
    NOARK5_CLIENT_ID    - OIDC client_id (optional, used with oidc)
    NOARK5_ACCESS_TOKEN - Pre-existing Bearer token; skip login flow entirely.

Or set credentials via the noark5_set_credentials tool.
"""


import inspect

import json

import mimetypes

import os

import sys

from argparse import ArgumentParser, RawTextHelpFormatter

try:
    from mcp.server.fastmcp import FastMCP  # MCP 1.x
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # type: ignore[misc] # MCP 2.x


# ---- Server state ----

_server_state: dict = {
    "base_url": os.environ.get("NOARK5_BASE_URL", "http://localhost:8092/noark5v5/"),
    "username": os.environ.get("NOARK5_USERNAME", ""),
    "password": os.environ.get("NOARK5_PASSWORD", ""),
    "auth_method": os.environ.get("NOARK5_AUTH_METHOD", "auto"),
    "client_id": os.environ.get("NOARK5_CLIENT_ID", ""),
    "access_token": os.environ.get("NOARK5_ACCESS_TOKEN", None),
}

from noark5_tg_mcp.client import (  # noqa: E402
    Noark5Client,
    Noark5Error,
    RELBASE,
)


def _get_client() -> Noark5Client:
    """Create an authenticated client from server state."""
    access_token = _server_state.get("access_token")
    if not access_token and (
        not _server_state.get("username") or not _server_state.get("password")
    ):
        raise RuntimeError(
            "Not authenticated. Use noark5_set_credentials or set NOARK5_USERNAME/NOARK5_PASSWORD environment variables."
        )

    client = Noark5Client(
        _server_state["base_url"],
        _server_state["username"],
        _server_state["password"],
        auth_method=_server_state.get("auth_method", "auto"),
        client_id=_server_state.get("client_id", ""),
        access_token=access_token,
    )
    if not access_token:
        client.login()
    return client


def _format_entity(entity: dict, indent: int = 0) -> str:
    """Format a Noark 5 entity for display."""
    prefix = "  " * indent
    lines = []
    if not isinstance(entity, dict):
        return json.dumps(entity, ensure_ascii=False, indent=2)

    key_order = ["systemID", "tittel", "beskrivelse", "arkivstatus", "dokumentmedium"]
    shown = set()

    for key in key_order:
        if key in entity:
            lines.append(f"{prefix}{key}: {entity[key]}")
            shown.add(key)

    for key, value in entity.items():
        if key in ("_links", "_embedded"):
            continue
        if key not in shown:
            if isinstance(value, dict):
                val_str = json.dumps(value, ensure_ascii=False)
            else:
                val_str = str(value)
            lines.append(f"{prefix}{key}: {val_str}")

    links = entity.get("_links", {})
    self_href = links.get("self", {}).get("href", "")
    if self_href and indent < 1:
        lines.append(f"{prefix}URL: {self_href}")

    return "\n".join(lines)


def _format_list(items: list[dict], entity_type: str) -> str:
    """Format a list of entities for display."""
    if not items:
        return f"No {entity_type}(s) found."
    lines = [f"Found {len(items)} {entity_type}(s):"]
    for item in items:
        sid = item.get("systemID", "?")
        tittel = item.get("tittel", "?")
        href = item.get("_links", {}).get("self", {}).get("href", "")
        lines.append(f"  [{sid}] {tittel} ({href})")
    return "\n".join(lines)


# ---- MCP Server ----

mcp = FastMCP(
    "Noark5 Tjenestegrensesnitt",
    instructions=(
        "Interact with a Noark 5 tjenestegrensesnitt (N5TG) API.\n"
        "First call noark5_set_credentials to authenticate, then use the other tools.\n"
        "Entity URLs can be used as references between tool calls.\n\n"
        "IMPORTANT: The N5TG API models [0..*] and [1..*] fields like 'forfatter', 'noekkelord',\n"
        "'merknad', etc. as separate entities (not direct fields on the parent). Use\n"
        "noark5_create_secondary_entity to add them, not noark5_update_entity.\n"
        "The field name inside these sub-entities matches the entity type:\n"
        "  - forfatter: {'forfatter': 'Author Name'}\n"
        "  - noekkelord: {'noekkelord': 'keyword'}\n"
        "  - merknad: {'tekst': 'note text'}\n\n"
        "Entity hierarchy (Norwegian → English):\n"
        "  arkiv = fonds | arkivdel = series | mappe = file |\n"
        "  registrering = record | dokumentbeskrivelse = document description |\n"
        "  dokumentobjekt = document object | saksmappe = case file |\n"
        "  journalpost = registry entry | arkivnotat = record note\n\n"
        "Hierarchy notes:\n"
        "- Some entities can be under different parent types but only ONE at a time:\n"
        "  * mappe: under arkivdel OR klasse OR another mappe\n"
        "  * klasse: under klassifikasjonssystem OR another klasse\n"
        "- Entities that CAN have multiple parents simultaneously:\n"
        "  * dokumentbeskrivelse: linked to 0..* registreringer (e.g., Vedlegg attached to several records)\n"
        "- Some entities accept different child types:\n"
        "  * klasse: can have klasse, mappe, registrering children\n"
        "  * mappe: can have mappe, registrering children\n"
        "  * arkivdel: can have saksmappe, klassifikasjonssystem, mappe, registrering children\n\n"
        "Use noark5_entity_links to discover navigation links on an entity.\n"
        "Links are categorized as: parent (navigate up), children (collections),\n"
        "create (POST endpoints), and query (OData template URLs with $filter support).\n\n"
        "Filtering: Many list tools accept OData filter expressions. For MIME type filtering:\n"
        "  noark5_list_dokumentobjekter(dokbeskr_url, mimetype='application/epub+zip')\n"
        "For general field filtering on any collection URL:\n"
        "  noark5_filter_entities(collection_url, filter_str='mimetype eq ''application/pdf''')\n\n"
        "Downloads: A dokumentbeskrivelse can have multiple dokumentobjekter (different formats,\n"
        "variants, or derived content). To download a file:\n"
        "  1. noark5_list_dokumentobjekter(dokbeskr_url) — pick the objekt you want\n"
        "  2. noark5_download_dokumentobjekt(dokobj_url, output_path)\n"
    ),
)


# ---- Tools ----


@mcp.tool()
def noark5_set_credentials(
    username: str,
    password: str,
    base_url: str = "",
    auth_method: str = "auto",
    client_id: str = "",
) -> str:
    """Set authentication credentials for the Noark 5 API.

    Supports two authentication methods:
      - Basic auth (RFC 7617): username/password encoded as Base64
      - OIDC / OAuth2 password grant: auto-discovers token endpoint via login/oidc/,
        with automatic token renewal via refresh_token

    Args:
        username: The username for authentication.
        password: The password for authentication.
        base_url: Optional API base URL (default from env or http://localhost:8092/noark5v5/).
        auth_method: Authentication method — "auto" (default), "basic", or "oidc".
                     With "auto", the server's root entity is queried to detect
                     available login endpoints; OIDC is preferred over Basic.
        client_id: OIDC client identifier (optional, used with oidc method).

    Returns confirmation and root entity links on success.
    """
    _server_state["username"] = username
    _server_state["password"] = password
    _server_state["auth_method"] = auth_method
    _server_state["client_id"] = client_id
    if base_url:
        _server_state["base_url"] = base_url.rstrip("/") + "/"

    client = Noark5Client(
        _server_state["base_url"],
        username,
        password,
        auth_method=auth_method,
        client_id=client_id,
    )
    try:
        root = client.login()
        links = Noark5Client.parse_links(root)
        link_list = "\n".join(f"  {rel}: {href}" for rel, href in links.items())
        return f"Authenticated as '{username}'.\nAvailable relations:\n{link_list}"
    except Exception as e:
        _server_state["username"] = ""
        _server_state["password"] = ""
        raise RuntimeError(f"Authentication failed: {e}") from e


@mcp.tool()
def noark5_get_root_links() -> str:
    """Get the root API links using authenticated client.

    Returns all available relations from the API root, including those that
    require authentication (arkivstruktur/, metadata/, sakarkiv/). After login,
    this reveals top-level navigation endpoints.

    To find global entity collections, follow the arkivstruktur or sakarkiv
    link to its URL, then use noark5_entity_links on that URL to discover
    OData query templates for each entity type (e.g., dokumentobjekt/{?$filter}).
    The cleaned base URLs can be passed to noark5_filter_entities.
    """
    client = _get_client()
    root = client._get_json(".")
    links = Noark5Client.parse_links(root)
    link_list = "\n".join(f"  {rel}: {href}" for rel, href in links.items())
    return f"API root ({_server_state['base_url']}):\n{link_list}"


@mcp.tool()
def noark5_get_entity(entity_url: str) -> str:
    """Get full details of an entity by its URL.

    Args:
        entity_url: The self-href URL of the entity to fetch.

    Returns the formatted entity with all fields and links.
    """
    client = _get_client()
    entity = client.get_entity(entity_url)
    return (
        _format_entity(entity)
        + f"\n\n--- Full JSON ---\n{json.dumps(entity, ensure_ascii=False, indent=2)}"
    )


def _discover_children_links(raw_links: dict, etype: str) -> list[tuple[str, str]]:
    """Discover child collection links from raw _links dict using relation keys.

    Returns list of (rel, cleaned_href) for URLs that are true child collections.
    Classification is based on the relation key suffix per N5TG spec, not href structure.
    Skips self/canonical rels, create endpoints (ny-*), secondary entities, metadata,
    action endpoints, and parent references.
    """
    # True hierarchy children per entity type (N5TG ch 7 / UML model).
    # These are the ONLY relations that represent structural child collections.
    _true_children = {
        "arkiv": {"arkivdel", "underarkiv"},
        "arkivdel": {"mappe", "saksmappe", "klassifikasjonssystem", "registrering"},
        "klassifikasjonssystem": {"klasse"},
        "klasse": {"underklasse", "mappe", "registrering"},
        "mappe": {"undermappe", "registrering"},
        "saksmappe": {"journalpost", "arkivnotat"},
        "registrering": {"dokumentbeskrivelse"},
        "journalpost": set(),  # secondary entities only (avskrivning, dokumentflyt)
        "arkivnotat": set(),  # secondary entities only (dokumentflyt)
        "dokumentbeskrivelse": {"dokumentobjekt"},
    }

    def _rel_suffix(rel: str) -> str:
        """Get last non-empty path segment from a relation key."""
        return [s for s in rel.split("/") if s][-1]

    children = []
    valid_child_types = _true_children.get(etype, set())

    for rel, val in raw_links.items():
        if not isinstance(val, dict):
            continue

        # Skip create endpoints.
        rel_suffix = _rel_suffix(rel)
        if "ny-" in rel or rel.endswith("/new"):
            continue

        # Only include relations that are valid children for this entity type.
        if rel_suffix not in valid_child_types:
            continue

        href = val.get("href", "")
        clean = Noark5Client.clean_url(href)
        children.append((rel, clean))

    return children


@mcp.tool()
def noark5_list_children(parent_url: str = "", filter_str: str = "") -> str:
    """List all children of an entity using HATEOAS discovery.

    Without parent_url, lists top-level entities (arkiv/fonds and arkivskaper).
    With parent_url, automatically discovers available child collections from the
    entity's links and fetches each type. Mirrors noark5_navigate_up for upward traversal.

    Args:
        parent_url: The self-href URL of the parent entity (omit for top-level listing).
        filter_str: Optional OData $filter expression applied to each collection.

    Returns formatted grouped list of children by type, or error message.
    """
    client = _get_client()
    results_by_type = {}  # type_name -> list[dict]

    if not parent_url.strip():
        # Top-level listing: arkiv + arkivskaper from root.
        for top_rel, top_type in [
            (RELBASE + "arkivstruktur/arkiv/", "arkiv"),
            (RELBASE + "arkivstruktur/arkivskaper/", "arkivskaper"),
        ]:
            url = client.find_relation(top_rel)
            if not url:
                continue
            if filter_str:
                url += "?$filter=" + client._encode_filter(filter_str)
            data = client._get_json(url)
            results_by_type[top_type] = data.get("results", [])

        # Format output.
        lines = ["Top-level entities (no parent specified):"]
        for etype_name, items in results_by_type.items():
            if not items:
                lines.append(f"\n  No {etype_name}(s) found.")
                continue
            lines.append(f"\n  [{len(items)}] {etype_name}:")
            for item in items:
                sid = item.get("systemID", "?")
                tittel = (
                    item.get("tittel")
                    or item.get("filnavn")
                    or item.get("arkivskaperNavn")
                    or "?"
                )
                href = Noark5Client._self_href(item) or ""
                lines.append(f"    [{sid}] {tittel} ({href})")
        return "\n".join(lines)

    # Parent specified: discover children via HATEOAS.
    entity = client.get_entity(parent_url)
    title = entity.get("tittel") or entity.get("arkivskaperNavn") or "?"
    etype = Noark5Client.entity_type(parent_url)
    self_href = Noark5Client._self_href(entity) or parent_url

    child_links = _discover_children_links(entity.get("_links", {}), etype)
    if not child_links:
        return f"No children found for {title} ({etype})."

    lines = [f"Children of {title} ({etype}):"]

    for rel, coll_url in child_links:
        # Derive type name from the URL's last path segment.
        url_path = Noark5Client.clean_url(coll_url)
        last_segment = url_path.rstrip("/").split("/")[-1]
        type_name = last_segment or "unknown"

        fetch_url = coll_url
        if filter_str:
            fetch_url += "?$filter=" + client._encode_filter(filter_str)

        try:
            data = client._get_json(fetch_url)
            items = data.get("results", [])
        except Noark5Error as e:
            lines.append(f"\n  [{type_name}] Error fetching collection: {e}")
            continue

        if not items:
            lines.append(f"\n  No {type_name}(s) found.")
            continue

        lines.append(f"\n  [{len(items)}] {type_name}:")
        for item in items:
            sid = item.get("systemID", "?")
            tittel = (
                item.get("tittel")
                or item.get("filnavn")
                or item.get("arkivskaperNavn")
                or "?"
            )
            href = Noark5Client._self_href(item) or ""
            lines.append(f"    [{sid}] {tittel} ({href})")

    return "\n".join(lines)


@mcp.tool()
def noark5_search_entities(query: str, filter_str: str = "") -> str:
    """Global search across all entity types using $search (title match) with optional $filter.

    Searches all collections found under arkivstruktur and sakarkiv for entities
    whose title matches the query. An optional OData $filter expression is ANDed
    with the $search term to further narrow results.

    Use noark5_search_entities when you want to find entities globally by keyword,
    optionally constrained by a condition (e.g., date range, field value).

    Use noark5_filter_entities instead when you need precise filtering on a known
    collection URL discovered via noark5_entity_links or noark5_list_children.
    Filter operates on one collection at a time with full OData expression support.

    Args:
        query: The search term to match against entity titles (full-text, case-insensitive).
        filter_str: Optional OData $filter expression applied in addition to the
                    search term (e.g., 'opprettetDato ge 2026-01-01T00:00:00Z').

    Returns list of matching entities with their URLs, titles, and types.
    """
    client = _get_client()
    results = client.search_entities(query, filter_str or None)
    if not results:
        msg = f"No entities found matching '{query}'."
        if filter_str:
            msg += f" (filter: {filter_str})"
        return msg

    lines = [f"Found {len(results)} entity/entities matching '{query}'"]
    if filter_str:
        lines[-1] += f" (filtered by: {filter_str})"
    lines[-1] += ":"
    for href, tittel in results:
        etype = Noark5Client.entity_type(href)
        lines.append(f"  [{etype}] {tittel}\n    URL: {href}")
    return "\n".join(lines)


@mcp.tool()
def noark5_create_arkivskaper(
    arkivskaper_id: str, navn: str, attributes: str = "{}"
) -> str:
    """Create a new arkivskaper (archive creator).

    Args:
        arkivskaper_id: The unique identifier for the archive creator.
        navn: The name of the archive creator.
        attributes: Optional JSON object with additional fields. All optional: beskrivelse.

    Returns details of the created arkivskaper including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_arkivskaper(arkivskaper_id, navn, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created arkivskaper '{navn}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_arkiv(tittel: str, attributes: str = "{}") -> str:
    """Create a new top-level archive (fonds).

    Args:
        tittel: The title of the new fonds.
        attributes: Optional JSON object with additional fields. All optional: beskrivelse, arkivstatus, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv.

    Returns details of the created fonds including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_arkiv(tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created fonds '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_arkivdel(arkiv_url: str, tittel: str, attributes: str = "{}") -> str:
    """Create a new arkivdel (series/partition) under a fonds.

    Args:
        arkiv_url: The self-href URL of the parent fonds.
        tittel: The title of the new arkivdel.
        attributes: Optional JSON object with additional fields. All optional: beskrivelse, arkivdelstatus, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv, arkivperiodeStartDato, arkivperiodeSluttDato, referanseForloeper, referanseArvtaker.

    Returns details of the created arkivdel including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_arkivdel(arkiv_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created arkivdel '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_mappe(
    parent_url: str, tittel: str, beskrivelse: str = "", attributes: str = "{}"
) -> str:
    """Create a new mappe (file) under a parent entity.

    Args:
        parent_url: The self-href URL of the parent (arkivdel, klasse, or mappe).
        tittel: The title of the new file.
        beskrivelse: Optional description for the file.
        attributes: Optional JSON object with additional fields. All optional: mappeID, offentligTittel, noekkelord, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv.

    Returns details of the created mappe including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_mappe(parent_url, tittel, beskrivelse or None, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created mappe '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_registrering(
    mappe_url: str, tittel: str, attributes: str = "{}"
) -> str:
    """Create a new registrering (registration) under a mappe.

    Args:
        mappe_url: The self-href URL of the parent mappe.
        tittel: The title of the new registration.
        attributes: Optional JSON object with additional fields. All optional: arkivertDato, arkivertAv, referanseArkivertAv, registreringsID, offentligTittel, beskrivelse, noekkelord, forfatter, dokumentmedium, oppbevaringssted.

    Returns details of the created registrering including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_registrering(mappe_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created registrering '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_dokumentbeskrivelse(
    registrering_url: str, tittel: str, attributes: str = "{}"
) -> str:
    """Create a new dokumentbeskrivelse (document description) under a registrering.

    Args:
        registrering_url: The self-href URL of the parent registrering.
        tittel: The title of the document description.
        attributes: Optional JSON object with additional fields. All optional: dokumenttype, dokumentstatus, beskrivelse, forfatter, dokumentmedium, oppbevaringssted, tilknyttetRegistreringSom, dokumentnummer, tilknyttetDato, tilknyttetAv, referanseTilknyttetAv, eksternReferanse.

    Returns details of the created dokumentbeskrivelse including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_dokumentbeskrivelse(registrering_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created dokumentbeskrivelse '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_klassifikasjonssystem(
    arkivdel_url: str, tittel: str, attributes: str = "{}"
) -> str:
    """Create a new klassifikasjonssystem (classification system) under an arkivdel.

    Args:
        arkivdel_url: The self-href URL of the parent arkivdel.
        tittel: The title of the classification system.
        attributes: Optional JSON object with additional fields. All optional: klassifikasjonstype, beskrivelse, avsluttetDato, avsluttetAv, referanseAvsluttetAv.

    Returns details of the created klassifikasjonssystem including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_klassifikasjonssystem(arkivdel_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created klassifikasjonssystem '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_klasse(parent_url: str, tittel: str, attributes: str = "{}") -> str:
    """Create a new klasse (class) under a klassifikasjonssystem or another klasse.

    Args:
        parent_url: The self-href URL of the parent (klassifikasjonssystem or klasse).
        tittel: The title of the class.
        attributes: Optional JSON object with additional fields. All optional: klasseID, beskrivelse, noekkelord, avsluttetDato, avsluttetAv, referanseAvsluttetAv.

    Returns details of the created klasse including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_klasse(parent_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created klasse '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_saksmappe(
    parent_url: str, tittel: str, saksaar: int = 0, attributes: str = "{}"
) -> str:
    """Create a new saksmappe (case file) under an arkivdel.

    Args:
        parent_url: The self-href URL of the parent arkivdel.
        tittel: The title of the case file.
        saksaar: Optional case year. Set to 0 or omit to let the server auto-assign.
        attributes: Optional JSON object with additional fields. All optional: sakssekvensnummer, saksdato, administrativEnhet, referanseAdministrativEnhet, saksansvarlig, referanseSaksansvarlig, journalenhet, saksstatus, utlaantDato, utlaantTil, referanseUtlaantTil. Also inherits from Mappe: mappeID, offentligTittel, beskrivelse, noekkelord, dokumentmedium, oppbevaringssted, avsluttetDato, avsluttetAv, referanseAvsluttetAv.

    Returns details of the created saksmappe including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_saksmappe(
        parent_url, tittel, saksaar if saksaar else None, attrs or None
    )
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created saksmappe '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_journalpost(
    saksmappe_url: str, tittel: str, attributes: str = "{}"
) -> str:
    """Create a new journalpost (registry entry) under a saksmappe.

    Args:
        saksmappe_url: The self-href URL of the parent saksmappe.
        tittel: The title of the registry entry.
        attributes: Optional JSON object with additional fields. All optional: journalaar, journalsekvensnummer, journalpostnummer, journalposttype, journalstatus, journaldato, dokumentetsDato, mottattDato, sendtDato, forfallsdato, offentlighetsvurdertDato, antallVedlegg, utlaantDato, utlaantTil, referanseUtlaantTil, journalenhet. Also inherits from Registrering: arkivertDato, arkivertAv, referanseArkivertAv, registreringsID, offentligTittel, beskrivelse, noekkelord, forfatter, dokumentmedium, oppbevaringssted.

    Returns details of the created journalpost including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_journalpost(saksmappe_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created journalpost '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_arkivnotat(
    saksmappe_url: str, tittel: str, attributes: str = "{}"
) -> str:
    """Create a new arkivnotat (record note) under a saksmappe.

    Args:
        saksmappe_url: The self-href URL of the parent saksmappe.
        tittel: The title of the record note.
        attributes: Optional JSON object with additional fields. All optional: dokumentetsDato, mottattDato, sendtDato, forfallsdato, offentlighetsvurdertDato, antallVedlegg, utlaantDato, utlaantTil, referanseUtlaantTil. Also inherits from Registrering: arkivertDato, arkivertAv, referanseArkivertAv, registreringsID, offentligTittel, beskrivelse, noekkelord, forfatter, dokumentmedium, oppbevaringssted.

    Returns details of the created arkivnotat including its URL.
    """
    client = _get_client()
    attrs = json.loads(attributes) if attributes.strip() else {}
    result = client.create_arkivnotat(saksmappe_url, tittel, attrs or None)
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created arkivnotat '{tittel}'\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_update_entity(entity_url: str, changes: str = "{}") -> str:
    """Update one or more fields on an entity using merge PATCH.

    Accepts a JSON object mapping field names to new values. Multiple fields
    can be updated in a single call. Only the specified fields are sent;
    unchanged fields are preserved server-side (RFC 7396 merge semantics).

    NOTE: This does NOT work for [0..*] or [1..*] sub-resources like 'forfatter' or
    'noekkelord', which are modelled as separate entities by the API service. Use
    noark5_create_secondary_entity instead to add those.

    Examples:
      - Update single field: '{"tittel": "New Title"}'
      - Update multiple fields: '{"tittel": "New", "beskrivelse": "Description"}'
      - Structured field: '{"dokumenttype": {"kode": "U"}}'

    To move an entity to a new parent, include '_links' in changes.
    First find the parent link's rel key using noark5_list_parents or noark5_entity_links.
    Examples:

      - Move registrering to another mappe:
          '{"_links": {"https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/mappe/": {"href": "<new_mappe_url>"}}}'

      - Move mappe to another arkivdel:
          '{"_links": {"https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/arkivdel/": {"href": "<new_arkivdel_url>"}}}'

    Args:
        entity_url: The self-href URL of the entity to update.
        changes: JSON object mapping field names to new values (e.g., '{"tittel": "New"}').

    Returns details of the updated entity.
    """
    client = _get_client()
    parsed_changes = json.loads(changes) if changes.strip() else {}
    result = client.update_entity(entity_url, parsed_changes)
    field_names = ", ".join(parsed_changes.keys()) or "(empty)"
    return f"Updated '{field_names}' on entity.\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_create_secondary_entity(
    parent_url: str, entity_type: str, field_name: str, field_value: str
) -> str:
    """Create a secondary [0..*]/[1..*] entity under a parent (e.g., forfatter, noekkelord).

    In N5TG, fields with [0..*] or [1..*] cardinality are modelled as separate entities.
    Use this instead of noark5_update_entity to add them.

    Common types and their field names:
        - forfatter: {'forfatter': 'Author Name'}
        - noekkelord: {'noekkelord': 'keyword'}
        - merknad: {'tekst': 'note text'}
        - kryssreferanse: {'kryssreferanse': 'reference'}

    Args:
        parent_url: The self-href URL of the parent entity (e.g., dokumentbeskrivelse).
        entity_type: The type ('forfatter', 'noekkelord', 'merknad', etc.).
        field_name: The field name within the secondary entity.
        field_value: The value for that field.

    Returns details of the created secondary entity.
    """
    client = _get_client()
    result = client.create_secondary_entity(
        parent_url, entity_type, {field_name: field_value}
    )
    href = result.get("_links", {}).get("self", {}).get("href", "")
    return f"Created secondary entity '{entity_type}' with value '{field_value}'.\nURL: {href}\n\n{_format_entity(result)}"


@mcp.tool()
def noark5_delete_entity(entity_url: str) -> str:
    """Delete an entity.

    Args:
        entity_url: The self-href URL of the entity to delete.

    Returns confirmation or error message.
    """
    client = _get_client()
    result = client.delete_entity(entity_url)
    return f"Entity deleted successfully.\nResponse: {result}"


@mcp.tool()
def noark5_list_parents(entity_url: str) -> str:
    """List all parent entities of an entity using HATEOAS discovery.

    Uses N5TG-compliant link detection (per chapter 6 "Identifisere entitetstype" and
    "Rekursive entitetshierarkier") to find parent links via the entity's relation key
    and over{xx} relations for recursive hierarchies.

    Some entities can have multiple parents simultaneously (e.g., dokumentbeskrivelse
    linked to several registreringer). Others have only one parent at a time but can be
    under different parent types (e.g., mappe under arkivdel, klasse, or another mappe).
    This tool finds all current parents and returns details about each.

    Args:
        entity_url: The self-href URL of the entity to list parents for.

    Returns formatted list of parent entities with their titles, types, and URLs.
    """
    client = _get_client()
    entity = client.get_entity(entity_url)
    raw_links = entity.get("_links", {})
    if not raw_links:
        return "No links found for this entity."

    title = entity.get("tittel", "?")
    etype = Noark5Client.entity_type(entity_url)
    lines = [f"Parents of {title} ({etype}):"]

    # Determine possible parent types from UML hierarchy.
    possible_parents = Noark5Client._possible_parents(etype)
    if not possible_parents:
        return f"No known parents for entity type '{etype}'."

    skip_prefixes = ("metadata/", "loggingogsporing/", "login/")
    # Known child-collection and action rels that are NOT parents.
    skip_child_rels = (
        "undermappe/",  # children: sub-mapper under this mappe/saksmappe
        "avslutt-mappe/",  # action endpoint (POST-only)
        "merknad/",  # secondary entity collection
        "kryssreferanse/",  # secondary entity collection
    )
    parent_rels = []

    for rel, val in raw_links.items():
        if not isinstance(val, dict):
            continue

        href = val.get("href", "")
        clean = Noark5Client.clean_url(href)

        # Skip internal/system links and collection endpoints.
        if any(clean.startswith(p) for p in skip_prefixes):
            continue
        if "ny-" in rel or rel.endswith("/new"):
            continue
        if val.get("templated", False):
            continue
        if any(rel.endswith(cr) for cr in skip_child_rels):
            continue

        # Skip self-referencing canonical relation (entity points to itself).
        entity_self = Noark5Client._self_href(entity) or ""
        if clean == Noark5Client.clean_url(entity_self):
            continue

        # Check if this link matches a known parent relation key.
        is_parent = False
        for parent_type in possible_parents:
            # Non-recursive: parent type != current type → check arkivdel/, klasse/ etc.
            if parent_type != etype and rel.endswith(parent_type + "/"):
                is_parent = True
                break
            # Recursive: same type → check over{xx}/ relations per N5TG ch 6.
            if parent_type == etype:
                if etype == "klasse" and rel.endswith("overklasse/"):
                    is_parent = True
                    break
                if etype in ("mappe", "saksmappe") and rel.endswith("overmappe/"):
                    is_parent = True
                    break

        if is_parent:
            parent_rels.append((rel, href))

    if not parent_rels:
        return f"No parent entities found for {title}."

    for rel, href in parent_rels:
        try:
            data = client.get_entity(href)
            # Parent links return a collection {"count": N, "results": [...]}.
            # Extract the actual entity via results[0]._links.self.href.
            if isinstance(data, dict) and "results" in data:
                first = data["results"][0]
                self_link = Noark5Client._self_href(first)
                if self_link:
                    parent = client.get_entity(self_link)
                    purl = self_link
                else:
                    parent = first
                    purl = href
            elif isinstance(data, dict):
                parent = data
                purl = href
            else:
                lines.append(f"\n  Parent via {rel}:")
                lines.append(f"    Unexpected response from {href}")
                continue

            ptitle = parent.get("tittel", "?")
            ptype = Noark5Client.entity_type(purl)
            psid = parent.get("systemID", "?")
            lines.append(f"\n  Parent via {rel}:")
            lines.append(f"    Type: {ptype}")
            lines.append(f"    Title: {ptitle}")
            lines.append(f"    systemID: {psid}")
            lines.append(f"    URL: {purl}")
        except Noark5Error as e:
            lines.append(f"\n  Parent via {rel}:")
            lines.append(f"    Error fetching parent: {e}")

    return "\n".join(lines)


@mcp.tool()
def noark5_entity_links(entity_url: str) -> str:
    """List all navigation links on an entity, categorized by type.

    Returns links organized into four categories:
      - Parent links: navigate up the hierarchy (note: entities can have multiple parents)
      - Children collections: list sub-entities (e.g., mapper under arkivdel)
      - Create endpoints: POST to create new entities (ny-* relations)
      - Query templates: OData URLs with {?$filter} for filtered queries

    Useful to discover what navigation is possible from any entity.
    Use noark5_filter_entities with a query template URL for filtered listing.
    Use noark5_navigate_up to see details of all parent entities at once.

    Args:
        entity_url: The self-href URL of the entity to inspect.

    Returns categorized list of links with URLs and descriptions.
    """
    client = _get_client()
    entity = client.get_entity(entity_url)
    raw_links = entity.get("_links", {})
    if not raw_links:
        return "No links found for this entity."

    title = entity.get("tittel", "?")
    sid = entity.get("systemID", "?")
    etype = Noark5Client.entity_type(entity_url)
    lines = [f"Links for {title} ({etype}, systemID: {sid}):"]

    # Categorize each link
    parent_links = []
    children_collections = []
    create_endpoints = []
    query_templates = []

    skip_rels = {"self", "metadata", "loggingogsporing"}
    skip_rel_substrings = ("/metadata/", "/loggingogsporing/", "/login/")

    for rel, val in raw_links.items():
        if rel in skip_rels or not isinstance(val, dict):
            continue

        # Skip internal/system relations by checking the rel key itself.
        if any(sub in rel for sub in skip_rel_substrings):
            continue

        href = val.get("href", "")
        clean = Noark5Client.clean_url(href)
        templated = val.get("templated", False)

        # Skip self-referencing canonical relation (entity points to itself).
        entity_self = Noark5Client._self_href(entity) or ""
        if clean == Noark5Client.clean_url(entity_self):
            continue

        if "ny-" in rel or rel.endswith("/new"):
            create_endpoints.append((rel, clean))
        elif templated:
            query_templates.append((rel, href))  # Keep template params visible
        else:
            # Check if this relation is a known parent for this entity type.
            # Some relations (e.g., registrering/) are children for some types but
            # parents for others (dokumentbeskrivelse can have multiple parents).
            possible_parents = Noark5Client._possible_parents(etype)
            is_parent_rel = False
            for parent_type in possible_parents:
                if parent_type != etype and rel.endswith(parent_type + "/"):
                    is_parent_rel = True
                    break
                # Recursive: same type → check over{xx}/ relations.
                if parent_type == etype:
                    if etype == "klasse" and rel.endswith("overklasse/"):
                        is_parent_rel = True
                        break
                    if etype in ("mappe", "saksmappe") and rel.endswith("overmappe/"):
                        is_parent_rel = True
                        break
            if is_parent_rel:
                parent_links.append((rel, clean))
            elif "/" + etype + "/" in clean:
                # href is on this entity's own path (e.g., /dokumentobjekt/) → child collection
                children_collections.append((rel, clean))
            else:
                # Points to a different entity → parent link
                parent_links.append((rel, clean))

    if parent_links:
        lines.append("\n  Parent links (navigate up):")
        for rel, href in parent_links:
            lines.append(f"    {rel}")
            lines.append(f"      -> {href}")

    if children_collections:
        lines.append("\n  Children collections:")
        for rel, href in children_collections:
            lines.append(f"    {rel}")
            lines.append(f"      -> {href}")

    if create_endpoints:
        lines.append("\n  Create endpoints (POST):")
        for rel, href in create_endpoints:
            lines.append(f"    {rel}")
            lines.append(f"      -> {href}")

    if query_templates:
        lines.append("\n  Query templates (OData $filter):")
        for rel, href in query_templates:
            clean = Noark5Client.clean_url(href)
            tmpl = href[len(clean) :]  # Show the template part like {?$filter}
            lines.append(f"    {rel}{tmpl}")
            lines.append(f"      -> base: {clean}")

    if not any([parent_links, children_collections, create_endpoints, query_templates]):
        return f"No navigable links found for this entity ({title})."

    return "\n".join(lines)


@mcp.tool()
def noark5_list_metadata(catalog_name: str = "", filter_str: str = "") -> str:
    """List or search metadata posts (katalogpost) within a specific catalog.

    Use `catalog_name` to select the target katalog (e.g., "dokumentmedium", "format").
    Omit `filter_str` to list all entries in small catalogs, or provide an OData filter
    to narrow down results in large ones (postal codes, countries, etc.).

    Common filter examples:
      - Exact code match: 'kode eq ''E'''
      - Title substring: 'contains(kodenavn, ''EPUB'')'
      - Multiple conditions: 'kode eq ''U'' and contains(kodenavn, ''UNKNOWN'')'

    Args:
        catalog_name: Name of the metadata katalog to search in (e.g., "dokumentmedium",
                      "format"). Leave empty to list all available catalogs.
        filter_str: Optional OData $filter expression applied within the catalog.

    Returns formatted list of matching metadata entries with kode and kodenavn.
    """
    client = _get_client()
    if not catalog_name:
        catalogs = client.list_metadata()
        if not catalogs:
            return "No metadata catalogs found."
        lines = [f"Available metadata catalogs ({len(catalogs)}):"]
        for cat in catalogs:
            lines.append(f"  - {cat.get('tittel', '?')}")
        return "\n".join(lines)

    results = client.list_metadata_poster(catalog_name, filter_str)
    if not results:
        return f"No metadata posts found in katalog '{catalog_name}'."

    lines = [f"Katalog '{catalog_name}': {len(results)} post(s):"]
    for r in results:
        kode = r.get("kode", "?")
        kodenavn = r.get("kodenavn", "?")
        lines.append(f"  kode={kode}, kodenavn={kodenavn}")

    return "\n".join(lines)


@mcp.tool()
def noark5_filter_entities(collection_url: str, filter_str: str = "") -> str:
    """List or filter entities from a specific collection URL using OData $filter.

    Operates on one collection at a time with full OData expression support.
    Use this when you have a known collection URL from noark5_entity_links or
    noark5_list_children and need precise field-level filtering.

    Contrast with noark5_search_entities, which searches globally across all
    entity types using $search (title/text matching) — optionally combined
    with $filter for additional constraints.

    Common filter examples:
      - Filter by MIME type: 'mimetype eq ''application/epub+zip'''
      - Filter by title substring: 'contains(tittel, ''MyArchive'')'
      - Multiple conditions: 'mimetype eq ''application/pdf'' and contains(filnavn, ''report'')'

    Args:
        collection_url: The base URL of the collection endpoint (without {?$filter}).
                        E.g., from noark5_entity_links query template "base" URLs.
        filter_str: Optional OData $filter expression. Leave empty to list all entities.

    Returns formatted list with systemID, title, and URL for each matching entity.
    """
    client = _get_client()
    items = client.filter_collection(collection_url, filter_str or None)
    if not items:
        return f"No entities found{f' matching filter: {filter_str}' if filter_str else ''}."

    lines = [f"Found {len(items)} entity/entities"]
    if filter_str:
        lines[-1] += f" (filtered by: {filter_str})"
    lines[-1] += ":"
    for item in items:
        sid = item.get("systemID", "?")
        tittel = item.get("tittel", "") or item.get("filnavn", "(no title)")
        href = item.get("_links", {}).get("self", {}).get("href", "")
        extra = []
        if item.get("mimetype"):
            extra.append(f"mime={item['mimetype']}")
        if item.get("storrelse"):
            extra.append(f"{item['storrelse']} bytes")
        extra_str = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"  [{sid}] {tittel}{extra_str}")
        lines.append(f"    URL: {href}")

    return "\n".join(lines)


@mcp.tool()
def noark5_download_dokumentobjekt(dokobj_url: str, output_path: str = "") -> str:
    """Download file content from a dokumentobjekt.

    Resolves the referanseFil HATEOAS link on the given dokumentobjekt and
    downloads the binary content to disk (per N5TG chapter 6). Use
    noark5_list_dokumentobjekter first to find the desired objekt URL.

    Args:
        dokobj_url: The self-href URL of the dokumentobjekt to download.
        output_path: Optional file path to save the downloaded content.
                     If empty, a temporary file in /tmp/ is created with a random name.
                     Note: Temporary files are NOT removed automatically. It is the user's
                     responsibility to clean them up when no longer needed.

    Returns saved file path and metadata.
    """
    client = _get_client()
    data = client.download_dokumentobjekt(dokobj_url)

    if not output_path:
        import uuid, tempfile

        output_path = os.path.join(
            tempfile.gettempdir(), f"noark5-download-{uuid.uuid4().hex}"
        )

    with open(output_path, "wb") as f:
        f.write(data)
    mime = mimetypes.guess_type(output_path)[0] or "application/octet-stream"
    return f"Downloaded {len(data)} bytes to {output_path} (MIME: {mime})"


@mcp.tool()
def noark5_upload_file(
    entity_url: str, file_path: str, mime_type: str = "application/octet-stream"
) -> str:
    """Upload a file to an entity that has a fil relation key.

    Any entity whose _links contains the relation key
    https://rel.arkivverket.no/noark5/v5/api/arkivstruktur/fil/ supports upload.
    (Use noark5_entity_links or noark5_list_children to discover this.)

    Resolves the href of the fil relation from the entity's _links,
    then POSTs raw binary content to that URL. The server returns JSON containing all
    created and updated instances — typically a dokumentobjekt with file metadata
    (filnavn, mimeType, checksum, etc), plus any other entities it created during
    the upload (e.g., an embedded dokumentbeskrivelse when uploading from a registrering).

    Args:
        entity_url: The self-href URL of any entity with a fil relation key.
        file_path: Path to a local file to upload.
        mime_type: MIME type of the uploaded file (default: application/octet-stream).

    Returns details of all created/updated entities from the server response.
    """
    with open(file_path, "rb") as f:
        file_data = f.read()

    client = _get_client()
    result = client.upload_file(entity_url, file_data, mime_type)
    return f"Uploaded {len(file_data)} bytes.\n\n{_format_entity(result)}"


# ---- Main entry point ----


def _list_tools() -> list[tuple[str, str]]:
    """Collect MCP tool names and descriptions from this module."""
    mod = sys.modules[__name__]
    tools = []
    for name in sorted(inspect.getmembers(mod, inspect.isfunction)):
        fname = name[0]
        if not fname.startswith("noark5_"):
            continue
        func = name[1]
        doc = (func.__doc__ or "").strip().split("\n")[0]
        tools.append((fname, doc))
    return tools


def _list_tools_full() -> list[tuple[str, str]]:
    """Collect MCP tool names and full docstrings from this module."""
    import textwrap

    mod = sys.modules[__name__]
    tools = []
    for name in sorted(inspect.getmembers(mod, inspect.isfunction)):
        fname = name[0]
        if not fname.startswith("noark5_"):
            continue
        func = name[1]
        doc = (func.__doc__ or "").strip()
        # Dedent and collapse whitespace for clean output.
        indented = textwrap.indent(doc, "  ")
        tools.append((fname, indented))
    return tools


def main() -> None:
    """CLI entry point for the noark5-tg-mcp server."""
    parser = ArgumentParser(
        description="MCP server for Noark 5 tjenestegrensesnitt (N5TG) API.",
        formatter_class=RawTextHelpFormatter,
        epilog="""\
Environment variables:
  NOARK5_BASE_URL     API base URL (default: http://localhost:8092/noark5v5/)
  NOARK5_USERNAME     Auth username for Basic or OIDC login
  NOARK5_PASSWORD     Auth password (required with NOARK5_USERNAME)
  NOARK5_AUTH_METHOD  Auth method: auto, basic, or oidc (default: auto)
  NOARK5_CLIENT_ID    OIDC client_id (optional, used with oidc method)
  NOARK5_ACCESS_TOKEN Pre-existing access token (skips login if set)

Usage examples:
  noark5-tg-mcp                          Run with env var settings
  noark5-tg-mcp --base-url URL           Override API base URL
  noark5-tg-mcp --list-tools             List available MCP tools
  noark5-tg-mcp --list-tools-full        List tools with full instructions""",
    )

    parser.add_argument(
        "--base-url",
        default=_server_state["base_url"],
        help="API base URL (overrides NOARK5_BASE_URL environment variable)",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List available MCP tools and exit",
    )
    parser.add_argument(
        "--list-tools-full",
        action="store_true",
        help="List available MCP tools with full instructions and exit",
    )

    args = parser.parse_args()

    if args.list_tools_full:
        tools = _list_tools_full()
        print(f"Available MCP tools ({len(tools)}):\n")
        for name, doc in tools:
            print(f"{name}:")
            print(doc)
            print()
        return

    if args.list_tools:
        tools = _list_tools()
        col_width = max(len(t[0]) for t in tools) + 2
        print(f"Available MCP tools ({len(tools)}):")
        for name, desc in tools:
            print(f"  {name:{col_width}}{desc}")
        return

    if args.base_url:
        _server_state["base_url"] = args.base_url.rstrip("/") + "/"

    print(
        f"Noark 5 MCP Server starting, base URL: {_server_state['base_url']}",
        file=sys.stderr,
    )
    mcp.run()


if __name__ == "__main__":
    main()
