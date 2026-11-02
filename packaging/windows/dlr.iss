; Windows installer for Dlr (Inno Setup 6): turns dist\Dlr\ (from build.py) into one
; Dlr-windows-setup.exe that anyone can double-click.
;
;   iscc /DAppVersion=1.1.0 packaging\windows\dlr.iss
;
; Installs for the current user only, so it never asks for an administrator password.
; Adds Dlr to the Start menu (and the desktop), and to Settings > Apps for uninstalling.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{13C9F04A-D872-4416-AE17-6B9326CA7528}
AppName=Dlr
AppVersion={#AppVersion}
AppVerName=Dlr {#AppVersion}
AppPublisher=Ziad Gahlan
AppPublisherURL=https://github.com/Ziad-cp/Dlr
AppSupportURL=https://github.com/Ziad-cp/Dlr
DefaultDirName={localappdata}\Programs\Dlr
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UninstallDisplayName=Dlr
UninstallDisplayIcon={app}\Dlr.exe
SetupIconFile=..\icon.ico
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
OutputDir=..\..\dist
OutputBaseFilename=Dlr-windows-setup

[Tasks]
Name: "desktopicon"; Description: "Put a Dlr shortcut on the desktop"

[Files]
Source: "..\..\dist\Dlr\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An update replaces the whole app folder, so no old files are left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Dlr"; Filename: "{app}\Dlr.exe"
Name: "{autodesktop}\Dlr"; Filename: "{app}\Dlr.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Dlr.exe"; Description: "Open Dlr now"; Flags: nowait postinstall skipifsilent
