; Inno Setup Script para AI Lyrics Assistant (Sprint 23.0 — Beta).
;
; Build: iscc installer\ai-lyrics.iss
; Requer: Inno Setup 6+ (https://jrsoftware.org/isdl.php)
;
; O instalador:
;   1. Copia o payload PyInstaller (dist/ai-lyrics/) para {app}.
;   2. Detecta Visual C++ Redistributable 2015-2022 x64; se ausente,
;      orienta o usuário a instalar (link mostrado).
;   3. Detecta Ollama; se ausente, orienta o usuário a instalar
;      (link mostrado). O download automático requereria IDP
;      (Inno Download Plugin) que não vem com Inno Setup padrão —
;      será adicionado em 23.1 se necessário.
;   4. Cria atalhos (Menu Iniciar + Área de Trabalho opcional).
;   5. Registra desinstalador no Windows.
;
; O wizard de primeira execução (áudio/Holyrics/Ollama modelo/Bíblia/teste)
; é responsabilidade do próprio AI Lyrics na primeira execução, não do
; instalador. O modelo Ollama (~5GB) também é baixado no wizard.

#define MyAppName "AI Lyrics Assistant"
#define MyAppVersion "1.0.0-beta"
#define MyAppPublisher "AI Lyrics"
#define MyAppExeName "ai-lyrics.exe"
#define MyAppURL "https://github.com/ai-lyrics/ai-lyrics"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=ai-lyrics-setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
PrivilegesRequired=admin
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar ícone na &área de trabalho"; GroupDescription: "Ícones adicionais:"

[Files]
; Payload PyInstaller (dist/ai-lyrics/) — gerado antes por build_installer.py.
Source: "..\dist\ai-lyrics\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Visual C++ Redistributable 2015-2022 x64 — se o arquivo vc_redist.x64.exe
; estiver presente no {tmp} (colocado manualmente pelo usuário ou por
; build_installer.py), instala silenciosamente. Caso contrário, a mensagem
; de PrepareForm orienta o usuário a baixar em aka.ms/vs/17/release/vc_redist.x64.exe
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Instalando Visual C++ Redistributable..."; \
  Check: NeedsVCRedistAndFileExists; Flags: waituntilterminated
; Ollama installer — se OllamaSetup.exe estiver presente no {tmp}, instala
; silenciosamente. Caso contrário, mensagem orienta o usuário a baixar em
; ollama.com/download.
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/S"; \
  StatusMsg: "Instalando Ollama (IA local, ~300 MB)..."; \
  Check: NeedsOllamaAndFileExists; Flags: waituntilterminated
; Iniciar AI Lyrics ao final (opcional).
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// ============================================================
// Helper inline-if para montagem de mensagem.
// ============================================================

function iff(cond: Boolean; iftrue, iffalse: String): String;
begin
  if cond then Result := iftrue else Result := iffalse;
end;

// ============================================================
// Detecção de dependências externas
// ============================================================

// Verifica se o Visual C++ Redistributable 2015-2022 x64 está instalado.
// Chave: HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64\Installed=1
function VCRedistInstalled(): Boolean;
var
  Installed: Cardinal;
begin
  if RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
    Result := (Installed <> 0)
  else
    Result := False;
end;

function NeedsVCRedist(): Boolean;
begin
  Result := not VCRedistInstalled();
end;

// Verifica se o arquivo vc_redist.x64.exe está disponível no {tmp}.
function VCRedistFileExists(): Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\vc_redist.x64.exe'));
end;

// Check composto: só tenta instalar se faltar E o arquivo estiver presente.
function NeedsVCRedistAndFileExists(): Boolean;
begin
  Result := NeedsVCRedist() and VCRedistFileExists();
end;

// Verifica se o Ollama está instalado (caminhos comuns no Windows).
function OllamaInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{userpf}\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{userappdata}\Local\Programs\Ollama\ollama.exe')) or
    FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

function NeedsOllama(): Boolean;
begin
  Result := not OllamaInstalled();
end;

function OllamaFileExists(): Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\OllamaSetup.exe'));
end;

function NeedsOllamaAndFileExists(): Boolean;
begin
  Result := NeedsOllama() and OllamaFileExists();
end;

// ============================================================
// Orientação ao usuário quando dependência falta e arquivo não está presente
// ============================================================

function ShouldSkipPage(CurPageID: Integer): Boolean;
begin
  Result := False;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    if NeedsVCRedist() and not VCRedistFileExists() then begin
      SuppressibleMsgBox(
        'ATENÇÃO: O Visual C++ Redistributable 2015-2022 x64 não está instalado.' + #13#10 +
        'O AI Lyrics pode não funcionar corretamente sem ele.' + #13#10#13#10 +
        'Baixe e instale em:' + #13#10 +
        'https://aka.ms/vs/17/release/vc_redist.x64.exe' + #13#10#13#10 +
        'Após instalar, reinicie o AI Lyrics.',
        mbInformation, MB_OK, IDOK);
    end;
    if NeedsOllama() and not OllamaFileExists() then begin
      SuppressibleMsgBox(
        'ATENÇÃO: O Ollama (IA local) não está instalado.' + #13#10 +
        'O AI Lyrics precisa do Ollama para inferência semântica.' + #13#10#13#10 +
        'Baixe e instale em:' + #13#10 +
        'https://ollama.com/download' + #13#10#13#10 +
        'Após instalar, execute o AI Lyrics novamente. O wizard de primeira' + #13#10 +
        'execução vai orientar o download do modelo de IA (~5 GB).',
        mbInformation, MB_OK, IDOK);
    end;
  end;
end;

// ============================================================
// Prepara mensagem de boas-vindas informativa
// ============================================================

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption :=
    'Este instalador vai copiar o AI Lyrics Assistant para o seu computador.' + #13#10#13#10 +
    'Dependências externas verificadas:' + #13#10 +
    '  • Visual C++ Redistributable: ' + iff(VCRedistInstalled(), 'instalado', 'sera orientado') + #13#10 +
    '  • Ollama (IA local): ' + iff(OllamaInstalled(), 'instalado', 'sera orientado') + #13#10#13#10 +
    'Na primeira execucao, o AI Lyrics abrira um assistente de configuracao' + #13#10 +
    'para selecionar o microfone, validar o Holyrics, baixar o modelo de IA' + #13#10 +
    '(~5 GB) e validar a Biblia local.';
end;
