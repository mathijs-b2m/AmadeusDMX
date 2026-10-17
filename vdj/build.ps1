# Build the AmadeusLink VirtualDJ plugin for 64-bit Windows and (with -Install) copy it into VirtualDJ.
#   .\vdj\build.ps1             -> vdj\build\AmadeusLink.dll
#   .\vdj\build.ps1 -Install    and into Documents\VirtualDJ\Plugins64\SoundEffect (VirtualDJ loads it at its next start)
# The SDK headers are downloaded from virtualdj.com (not stored in this repository). Needs Visual Studio (or its
# Build Tools) with "Desktop development with C++": cl.exe is found with vswhere, no developer prompt needed.
param([switch]$Install)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$SdkUrl = 'https://www.virtualdj.com/developers/VirtualDJ8_SDK_20211003.zip'
New-Item -ItemType Directory -Force sdk, build | Out-Null
if (-not (Test-Path sdk\vdjDsp8.h)) {
    Write-Host 'Downloading VirtualDJ SDK headers ...'
    Invoke-WebRequest $SdkUrl -OutFile sdk\sdk.zip -UseBasicParsing
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path sdk\sdk.zip))
    try {
        foreach ($e in $zip.Entries | Where-Object { $_.Name -like '*.h' }) {
            [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path $PWD "sdk\$($e.Name)"), $true)
        }
    } finally { $zip.Dispose() }
}

# cl.exe for x64: from a developer prompt as it is, else Visual Studio's own environment script
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue) -or $env:VSCMD_ARG_TGT_ARCH -ne 'x64') {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { throw 'Visual Studio (or its Build Tools) with C++ is needed to build the plugin' }
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $vs) { throw 'Visual Studio has no C++ tools: add "Desktop development with C++"' }
    $vcvars = Join-Path $vs 'VC\Auxiliary\Build\vcvars64.bat'
    $env_cmd = Join-Path $env:TEMP 'amadeus-vcvars.cmd'  # a script of its own: no quoting through cmd /c
    Set-Content $env_cmd "@call `"$vcvars`" >nul`r`n@set" -Encoding ASCII
    cmd /c $env_cmd | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2]) }
    }
    Remove-Item $env_cmd
}

# /MT: the C++ runtime inside the DLL (a DJ laptop needn't have Visual C++'s runtime); /EHsc /O2 like -O2
$out = 'build\AmadeusLink.dll'
cl.exe /nologo /std:c++17 /O2 /EHsc /MT /LD /utf-8 /W3 /Isdk AmadeusLink.cpp /Fobuild\ /Fe:$out /link ws2_32.lib | Out-Host
if ($LASTEXITCODE -ne 0) { throw "cl.exe failed ($LASTEXITCODE)" }
Remove-Item build\AmadeusLink.lib, build\AmadeusLink.exp -ErrorAction SilentlyContinue
$exports = dumpbin /nologo /exports $out | Out-String
if ($exports -notmatch 'DllGetClassObject') { throw "$out doesn't export DllGetClassObject" }
Write-Host "Built vdj\$out (exports DllGetClassObject)"

if ($Install) {
    # VirtualDJ's home: Documents\VirtualDJ, or %LOCALAPPDATA%\VirtualDJ where Documents is on a network share
    $homes = @((Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'VirtualDJ'), (Join-Path $env:LOCALAPPDATA 'VirtualDJ'))
    $vdj = ($homes | Where-Object { (Test-Path "$_\settings.xml") -or (Test-Path "$_\database.xml") } | Select-Object -First 1) ??
        ($homes | Where-Object { Test-Path $_ } | Select-Object -First 1) ?? $homes[0]
    $dest = Join-Path $vdj 'Plugins64\SoundEffect'
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item $out (Join-Path $dest 'AmadeusLink.dll') -Force
    Write-Host "Installed to $dest - restart VirtualDJ, then enable 'AmadeusLink' as a master effect."
}
