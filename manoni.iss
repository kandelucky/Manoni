; Inno Setup script for Manoni — builds the Windows installer.
;
; Prerequisite: build the app first so dist\Manoni\ exists and is the SHIPPING
; build (CONSOLE = False in manoni.spec):
;     .venv\Scripts\pyinstaller.exe manoni.spec --noconfirm
;
; Compile:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" manoni.iss
; Output:   installer\Manoni-1.3.2-Setup.exe
;
; What it does:
;   * installs the one-folder PyInstaller build into Program Files
;   * Start-menu shortcut (+ optional desktop icon)
;   * registers .mnf (filter) and .mnl (language) so a double-click / "Open with"
;     opens Manoni with the shared file, each with its own Explorer icon
;   * clean uninstall (user data under %APPDATA%\Manoni is intentionally KEPT)

#define AppName    "Manoni"
#define AppVersion "1.3.2"
#define AppExe     "Manoni.exe"
#define Publisher  "Lasha Kandelaki"

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

; --- Photos: "Open with Manoni" -------------------------------------------
; Manoni is registered as an application that CAN open photos — it does not take
; the association. Whatever opens your .jpg today still opens it tomorrow; Manoni
; simply appears in the Open-with list, and the app already handles being handed a
; file path (manoni.py, single-instance forwarding included).
;
; Two keys do the work. SupportedTypes is what makes Manoni offer itself for these
; types in "Choose another app"; OpenWithList is what puts it in the right-click
; Open-with menu directly. FriendlyAppName is the name Windows shows there —
; without it the list reads "Manoni.exe".
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; The formats Manoni actually opens — keep in step with config.SUPPORTED.
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".jpg";  ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".jpeg"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".png";  ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".webp"; ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".bmp";  ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".gif";  ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".tif";  ValueData: ""
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".tiff"; ValueData: ""
; Offer Manoni in each type's Open-with menu (uninsdeletekey removes only OUR entry).
Root: HKA; Subkey: "Software\Classes\.jpg\OpenWithList\{#AppExe}";  Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.jpeg\OpenWithList\{#AppExe}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.png\OpenWithList\{#AppExe}";  Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.webp\OpenWithList\{#AppExe}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.bmp\OpenWithList\{#AppExe}";  Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.gif\OpenWithList\{#AppExe}";  Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.tif\OpenWithList\{#AppExe}";  Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\.tiff\OpenWithList\{#AppExe}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
