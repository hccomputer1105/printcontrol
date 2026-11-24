; Script de Instalación Empresarial para PrintControl Agente

[Setup]
AppName=PrintControl Agente
AppVersion=1.0.0
AppPublisher=PrintControl Systems
DefaultDirName={autopf}\PrintControl
DefaultGroupName=PrintControl
UninstallDisplayIcon={app}\PrintControlAgente.exe
Compression=lzma2
SolidCompression=yes
OutputDir=instalador_final
OutputBaseFilename=InstalarPrintControlAgente
PrivilegesRequired=admin
WizardStyle=modern

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "dist\PrintControlAgente.exe"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; Arranque automático en Windows para todos los usuarios
Root: HKLM; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "PrintControlAgente"; ValueData: """{app}\PrintControlAgente.exe"""; Flags: uninsdeletevalue

[Run]
; Detener cualquier instancia previa antes de iniciar la nueva
Filename: "taskkill.exe"; Parameters: "/F /IM PrintControlAgente.exe"; Flags: runhidden; StatusMsg: "Deteniendo versiones anteriores..."
; Ejecutar el agente en segundo plano al terminar la instalación
Filename: "{app}\PrintControlAgente.exe"; Flags: nowait postinstall skipifsilent; Description: "Iniciar PrintControl Agente ahora"
Filename: "{app}\PrintControlAgente.exe"; Flags: nowait runhidden; Check: WizardSilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM PrintControlAgente.exe"; Flags: runhidden

[Code]
var
  ConfigPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  // Crea una pantalla personalizada en el asistente para pedir URL y Token API
  ConfigPage := CreateInputQueryPage(wpSelectDir,
    'Configuración del Servidor PrintControl',
    'Ingrese los datos de conexión de la empresa cliente.',
    'Estos valores vinculan esta computadora con el panel central.');
  ConfigPage.Add('URL del Servidor (ej. https://impresion.tuempresa.com):', False);
  ConfigPage.Add('Token API de la Empresa (UUID):', False);

  // Valores por defecto o recibidos por línea de comandos (/URL=... /TOKEN=...)
  ConfigPage.Values[0] := ExpandConstant('{param:URL|http://127.0.0.1:8000}');
  ConfigPage.Values[1] := ExpandConstant('{param:TOKEN|}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ConfigPage.ID then
  begin
    if Trim(ConfigPage.Values[0]) = '' then
    begin
      MsgBox('Debe ingresar la URL del servidor.', mbError, MB_OK);
      Result := False;
    end
    else if Trim(ConfigPage.Values[1]) = '' then
    begin
      MsgBox('Debe ingresar el Token API de la empresa.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  IniFile: String;
  UrlVal, TokenVal: String;
begin
  if CurStep = ssPostInstall then
  begin
    IniFile := ExpandConstant('{app}\config.ini');
    UrlVal := Trim(ConfigPage.Values[0]);
    TokenVal := Trim(ConfigPage.Values[1]);

    // Genera el archivo config.ini automáticamente en la carpeta de instalación
    SaveStringToFile(IniFile, '[SERVIDOR]' + #13#10, False);
    SaveStringToFile(IniFile, 'url_base = ' + UrlVal + #13#10, True);
    SaveStringToFile(IniFile, 'token_api = ' + TokenVal + #13#10, True);
    SaveStringToFile(IniFile, 'intervalo_sincronizacion = 60' + #13#10, True);
  end;
end;