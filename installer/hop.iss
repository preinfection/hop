; Hop — installer for Hop Island and Hop Clipper (Inno Setup 6).
; Build with installer\build.ps1, which makes the two apps with PyInstaller,
; fetches ffmpeg, and then compiles this script.

#define AppName "Hop"
#define AppVersion Trim(FileRead(FileOpen("..\VERSION")))
#define AppPublisher "preinfection"
#define AppURL "https://github.com/preinfection/hop"
#define Dist "..\build\dist"

[Setup]
AppId={{8C1B6A52-4E0D-4F3B-9E62-6F0A2B7D1C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\Programs\Hop
DefaultGroupName=Hop
DisableProgramGroupPage=yes
; Per user: no admin prompt, and startup entries belong to the user anyway.
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=HopSetup-{#AppVersion}
SetupIconFile=..\assets\hop.ico
UninstallDisplayIcon={app}\Island\HopIsland.exe
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
LicenseFile=..\LICENSE

[Types]
Name: "both"; Description: "Hop Island and Hop Clipper"
Name: "island"; Description: "Hop Island only"
Name: "clipper"; Description: "Hop Clipper only"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "island"; Description: "Hop Island — music, lyrics, prayer times and PC stats at the top of your screen"; Types: both island
Name: "clipper"; Description: "Hop Clipper — press F8 to save the last moments of your screen"; Types: both clipper

[Tasks]
Name: "startisland"; Description: "Start Hop Island with Windows"; Components: island
Name: "startclipper"; Description: "Start Hop Clipper with Windows"; Components: clipper
Name: "desktop"; Description: "Desktop shortcuts"; Flags: unchecked

[InstallDelete]
; An update removes the previous version's app files completely before the new
; ones go in (nothing stale is left behind). Settings live in AppData and are
; never touched.
Type: filesandordirs; Name: "{app}\Island"
Type: filesandordirs; Name: "{app}\Clipper"
Type: filesandordirs; Name: "{app}fmpeg"

[Files]
Source: "{#Dist}\HopIsland\*"; DestDir: "{app}\Island"; Components: island; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Dist}\HopClipper\*"; DestDir: "{app}\Clipper"; Components: clipper; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Dist}\ffmpeg\*"; DestDir: "{app}\ffmpeg"; Components: clipper; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Hop Island"; Filename: "{app}\Island\HopIsland.exe"; Components: island
Name: "{group}\Hop Clipper"; Filename: "{app}\Clipper\HopClipper.exe"; Components: clipper
Name: "{group}\Uninstall Hop"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Hop Island"; Filename: "{app}\Island\HopIsland.exe"; Components: island; Tasks: desktop
Name: "{userdesktop}\Hop Clipper"; Filename: "{app}\Clipper\HopClipper.exe"; Components: clipper; Tasks: desktop
; The same shortcut names the apps' own "Start with Windows" switches use.
Name: "{userstartup}\Hop Island"; Filename: "{app}\Island\HopIsland.exe"; WorkingDir: "{app}\Island"; Components: island; Tasks: startisland
Name: "{userstartup}\Hop Clipper"; Filename: "{app}\Clipper\HopClipper.exe"; WorkingDir: "{app}\Clipper"; Components: clipper; Tasks: startclipper

[Run]
Filename: "{app}\Clipper\HopClipper.exe"; Description: "Start Hop Clipper"; Components: clipper; Flags: nowait postinstall skipifsilent
Filename: "{app}\Island\HopIsland.exe"; Description: "Start Hop Island"; Components: island; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM HopIsland.exe"; Flags: runhidden; RunOnceId: "KillIsland"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM HopClipper.exe"; Flags: runhidden; RunOnceId: "KillClipper"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\Hop Island\web"

[Code]
var
  ModePage: TInputOptionWizardPage;
  IslandPage, ClipperPage: TWizardPage;
  CityEdit: TNewEdit;
  MethodCombo, AsrCombo, SizeCombo, LeftCombo, RightCombo: TNewComboBox;
  LenCombo, FpsCombo, QualityCombo: TNewComboBox;
  FolderEdit: TNewEdit;
  WatermarkCheck, SoundCheck: TNewCheckBox;

{ Aladhan's method id for each line of the calculation list }
function MethodId(I: Integer): Integer;
begin
  case I of
    0: Result := 2;  1: Result := 3;  2: Result := 4;  3: Result := 5;  4: Result := 1;
    5: Result := 13; 6: Result := 15; 7: Result := 16; 8: Result := 8;  9: Result := 12;
  else Result := 2;
  end;
end;

function Customizing: Boolean;
begin
  Result := ModePage.Values[1];
end;

{ ---- small helpers to lay controls out on a custom page ---- }
function AddLabel(Page: TWizardPage; Top: Integer; Text: String): Integer;
var L: TNewStaticText;
begin
  L := TNewStaticText.Create(Page);
  L.Parent := Page.Surface; L.Caption := Text; L.Top := Top; L.Left := 0;
  Result := Top + ScaleY(18);
end;

function AddCombo(Page: TWizardPage; Top: Integer; Items: String; Index: Integer): TNewComboBox;
var C: TNewComboBox; S: String; P: Integer;
begin
  C := TNewComboBox.Create(Page);
  C.Parent := Page.Surface; C.Style := csDropDownList; C.Top := Top; C.Left := 0;
  C.Width := Page.SurfaceWidth;
  S := Items;
  repeat
    P := Pos('|', S);
    if P > 0 then begin C.Items.Add(Copy(S, 1, P - 1)); S := Copy(S, P + 1, Length(S)); end
    else begin C.Items.Add(S); S := ''; end;
  until S = '';
  C.ItemIndex := Index;
  Result := C;
end;

procedure BrowseFolder(Sender: TObject);
var Dir: String;
begin
  Dir := FolderEdit.Text;
  if BrowseForFolder('Where should clips be saved?', Dir, True) then FolderEdit.Text := Dir;
end;

procedure InitializeWizard;
var T: Integer; B: TNewButton;
begin
  ModePage := CreateInputOptionPage(wpSelectTasks, 'Settings', 'Start with the recommended settings, or set things up now?',
    'You can change everything later in Hop Island''s settings (the gear on the island''s last page, or its tray icon).',
    True, False);
  ModePage.Add('Use the recommended settings');
  ModePage.Add('Customize now');
  ModePage.Values[0] := True;
  { /CUSTOMIZE=1 picks "Customize now" (lets the tests run a customized install silently) }
  if ExpandConstant('{param:CUSTOMIZE|0}') = '1' then ModePage.Values[1] := True;
  { /CUSTOMIZE=1 picks "Customize now" (for testing silent installs) }
  if ExpandConstant('{param:CUSTOMIZE|0}') = '1' then ModePage.Values[1] := True;

  { ---- Hop Island ---- }
  IslandPage := CreateCustomPage(ModePage.ID, 'Hop Island', 'Set up the island');
  T := 0;
  T := AddLabel(IslandPage, T, 'Your city, for prayer times and weather (leave empty to skip):');
  CityEdit := TNewEdit.Create(IslandPage);
  CityEdit.Parent := IslandPage.Surface; CityEdit.Top := T; CityEdit.Width := IslandPage.SurfaceWidth;
  T := T + ScaleY(30);
  T := AddLabel(IslandPage, T, 'Prayer time calculation:');
  MethodCombo := AddCombo(IslandPage, T, 'ISNA (North America)|Muslim World League|Umm al-Qura (Makkah)|Egyptian Authority|Karachi|Turkey (Diyanet)|Moonsighting Committee|Dubai|Gulf Region|France (UOIF)', 0);
  T := T + ScaleY(30);
  T := AddLabel(IslandPage, T, 'Asr time:');
  AsrCombo := AddCombo(IslandPage, T, 'Standard|Hanafi', 0);
  T := T + ScaleY(30);
  T := AddLabel(IslandPage, T, 'Island size:');
  SizeCombo := AddCombo(IslandPage, T, 'Small|Normal|Large', 1);
  T := T + ScaleY(30);
  T := AddLabel(IslandPage, T, 'Left of the song:');
  LeftCombo := AddCombo(IslandPage, T, 'Record button (needs Hop Clipper)|Album cover|Nothing', 0);
  T := T + ScaleY(30);
  T := AddLabel(IslandPage, T, 'Right side of the player:');
  RightCombo := AddCombo(IslandPage, T, 'Next prayer|Music bars|Time|Nothing', 0);

  { ---- Hop Clipper ---- }
  ClipperPage := CreateCustomPage(IslandPage.ID, 'Hop Clipper', 'Set up the clipper');
  T := 0;
  T := AddLabel(ClipperPage, T, 'F8 saves the last:');
  LenCombo := AddCombo(ClipperPage, T, '15 seconds|30 seconds|1 minute', 1);
  T := T + ScaleY(30);
  T := AddLabel(ClipperPage, T, 'Frame rate (120 needs a strong PC and a 120 Hz+ screen):');
  FpsCombo := AddCombo(ClipperPage, T, '30 fps|60 fps|120 fps', 1);
  T := T + ScaleY(30);
  T := AddLabel(ClipperPage, T, 'Quality:');
  QualityCombo := AddCombo(ClipperPage, T, 'Best (biggest files)|High|Small (saves space)', 1);
  T := T + ScaleY(30);
  T := AddLabel(ClipperPage, T, 'Save clips to:');
  FolderEdit := TNewEdit.Create(ClipperPage);
  FolderEdit.Parent := ClipperPage.Surface; FolderEdit.Top := T;
  FolderEdit.Width := ClipperPage.SurfaceWidth - ScaleX(90);
  FolderEdit.Text := ExpandConstant('{%USERPROFILE}\Videos\Hop Clips');
  B := TNewButton.Create(ClipperPage);
  B.Parent := ClipperPage.Surface; B.Caption := 'Browse...'; B.Top := T - ScaleY(1);
  B.Left := ClipperPage.SurfaceWidth - ScaleX(82); B.Width := ScaleX(82); B.OnClick := @BrowseFolder;
  T := T + ScaleY(34);
  WatermarkCheck := TNewCheckBox.Create(ClipperPage);
  WatermarkCheck.Parent := ClipperPage.Surface; WatermarkCheck.Top := T; WatermarkCheck.Width := ClipperPage.SurfaceWidth;
  WatermarkCheck.Caption := 'Put the small "recorded with" watermark on clips'; WatermarkCheck.Checked := True;
  T := T + ScaleY(24);
  SoundCheck := TNewCheckBox.Create(ClipperPage);
  SoundCheck.Parent := ClipperPage.Surface; SoundCheck.Top := T; SoundCheck.Width := ClipperPage.SurfaceWidth;
  SoundCheck.Caption := 'Play a click when a clip is saved'; SoundCheck.Checked := True;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = IslandPage.ID) then Result := (not Customizing) or (not WizardIsComponentSelected('island'));
  if (PageID = ClipperPage.ID) then Result := (not Customizing) or (not WizardIsComponentSelected('clipper'));
end;

function Q(S: String): String;          { a JSON string }
begin
  StringChangeEx(S, '\', '\\', True);
  StringChangeEx(S, '"', '\"', True);
  Result := '"' + S + '"';
end;

function B(V: Boolean): String;
begin
  if V then Result := 'true' else Result := 'false';
end;

procedure WriteIslandSettings;
var S, Dir: String; Scale: String; Lefts, Rights: array[0..3] of String;
begin
  Lefts[0] := 'rec'; Lefts[1] := 'art'; Lefts[2] := 'none';
  Rights[0] := 'prayer'; Rights[1] := 'bars'; Rights[2] := 'clock'; Rights[3] := 'none';
  case SizeCombo.ItemIndex of 0: Scale := '0.85'; 2: Scale := '1.2'; else Scale := '1.0'; end;
  S := '{' +
    '"city": ' + Q(Trim(CityEdit.Text)) + ', ' +
    '"prayerMethod": ' + IntToStr(MethodId(MethodCombo.ItemIndex)) + ', ' +
    '"asrSchool": ' + IntToStr(AsrCombo.ItemIndex) + ', ' +
    '"startAtLogin": ' + B(WizardIsTaskSelected('startisland')) + ', ' +
    '"layout": {"scale": ' + Scale + ', "musicLeft": "' + Lefts[LeftCombo.ItemIndex] + '", "musicRight": "' + Rights[RightCombo.ItemIndex] + '"}' +
    '}';
  Dir := ExpandConstant('{userappdata}\LyricsIslandLite');
  ForceDirectories(Dir);
  SaveStringToFile(Dir + '\installer-settings.json', S, False);
end;

procedure WriteClipperSettings;
var S, Dir, Q1: String; Lens: array[0..2] of String; Fps: array[0..2] of String;
begin
  Lens[0] := '15'; Lens[1] := '30'; Lens[2] := '60';
  Fps[0] := '30'; Fps[1] := '60'; Fps[2] := '120';
  case QualityCombo.ItemIndex of 0: Q1 := 'best'; 2: Q1 := 'small'; else Q1 := 'high'; end;
  S := '{' +
    '"defaultSeconds": ' + Lens[LenCombo.ItemIndex] + ', ' +
    '"fps": ' + Fps[FpsCombo.ItemIndex] + ', ' +
    '"quality": "' + Q1 + '", ' +
    '"saveDir": ' + Q(Trim(FolderEdit.Text)) + ', ' +
    '"watermark": ' + B(WatermarkCheck.Checked) + ', ' +
    '"sounds": ' + B(SoundCheck.Checked) + ', ' +
    '"cursor": true, "toastInClips": false, "islandInClips": true' +
    '}';
  Dir := ExpandConstant('{localappdata}\clipper');
  ForceDirectories(Dir);
  SaveStringToFile(Dir + '\settings.json', S, False);
end;

{ Close running copies first, however they were started: ask each one to
  quit through its own window (the clipper saves a recording in progress),
  wait, then force-close anything left. }
procedure AskToQuit(WindowClass: String; Msg, WParam: Integer);
var W: HWND; I: Integer;
begin
  W := FindWindowByClassName(WindowClass);
  if W = 0 then Exit;
  PostMessage(W, Msg, WParam, 0);
  for I := 1 to 100 do
  begin
    if FindWindowByClassName(WindowClass) = 0 then Exit;
    Sleep(100);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer;
begin
  AskToQuit('lyrics-island-lite', $8004, 0);
  AskToQuit('clipper-tray', $0312, 2);          { WM_HOTKEY 2 = Ctrl+Shift+F8, quit }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM HopIsland.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM HopClipper.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if Customizing and WizardIsComponentSelected('island') then WriteIslandSettings;
    if Customizing and WizardIsComponentSelected('clipper') then WriteClipperSettings;
  end;
end;

{ WebView2 (what draws the island) ships with Windows 11 and most Windows 10;
  if it's missing, say where to get it instead of failing silently. }
function InitializeSetup: Boolean;
var V: String;
begin
  Result := True;
  if not (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V)
       or RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', V)) then
    MsgBox('Hop Island needs the Microsoft Edge WebView2 Runtime, which this PC does not seem to have.' + #13#10 +
           'Get it free from Microsoft: https://go.microsoft.com/fwlink/p/?LinkId=2124703' + #13#10#13#10 +
           'Hop Clipper works without it.', mbInformation, MB_OK);
end;
