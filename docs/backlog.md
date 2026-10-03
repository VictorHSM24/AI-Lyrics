# Backlog

Ações pendentes do AI Lyrics. Mantido por agentes e humanos — **item
concluído sai daqui e vira entrada em `docs/historico.md`** (ver protocolo em
`AGENTS.md`).

Formato:

```
- [ ] (PRIORIDADE) Descrição — contexto/origem — data
```

Prioridades: `P0` bloqueante/urgente · `P1` importante · `P2` melhoria · `P3` someday.

---

## Em andamento

- [ ] (P0) **Commitar e validar correções de observabilidade + gravação
  de auditoria** — working tree tem as correções de observabilidade
  (`AuditingEventStore`, wildcard `"*"` no EventBus, `close_all()` de
  WebSockets, parada de SlidingWindow/StreamingSTT,
  `tests/test_observability_fixes.py`) e a nova gravação de auditoria
  (`pipeline/audit_recorder.py`, `api/routers/recording.py`, página
  Sessões). Suíte backend (3572) e frontend (624) verdes. — 2026-10-02

## Pendente

- [ ] (P1) **Token do Holyrics sem permissão para actions** —
  `POST /operator/close-presentation` (e possivelmente `show_verse`)
  recebe HTTP 401 da API do Holyrics (`http://127.0.0.1:8091/api`).
  Há tokens divergentes entre `config.yaml` e `config.overrides.json` —
  um deles responde info da API mas falha nas actions. Revalidar o token
  no Holyrics (Configurações → API) e alinhar os arquivos. — origem:
  teste do botão "Encerrar" (`5120637`), 2026-10-02
- [ ] (P1) **Testar pipeline no microfone do pastor** — commit `c941b61`
  ("Falta testar de novo no microfone do pastor") indica validação de campo
  pendente com o dispositivo real (CODEC USB). — origem: git log
- [ ] (P2) **Endpoint real de limpeza de cache** — `SystemTab.tsx:48` chama
  placeholder; backend ainda não expõe o endpoint. — origem: TODO no código
- [ ] (P2) **SemanticEngine desativado por config** — startup loga
  "Sprint 21.1: SemanticEngine disabled by config". Decidir se volta a
  habilitar ou remove o caminho morto. — origem: logs de boot
- [ ] (P3) **Embeddings desabilitados no Searcher** — `Searcher initialized
  ... embeddings=disabled`. Avaliar ganho de relevância vs. custo. — origem:
  logs de boot

## Concluído recentemente

_(movido para `docs/historico.md` — manter esta seção vazia ou com apontador)_
