# -*- coding: utf-8 -*-
"""Smoke test Sprint 19.1.1 — Etapas 1, 5, 6 (sem carregar modelo)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from _smoke_sprint19_1_1 import (
    etapa1_hardware_check,
    etapa5_streaming_simulated,
    etapa6_fallback,
)

print("### ETAPA 1 ###")
r1 = etapa1_hardware_check()

print()
print("### ETAPA 5 ###")
r5 = etapa5_streaming_simulated("tiny")

print()
print("### ETAPA 6 ###")
r6 = etapa6_fallback()

print()
print("### RESUMO ###")
print(f"Etapa 1: rx7600={r1['rx7600']} directml={r1['directml']}")
print(f"Etapa 5: imports_ok={r5['imports_ok']} events_registered={r5['events_registered']}")
print(f"Etapa 6: fallback={r6['fallback_triggered']} cpu_used={r6['cpu_used_after_fallback']}")
