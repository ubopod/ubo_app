# Contributing to Ubo App

Contributions following Python best practices are welcome. This guide covers
the workflow; the [README](README.md#-contributing) has the full development
reference (device setup, testing details, conventions).

## Getting started

The automated path detects your platform (macOS or Raspberry Pi/Linux),
installs the tooling (`uv`, `buf`, `git-lfs`, `node`), and bootstraps the
project:

```bash
git clone https://github.com/ubopod/ubo_app.git
cd ubo_app
./scripts/setup-dev.sh
```

Manual path:

```bash
git lfs install && git lfs pull   # snapshots are LFS-tracked
uv sync --dev                     # on Raspberry Pi OS first: uv venv --system-site-packages
uv run poe proto:compile:raw      # build the gRPC bindings
uv run poe test:unit              # verify: ~285 tests in ~5s
```

Run the app locally with `HEADLESS_KIVY_DEBUG=true uv run ubo`.

## Branch model

- Feature branches PR into **`development`** — never straight into `main`.
- `main` only ever receives `development`, promoted as a fast-forward.
- Releases are annotated, GPG-signed `vX.Y.Z` tags on `main`; CI publishes
  PyPI packages, Pi images, and the GitHub Release. See [RELEASING.md](RELEASING.md).
- Commit messages follow conventional commits: `type(scope): subject`.

## Local quality gate

```bash
uv run poe sanity
```

This is exactly what CI runs: `typecheck` (pyright) + `lint` (ruff) + `test`
(pytest), fanned out across the five Python workspaces — the repo root plus
`ubo_app/rpc/`, `ubo_app/services/090-assistant/ubo-service/`,
`ubo_app/services/090-mcp/ubo-service/`, and `ubo_app/gui/`. Every error must
be fixed; a green `sanity` locally means a green PR gate.

## Proto & generated artifacts

If you add, change, or remove a store action/event (or touch
`ubo_app/rpc/proto/`):

```bash
uv run poe proto                  # regenerate proto + Python bindings
cd ubo_app/services/090-web-ui/web-app
npm run proto:compile && npm run build   # regenerate the web client too
```

Commit the regenerated files — CI builds against them, and a stale `dist/`
or bindings diff means the clients and core disagree about the wire format.

## Snapshot testing

Store snapshots (`.jsonc`) and window snapshots (`.hash`/`.png`) live under
`tests/**/results/` and are asserted by the integration and flow tests.

- **Never hand-edit snapshot files.** Regenerate them.
- Regenerate with the pytest flags `--override-store-snapshots`,
  `--override-window-snapshots`, and `--make-screenshots` (for debugging
  mismatches via `.mismatch.png`).
- Window snapshots are DPI-sensitive: generate them **in Docker**
  (`uv run poe build-docker-images` once, then run the `ubo-app-test` image —
  see the README's [testing section](README.md#running-tests-on-desktop)),
  not on macOS.

## On-device development

```bash
uv run poe device:deploy:complete   # once, to set up the pod
uv run poe device:deploy            # deploy your working tree
uv run poe device:test              # run the test suite on the device
```

Gotcha: pip-based deploys can leave stale `~NN-*` shadow directories next to
the real `0NN-*` service directories under `services/` — if the device runs
old code after a deploy, remove the `~*` directories and restart the app.

## Using Claude Code

The project ships curated agents, skills, and slash commands in a separate
repo, [ubopod/ubo-claude](https://github.com/ubopod/ubo-claude), designed to
be cloned **as** your `.claude/` directory:

```bash
git clone git@github.com:ubopod/ubo-claude.git .claude
ln -s .claude/CLAUDE.md CLAUDE.md   # Windows: copy instead
```

Both paths are gitignored here. Notes:

- **Review `.claude/settings.json` and `.claude/hooks/` before cloning** — it
  enables plugins and hooks in your sessions (all fail-safe/warn-only).
- `.claude/` is its own git repo: improvements to agents/skills go to
  ubo-claude PRs, not ubo-app.
- Start with the `/onboard` skill, and run `/pr-preflight` before opening a PR.
