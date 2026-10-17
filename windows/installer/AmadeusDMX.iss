; The Amadeus DMX installer: build.ps1 -Release -Installer makes build\AmadeusDMX-Setup-<version>.exe.

#define AppName "Amadeus DMX"
#define AppBase "AmadeusDMX"
#define AppExe "AmadeusDMX.exe"
#define AppGuid "{{C78A06CF-5E91-403C-BD0A-8D286EE31474}"
#define AppMutexName "AmadeusDMX.SingleInstance"
#define IconFile "..\AmadeusDMX\Assets\AppIcon.ico"
#define FirewallRule "Amadeus DMX engine"
#include "common.iss"

[InstallDelete]
; an update replaces the engine and its Python whole: nothing left over from the release before
Type: filesandordirs; Name: "{app}\engine"
Type: filesandordirs; Name: "{app}\runtime"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\engine"
Type: filesandordirs; Name: "{app}\runtime"

[Run]
; Windows Firewall (an install for everyone only): the engine's Python may receive UDP from the local network:
; Art-Net replies (6454), sACN (5568), Ableton Link (20808) and Amadeus Link's deck state (a port it picks). The
; feed (8765) and the setup service (8181) are on 127.0.0.1 only and need no rule. Replaced on every install.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden; StatusMsg: "Setting up Windows Firewall..."; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow protocol=UDP remoteip=localsubnet profile=any program=""{app}\runtime\python.exe"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#FirewallRule}"" dir=in action=allow protocol=UDP remoteip=localsubnet profile=any program=""{app}\runtime\pythonw.exe"""; Flags: runhidden; Check: IsAdminInstallMode

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#FirewallRule}"""; Flags: runhidden; RunOnceId: "FirewallEngine"; Check: IsAdminInstallMode
