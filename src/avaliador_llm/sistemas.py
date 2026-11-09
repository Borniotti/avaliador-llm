"""O "sistema avaliado": qualquer função que recebe uma pergunta e devolve uma resposta.

O avaliador não depende de nenhum projeto específico. Basta apontar para uma
função no formato ``modulo:funcao`` que siga este contrato:

    def meu_sistema(pergunta: str, contexto: dict) -> Saida | dict | str

Exemplos prontos estão em ``avaliador_llm.exemplos``.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Saida:
    resposta: str
    fontes: list[str] = field(default_factory=list)
    encontrou: bool | None = None  # o próprio sistema disse se achou a resposta?
    extras: dict = field(default_factory=dict)

    @classmethod
    def de(cls, valor: Any) -> "Saida":
        """Aceita Saida, dict ou texto puro, para facilitar adaptar sistemas existentes."""
        if isinstance(valor, Saida):
            return valor
        if isinstance(valor, str):
            return cls(resposta=valor)
        if isinstance(valor, dict):
            return cls(
                resposta=str(valor.get("resposta", "")),
                fontes=[str(f) for f in valor.get("fontes", [])],
                encontrou=valor.get("encontrou"),
                extras={k: v for k, v in valor.items() if k not in {"resposta", "fontes", "encontrou"}},
            )
        raise TypeError(f"o sistema devolveu um tipo não suportado: {type(valor).__name__}")


Sistema = Callable[[str, dict], Any]


def carregar_sistema(referencia: str) -> Sistema:
    """'pacote.modulo:funcao' -> a função. Se for uma classe, cria uma instância."""
    if ":" not in referencia:
        raise ValueError("use o formato modulo:funcao (ex.: avaliador_llm.exemplos:eco)")
    nome_modulo, nome_objeto = referencia.split(":", 1)
    objeto = getattr(importlib.import_module(nome_modulo), nome_objeto)
    if isinstance(objeto, type):
        objeto = objeto()
    if not callable(objeto):
        raise TypeError(f"{referencia} não é chamável")
    return objeto
