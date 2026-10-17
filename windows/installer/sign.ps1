# Sign files with a code-signing certificate (.pfx) and signtool, time-stamped (the signature outlives the
# certificate). release.yml uses it when WINDOWS_PFX_BASE64 is set; Azure Trusted Signing has its own action there.
#   ./sign.ps1 -Pfx cert.pfx -Password $env:PFX_PASSWORD file.exe [more.exe …]
param(
    [Parameter(Mandatory)][string]$Pfx,
    [Parameter(Mandatory)][string]$Password,
    [Parameter(Mandatory, ValueFromRemainingArguments)][string[]]$Files
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

# signtool comes with the Windows SDK (on GitHub's Windows runners): the newest x64 one
$signtool = (Get-Command signtool -ErrorAction SilentlyContinue).Source
if (-not $signtool) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Parent.Name -match '^\d+(\.\d+)+$' } | Sort-Object { [version]$_.Directory.Parent.Name } | Select-Object -Last 1 -ExpandProperty FullName
}
if (-not $signtool) { throw 'signtool is needed: install the Windows SDK' }

$timestamp = if ($env:WINDOWS_TIMESTAMP_URL) { $env:WINDOWS_TIMESTAMP_URL } else { 'http://timestamp.digicert.com' }
& $signtool sign /fd SHA256 /td SHA256 /tr $timestamp /f $Pfx /p $Password /q @Files
& $signtool verify /pa /q @Files
Write-Host "Signed $($Files.Count) file(s)"
