# ubo-app MCP gateway

A standalone subprocess that aggregates every **enabled** MCP server the user
has configured behind a single, token-gated HTTP endpoint. It is the network
boundary for MCP in ubo-app: any client — the on-device assistant, Claude
Desktop, hermes, OpenClaw, etc. — talks to this one endpoint instead of
spawning/managing MCP servers itself.

## Why it exists

MCP server management used to live *inside* the assistant service, so the tools
were reachable only by the assistant. Extracting the gateway into its own
service (`ubo_app/services/090-mcp`) decouples MCP from the assistant: the
gateway owns the servers, and the assistant becomes just one more client of the
aggregated endpoint.

## How it works

```
                 ┌──────────────── ubo-app core (gRPC :50051) ───────────────┐
                 │  state.mcp slice  (servers, enabled set, metadata)         │
                 └─────────────▲──────────────────────────────┬──────────────┘
                               │ autorun subscription         │ query_secret
                               │ (enabled servers + metadata) │ (bearer token)
                 ┌─────────────┴──────────────────────────────▼──────────────┐
                 │  MCP gateway subprocess (this service)                     │
                 │                                                            │
                 │  state → build_mcp_config() → FastMCP proxy                │
                 │                              ├── backend: server A (stdio) │
                 │                              ├── backend: server B (sse)   │
                 │                              └── …                         │
                 │  served over  /mcp (Streamable HTTP)  +  /sse              │
                 │  guarded by   Bearer <token>                               │
                 └────────────────────────────▲───────────────▲─────────────┘
                                               │               │
                                    assistant client      external clients
                                    (Streamable HTTP)     (Claude Desktop, …)
```

1. **Startup** (`main.py`) — connects to ubo-app's gRPC store, reads the
   gateway bearer token from secrets (`MCP_GATEWAY_TOKEN_SECRET_ID`). If no
   token is configured it logs and exits rather than serve an open endpoint.
2. **State → config** (`gateway.py`) — subscribes via `autorun` to
   `state.mcp.enabled_mcp_servers_with_metadata` and translates each enabled
   server's betterproto config (the `stdio_mcp_config` / `sse_mcp_config`
   oneof) into a FastMCP `{"mcpServers": {...}}` config. Servers with an
   unrecognized/empty config are skipped with a warning.
3. **Serving** (`server.py`) — builds a single `FastMCP` proxy from that config
   and exposes its aggregated tools over **both** transports: Streamable HTTP at
   `/mcp` and SSE at `/sse`. A pure-ASGI `_BearerAuthMiddleware` rejects any
   request without `Authorization: Bearer <token>` (pure ASGI so it doesn't
   buffer the streaming responses).

## The persistent-socket rebuild (the one non-obvious bit)

FastMCP has **no API to remove a backend from a running proxy**. So whenever the
enabled-server set changes, the whole proxy and its ASGI apps must be rebuilt.

To avoid dropping the port (and breaking connected clients) during a rebuild,
`GatewayServer` owns a **persistent listening socket** that is created once and
never closed. The serve loop:

- builds the app for the current config and runs a `uvicorn.Server` on that
  shared socket;
- waits on an `asyncio.Event` that the autorun callback sets when the desired
  config differs from the running one;
- on change, signals `should_exit`, awaits the old server, and loops to rebuild
  — the listener stays bound the entire time, so the endpoint never disappears.

An empty config still serves a valid (tool-less) gateway rather than crashing.

## Configuration

Environment is provided by the service's `ubo_handle.py::binary_env_provider`:

| Variable | Meaning | Default |
| --- | --- | --- |
| `MCP_GATEWAY_TOKEN_SECRET_ID` | secret id holding the bearer token | `mcp_gateway_token` |
| `MCP_GATEWAY_LISTEN_ADDRESS` | bind address | `0.0.0.0` |
| `MCP_GATEWAY_LISTEN_PORT` | bind port | `4322` |
| `UBO_MCP_GATEWAY_LOG_LEVEL` | log level | `INFO` |
| `UBO_MCP_GATEWAY_LOG_PATH` | log file path | `./ubo-mcp-gateway.log` |

Server definitions themselves live on disk under `CONFIG_PATH/mcp_servers/`
(`{name}_{uuid}/config.json`), owned by the core MCP service, not this
subprocess. This subprocess never reads the filesystem — it only consumes the
`state.mcp` slice over gRPC.

## Boundaries

- **Source of truth is the store.** This process is a pure projection of
  `state.mcp`; it dispatches nothing and persists nothing.
- **Stdio MCP backends are launched by FastMCP** as child processes of this
  subprocess, so their runtimes (e.g. `uvx`, `npx`) must be on `PATH` here. See
  the runtime-provisioning note below / in the service-level docs.
