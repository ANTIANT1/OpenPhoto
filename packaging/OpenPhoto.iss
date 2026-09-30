#ifndef AppVersion
  #define AppVersion "0.2.4"
#endif
[Setup]
AppId={{8241753F-117E-436F-9E5F-7235B3FBDCC5}
AppName=OpenPhoto
AppVersion={#AppVersion}
AppPublisher=OpenPhoto contributors
DefaultDirName={localappdata}\Programs\OpenPhoto
DefaultGroupName=OpenPhoto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=OpenPhoto-{#AppVersion}-setup
Compression=zip/6
SolidCompression=no
DiskSpanning=yes
DiskSliceSize=2000000000
WizardStyle=modern
UninstallDisplayIcon={app}\OpenPhoto.exe
LicenseFile=..\LICENSE
SetupIconFile=OpenPhoto.ico
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
[Files]
Source: "..\tools\vendor\webview2\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: dontcopy
Source: "..\dist\OpenPhoto\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\OpenPhoto"; Filename: "{app}\OpenPhoto.exe"
Name: "{autodesktop}\OpenPhoto"; Filename: "{app}\OpenPhoto.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"
[Run]
Filename: "{app}\OpenPhoto.exe"; Description: "{cm:LaunchProgram,OpenPhoto}"; Flags: nowait postinstall skipifsilent

[Code]
function WebViewInstalled: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
  if not Result then
    Result := (RegQueryStringValue(HKLM32, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if WebViewInstalled then exit;
  ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := 'Unable to start the bundled Microsoft WebView2 installer.'
  else if not WebViewInstalled then
    Result := 'Microsoft WebView2 installation failed. Error: ' + IntToStr(ResultCode);
end;
