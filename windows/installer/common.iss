; What both installers share. AmadeusDMX.iss and AmadeusLink.iss define the app and include this.
; build.ps1 passes AppVersion (0.3.0), FileVersion (0.3.0.412: Windows' four numbers), AppFiles (the published app)
; and OutputDir; without them (opened in the Inno Setup IDE) it builds from ..\build\<app>.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef FileVersion
  #define FileVersion "0.0.0.0"
#endif
#ifndef AppFiles
  #define AppFiles "..\build\" + AppBase
#endif
#ifndef OutputDir
  #define OutputDir "..\build"
#endif

[Setup]
; AppId is the app's identity to Windows (upgrades, the uninstaller): fixed forever, never change it
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Amadeus DMX
VersionInfoVersion={#FileVersion}
VersionInfoProductTextVersion={#AppVersion}
; for everyone in Program Files (admin), or, chosen in the first dialog, for you alone in
; %LOCALAPPDATA%\Programs (no admin, no firewall rules)
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UsedUserAreasWarning=no
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 22H2
MinVersion=10.0.19045
LicenseFile=..\..\LICENSE
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir={#OutputDir}
OutputBaseFilename={#AppBase}-Setup-{#AppVersion}
; a running app is closed first (the app holds this mutex; Restart Manager closes what's left, e.g. the engine)
AppMutex={#AppMutexName},Global\{#AppMutexName}
SetupMutex={#AppBase}.Setup
CloseApplications=yes
RestartApplications=no
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppFiles}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Your data (%LOCALAPPDATA%\Amadeus DMX: sets, rigs, settings, packs, the cache) is never touched: the uninstaller
; removes only the program folder.
