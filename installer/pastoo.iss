; Pastoo installer (Inno Setup 6). Built by build.bat:
;   ISCC /DAppVersion=<version> installer\pastoo.iss  ->  dist\Pastoo-Setup-<version>.exe
; Installs per user (no admin rights) from dist\Pastoo, the PyInstaller folder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{0D06521E-9AC2-403A-8930-8FC8A20CE2CB}
AppName=Pastoo
AppVersion={#AppVersion}
AppVerName=Pastoo {#AppVersion}
AppPublisher=sadi754
AppPublisherURL=https://github.com/sadi754/pastoo
AppSupportURL=https://github.com/sadi754/pastoo/issues
VersionInfoVersion={#AppVersion}
; Per user: %LOCALAPPDATA%\Programs\Pastoo, no UAC prompt
PrivilegesRequired=lowest
DefaultDirName={autopf}\Pastoo
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
; Pastoo holds this mutex while it runs: Setup asks you to exit it first.
AppMutex=Local\Pastoo
CloseApplications=no
SetupIconFile=..\build\pastoo.ico
UninstallDisplayIcon={app}\Pastoo.exe
UninstallDisplayName=Pastoo
WizardStyle=modern
ShowLanguageDialog=auto
OutputDir=..\dist
OutputBaseFilename=Pastoo-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fa"; MessagesFile: "Farsi.isl"

[CustomMessages]
en.AutoStart=Start Pastoo when I sign in to Windows (in the tray)
fa.AutoStart=اجرای Pastoo هنگام ورود به ویندوز (در tray)
en.DeleteData=Also delete Pastoo's data on this PC (settings, backup history)?%n%nYour backups on files.ir stay either way. Choose No to keep the data for a later installation.
fa.DeleteData=داده‌های Pastoo روی این کامپیوتر هم پاک شود؟ (تنظیمات، تاریخچه‌ی بکاپ‌ها)%n%nبکاپ‌های شما روی files.ir در هر حال می‌مانند. اگر بعداً دوباره نصب می‌کنید، «خیر» را بزنید.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStart}"; Check: not AutoStartEnabled

[InstallDelete]
; An update replaces the program files completely (no leftovers from the old version).
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Pastoo\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Pastoo"; Filename: "{app}\Pastoo.exe"
Name: "{autodesktop}\Pastoo"; Filename: "{app}\Pastoo.exe"; Tasks: desktopicon

[Registry]
; The same entry Pastoo's own Settings -> "Start with Windows" switch writes.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Pastoo"; \
    ValueData: """{app}\Pastoo.exe"" --minimized"; Tasks: autostart

[Run]
Filename: "{app}\Pastoo.exe"; Description: "{cm:LaunchProgram,Pastoo}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

{ Already starting with Windows (set in Pastoo or by an earlier install): don't offer it again. }
function AutoStartEnabled: Boolean;
begin
  Result := RegValueExists(HKCU, RunKey, 'Pastoo');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, RunKey, 'Pastoo');
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\Pastoo');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
