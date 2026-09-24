; Instalador de Windows (Inno Setup 6).
;   iscc /DVersion=2.0.0 empaquetado\instalador.iss
; Empaqueta dist\GuionTimecodes\ (lo que genera PyInstaller) en
; dist\GuionTimecodes-Setup-<versión>.exe
;
; Se instala solo para el usuario actual (no pide permisos de administrador).
; Los modelos descargados y las librerías de GPU viven en %LOCALAPPDATA%\GuionTimecodes
; y se conservan al actualizar o desinstalar (pesan varios GB).

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6F1C7B52-2B7E-4B0F-9C1E-6A1D3E0B7A51}
AppName=Guion con Time Codes
AppVersion={#Version}
AppPublisher=sunkpoet-lang
AppPublisherURL=https://github.com/sunkpoet-lang/guion-timecodes-whisper-
AppSupportURL=https://github.com/sunkpoet-lang/guion-timecodes-whisper-/issues
AppUpdatesURL=https://github.com/sunkpoet-lang/guion-timecodes-whisper-/releases
DefaultDirName={localappdata}\Programs\GuionTimecodes
DefaultGroupName=Guion con Time Codes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GuionTimecodes-Setup-{#Version}
SetupIconFile=icono.ico
UninstallDisplayIcon={app}\GuionTimecodes.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\GuionTimecodes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Al actualizar, borra los archivos del programa anterior (no toca modelos ni configuración)
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Guion con Time Codes"; Filename: "{app}\GuionTimecodes.exe"
Name: "{autodesktop}\Guion con Time Codes"; Filename: "{app}\GuionTimecodes.exe"; Tasks: escritorio

[Run]
Filename: "{app}\GuionTimecodes.exe"; Description: "Abrir Guion con Time Codes"; Flags: nowait postinstall skipifsilent
