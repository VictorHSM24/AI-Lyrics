# Relatório — Sprint 14: Backend Capability Completion

**Data:** 2025-01-XX  
**Sprint:** 14 — Backend Capability Completion  
**Status:** ✅ Concluído  
**Testes:** 2517 backend (Python) + 434 frontend (TypeScript) = 2951 testes, todos passando

---

## Objetivo

Substituir todas as implementações mock e placeholder por funcionalidades reais de backend nas seções Configuration, Audio, Health, System e About, mantendo rigorosamente a arquitetura estabelecida no Sprint 13 (fluxo Backend → REST → SDK → Bootstrap/Store → Hook → React).

---

## Resumo das Mudanças

### 1. Configuration PUT — Persistência Real

**Problema:** Apenas `GET /configuration` existia. A `ConfigurationPresentationService` usava `_minimal_config()` (SimpleNamespace) em vez de carregar `config.yaml`. Não havia persistência.

**Solução:**
- **`config/persistence.py`** (novo): funções `load_overrides()`, `save_overrides()`, `merge_overrides()`, `validate_overrides()`. Persiste overrides em `config/config.overrides.json` atomicamente (write tmp + `os.replace`).
- **`presentation/services.py`**: `ConfigurationPresentationService.update_configuration()` — valida, mescla, persiste e aplica overrides na config em memória.
- **`api/routers/configuration.py`**: adicionado `PUT /configuration` com `ConfigurationUpdateModel` (Pydantic). Apenas campos não-null são aplicados.
- **`api/startup/composition.py`**: `_load_config()` carrega `config.yaml` real via `config.loader.load_config()` + aplica overrides persistidos. Fallback para `_minimal_config()` apenas se config.yaml não existir.

**Fluxo:** `PUT /configuration` → valida → mescla → salva em disco → aplica em memória → retorna DTO atualizado.

### 2. Audio API — Dispositivos e Níveis Reais

**Problema:** Nenhum router de áudio existia. `AudioTab` usava `MOCK_DEVICES` hardcoded.

**Solução:**
- **`presentation/dtos_system.py`** (novo): `AudioDeviceDTO`, `AudioLevelsDTO`, `SystemInfoDTO`, `InfoDTO` — frozen dataclasses.
- **`presentation/services_system.py`** (novo): `AudioPresentationService` — usa `sounddevice` (PortAudio) para listar dispositivos e capturar níveis RMS/peak em tempo real (200ms a 16kHz).
- **`api/routers/audio.py`** (novo): `GET /audio/devices`, `GET /audio/current`, `GET /audio/levels`.
- **Frontend:** `AudioTab` reescrito para usar `useAudio()` hook. Lista dispositivos reais, mostra propriedades (nome, índice, canais, sample rate, padrão do sistema), teste de áudio captura níveis reais via `services.audio.getLevels()`.

### 3. Health Checks Reais

**Problema:** `speech_recognition`, `searcher`, `ranking`, `intelligence` e `holyrics` retornavam `"unknown" — "Not verified"`.

**Solução:**
- **`presentation/health_checks.py`** (novo): 5 funções de verificação real:
  - `check_stt_health()`: verifica se `faster-whisper` está instalado e se o modelo configurado existe.
  - `check_searcher_health()`: verifica se o banco FTS5 está acessível (query `SELECT count(*)`).
  - `check_ranking_health()`: verifica se o arquivo de embeddings existe e se `sentence-transformers` está instalado.
  - `check_intelligence_health()`: tenta conectar ao endpoint do LLM (Ollama `/api/tags`) com timeout 2s.
  - `check_holyrics_health()`: usa `HolyricsClient.test_connection()` (GetTokenInfo) com timeout 2s.
- **`presentation/services.py`**: `HealthPresentationService` estendido com `stt`, `searcher`, `stt_config`, `search_config`, `llm_config`, `holyrics_config`, `holyrics_client`. Cada `*_health()` delega para o check real correspondente.

**Resultado verificado:** Todos os 8 componentes retornam status real (healthy/degraded/unhealthy) com detalhes (latência, db_path, model, etc.).

### 4. System API Consolidada

**Problema:** Nenhum router de sistema existia. `SystemTab` usava valores hardcoded (`"./logs"`, `"./cache"`, `"—"`).

