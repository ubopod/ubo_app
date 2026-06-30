# MCP service — connecting clients to the gateway

This service aggregates every **enabled** MCP server you've configured on the
device behind a single, token-gated HTTP endpoint (the *gateway*). Any MCP
client — Claude Code, Claude Desktop, Codex, MCP Inspector, Hermes, OpenClaw, or
your own — connects to this one endpoint instead of running MCP servers itself.

> Looking for how the gateway works internally (the FastMCP proxy, the
> persistent-socket rebuild, env vars)? See
> [`ubo-service/README.md`](./ubo-service/README.md). This file is only about
> **connecting clients**.

## Endpoints

The gateway listens on port **4322** and serves the same aggregated tools over
two transports:

| Transport | Path | Example URL |
| --- | --- | --- |
| **Streamable HTTP** (recommended) | `/mcp` | `http://<host>:4322/mcp` |
| **SSE** (legacy) | `/sse` | `http://<host>:4322/sse` |

Every request must carry the gateway bearer token:

```
Authorization: Bearer <TOKEN>
```

Requests without it get `401 Unauthorized`.

### Which `<host>`?

- **On the device itself** (SSH'd in, or a client running on the Pi):
  `localhost` → `http://localhost:4322/mcp`.
- **From another machine on the LAN** (Claude Desktop on your laptop): use the
  device's hostname or IP, e.g. `http://<hostname>.local:4322/mcp`. The gateway
  binds `0.0.0.0`, so it's reachable across the LAN.
- **From a container on the device** (Hermes, OpenClaw): `localhost` points at
  the *container*, not the host — see [Containers](#containers-hermes-openclaw-).

### Getting the token

On the device UI: **Settings → Assistant → MCP Tools → "Show gateway token"**.
That reveals the bearer token plus the ready-to-copy endpoint URLs (with the
device hostname already substituted).

The token is also the `mcp_gateway_token` key in the device secrets file
(`~/.config/ubo/.secrets.env`) if you'd rather read it over SSH.

---

## Client setup

In every block below, replace `<TOKEN>` with your gateway token and pick the
right `<host>` per [Which host?](#which-host) above.

### Claude Code

Claude Code supports remote MCP servers natively — no bridge needed. Streamable
HTTP is recommended:

```bash
claude mcp add --transport http ubo-gateway http://<host>:4322/mcp \
  --header "Authorization: Bearer <TOKEN>"
```

SSE also works (deprecated, but matches the `/sse` endpoint):

```bash
claude mcp add --transport sse ubo-gateway http://<host>:4322/sse \
  --header "Authorization: Bearer <TOKEN>"
```

Add `--scope project` to share it via a checked-in `.mcp.json`, or `--scope
user` to enable it across all your projects (default scope is `local`). The
resulting `.mcp.json` entry looks like:

```json
{
  "mcpServers": {
    "ubo-gateway": {
      "type": "http",
      "url": "http://<host>:4322/mcp",
      "headers": { "Authorization": "Bearer <TOKEN>" }
    }
  }
}
```

### Codex CLI

Codex connects to Streamable HTTP servers natively. Edit `~/.codex/config.toml`
(or a project-scoped `.codex/config.toml`):

```toml
[mcp_servers.ubo_gateway]
url = "http://<host>:4322/mcp"
bearer_token_env_var = "UBO_MCP_TOKEN"
```

Then export the token before running Codex (keeps the secret out of the config
file):

```bash
export UBO_MCP_TOKEN="<TOKEN>"
```

Codex sends it as `Authorization: Bearer $UBO_MCP_TOKEN`. Codex speaks
Streamable HTTP only, so use the `/mcp` endpoint (not `/sse`).

### Claude Desktop

Claude Desktop can't talk to a bearer-gated remote server directly, so bridge it
with [`mcp-remote`](https://www.npmjs.com/package/mcp-remote). In
`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ubo-gateway": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "http://<host>:4322/sse",
        "--allow-http",
        "--transport", "sse-only",
        "--header", "Authorization: Bearer <TOKEN>"
      ]
    }
  }
}
```

Notes:
- The **URL is the first positional argument** — there is no `--sse` flag.
  `--transport sse-only` is how you force the SSE endpoint. (To use Streamable
  HTTP instead, point at `…/mcp` and drop the `--transport` line.)
- `--allow-http` is required because the endpoint is plain HTTP, not HTTPS.
- `-y` keeps `npx` from hanging on a first-run install prompt under Claude
  Desktop's non-interactive shell.
- Fully quit and reopen Claude Desktop — it only loads MCP servers at startup.

### MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

In the UI: **Transport Type** `SSE`, **URL** `http://<host>:4322/sse`, then under
**Authentication → Custom Headers** add `Authorization` = `Bearer <TOKEN>`.
(Or Transport `Streamable HTTP` with `http://<host>:4322/mcp`.)

### Containers (Hermes, OpenClaw, …)

Any MCP-capable tool can connect using the endpoint + bearer header above. The
only twist for tools running **in a Docker container on the device** is the
host: inside a container `localhost` is the container itself, so point at the
host instead — either:

- `http://host.docker.internal:4322/mcp` (add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service in its compose file), or
- the device's LAN address, `http://<hostname>.local:4322/mcp`.

A generic Streamable HTTP MCP client entry is just:

```jsonc
{
  "url": "http://host.docker.internal:4322/mcp",
  "headers": { "Authorization": "Bearer <TOKEN>" }
}
```

Consult the specific tool's MCP-configuration docs for its exact field names;
the three things it always needs are the **`/mcp` URL**, the **`Authorization:
Bearer <TOKEN>`** header, and a host that resolves to the device.

---

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Invalid URL … input: '--sse'` (mcp-remote) | `--sse` isn't a flag. Put the URL first; use `--transport sse-only`. |
| `401 Unauthorized` | Missing/incorrect bearer token, or an extra space — header must be exactly `Authorization: Bearer <TOKEN>`. Re-check via "Show gateway token". |
| Works in Inspector, fails from a container | `localhost` resolves to the container — use `host.docker.internal` or `<hostname>.local`. |
| Connects but **no tools** listed | No servers are *enabled* on the device. Enable them under **MCP Tools**; the gateway rebuilds automatically. |
| mcp-remote first run hangs | Add `-y` to the `npx` args. |
