#!/usr/bin/env bash
#
# setup-dev.sh — one-shot Ubo App development environment bootstrap.
#
# Detects the platform and installs the tooling needed to develop ubo-app
# (uv, buf, git-lfs, node/npm), then bootstraps the project (venv, deps,
# protobuf, web app). Safe to re-run: every step is idempotent.
#
#   macOS              -> Homebrew (installed if missing): buf, git-lfs, node
#   Raspberry Pi/Linux -> non-sudo: binaries to ~/.local/bin + fnm for node
#
# Designed to run as the unprivileged `ubo` user on the Raspberry Pi; it never
# requires sudo on Linux.
#
# Usage:
#   ./scripts/setup-dev.sh [--tools-only] [--skip-web] [--help]
#
# Pinned tool versions can be overridden via environment variables, e.g.:
#   BUF_VERSION=1.47.2 NODE_VERSION=22 ./scripts/setup-dev.sh
#
set -euo pipefail

# --- pinned versions (override via env) -------------------------------------
BUF_VERSION="${BUF_VERSION:-1.47.2}"
GIT_LFS_VERSION="${GIT_LFS_VERSION:-3.6.1}"
NODE_VERSION="${NODE_VERSION:-22}"

LOCAL_BIN="$HOME/.local/bin"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WEB_APP_DIR="$REPO_ROOT/ubo_app/services/090-web-ui/web-app"

TOOLS_ONLY=false
SKIP_WEB=false

# --- logging ----------------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET='\033[0m'; C_BLUE='\033[1;34m'; C_GREEN='\033[1;32m'
  C_YELLOW='\033[1;33m'; C_RED='\033[1;31m'
else
  C_RESET=''; C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''
fi

log()  { printf "${C_BLUE}==>${C_RESET} %s\n" "$*"; }
ok()   { printf "  ${C_GREEN}\xE2\x9C\x93${C_RESET} %s\n" "$*"; }
warn() { printf "  ${C_YELLOW}!${C_RESET} %s\n" "$*"; }
die()  { printf "${C_RED}error:${C_RESET} %s\n" "$*" >&2; exit 1; }

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

# --- args -------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --tools-only) TOOLS_ONLY=true ;;
    --skip-web)   SKIP_WEB=true ;;
    -h|--help)    usage ;;
    *) die "unknown option: $arg (try --help)" ;;
  esac
done

# --- platform detection -----------------------------------------------------
OS=""; ARCH_BUF=""; ARCH_LFS=""
detect_platform() {
  local kernel machine
  kernel="$(uname -s)"
  machine="$(uname -m)"

  case "$kernel" in
    Darwin) OS="macos" ;;
    Linux)  OS="linux" ;;
    *) die "unsupported OS: $kernel" ;;
  esac

  # buf release assets use `uname -s`/`uname -m` verbatim (e.g. buf-Linux-aarch64).
  ARCH_BUF="$machine"
  # git-lfs uses go-style arch names.
  case "$machine" in
    aarch64|arm64) ARCH_LFS="arm64" ;;
    x86_64|amd64)  ARCH_LFS="amd64" ;;
    *) die "unsupported architecture: $machine" ;;
  esac

  log "Platform: ${OS} (${machine})"
}

# --- PATH handling ----------------------------------------------------------
rc_file() {
  case "$(basename "${SHELL:-/bin/bash}")" in
    zsh)  echo "$HOME/.zshrc" ;;
    *)    echo "$HOME/.bashrc" ;;
  esac
}

ensure_local_bin_on_path() {
  mkdir -p "$LOCAL_BIN"
  export PATH="$LOCAL_BIN:$PATH"

  local rc marker
  rc="$(rc_file)"
  marker="# Added by ubo-app setup-dev.sh"
  if [ -f "$rc" ] && grep -qF "$marker" "$rc"; then
    return
  fi
  {
    printf '\n%s\n' "$marker"
    printf 'export PATH="$HOME/.local/bin:$PATH"\n'
    if [ "$OS" = "linux" ]; then
      printf 'command -v fnm >/dev/null 2>&1 && eval "$(fnm env --use-on-cd)"\n'
    fi
  } >> "$rc"
  warn "Added ~/.local/bin to PATH in $rc — restart your shell or 'source $rc' afterwards."
}

# --- installers -------------------------------------------------------------
install_uv() {
  if command -v uv >/dev/null 2>&1; then
    ok "uv already installed ($(uv --version 2>/dev/null))"
    return
  fi
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv install failed"
  ok "uv installed"
}

# Homebrew (macOS only) — installed on demand.
ensure_brew() {
  if command -v brew >/dev/null 2>&1; then return; fi
  log "Installing Homebrew"
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Make brew available in this session.
  if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  command -v brew >/dev/null 2>&1 || die "Homebrew install failed"
}