**Solução:**
- **`presentation/services_system.py`**: `SystemPresentationService` — coleta via `psutil` (CPU/memória/disco), `platform` (OS/arquitetura), `torch.cuda` (GPU), e importações dinâmicas para versões de bibliotecas.
- **`api/routers/system.py`** (novo): `GET /system` retorna `SystemInfoDTO` completo.
- **Frontend:** `SystemTab` reescrito para usar `useSystemInfo()` e `useInfo()`. Mostra: diretórios, versões (frontend/backend/API/build/commit), OS, arquitetura, Python, CPUs, CPU%, memória (total/disponível/usada), disco (usado/total/percentual), GPU (se disponível), bibliotecas (PyTorch/Faster-Whisper/Sentence-Transformers/SoundDevice).

### 5. About com /info Real

**Problema:** `AboutPage` mostrava `"—"` para backend, build, commit, OS. `ApplicationContext` tinha versão hardcoded.

**Solução:**
- **`presentation/services_system.py`**: `InfoPresentationService` — combina versão da API + build_id + commit + build_date + frontend_version + sdk_compatibility.
- **`api/routers/info.py`**: reescrito para usar `InfoPresentationService` em vez de retornar dict hardcoded.
- **`api/startup/composition.py`**: `InfoPresentationService` instanciado com `CURRENT_API_VERSION` e variáveis de ambiente (`AI_LYRICS_BUILD_ID`, `AI_LYRICS_COMMIT`, `AI_LYRICS_BUILD_DATE`).
- **Frontend:** `AboutPage` reescrito para usar `useInfo()` e `useSystemInfo()`. Mostra: nome, versão, build, commit, descrição, frontend, backend, API, arquitetura, OS, Python, GPU (se disponível), modelos STT/LLM, status geral.

### 6. Bootstrap com Promise.allSettled

**Problema:** Bootstrap anterior cobria apenas 6 domínios. Sem `Promise.allSettled`, uma falha impedia o resto.

**Solução:**
- **`frontend/src/stream/bootstrap.ts`** (reescrito): 10 tarefas em paralelo via `Promise.allSettled`:
  1. pipeline.getStatus → stores.pipeline
  2. pipeline.getSession → stores.session
  3. pipeline.getMetrics → stores.metrics
  4. configuration.getConfiguration → stores.configuration
  5. diagnostics.getDiagnostics → stores.diagnostics
  6. health.getHealth → stores.health
  7. audio.getDevices → stores.audio
  8. audio.getCurrentDevice → stores.audio.current
  9. system.getSystemInfo → stores.system
  10. info.getInfo → stores.info

  Cada falha é registrada individualmente sem impedir as outras. Retorna `BootstrapResult` com `allOk`, `results` por domínio e `errors`.

### 7. Stores para Novos Dados

- **`frontend/src/stores/domain.ts`**: adicionados `AudioStore` (com `AudioState`), `SystemStore`, `InfoStore`.
- **`frontend/src/stores/index.ts`**: exports atualizados.
- **`StoreRegistry`**: agora tem 12 stores (9 anteriores + 3 novos).

### 8. SDK e Services Frontend

- **`frontend/src/sdk/transports/rest.ts`**: adicionados mapeamentos `configuration.update`, `audio.getDevices`, `audio.getCurrent`, `audio.getLevels`, `system.get`, `info.get`. Suporte a PUT via `PUT_METHODS` set (body JSON em vez de query params).
- **`frontend/src/services/index.ts`**: adicionados `AudioService`, `SystemService`, `InfoService`. `ConfigurationService.updateConfiguration()` adicionado.
- **`frontend/src/types/index.ts`**: adicionados `AudioDeviceDTO`, `AudioDevicesResponse`, `AudioLevelsDTO`, `SystemInfoDTO`, `InfoDTO`.
- **`frontend/src/hooks/index.ts`**: adicionados `useAudio()`, `useSystemInfo()`, `useInfo()`.

---

## Arquivos Criados (Backend)

| Arquivo | Descrição |
|---------|-----------|
| `presentation/dtos_system.py` | DTOs de Audio, System, Info (frozen dataclasses) |
| `presentation/services_system.py` | Services de Audio, System, Info |
| `presentation/health_checks.py` | 5 health checks reais (STT, Search, Ranking, Intelligence, Holyrics) |
| `config/persistence.py` | Persistência de overrides de configuração |
| `api/routers/audio.py` | Router /audio (devices, current, levels) |
| `api/routers/system.py` | Router /system (info consolidada) |

