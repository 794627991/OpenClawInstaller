; ============================================================
; 🦞 OpenClaw 一键安装器 - Inno Setup 脚本
; ============================================================
; 用法: 编译此脚本生成最终的 .exe 安装器
; 需要: Inno Setup 6+ (https://jrsoftware.org/isinfo.php)
; ============================================================

#define MyAppName "OpenClaw 一键安装器"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "OpenClaw Community"
#define MyAppURL "https://docs.openclaw.ai"
#define MyAppExeName "OpenClaw一键安装器.exe"

[Setup]
AppId={{B8F3A7D2-4E5C-4F8A-9C1D-6A2B3E4F5D6E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\OpenClaw
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=OpenClaw-一键安装-v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=resources\logo.ico
UninstallDisplayIcon={app}\OpenClaw一键安装器.exe
WizardImageFile=resources\welcome.bmp
WizardSmallImageFile=resources\logo.bmp

; 中文语言
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=yes

; 界面颜色自定义（Inno Setup 6.3+）
; BackColor=1e1e2e
; BackColor2=2d2d44

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; 主程序（PyInstaller 打包后的文件夹）
Source: "dist\OpenClaw一键安装器\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 配置文件
Source: "config\*"; DestDir: "{app}\config"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// ============================================================
// 安装前检查
// ============================================================
function InitializeSetup(): Boolean;
begin
  Result := True;
end;

// ============================================================
// 安装完成后操作
// ============================================================
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // 可以在这里执行额外的安装后操作
  end;
end;

// ============================================================
// 卸载时清理
// ============================================================
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 清理 Node.js（如果是我们安装的）
    // 注意：不自动卸载 Node.js，因为用户可能其他地方也在用
  end;
end;
