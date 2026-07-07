; Inno Setup script per Traduttore Live.
; Compila con:  scripts\build_installer.ps1  (richiede Inno Setup 6 / ISCC.exe)
; Presuppone che la build PyInstaller one-folder esista in
; dist\TranslatorLowerThird\  (vedi scripts\build_exe.ps1).

; MyAppName = user-visible name (shortcuts, Programs list). MyAppShortName =
; internal id kept stable for the install folder and exe filename.
#define MyAppName "Traduttore Live"
#define MyAppShortName "TranslatorLowerThird"
#define MyAppVersion "0.3.0"
#define MyAppPublisher "Michele Dipace"
#define MyAppExeName "TranslatorLowerThird.exe"

[Setup]
; AppId identifica il programma per aggiornamenti/disinstallazione: NON cambiarlo
; tra una versione e l'altra. GUID fisso e valido.
AppId={{A7F3C2E9-4B1D-4E8A-9C6F-2D5B8E1A0F34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppShortName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename={#MyAppShortName}-Setup
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
; Version/metadata stamped into Setup.exe itself (Properties tab).
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Installazione per-macchina sotto Program Files (richiede privilegi admin).
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; La configurazione utente (%APPDATA%\TranslatorLowerThird) e i log
; (%LOCALAPPDATA%\TranslatorLowerThird\logs) NON vengono toccati: l'installer
; scrive solo sotto {app}, quindi la disinstallazione li preserva.

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tutta la cartella one-folder prodotta da PyInstaller.
Source: "..\dist\{#MyAppShortName}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
