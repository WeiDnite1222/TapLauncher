#!/bin/bash
# Build the native macOS application using the project's Nuitka configuration.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./build_macos.sh [--dry-run] [Nuitka options...]

Sync build dependencies and create build/TapLauncher.app and TapLauncher.dmg
for the current Python architecture (Apple Silicon or Intel). Requires uv and
Xcode Command Line Tools (install with: xcode-select --install).

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
for command_name in ditto hdiutil; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Error: required macOS command not found: $command_name" >&2
        exit 1
    fi
done

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

app_path="$project_dir/build/TapLauncher.app"
dmg_path="$project_dir/build/TapLauncher.dmg"

if [[ ! -d "$app_path/Contents/MacOS" ]]; then
    echo "Error: application output is missing or incomplete: $app_path" >&2
    exit 1
fi

printf '\nApplication build completed: %s\n' "$app_path"

dmg_staging_dir="$(mktemp -d "$project_dir/build/dmg-temp.XXXXXX")"
dmg_output_dir="$(mktemp -d "$project_dir/build/dmg-output.XXXXXX")"
dmg_candidate="$dmg_output_dir/TapLauncher.dmg"

cleanup() {
    rm -rf "$dmg_staging_dir"
    rm -rf "$dmg_output_dir"
}
trap cleanup EXIT INT TERM

ditto --noqtn "$app_path" "$dmg_staging_dir/TapLauncher.app"
ln -s /Applications "$dmg_staging_dir/Applications"

create_dmg() {
    hdiutil create \
        -volname "TapLauncher" \
        -srcfolder "$dmg_staging_dir" \
        -format UDZO \
        -imagekey zlib-level=9 \
        "$dmg_candidate"
}

for attempt in 1 2 3; do
    if create_dmg; then
        break
    fi
    if [[ "$attempt" -eq 3 ]]; then
        echo "Error: unable to create DMG after $attempt attempts." >&2
        exit 1
    fi
    echo "DMG creation failed (attempt $attempt/3); retrying..." >&2
    rm -f "$dmg_candidate"
    sleep "$attempt"
done

if ! hdiutil verify "$dmg_candidate"; then
    echo "Error: DMG verification failed; existing output was not replaced." >&2
    exit 1
fi

mv -f "$dmg_candidate" "$dmg_path"
printf 'DMG build completed: %s\n' "$dmg_path"
