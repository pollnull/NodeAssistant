; El instalador de Node Assistant (Inno Setup 6). Lo compila la Action "Instaladores" para x64 y ARM64:
;   iscc /DArch=x64 /DSource=..\dist\x64 /DVersion=1.0.0 installer\NodeAssistant.iss
; Se instala para el usuario (sin pedir administrador) en %LOCALAPPDATA%\Programs\NodeAssistant: ahí Node guarda sus
; ajustes, plugins, skills y voces, y al actualizar no se pierden (el instalador no los pisa ni los borra).

#ifndef Arch
  #define Arch "x64"
#endif
#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Source
  #define Source "..\dist\NodeAssistant"
#endif

[Setup]
AppId={{6F3B0C1E-8E57-4C8A-9D53-2E4B9A1D7C20}
AppName=Node Assistant
AppVersion={#Version}
AppPublisher=PollNull
AppPublisherURL=https://github.com/pollnull/NodeAssistant
AppSupportURL=https://github.com/pollnull/NodeAssistant/issues
DefaultDirName={localappdata}\Programs\NodeAssistant
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=NodeAssistant-{#Version}-setup-{#Arch}
SetupIconFile=..\icons\node.ico
UninstallDisplayIcon={app}\NodeAssistant.exe
UninstallDisplayName=Node Assistant
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[CustomMessages]
es.CloseNode=Cerrar Node Assistant
en.CloseNode=Close Node Assistant
pt.CloseNode=Fechar o Node Assistant
fr.CloseNode=Fermer Node Assistant
de.CloseNode=Node Assistant beenden
it.CloseNode=Chiudi Node Assistant
es.StartWithWindows=Iniciar Node Assistant con Windows
en.StartWithWindows=Start Node Assistant with Windows
pt.StartWithWindows=Iniciar o Node Assistant com o Windows
fr.StartWithWindows=Démarrer Node Assistant avec Windows
de.StartWithWindows=Node Assistant mit Windows starten
it.StartWithWindows=Avvia Node Assistant con Windows

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "{cm:StartWithWindows}"

[Files]
; Todo lo que armó installer/build.py. Lo tuyo (ajustes.json, proveedores.json, voices/, plugins que instalaste…) no
; viene en el instalador, así que se conserva al actualizar.
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Node Assistant"; Filename: "{app}\NodeAssistant.exe"
Name: "{autoprograms}\{cm:CloseNode}"; Filename: "{app}\NodeAssistant.exe"; Parameters: "--stop"; IconFilename: "{app}\icons\cerrar.ico"
Name: "{autodesktop}\Node Assistant"; Filename: "{app}\NodeAssistant.exe"; Tasks: desktopicon

[Registry]
; El mismo valor que escribe /settings → General → Iniciar con Windows (se puede cambiar ahí después).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "NodeAssistant"; ValueData: """{app}\NodeAssistant.exe"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\NodeAssistant.exe"; Description: "{cm:LaunchProgram,Node Assistant}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\NodeAssistant.exe"; Parameters: "--stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopNode"

[Code]
// Antes de instalar o actualizar: cierra Node si está abierto (si no, Windows no deja reemplazar sus archivos).
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  if FileExists(ExpandConstant('{app}\NodeAssistant.exe')) then
    Exec(ExpandConstant('{app}\NodeAssistant.exe'), '--stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