install_buf() {
  if command -v buf >/dev/null 2>&1; then
    ok "buf already installed ($(buf --version 2>/dev/null))"
    return
  fi
  log "Installing buf"
  if [ "$OS" = "macos" ]; then
    ensure_brew
    brew install bufbuild/buf/buf
  else
    curl -fsSL \
      "https://github.com/bufbuild/buf/releases/download/v${BUF_VERSION}/buf-$(uname -s)-${ARCH_BUF}" \
      -o "$LOCAL_BIN/buf"
    chmod +x "$LOCAL_BIN/buf"
  fi
  command -v buf >/dev/null 2>&1 || die "buf install failed"
  ok "buf installed"
}

install_git_lfs() {
  if command -v git-lfs >/dev/null 2>&1; then
    ok "git-lfs already installed ($(git-lfs version 2>/dev/null))"
  elif [ "$OS" = "macos" ]; then
    log "Installing git-lfs"
    ensure_brew
    brew install git-lfs
  else
    log "Installing git-lfs"
    local tmp tarball
    tmp="$(mktemp -d)"
    tarball="git-lfs-linux-${ARCH_LFS}-v${GIT_LFS_VERSION}.tar.gz"
    curl -fsSL \
      "https://github.com/git-lfs/git-lfs/releases/download/v${GIT_LFS_VERSION}/${tarball}" \
      -o "$tmp/$tarball"
    tar -xzf "$tmp/$tarball" -C "$tmp"
    # Tarball extracts to git-lfs-<version>/git-lfs; copy just the binary (no sudo).
    find "$tmp" -name git-lfs -type f -exec cp {} "$LOCAL_BIN/git-lfs" \;
    chmod +x "$LOCAL_BIN/git-lfs"
    rm -rf "$tmp"
  fi
  command -v git-lfs >/dev/null 2>&1 || die "git-lfs install failed"
  # Register git-lfs hooks for the current user (writes to ~/.gitconfig, no sudo).
  git lfs install --skip-repo
  ok "git-lfs installed"
}

install_node() {
  if command -v npm >/dev/null 2>&1; then
    ok "node already installed ($(node --version 2>/dev/null))"
    return
  fi
  log "Installing node ${NODE_VERSION}"
  if [ "$OS" = "macos" ]; then
    ensure_brew
    brew install node
  else
    # fnm: single static binary, no sudo, manages node per-user.
    if ! command -v fnm >/dev/null 2>&1; then
      curl -fsSL https://fnm.vercel.app/install | \
        bash -s -- --install-dir "$LOCAL_BIN" --skip-shell
    fi
    export PATH="$LOCAL_BIN:$PATH"
    eval "$(fnm env)"
    fnm install "$NODE_VERSION"
    fnm use "$NODE_VERSION"
    fnm default "$NODE_VERSION"
  fi
  command -v npm >/dev/null 2>&1 || die "node install failed"
  ok "node installed ($(node --version 2>/dev/null))"
}

# --- project bootstrap ------------------------------------------------------
bootstrap_project() {
  log "Bootstrapping project in $REPO_ROOT"
  cd "$REPO_ROOT"

  log "Pulling git-lfs objects"
  git lfs install
  git lfs pull

  # On Linux some python packages (picamera2, etc.) are provided system-wide.
  if [ "$OS" = "linux" ]; then
    [ -d .venv ] || uv venv --system-site-packages
  else
    [ -d .venv ] || uv venv
  fi

  log "Installing python dependencies (uv sync --dev)"
  uv sync --dev

  log "Generating protobuf files (uv run poe proto)"
  uv run poe proto

  if [ "$SKIP_WEB" = true ]; then
    warn "Skipping web app build (--skip-web)"
    return
  fi

  log "Building the web application"
  ( cd "$WEB_APP_DIR"
    [ "$OS" = "linux" ] && command -v fnm >/dev/null 2>&1 && eval "$(fnm env)" && fnm use "$NODE_VERSION"
    npm install
    npm run proto:compile
    npm run build )
}

# --- next steps -------------------------------------------------------------
print_next_steps() {
  printf "\n${C_GREEN}==> Development environment is ready.${C_RESET}\n\n"
  printf "To run the app in development mode:\n\n"
  if [ "$OS" = "linux" ]; then
    printf "  ${C_YELLOW}# 1. Stop the system ubo-app service first (it owns the screen/hardware):${C_RESET}\n"
    printf "  systemctl --user stop ubo-app\n\n"
  fi
  printf "  ${C_YELLOW}# Run from the repo root:${C_RESET}\n"
  printf "  cd %s\n" "$REPO_ROOT"
  printf "  UBO_LOG_LEVEL=DEBUG HEADLESS_KIVY_DEBUG=true uv run ubo\n\n"
  warn "If this was a fresh tool install, open a new shell (or 'source $(rc_file)') so PATH updates take effect."
}

main() {
  detect_platform
  ensure_local_bin_on_path

  log "Installing tools"
  install_uv
  install_buf
  install_git_lfs
  install_node

  if [ "$TOOLS_ONLY" = true ]; then
    warn "Skipping project bootstrap (--tools-only)"
  else
    bootstrap_project
  fi

  print_next_steps
}

main
