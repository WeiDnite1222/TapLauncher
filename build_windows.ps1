param(
    [switch]$DryRun,
    [switch]$Help,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$NuitkaOptions = @()
)

$ErrorActionPreference = 'Stop'

if ($Help) {
    @'
Usage: .\build_windows.ps1 [-DryRun] [Nuitka options...]

Sync build dependencies and create build\TapLauncher.dist\TapLauncher.exe.
Requires uv, and Visual Studio 2022 Build Tools with the Desktop
development with C++ workload and Windows SDK.

  -DryRun  Print the build command without syncing or compiling.
  -Help    Show this help.

Examples:
  .\build_windows.ps1
  .\build_windows.ps1 -DryRun
  .\build_windows.ps1 --jobs=4
'@ | Write-Output
    exit 0
}

if ($env:OS -ne 'Windows_NT') {
    Write-Error 'This script must run on Windows.'
    exit 1
}
if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) {
    Write-Error 'uv is required. See https://docs.astral.sh/uv/getting-started/installation/'
    exit 1
}

# Reuse main.py's PySide6, resources, icon, and GUI console settings.
# Plugins load source files by path and import the public API dynamically.
$buildArgs = @(
    'run', '--no-sync', 'python', '-m', 'nuitka',
    '--standalone',
    '--msvc=latest',
    '--output-filename=TapLauncher.exe',
    '--output-folder-name=TapLauncher',
    '--include-package=TapLauncher',
    '--include-package=keyring.backends',
    '--include-module=PySide6.QtNetwork',
    '--include-module=xml.etree.ElementTree',
    '--include-raw-dir=resources/builtin_plugins=resources/builtin_plugins',
    '--noinclude-data-files=**/__pycache__/**',
    '--noinclude-data-files=**/.DS_Store',
    "--file-version=1.0.0"
) + @($NuitkaOptions) + @('main.py')

Push-Location -LiteralPath $PSScriptRoot
try {
    if ($DryRun) {
        Write-Output "Working directory: $PSScriptRoot"
        Write-Output 'uv sync --group build'
        $quotedArgs = $buildArgs | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }
        Write-Output ('& uv ' + ($quotedArgs -join ' '))
    }
    else {
        & uv sync --group build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        & uv @buildArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

        Write-Output "Build completed. Default executable path: $PSScriptRoot\build\TapLauncher.dist\TapLauncher.exe"
    }
}
finally {
    Pop-Location
}
