"""Avaliação automática de sistemas baseados em LLM: casos em JSONL, verificações, juiz LLM e relatórios."""

from .casos import Caso, Esperado, carregar_casos
from .executor import ResultadoCaso, Rodada, avaliar_caso, rodar
from .metricas import JuizLLM, Verificacao, verificar_deterministico
from .relatorio import comparar
from .sistemas import Saida, carregar_sistema

__all__ = [
    "Caso", "Esperado", "JuizLLM", "ResultadoCaso", "Rodada", "Saida", "Verificacao",
    "avaliar_caso", "carregar_casos", "carregar_sistema", "comparar", "rodar", "verificar_deterministico",
]
