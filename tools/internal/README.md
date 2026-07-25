# tools/internal — Ferramentas internas de desenvolvimento e diagnóstico

**NÃO INCLUÍDAS NO INSTALADOR.** Este diretório contém scripts e outputs de
diagnóstico usados durante o desenvolvimento das Sprints. Nenhum arquivo
aqui é importado pelo código fonte principal nem é necessário para
execução do AI Lyrics em produção.

## Conteúdo

- `_diag_*.py` (38 arquivos) — Scripts de diagnóstico pontual por Sprint.
  Ex: `_diag_sprint21_5_2.py` valida o SemanticEngine em cenários específicos.
- `_bench_*.py` (3 arquivos) — Benchmarks de performance (searcher, GPU, DML).
- `_smoke_*.py` (3 arquivos) — Smoke tests manuais antes da suíte automatizada.
- `_demo_*.py` (3 arquivos) — Demos de funcionalidades por Sprint.
- `_check_*.py` / `_check_*.ps1` (3 arquivos) — Checagens rápidas manuais
  (health, holyrics, ollama).
- `_stability_*.py` (1 arquivo) — Testes de estabilidade de longa duração.
- `_run_diag.py` — Runner para os scripts `_diag_*.py`.
- `*.txt` (31 arquivos) — Outputs de diagnóstico salvos durante o
  desenvolvimento. Sem valor runtime.

## Por que mover da raiz?

A Sprint 23.0 (item 16 do enunciado) exige separar claramente código
fonte, ferramentas de desenvolvimento, ferramentas de diagnóstico e
arquivos temporários. Os 78 arquivos com prefixo `_` na raiz violavam
essa separação e corriam risco de serem incluídos no instalador. Mover
para `tools/internal/` permite que o `ai-lyrics.spec` exclua o diretório
inteiro com uma regra.

## Executar

```powershell
# Exemplo: rodar um diagnóstico
python tools/internal/_diag_sprint22_0.py

# Exemplo: checar saúde da API em execução
python tools/internal/_check_health.py
```
