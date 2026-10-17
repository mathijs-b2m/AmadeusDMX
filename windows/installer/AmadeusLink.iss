; The Amadeus Link installer (the DJ's laptop): build.ps1 -Release -Installer makes
; build\AmadeusLink-Setup-<version>.exe. It carries the VirtualDJ plugin (vdj\) and the Mixxx mapping (mixxx\).

#define AppName "Amadeus Link"
#define AppBase "AmadeusLink"
#define AppExe "AmadeusLink.exe"
#define AppGuid "{{8DA99DBD-2AAD-47DA-936D-DAD6BEA45396}"
#define AppMutexName "AmadeusLink.SingleInstance"
#define IconFile "..\AmadeusLink\Assets\AppIcon.ico"
#define FirewallRule "Amadeus Link"
#include "common.iss"

[Run]
; Windows Firewall (an install for everyone only): the lighting computer pairs over TCP 7123 and fetches tracks
; on it; the VirtualDJ plugin's packets (UDP 9123) come from this computer. Replaced on every install.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden; StatusMsg: "Setting up Windows Firewall..."; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow protocol=TCP localport=7123 remoteip=localsubnet profile=any program=""{app}\{#AppExe}"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow protocol=UDP localport=9123 profile=any program=""{app}\{#AppExe}"""; Flags: runhidden; Check: IsAdminInstallMode

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden; RunOnceId: "FirewallLink"; Check: IsAdminInstallMode
