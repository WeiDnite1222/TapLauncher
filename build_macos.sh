#!/bin/bash
# Build the native macOS application using the project's Nuitka configuration.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./build_macos.sh [--dry-run] [Nuitka options...]

Sync build dependencies and create build/TapLauncher.app for the current
Python architecture (Apple Silicon or Intel). Requires uv and Xcode Command
Line Tools (install with: xcode-select --install).

  --dry-run  Print the build command without syncing or compiling.
  --help     Show this help.

Additional arguments are passed directly to Nuitka, for example:
  ./build_macos.sh --jobs=4
  ./build_macos.sh --macos-sign-identity="Developer ID Application: ..."
EOF
}

dry_run=false
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if [[ "${1:-}" == "--dry-run" ]]; then
    dry_run=true
    shift
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Error: this script must run on macOS." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required. See https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

# Plugins load source files by path and import the public API dynamically.
# Keep their sources as raw data and explicitly compile the public API package.
build_command=(
    uv run --no-sync python -m nuitka
    --standalone
    --include-package=TapLauncher
    --include-package=keyring.backends
    --include-module=PySide6.QtNetwork
    --include-module=xml.etree.ElementTree
    --include-raw-dir=resources/builtin_plugins=resources/builtin_plugins
    '--noinclude-data-files=**/__pycache__/**'
    '--noinclude-data-files=**/.DS_Store'
    "$@"
    main.py
)

if "$dry_run"; then
    printf 'Working directory: %s\n' "$project_dir"
    printf '%s\n' 'uv sync --group build'
    printf '%q ' "${build_command[@]}"
    printf '\n'
    exit 0
fi

if ! xcrun --find clang >/dev/null 2>&1; then
    echo "Error: install Xcode Command Line Tools with: xcode-select --install" >&2
    exit 1
fi

uv sync --group build
"${build_command[@]}"
printf '\nBuild completed. Default application path: %s/build/TapLauncher.app\n' "$project_dir"
