#define MyAppName "VFX Texture Lab"
#define MyAppPublisher "Matty Wyett-Simmonds and contributors"
#define MyAppURL "https://github.com/MattyGWS/VFXTextureLab"
#define MyAppExeName "VFX Texture Lab.exe"
#define MyAppVersion GetEnv("VFXTL_VERSION")
#define MyWindowsVersion GetEnv("VFXTL_WINDOWS_VERSION")
#define MySourceDir GetEnv("VFXTL_SOURCE_DIR")
#define MyOutputDir GetEnv("VFXTL_OUTPUT_DIR")
#define MyOutputBaseFilename GetEnv("VFXTL_INSTALLER_BASENAME")

#if MyAppVersion == ""
  #error VFXTL_VERSION was not provided.
#endif
#if MyWindowsVersion == ""
  #error VFXTL_WINDOWS_VERSION was not provided.
#endif
#if MySourceDir == ""
  #error VFXTL_SOURCE_DIR was not provided.
#endif
#if MyOutputDir == ""
  #error VFXTL_OUTPUT_DIR was not provided.
#endif
#if MyOutputBaseFilename == ""
  #error VFXTL_INSTALLER_BASENAME was not provided.
#endif

[Setup]
AppId={{5D625FF6-4A27-4D8D-A321-A14C395A8E32}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseFilename}
SetupIconFile=VFXTextureLab.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#MyWindowsVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\.vfxgraph"; ValueType: string; ValueName: ""; ValueData: "VFXTextureLab.Graph"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.Graph"; ValueType: string; ValueName: ""; ValueData: "VFX Texture Lab Graph"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.Graph\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.Graph\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

Root: HKCU; Subkey: "Software\Classes\.vfxpackage"; ValueType: string; ValueName: ""; ValueData: "VFXTextureLab.Package"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.Package"; ValueType: string; ValueName: ""; ValueData: "VFX Texture Lab Package"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.Package\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.Package\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

Root: HKCU; Subkey: "Software\Classes\.vfxexport"; ValueType: string; ValueName: ""; ValueData: "VFXTextureLab.ExportTemplate"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.ExportTemplate"; ValueType: string; ValueName: ""; ValueData: "VFX Texture Lab Export Template"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.ExportTemplate\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.ExportTemplate\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

Root: HKCU; Subkey: "Software\Classes\.vfxnodepkg"; ValueType: string; ValueName: ""; ValueData: "VFXTextureLab.NodePackage"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.NodePackage"; ValueType: string; ValueName: ""; ValueData: "VFX Texture Lab Node Package"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.NodePackage\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKCU; Subkey: "Software\Classes\VFXTextureLab.NodePackage\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
