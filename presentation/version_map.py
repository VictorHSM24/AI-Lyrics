"""Mapeamento entre keys de versão do Holyrics e a base FTS5 local.

O Holyrics identifica versões por keys como ``"pt_acf"``, ``"en_kjv"``,
``"es_nvi"``. A base FTS5 local (``data/bible.pt-br.sqlite``) é gerada
a partir de ``data/sources/*.sqlite`` e contém versões em português
com nomes curtos (``"ACF"``, ``"ARA"``, ``"NVI"``...).

- Apresentação (Holyrics): usar sempre a key original (``"pt_nvi"``).
- Busca de texto na base local: mapear para a versão local equivalente
  quando existir; versões sem equivalente não têm texto local —
  o Holyrics resolve o texto por conta própria na apresentação.
"""

from __future__ import annotations

import re

__all__ = ["HOLYRICS_TO_LOCAL_VERSION", "local_version", "normalize_version_key"]

HOLYRICS_TO_LOCAL_VERSION: dict[str, str] = {
    "pt_acf": "ACF",
    "pt_ra": "ARA",
    "pt_arc": "ARC",
    "pt_a21": "AS21",
    "pt_jfaa": "JFAA",
    "pt_naa": "NAA",
    "pt_nbv": "NBV",
    "pt_ntlh": "NTLH",
    "pt_nvi": "NVI",
    "pt_nvt": "NVT",
}

_HOLYRICS_KEY_PATTERN = re.compile(r"^[a-z]{2,3}_[a-z0-9]+$")


def local_version(version: str) -> str:
    """Retorna a versão equivalente na base local, ou a própria key."""
    return HOLYRICS_TO_LOCAL_VERSION.get(version, version)


def normalize_version_key(version: str) -> str:
    """Normaliza uma versão informada pelo operador/voz.

    Keys do Holyrics (``pt_acf``, ``en_kjv``...) são case-sensitive e
    devem permanecer lowercase. Nomes locais simples (``"acf"``) são
    uppercased para casar com a base FTS5.
    """
    v = version.strip()
    if _HOLYRICS_KEY_PATTERN.match(v):
        return v.lower()
    return v.upper()
