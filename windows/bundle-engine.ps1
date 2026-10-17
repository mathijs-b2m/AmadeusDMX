# Put the engine and a Python of its own next to an app (a release: nothing to install, no checkout needed).
#   ./bundle-engine.ps1 build\AmadeusDMX
# <out>\runtime   a relocatable CPython (python-build-standalone, via uv) with requirements-app.txt
# <out>\engine    the package, the web UI, fixtures, examples, the Mixxx mapping, the VirtualDJ plugin
# Your data is not in the app: the app gives the engine %LOCALAPPDATA%\Amadeus DMX (amadeus/paths.py).
# Needs uv (winget install astral-sh.uv). $env:PYTHON_VERSION picks the Python (default 3.14, as in CI).
# $env:FFMPEG_EXE=…\ffmpeg.exe puts that ffmpeg in engine\bin (optional: only if the engine decodes with it).
param([Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true  # a failing uv / python stops the script (PowerShell 7.3+)

$Here = $PSScriptRoot
$Root = (Resolve-Path "$Here\..").Path
$Py = if ($env:PYTHON_VERSION) { $env:PYTHON_VERSION } else { '3.14' }
$Cache = Join-Path $Here 'build\python'
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$Runtime = Join-Path $Out 'runtime'
$Engine = Join-Path $Out 'engine'

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv is needed: winget install astral-sh.uv' }

function Remove-Here([string[]]$Paths) {
    foreach ($p in $Paths) { if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
}

# the runtime: a standalone CPython, without what the engine never uses
# the x64 build by name: uv would otherwise pick this machine's own (ARM64 on a Snapdragon or a Mac's VM)
uv python install "cpython-$Py-windows-x86_64-none" --install-dir $Cache --no-bin --no-registry | Out-Null
$Src = Get-ChildItem $Cache -Directory -Filter "cpython-$Py*-windows-x86_64-none" | Where-Object Name -NotMatch '\+' |
    Sort-Object { [version](($_.Name -split '-')[1] -replace '[^0-9.].*$', '') } | Select-Object -Last 1
if (-not $Src) { throw "No Python $Py in $Cache" }
Remove-Here $Runtime
Copy-Item -Recurse $Src.FullName $Runtime
$Lib = Join-Path $Runtime 'Lib'
Remove-Here (@('test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3') | ForEach-Object { Join-Path $Lib $_ })
Remove-Here (@('tcl', 'include', 'libs', 'DLLs\_tkinter.pyd', 'DLLs\tcl86t.dll', 'DLLs\tk86t.dll') |
    ForEach-Object { Join-Path $Runtime $_ })
Remove-Here (Join-Path $Lib 'EXTERNALLY-MANAGED')
$Python = Join-Path $Runtime 'python.exe'
uv pip install --quiet --python $Python -r (Join-Path $Root 'requirements-app.txt')
$Site = Join-Path $Lib 'site-packages'
Get-ChildItem $Runtime -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $Site -Recurse -Directory -Filter 'tests' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue  # numpy's and scipy's own test suites
Get-ChildItem $Site -Directory -Filter 'setuptools*' | Remove-Item -Recurse -Force  # pip stays: it installs the optional packs

# the engine: what a checkout ships, without the caches, tests and your own data
Remove-Here $Engine
New-Item -ItemType Directory -Force $Engine | Out-Null
foreach ($item in 'amadeus', 'web', 'fixtures', 'examples', 'mixxx', 'licenses', 'LICENSE', 'THIRD_PARTY_NOTICES.md') {
    Copy-Item -Recurse (Join-Path $Root $item) (Join-Path $Engine $item)
}
Get-ChildItem $Engine -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $Engine -Recurse -File -Force -Filter '.DS_Store' | Remove-Item -Force
# the VirtualDJ plugin, when it's built (vdj\build.ps1; release.yml builds it first)
$Plugin = Join-Path $Root 'vdj\build\AmadeusLink.dll'
if (Test-Path $Plugin) {
    New-Item -ItemType Directory -Force (Join-Path $Engine 'vdj\build') | Out-Null
    Copy-Item $Plugin (Join-Path $Engine 'vdj\build\AmadeusLink.dll')
} else {
    Write-Warning "No VirtualDJ plugin ($Plugin): the engine can't install it from this build"
}
# ffmpeg, if one is given (the engine's decoder for formats libsndfile doesn't read)
if ($env:FFMPEG_EXE) {
    New-Item -ItemType Directory -Force (Join-Path $Engine 'bin') | Out-Null
    Copy-Item $env:FFMPEG_EXE (Join-Path $Engine 'bin\ffmpeg.exe')
}

# compiled once here: the installed program folder is never written to (the engine runs with
# PYTHONDONTWRITEBYTECODE), and "unchecked-hash" keeps the .pyc files valid whatever the files' dates become
& $Python -m compileall -q -j 0 --invalidation-mode unchecked-hash $Lib (Join-Path $Engine 'amadeus') | Out-Null

& $Python -c 'import numpy, scipy, soundfile, sounddevice, websockets, openai, serial, aalink, comtypes, zeroconf'
# djay's UI Automation wrapper, generated now: at first use comtypes would write it into %APPDATA%
& $Python -c "import comtypes.client; comtypes.client.GetModule('UIAutomationCore.dll')"
$size = { param($p) '{0:N0} MB' -f ((Get-ChildItem $p -Recurse -File | Measure-Object Length -Sum).Sum / 1MB) }
$version = & $Python -c 'import platform; print(platform.python_version())'
Write-Host "Bundled the engine ($(& $size $Runtime) runtime, $(& $size $Engine) engine, Python $version)"
