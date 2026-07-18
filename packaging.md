# Empacotamento com PyInstaller — AI Lyrics Assistant

## Pré-requisitos

```bash
pip install pyinstaller
```

## Comando de build

```bash
pyinstaller ai-lyrics.spec
```

## Notas técnicas

### pysilero-vad (VAD)

O `pysilero-vad` é uma extensão nativa (cp39-abi3) que inclui:
- `silero_vad` (módulo compilado C/C++)
- `ggml-silero-v6.2.0.bin` (modelo ~2MB embutido no wheel)

O PyInstaller detecta automaticamente a extensão nativa via `hookutils`.
O arquivo `.bin` (modelo) é incluído via `--collect-data pysilero_vad`
ou explicitamente no `datas` do .spec.

### sounddevice

O `sounddevice` depende de `PortAudio` (DLL no Windows). O PyInstaller
inclui automaticamente via hookutils. Se necessário, copie
`portaudio.dll` manualmente.

### Arquitetura

O .spec está configurado para Windows 64-bit. Para distribuição:
- Build em Windows 10/11 64-bit
- Python 3.12+ (recomendado 3.12 ou 3.13 para máxima compatibilidade de wheels)
- O wheel cp39-abi3 do pysilero-vad é compatível com Python 3.9–3.14+

### Instalador .exe / .msi

Após gerar `dist/ai-lyrics/` com PyInstaller:
1. Use **Inno Setup** (gratuito) para criar instalador .exe
2. Ou use **WiX Toolset** para criar .msi

Veja `installer/ai-lyrics.iss` (Inno Setup) para template.
