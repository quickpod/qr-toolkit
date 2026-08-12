; Inno Setup — QR & Barcode Toolkit. Signed single-file installer, compiled in CI.
#define AppName "QR & Barcode Toolkit"
#define AppVersion "1.0.2"

[Setup]
AppId={{3C3F7C20-6D48-4E5B-8C71-9B0E2F3A4D53}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=QuickOpen (quickopen.ai)
AppPublisherURL=https://quickopen.ai/projects/qr-toolkit
DefaultDirName={autopf}\QRToolkit
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\QRToolkit.exe
OutputDir=dist
OutputBaseFilename=QRToolkit-Setup
SetupIconFile=..\qr-toolkit.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=branding\wizard-large.bmp
WizardSmallImageFile=branding\wizard-small.bmp
AppCopyright=Apache-2.0. 100%% AI-built, published on QuickOpen (quickopen.ai).
VersionInfoCompany=QuickOpen
VersionInfoProductName=QR & Barcode Toolkit
VersionInfoVersion=1.0.2.0
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=QR & Barcode Toolkit is a 100%% AI-built, open-source offline tool, published on QuickOpen (quickopen.ai).%n%nThis will install it on your computer.
BeveledLabel=QuickOpen · quickopen.ai

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "trustca"; Description: "Trust the QuickOpen Root CA (lets Windows verify QuickOpen signatures)"; GroupDescription: "Security:"; Flags: unchecked

[Files]
Source: "staging\QRToolkit.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "staging\quickopen-root.crt"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "staging\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme skipifsourcedoesntexist
Source: "staging\LICENSE"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\QR & Barcode Toolkit"; Filename: "{app}\QRToolkit.exe"; IconFilename: "{app}\QRToolkit.exe"
Name: "{group}\Uninstall QR & Barcode Toolkit"; Filename: "{uninstallexe}"
Name: "{autodesktop}\QR & Barcode Toolkit"; Filename: "{app}\QRToolkit.exe"; IconFilename: "{app}\QRToolkit.exe"; Tasks: desktopicon

[Run]
Filename: "certutil.exe"; Parameters: "-addstore -user Root ""{app}\quickopen-root.crt"""; Tasks: trustca; Flags: runhidden; StatusMsg: "Trusting the QuickOpen Root CA..."
Filename: "{app}\QRToolkit.exe"; Description: "Launch QR & Barcode Toolkit now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\QRToolkit"

