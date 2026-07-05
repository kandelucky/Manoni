; Inno Setup script for Manoni — builds the Windows installer.
;
; Prerequisite: build the app first so dist\Manoni\ exists and is the SHIPPING
; build (CONSOLE = False in manoni.spec):
;     .venv\Scripts\pyinstaller.exe manoni.spec --noconfirm
;
; Compile:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" manoni.iss
; Output:   installer\Manoni-1.0.0-Setup.exe
;
; What it does:
;   * installs the one-folder PyInstaller build into Program Files
;   * Start-menu shortcut (+ optional desktop icon)
;   * registers .mnf (filter) and .mnl (language) so a double-click / "Open with"
;     opens Manoni with the shared file, each with its own Explorer icon
;   * clean uninstall (user data under %APPDATA%\Manoni is intentionally KEPT)

#define AppName    "Manoni"
#define AppVersion "1.0.0"
#define AppExe     "Manoni.exe"
#define Publisher  "Voxe Studio"

[Setup]
; AppId uniquely identifies Manoni for upgrades/uninstall — never change it.
AppId={{8F3A6C21-4D9E-4E2B-9A17-2C6B5F0D8E44}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=manoni.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 64-bit only — the PyInstaller bootloader here is Windows-64bit.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Program Files + HKCR file associations need admin.
PrivilegesRequired=admin
ChangesAssociations=yes
OutputDir=installer
OutputBaseFilename=Manoni-{#AppVersion}-Setup

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole one-folder build (Manoni.exe + _internal\...).
Source: "dist\Manoni\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; File-type icons used by the registry associations below — must persist on disk.
Source: "mnf.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "mnl.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; --- .mnf : Manoni filter preset ------------------------------------------
Root: HKA; Subkey: "Software\Classes\.mnf"; ValueType: string; ValueName: ""; ValueData: "Manoni.Filter"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Manoni.Filter"; ValueType: string; ValueName: ""; ValueData: "Manoni Filter"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Manoni.Filter\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\mnf.ico"
Root: HKA; Subkey: "Software\Classes\Manoni.Filter\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; --- .mnl : Manoni language pack ------------------------------------------
Root: HKA; Subkey: "Software\Classes\.mnl"; ValueType: string; ValueName: ""; ValueData: "Manoni.Language"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Manoni.Language"; ValueType: string; ValueName: ""; ValueData: "Manoni Language"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Manoni.Language\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\mnl.ico"
Root: HKA; Subkey: "Software\Classes\Manoni.Language\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
