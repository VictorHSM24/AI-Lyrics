"""Sprint 32 — regressão: LocalAgreement-2 re-commitava bloco estável
quando o Whisper reescrevia palavras já committed.

Incidente real (gravação 20261002_195356): "1ª Crônica, capítulo 28,
versículo 9" → Whisper reescreveu como "crônicas, capítulo 28, 9" → o
prefix-match exato contra a cauda do committed falhou → o delta
"crônicas, capítulo 28, 9." foi emitido 5× como "novo" → o parser
recebeu tokens duplicados ("...cronicas capitulo cronicas capitulo
28 9...") e nunca detectou a referência.
"""

from __future__ import annotations

from microfone.streaming_stt_service import (
    StreamingSTTService,
    _committed_prefix_consumed,
)


def _svc() -> StreamingSTTService:
    s = StreamingSTTService.__new__(StreamingSTTService)
    s._prev_words = None
    s._committed_text = ""
    s._committed_word_count = 0
    return s


def _w(*words: str) -> list[tuple[str, float, float]]:
    return [(t, 0.0, 0.0) for t in words]


def test_consumed_bloco_ate_o_fim_do_committed():
    committed = "no livro de 1a crônia, capítulo 28, versículo 9.".split()
    stable = "crônicas, capítulo 28, 9.".split()
    assert _committed_prefix_consumed(committed, stable) == 4


def test_consumed_continuacao_estende_alem_do_fim():
    committed = "no livro de 1a crônia, capítulo 28, versículo 9.".split()
    stable = "crônicas, capítulo 28, 9. e tu,".split()
    assert _committed_prefix_consumed(committed, stable) == 4


def test_consumed_sem_overlap_emite_tudo():
    committed = "a bíblia diz em".split()
    stable = "joão capítulo três".split()
    assert _committed_prefix_consumed(committed, stable) == 0


def test_consumed_reescrita_na_cauda_usa_bloco_interior():
    # Committed termina diferente ("9," vs "9.") → bloco "capítulo 28,"
    # de tamanho 2 dentro do committed consome o prefixo estável.
    committed = "no livro de 1a crônia, capítulo 28, versículo 9,".split()
    stable = "crônicas, capítulo 28, 9.".split()
    assert _committed_prefix_consumed(committed, stable) == 3


def test_local_agreement_nao_recommit_bloco_reescrito():
    """Cenário da gravação: committed tem "versículo 9." e a janela
    reescreveu sem "versículo" — o bloco estável NÃO pode re-commit."""
    s = _svc()
    s._committed_text = "no livro de 1a crônia, capítulo 28, versículo 9."
    s._committed_word_count = 10
    s._prev_words = _w("1a", "crônicas,", "capítulo", "28,", "9.")
    new = s._local_agreement(_w("crônicas,", "capítulo", "28,", "9."))
    assert [w[0] for w in new] == []


def test_local_agreement_committa_so_o_sufixo_novo_apos_reescrita():
    s = _svc()
    s._committed_text = "no livro de 1a crônia, capítulo 28, versículo 9."
    s._committed_word_count = 10
    s._prev_words = _w("1a", "crônicas,", "capítulo", "28,", "9.", "e", "tu,")
    new = s._local_agreement(_w("crônicas,", "capítulo", "28,", "9.", "e", "tu,"))
    assert [w[0] for w in new] == ["e", "tu,"]


def test_local_agreement_fluxo_normal_intocado():
    s = _svc()
    s._prev_words = _w("irmãos", "vamos", "abrir")
    new = s._local_agreement(_w("irmãos", "vamos", "abrir", "joão"))
    assert [w[0] for w in new] == ["irmãos", "vamos", "abrir"]
    # Próximo ciclo com as mesmas palavras estáveis → nada novo.
    s._prev_words = _w("irmãos", "vamos", "abrir", "joão")
    new = s._local_agreement(_w("irmãos", "vamos", "abrir", "joão", "três"))
    assert [w[0] for w in new] == ["joão"]
