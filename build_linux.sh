#!/bin/bash
# Build the native Linux application using the project's Nuitka configuration.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./build_linux.sh [--dry-run] [Nuitka options...]

Sync build dependencies and create build/TapLauncher.dist/TapLauncher (executable).
Requires uv, GCC, and patchelf.

  --dry-run  Print the build command without syncing or compiling.
  --help     Show this help.

Additional arguments are passed directly to Nuitka, for example:
  ./build_linux.sh --jobs=4
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

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Error: this script must run on Linux." >&2
    exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv is required. See https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"

# Plugins load source files by path and import the public API dynamically.
build_command=(
    uv run --no-sync python -m nuitka
    --standalone
    --output-filename=TapLauncher.bin
    --output-folder-name=TapLauncher
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

for dependency in gcc patchelf; do
    if ! command -v "$dependency" >/dev/null 2>&1; then
        printf 'Error: install %s using your Linux distribution package manager.\n' "$dependency" >&2
        exit 1
    fi
done

uv sync --group build
"${build_command[@]}"
printf '\nBuild completed. Default executable path: %s/build/TapLauncher.dist/TapLauncher.bin\n' "$project_dir"
