#ifndef PackageDir
  #error PackageDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

#ifndef AppIdValue
  #define AppIdValue "{{A782FB3C-E802-4CC0-B55E-C94FDABFD980}"
#endif

[Setup]
AppId={#AppIdValue}
AppName=SHAD 智慧供热平台
AppVersion=0.7.3
AppPublisher=SHAD
DefaultDirName={localappdata}\Programs\SHAD
DefaultGroupName=SHAD
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=SHAD-Setup-0.7.3-x64
SetupIconFile=..\..\desktop\icon.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
UsePreviousTasks=no
AppMutex=Local\SHAD.LocalService
SetupMutex=Local\SHAD.Setup
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\SHAD.exe
InfoBeforeFile=installer-info.txt

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建或更新桌面快捷方式"

[Files]
Source: "{#PackageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc"

[Icons]
Name: "{group}\启动 SHAD"; Filename: "{app}\SHAD.exe"; WorkingDir: "{app}"; IconFilename: "{app}\resources\shad-0.7.3.ico"; IconIndex: 0; AppUserModelID: "SHAD.Desktop"
Name: "{group}\停止 SHAD"; Filename: "{app}\停止SHAD.cmd"; WorkingDir: "{app}"
Name: "{group}\查看状态"; Filename: "{app}\查看状态.cmd"; WorkingDir: "{app}"
Name: "{group}\备份数据"; Filename: "{app}\备份数据.cmd"; WorkingDir: "{app}"
Name: "{group}\卸载 SHAD"; Filename: "{uninstallexe}"
Name: "{autodesktop}\SHAD"; Filename: "{app}\SHAD.exe"; WorkingDir: "{app}"; Tasks: desktopicon; IconFilename: "{app}\resources\shad-0.7.3.ico"; IconIndex: 0; AppUserModelID: "SHAD.Desktop"

[Run]
Filename: "{app}\SHAD.exe"; Description: "启动 SHAD"; Flags: nowait postinstall skipifsilent unchecked

; Deliberately no UninstallDelete or data-directory registration.
; Inno removes only installed files; business data and backups stay untouched.
