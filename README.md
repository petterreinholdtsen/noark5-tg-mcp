# noark5-tg-mcp

Model Context Protocol (MCP) server for interacting with a Noark 5 tjenestegrensesnitt API instance.
Tested on the Nikita Noark 5 Core implementation.

## Overview

This MCP server provides tools for browsing, searching, and managing archive entities through the Noark 5 REST API. It supports:

- **Authentication** via Basic auth (RFC 7617) or OIDC/OAuth2 password grant with auto-renewal
- **HATEOAS navigation** - discovers endpoints by walking `_links` in JSON responses
- **CRUD operations** on all major entity types
- **OData search/filter** across collections

## Available Tools

Run `noark5-tg-mcp --list-tools` to see all available tools with descriptions. The list is auto-discovered from the module, so it stays up to date as tools are added or removed.

### Quick Examples

```bash
# Authenticate and list top-level archives
noark5_set_credentials("http://localhost:8092/noark5v5/", "admin", "password")
noark5_list_arkiv()

# Search for an entity by title
noark5_search_entities("My Archive")

# Navigate HATEOAS links on an entity
noark5_entity_links("https://...entity-url...")

# Filter entities using OData
noark5_filter_entities("https://...collection-url...", "contains(tittel, 'Report')")

# Download a document file (list objekter first, then pick one)
noark5_list_dokumentobjekter("https://...dokumentbeskrivelse-url...")
noark5_download_dokumentobjekt("https://...dokumentobjekt-url...", "/tmp/doc.epub")
```

See `--help` for full usage information.

## Installation

### From source

```bash
git clone <repo-url> && cd noark5-tg-mcp
pip install -e .
```

### Debian package

```bash
dpkg-buildpackage -us -uc
sudo dpkg -i ../python3-noark5-tg-mcp_0.1.0-1_all.deb
```

## Configuration

Set via environment variables or the `noark5_set_credentials` tool:

| Variable | Default | Description |
|----------|---------|-------------|
| `NOARK5_BASE_URL` | `http://localhost:8092/noark5v5/` | API base URL |
| `NOARK5_AUTH_METHOD` | `auto` | Auth method: `basic`, `oidc`, or `auto` |
| `NOARK5_USERNAME` | *(empty)* | Auth username |
| `NOARK5_PASSWORD` | *(empty)* | Auth password |
| `NOARK5_CLIENT_ID` | *(empty)* | OIDC client_id (optional) |
| `NOARK5_ACCESS_TOKEN` | *(empty)* | Pre-existing Bearer token; skips login flow |

### Claude Desktop

```json
{
  "mcpServers": {
    "noark5": {
      "command": "noark5-tg-mcp",
      "env": {
        "NOARK5_BASE_URL": "http://localhost:8092/noark5v5/",
        "NOARK5_USERNAME": "your-username",
        "NOARK5_PASSWORD": "your-password"
      }
    }
  }
}
```

### opencode

Add to `~/.config/opencode/opencode.jsonc`:

```json
{
  "mcp": {
    "noark5": {
      "type": "local",
      "command": ["noark5-tg-mcp"],
      "environment": {
        "NOARK5_BASE_URL": "http://localhost:8092/noark5v5/",
        "NOARK5_USERNAME": "your-username",
        "NOARK5_PASSWORD": "your-password"
      },
      "enabled": true
    }
  }
}
```

Alternatively, skip environment variables and use the `noark5_set_credentials` tool after connecting.

## Testing

```bash
python3 -m pytest --cov=noark5_tg_mcp --cov-report=term-missing
```

## License

GPL-2.0-or-later

## References

- [Noark 5 tjenestegrensesnitt standard](https://github.com/petterreinholdtsen/noark5-tjenestegrensesnitt-standard)
- [Nikita Noark 5 Core implementation](https://github.com/arkivlab/nikita)
- [noark5-tester example clients](https://github.com/petterreinholdtsen/noark5-tester)
