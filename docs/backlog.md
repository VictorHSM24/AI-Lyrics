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

- [ ] (P1) **Referência ambígua em livro de capítulo único** — "2 joão 1"
  emite 1:1 imediatamente (livro + 1 número = completo); se o pregador
  continuar ",11" vira 1:11, mas o verso 1:1 chega a ser apresentado por
  ~4s. Corrigir segurando emissão quando o número solto puder ser
  capítulo-implícito. — origem: gravação 04/10, incidente 2Jo 1:11
- [ ] (P1) **Continuação `open` bloqueia menção completa posterior** —
  quando uma referência fica `open` no fim do stream, o scan para antes
  de alcançar menções completas posteriores no mesmo buffer. Mitigado
  pelo dedup de fronteira, mas o mecanismo segue. — origem: análise do
  incidente 2Ts 2:9 (04/10)
- [ ] (P1) **Palavras intercaladas quebram referência** — "provérbios ...
  outra ... 29, 2" e "2 coríntios importante. 6,14" não resolveram:
  tokens de fala/ruído entre livro-capítulo-versículo abortam a
  gramática. Avaliar tolerância a N palavras não-numéricas no gap.
  — origem: gravação 04/10 (Pv 29:2, 2Co 6:14)
- [ ] (P2) **Follow não ancora no último versículo do capítulo** —
  `verse_end <= verse` impede re-anchor quando o versículo apresentado
  é o último (ex.: Rm 1:32). — origem: gravação 04/10
- [ ] (P2) **Verificar Holyrics `status=ok` sem atualizar tela** — Rm
  1:32 foi enviado com `ok` mas operador não viu na hora; investigar se
  foi race com apresentação manual. — origem: gravação 04/10

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
