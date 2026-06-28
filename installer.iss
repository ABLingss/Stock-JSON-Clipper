; Inno Setup Script for 灵析 (LingXi) V3.2
; Produces a professional Windows installer (.exe)

#define MyAppName "LingXi"
#define MyAppVersion "3.2"
#define MyAppPublisher "LingXi"
#define MyAppURL "https://github.com/ABLingss/LingXi"
#define MyAppExeName "LingXi.exe"

[Setup]
AppId={{A8B3C5D7-1234-4567-89AB-CDEF01234567}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\LingXi
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=LingXi-Setup-V3.2
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\LingXi.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\灵析 V3.2 (LingXi)"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall 灵析 (LingXi)"; Filename: "{uninstallexe}"
Name: "{autodesktop}\灵析 V3.2 (LingXi)"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch 灵析 (LingXi)"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*.json"
Type: files; Name: "{app}\config.ini"
