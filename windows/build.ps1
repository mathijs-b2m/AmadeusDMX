# Build Amadeus DMX and Amadeus Link (release, x64) next to this script in build\.
#   ./build.ps1                      build the apps for this checkout (they run the engine from here, with its .venv)
#   ./build.ps1 -Release             build the apps people download: the engine and its Python inside (bundle-engine.ps1)
#   ./build.ps1 -Release -Installer  … and the installers (build\AmadeusDMX-Setup-<version>.exe, AmadeusLink-Setup-…)
#   ./build.ps1 -Installer -NoBuild  only the installers, from the apps already in build\ (release.yml signs in between)
# -Version 1.2.3 sets the version people see (default 0.1.<commits>); the build number is always the commit count,
# so every later build is newer (what the updater compares). -Out elsewhere builds elsewhere.
# Updates (NetSparkle): only a release with $env:FEED_URL, the appcast Amadeus DMX checks; Amadeus Link checks
# appcast-link-windows.xml next to it ($env:LINK_FEED_URL elsewhere). Both go into appsettings.json beside the exe,
# with the public update key (mac/Resources/sparkle-public-key.txt); a development build gets AmadeusEngineRoot there.
# Needs the .NET 10 SDK; -Release also uv, -Installer Inno Setup 6 (winget install JRSoftware.InnoSetup).
param(
    [switch]$Release,
    [switch]$Installer,
    [switch]$NoBuild,
    [string]$Version,
    [string]$Out = (Join-Path $PSScriptRoot 'build')
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$Here = $PSScriptRoot
$Root = (Resolve-Path "$Here\..").Path
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$Build = try { [int](git -C $Root rev-list --count HEAD) } catch { 0 }
if (-not $Version) { $Version = "0.1.$Build" }
# Windows' own version fields are four numbers: the version's first three and the build number
$m = [regex]::Match($Version, '^(\d+)\.(\d+)\.(\d+)')
if (-not $m.Success) { throw "-Version must start with three numbers (1.2.3), not $Version" }
$FileVersion = "$($m.Groups[1]).$($m.Groups[2]).$($m.Groups[3]).$([Math]::Min($Build, 65535))"

$Apps = @(
    @{ Name = 'AmadeusDMX'; Title = 'Amadeus DMX'; Feed = $env:FEED_URL }
    @{ Name = 'AmadeusLink'; Title = 'Amadeus Link'; Feed = $(
        if ($env:LINK_FEED_URL) { $env:LINK_FEED_URL }
        elseif ($env:FEED_URL) { $env:FEED_URL.Substring(0, $env:FEED_URL.LastIndexOf('/') + 1) + 'appcast-link-windows.xml' }
    ) }
)
$PublicKey = Join-Path $Root 'mac\Resources\sparkle-public-key.txt'

# appsettings.json beside the exe: what the build tells the app (the app reads it, never writes it)
function Write-Settings($App, $Dir) {
    $settings = [ordered]@{}
    # a development build runs the engine from this checkout; a release has its own beside the exe
    if (-not $Release) { $settings.AmadeusEngineRoot = $Root }
    # updates: only a release with a feed and the public update key (the updater stays off otherwise)
    if ($Release -and $App.Feed -and (Test-Path $PublicKey) -and (Get-Item $PublicKey).Length -gt 0) {
        $settings.UpdateFeedUrl = $App.Feed
        $settings.UpdatePublicEdKey = (Get-Content -Raw $PublicKey).Trim()
    }
    $settings | ConvertTo-Json | Set-Content -Encoding utf8NoBOM (Join-Path $Dir 'appsettings.json')
}

if (-not $NoBuild) {
    foreach ($app in $Apps) {
        $dir = Join-Path $Out $app.Name
        if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
        dotnet publish (Join-Path $Here "$($app.Name)\$($app.Name).csproj") -c Release -r win-x64 --self-contained `
            -p:AppVersion=$Version -p:BuildNumber=$Build -o $dir --nologo -v quiet
        Write-Settings $app $dir
    }

    # Amadeus DMX: the engine and its Python beside the exe
    $dmx = Join-Path $Out 'AmadeusDMX'
    if ($Release) { & (Join-Path $Here 'bundle-engine.ps1') $dmx }
    $feed = $Apps[0].Feed
    Write-Host "Built $dmx\AmadeusDMX.exe ($Version$(if ($Release) { ', engine inside' })$(if ($Release -and $feed) { ", updates from $feed" }))"

    # Amadeus Link: the companion for the DJ's laptop, with the VirtualDJ plugin and the Mixxx mapping to install
    $link = Join-Path $Out 'AmadeusLink'
    $plugin = Join-Path $Root 'vdj\build\AmadeusLink.dll'
    if (Test-Path $plugin) {
        New-Item -ItemType Directory -Force (Join-Path $link 'vdj') | Out-Null
        Copy-Item $plugin (Join-Path $link 'vdj\AmadeusLink.dll')
    } else {
        Write-Warning "No VirtualDJ plugin ($plugin, vdj\build.ps1 makes it): Amadeus Link can't install it from this build"
    }
    New-Item -ItemType Directory -Force (Join-Path $link 'mixxx') | Out-Null
    Copy-Item (Join-Path $Root 'mixxx\*.xml'), (Join-Path $Root 'mixxx\*.js') (Join-Path $link 'mixxx')
    $feed = $Apps[1].Feed
    Write-Host "Built $link\AmadeusLink.exe$(if ($Release -and $feed) { ", updates from $feed" })"
}

if ($Installer) {
    $iscc = @(
        (Get-Command iscc -ErrorAction SilentlyContinue).Source
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $iscc) { throw 'Inno Setup 6 is needed: winget install JRSoftware.InnoSetup' }
    if (-not (Test-Path (Join-Path $Out 'AmadeusDMX\engine'))) {
        Write-Warning 'The installer of a development build: it runs the engine from this checkout, not its own'
    }
    foreach ($app in $Apps) {
        $src = Join-Path $Out $app.Name
        if (-not (Test-Path (Join-Path $src "$($app.Name).exe"))) { throw "No $src\$($app.Name).exe: build first" }
        & $iscc /Q "/DAppVersion=$Version" "/DFileVersion=$FileVersion" "/DAppFiles=$src" "/DOutputDir=$Out" `
            (Join-Path $Here "installer\$($app.Name).iss")
        Write-Host "Installer: $Out\$($app.Name)-Setup-$Version.exe"
    }
}
