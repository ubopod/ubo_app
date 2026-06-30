# Releasing Ubo App

This is the canonical runbook for cutting a release. The actual publishing
(PyPI, Raspberry Pi images, GitHub Release) is fully automated by
`.github/workflows/integration_delivery.yml`, which runs **on push of a
`v*` tag**. The document sets the guideline for maintainers to prepare the tree, write the notes, pin dependencies, and push a signed tag.

## Versioning

- Follow [semver](https://semver.org): **major** for breaking changes, **minor**
  for backward-compatible features, **patch** for fixes.
- The version is **derived from the git tag** by `hatch-vcs` (`version.py` →
  `get_version()`). **Never hand-edit a version field** — there isn't one to edit.
  Sub-packages (`ubo_app/rpc/`, `ubo_app/services/090-assistant/ubo-service/`,
  `ubo_app/services/090-mcp/ubo-service/`) inherit the same version via
  `parent_version.py`.

## Per-release artifacts

Every release produces exactly one release note:

| File | Purpose | Audience |
|---|---|---|
| `docs/releases/X.Y.Z.md` | Curated, reader-friendly highlights and the GitHub Release body. | Users |

The release workflow requires `docs/releases/<version>.md` and uses it as the
**GitHub Release body**. `CHANGELOG.md` is **frozen as of 2.0.0** and kept only
as the historical pre-2.0 record — do not edit it for new releases. The commit
history (`git log vPREV..HEAD`) is the changelog; there is no longer a per-commit
list to maintain.

## Branching model

```
feature branch ──PR──▶ development ──(pre-release prep here)──▶ main ──tag vX.Y.Z──▶ CI publishes
```

- **`development`** is the integration branch. All feature branches merge here
  first (via PR) — never straight into `main`.
- **All pre-release steps happen on `development`** (via a short-lived
  `release/vX.Y.Z` branch that PRs back into `development`): regen, quality gates,
  release notes, dependency pins.
- **`main` only ever receives `development`.** The promotion is a
  **fast-forward** so the `chore(release): …` commit becomes the tip of `main`
  and the history stays linear (this matches every release since v1.1.0).
- **The tag lives on `main`**, on the release commit, annotated + GPG-signed.

## Checklist

Run these in order. Stop and fix on any failure — don't press on.

1. **Pre-flight.** Every feature branch intended for this release is already
   merged into `development`. Be on `development`, clean working tree, latest CI
   green. (`main` is protected and only accepts `development`.)
2. **Cut a release branch from `development`:**
   `git checkout development && git pull && git checkout -b release/vX.Y.Z`.
3. **Regenerate generated artifacts** and commit if anything changed:
   - `uv run poe proto` — regenerate gRPC bindings (required if actions/events/
     proto changed since last release).
   - `uv run poe build-web-app` — compile web-UI proto + build React assets.
4. **Quality gates:**
   - `uv run poe sanity` (= `typecheck` + `lint` + `test`), **and**
   - Docker integration tests (DPI-sensitive snapshots must run in Docker):
     ```bash
     docker run --rm -it --name ubo-app-test -e PRETEND_VERSION=0.0.0.dev0 \
       -v .:/ubo-app -v ubo-app-dev-uv-cache:/root/.cache/uv ubo-app-test
     ```
5. **Write `docs/releases/X.Y.Z.md`** (the only release-notes artifact): curated
   highlights grouped by theme (features, architecture, important fixes, upgrade
   notes). Skip chores/lint/test-infra noise. Aim for something people will
   actually read (< ~1000 words). Use `git log --pretty=format:'%s' vPREV..HEAD`
   as source material (in this workspace, prefix with `rtk proxy` to avoid the
   50-line cap). Do **not** touch `CHANGELOG.md` — it is frozen as of 2.0.0.
6. **Pin dependencies** (see the v1.7.0 recipe in the appendix). Pin in the
   **root `pyproject.toml`** and each **sub-project** pyproject (`ubo_app/rpc/`,
   `ubo_app/gui/`, `ubo_app/services/090-assistant/ubo-service/`,
   `ubo_app/services/090-mcp/ubo-service/`):
   - **ubo-owned wheels → the release version** (`==X.Y.Z`): `ubo-app`,
     `ubo-app-raw-bindings`, `ubo-app-assistant`, `ubo-app-mcp-gateway`,
     `ubo-gui-client`. These are workspace / `path` editable deps during dev —
     convert each to `==X.Y.Z`.
   - **Third-party pins to verify/refresh each release:** `pipecat-ai==1.3.0`
     (+ `pipecat-ai-whisker==2.0.0`), `piper-tts==1.4.2` (root **and** the
     assistant sub-project), `onnxruntime` (1.7.0 shipped `==1.22.1`),
     `headless-kivy`, `ubo-gui`, `pillow`, `platformdirs`, `vosk`, `pvorca`,
     `opencv-python`, `sentry-sdk`, `google-cloud-aiplatform`,
     `google-cloud-speech`.
   - Convert any remaining direct deps from `>=`/bare to exact `==`, add/refresh
     the `# Transitive dependency pins (resolved from uv.lock)` block, and
     refresh the lock: `uv lock`.

   > **Why pinning unpublished versions is build-safe.** Pinning the ubo-owned
   > wheels to a version that isn't on PyPI yet does **not** break CI — there is
   > no chicken-and-egg. `uv build` only packages code and writes the deps into
   > the wheel's `Requires-Dist` metadata; it never resolves or fetches them, so
   > building `ubo-app` with `ubo-app-raw-bindings==X.Y.Z` succeeds before that
   > version exists. The `[tool.uv.sources]` workspace/`path` entries are
   > dev-only and stripped from built wheels, so keep them — the published
   > metadata carries only the `==X.Y.Z` pin, which is consumed at the user's
   > `pip install` time. The single tagged CI run builds all four wheels from
   > source (`PRETEND_VERSION`) and the `publish` job uploads them to PyPI
   > **together**, so by the time anyone can install, every matching version is
   > already present. (v1.7.0 shipped exactly this way: `ubo-app-raw-bindings==1.7.0`
   > pinned in `dependencies` alongside a `workspace = true` source.)
7. **Release commit:** `git commit -am 'chore(release): prepare vX.Y.Z release with dependency pins'`.
8. **Merge the release branch back into `development`:** open
   `release/vX.Y.Z` → `development`, review, merge. Confirm `development` CI is
   green — this is the last gate before `main`.
9. **Promote `development` → `main`:** open a `development` → `main` PR (`main`
   accepts only `development`) and merge it **as a fast-forward** so the release
   commit becomes the tip of `main` and history stays linear.
10. **Tag on `main`, annotated + signed**, then push:
    ```bash
    git checkout main && git pull
    git tag -s vX.Y.Z -m 'Release vX.Y.Z'   # must point at the chore(release) commit
    git push origin vX.Y.Z
    ```
11. **CI takes over.** The tag push runs the `version → type-check/lint/test →
    build → publish → images → release` job graph and creates the GitHub Release.
12. **Post-release verification:**
    - PyPI package published: `https://pypi.org/project/ubo-app/X.Y.Z/`.
    - GitHub Release at `https://github.com/ubopod/ubo_app/releases/tag/vX.Y.Z`
      has the lite + default `.img.gz` images and the package wheels attached.
    - Release body shows the curated notes from `docs/releases/X.Y.Z.md` and the
      2GB-split footer.

## Post-release — re-open `development` for the next cycle

Once the tag is shipped and the PyPI package + GitHub Release are verified, undo
the release pins on `development` so everyday work resolves against the latest
compatible dependencies again. This is the inverse of step 6 (precedent: v1.7.0
commit `9c8f0a38`). `development`'s ruleset requires passing status checks, so it
**cannot be committed directly** — do this on a short-lived branch and PR it back
into `development`, the same as any other change.

1. **Branch from `development`** with a clean tree:
   `git checkout development && git pull && git checkout -b chore/post-release-unpin-vX.Y.Z`.
2. **Unpin the release-introduced pins** in each pyproject — revert exactly what
   step 6 pinned, and nothing else:
   - **Root `pyproject.toml`** — `platformdirs==…` → `platformdirs`,
     `ubo-app-raw-bindings==X.Y.Z` → `ubo-app-raw-bindings`,
     `onnxruntime==1.22.1` → `onnxruntime>=1.22.0`, `pillow==…` → `pillow>=11.3.0`,
     and **delete** the `# Transitive dependency pins (resolved from uv.lock)`
     block. Leave the deps that ship exact-pinned regardless of release as-is.
   - **`ubo_app/gui/pyproject.toml`** — revert the converted deps back to their
     `>=`/bare forms and `ubo-app-raw-bindings==X.Y.Z` → bare.
   - **`ubo_app/services/090-assistant/ubo-service/pyproject.toml`** —
     `platformdirs==…` → `>=`, `python-fake==…` → `>=`,
     `ubo-app-raw-bindings==X.Y.Z` → bare.
   - **`ubo_app/services/090-mcp/ubo-service/pyproject.toml`** —
     `fastmcp==…` → `>=`, `uvicorn==…` → `>=`, `starlette==…` → `>=`,
     `loguru==…` → `>=`, `ubo-app-raw-bindings==X.Y.Z` → bare.
   - **`ubo_app/rpc/pyproject.toml`** — nothing to do (it is never pinned per
     release; its version is tag-derived).
   > **Keep non-pin changes.** Anything bundled into the release commit that is
   > not a version pin stays. (In 2.0.0 the release commit also carried the
   > `build-web-app` `npm run compile` → `npm run proto:compile` fix — that is a
   > bug fix, not a pin; do **not** revert it.) Unpin = revert pins only.
3. **Re-open `CHANGELOG.md`** — add a fresh `## Upcoming` heading above the just-
   released version.
4. **Refresh every lock that carried pins** with plain `uv lock` (no
   `PRETEND_VERSION`), so the dev `.devNNN` versions come back:
   ```bash
   uv lock
   (cd ubo_app/gui && uv lock)
   (cd ubo_app/services/090-assistant/ubo-service && uv lock)
   (cd ubo_app/services/090-mcp/ubo-service && uv lock)
   ```
   The `Missing version constraint` warnings for now-bare deps are expected.
5. **Commit, push the branch, and open a PR into `development`** (no tag, no
   `main` promotion — `development` just continues from here once merged):
   `git commit -am 'chore(release): post-release unpin dependencies for development'`,
   then `git push -u origin HEAD` and
   `gh pr create --base development`.

## Appendix — 2.0.0 dependency-pin reference

The original template was the v1.7.0 release commit (`7a3cb7b3`). The tree has
five pyprojects, each pinned for release (replace `X.Y.Z` with the release
version, e.g. `2.0.0`). (The `090-mcp/ubo-service` wheel below was added after
2.0.0.)

- **Root `pyproject.toml`** (`ubo-app`) — convert `platformdirs`, `pillow`
  (`>=11.3.0` → `==`), `onnxruntime` (`>=1.22.0` → `==1.22.1`), `piper-tts`
  (`1.4.1` → `==1.4.2`), and `ubo-app-raw-bindings` (workspace → `==X.Y.Z`) to
  exact pins; keep the already-exact ones (`google-cloud-*`, `vosk==0.3.44`,
  `pvorca==1.1.1`, `opencv-python==4.10.0.84`, `sentry-sdk==2.29.1`,
  `headless-kivy==0.13.0`, `ubo-gui==0.13.17`, …). Add/refresh the ~70-line
  `# Transitive dependency pins (resolved from uv.lock)` block.
- **`ubo_app/rpc/pyproject.toml`** (`ubo-app-raw-bindings`) — version is
  tag-derived via `parent_version.py`; pins `betterproto[compiler]==2.0.0b7`.
- **`ubo_app/gui/pyproject.toml`** (`ubo-gui-client`) — pin `ubo-app-raw-bindings`
  (`path` → `==X.Y.Z`) and convert the `>=`/bare deps (`headless-kivy`,
  `ubo-gui`, `grpclib`, `betterproto`, `numpy`, `adafruit-circuitpython-rgb-display`,
  `pillow`, `pypng`, `python-fake`, `platformdirs`, `python-strtobool`) to `==`.
- **`ubo_app/services/090-assistant/ubo-service/pyproject.toml`**
  (`ubo-app-assistant`) — `pipecat-ai[…]==1.3.0`, `pipecat-ai-whisker==2.0.0`,
  `piper-tts==1.4.2`, `vosk==0.3.44`; convert `platformdirs`/`python-fake`
  (`>=`) to `==`, and pin `ubo-app-raw-bindings` (`path` → `==X.Y.Z`).
- **`ubo_app/services/090-mcp/ubo-service/pyproject.toml`**
  (`ubo-app-mcp-gateway`) — convert `fastmcp`, `uvicorn`, `starlette`, `loguru`
  (`>=`) to `==`, and pin `ubo-app-raw-bindings` (`path` → `==X.Y.Z`).
- **`uv.lock`** — refreshed (`uv lock`) to match.

The five ubo-owned wheels (`ubo-app`, `ubo-app-raw-bindings`, `ubo-app-assistant`,
`ubo-app-mcp-gateway`, `ubo-gui-client`) are workspace / `path` editable deps
during dev — every cross-reference to them must become `==X.Y.Z` for release.

To reproduce the transitive-pin block for a new release, resolve the locked
versions from `uv.lock` (e.g. via `uv export` / `uv pip compile`) and pin the
ones the project ships, keeping the same comment marker so the block is easy to
find and refresh next time.