## Arquivos Modificados (Backend)

| Arquivo | Mudança |
|---------|---------|
| `presentation/services.py` | `ConfigurationPresentationService.update_configuration()` + `HealthPresentationService` com checks reais |
| `presentation/__init__.py` | Exports dos novos DTOs e Services |
| `api/startup/composition.py` | Carrega config real + instancia novos services |
| `api/dependencies/services.py` | Dependencies para novos services |
| `api/dependencies/__init__.py` | Exports dos novos dependencies |
| `api/routers/__init__.py` | Registra audio_router e system_router |
| `api/routers/configuration.py` | Adicionado PUT /configuration |
| `api/routers/info.py` | Reescrito para usar InfoPresentationService |
| `tests/test_api.py` | Atualizado para novo formato de /info e /configuration |

## Arquivos Modificados (Frontend)

| Arquivo | Mudança |
|---------|---------|
| `frontend/src/types/index.ts` | Novos DTOs TypeScript |
| `frontend/src/services/index.ts` | Novos services + updateConfiguration |
| `frontend/src/sdk/transports/rest.ts` | Novos endpoints + suporte a PUT |
| `frontend/src/stores/domain.ts` | Novos stores (Audio, System, Info) |
| `frontend/src/stores/index.ts` | Exports dos novos stores |
| `frontend/src/stream/bootstrap.ts` | Reescrito com 10 tarefas + Promise.allSettled |
| `frontend/src/hooks/index.ts` | Novos hooks (useAudio, useSystemInfo, useInfo) |
| `frontend/src/components/settings/AudioTab.tsx` | Reescrito sem mocks |
| `frontend/src/components/settings/SystemTab.tsx` | Reescrito sem mocks |
| `frontend/src/pages/AboutPage.tsx` | Reescrito com dados reais |
| `frontend/src/api/client.ts` | Stubs para novos services |
| `frontend/tests/integration.test.tsx` | Mocks atualizados |
| `frontend/tests/operational.test.tsx` | (não modificado — passou sem mudanças) |

---

## Arquitetura Mantida

O fluxo Backend → REST → SDK → Bootstrap/Store → Hook → React foi rigorosamente seguido:

```
Backend (Presentation Services)
    ↓
REST Routers (FastAPI)
    ↓
SDK Transport (REST com PUT/GET)
    ↓
Services (frontend)
    ↓
Bootstrap (Promise.allSettled → 10 Stores)
    ↓
Hooks (useAudio, useSystemInfo, useInfo, etc.)
    ↓
React Components (AudioTab, SystemTab, AboutPage)
```

Nenhum componente React chama REST diretamente. Tudo passa por Services → SDK → Transport.

---

## Verificação

### Backend (Python)
- **2517 testes** passando (incluindo 32 testes de API)
- App FastAPI carrega com **37 rotas** (anterior: 29 rotas)
- Health checks verificados ao vivo:
  - `speech_recognition`: healthy (faster-whisper instalado, modelo large-v3-turbo)
  - `searcher`: healthy (FTS5 database 47MB)
  - `ranking`: healthy (embeddings 47MB)
  - `intelligence`: healthy (Ollama reachável, modelo qwen3:8b)
  - `holyrics`: healthy (API reachável)
- PUT /configuration verificado: persiste overrides em disco, sobrevive a restart

### Frontend (TypeScript)
- **434 testes** passando (19 arquivos de teste)
- **TypeCheck** sem erros
- **Build** de produção bem-sucedido (347KB JS, 24KB CSS)
- 12 stores no StoreRegistry
- 10 tarefas no bootstrap com Promise.allSettled

---

## Próximos Passos (Sprint 15+)

1. **Cache clear endpoint real** — atualmente `handleClearCache` usa setTimeout. Criar `POST /cache/clear` no backend.
2. **Config reload sem restart** — após PUT /configuration, recarregar componentes Core (STT, Searcher, etc.) sem reiniciar o processo.
3. **WebSocket events para audio levels** — streaming de níveis em tempo real via WS em vez de polling.
4. **Build metadata via CI** — injetar `AI_LYRICS_BUILD_ID`, `AI_LYRICS_COMMIT`, `AI_LYRICS_BUILD_DATE` no processo de build.
5. **Config diff/rollback** — mostrar diff entre config atual e padrão, permitir rollback.
