; Inno Setup script for HullVanguard
; Compile with:  iscc installer.iss
; Produces: installer_output\HullVanguard-Setup-1.0.0.exe

#define MyAppName        "HullVanguard"
#define MyAppVersion     "1.0.0"
#define MyAppPublisher   "WEIJIAN"
#define MyAppExeName     "HullVanguard.exe"
#define MyAppDebugExe    "HullVanguard-Debug.exe"

[Setup]
; Stable AppId — do NOT change between releases or upgrades will install side-by-side.
AppId={{8F4E2C1A-7B3D-4A6F-9E5C-1D2A8B7F3C4E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}

; Per-user OR per-machine — user picks at install time.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

OutputDir=installer_output
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

Compression=lzma2/ultra
SolidCompression=yes
LZMAUseSeparateProcess=yes

WizardStyle=modern
WizardSizePercent=110
ShowLanguageDialog=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "debugshortcut"; Description: "Create Start Menu shortcut for the &debug build (shows console log)"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Main app payload (PyInstaller --onedir output).
Source: "dist\HullVanguard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; YOLO model file lives outside the app dir, beside the exe under \AI\runs\...
; Source path is relative to this .iss file (GUI\), so we go up one level into AI\.
Source: "..\AI\runs\barnacle_detect_v2\weights\best.pt"; DestDir: "{app}\AI\runs\barnacle_detect_v2\weights"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\AI\runs\barnacle_detect\weights\best.pt";    DestDir: "{app}\AI\runs\barnacle_detect\weights";    Flags: ignoreversion skipifsourcedoesntexist

; Standalone README for the lab team.
Source: "README_install.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} (Debug Console)"; Filename: "{app}\{#MyAppDebugExe}"; IconFilename: "{app}\{#MyAppDebugExe}"; Tasks: debugshortcut
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean PyInstaller-generated runtime files. User data in %APPDATA%\HullVanguard is left alone
; so logs/settings/snapshots survive a reinstall — the user can delete that folder manually.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#MyAppExeName}"
Type: files; Name: "{app}\{#MyAppDebugExe}"
