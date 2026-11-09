"""Casos de teste: a pergunta, o contexto e o que se espera da resposta.

Os casos ficam num arquivo JSONL (um JSON por linha), fácil de editar e de
versionar no Git. Exemplo:

    {"id": "fato-01", "pergunta": "Quem matou o mosquito?",
     "contexto": {"assistiu_ate": "xdq-01"},
     "esperado": {"deve_conter": ["Nina"], "nao_deve_conter": ["Lucas matou"]},
     "tags": ["fato"]}

Em ``deve_conter``, ``"123|cento e vinte e três"`` aceita qualquer uma das opções.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Esperado:
    deve_conter: list[str] = field(default_factory=list)
    nao_deve_conter: list[str] = field(default_factory=list)
    deve_recusar: bool = False
    fontes_esperadas: list[str] = field(default_factory=list)
    resposta_referencia: str = ""  # opcional: usada pelo juiz LLM


@dataclass
class Caso:
    id: str
    pergunta: str
    esperado: Esperado
    contexto: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


class ErroNosCasos(ValueError):
    pass


CAMPOS_ESPERADO = set(Esperado.__dataclass_fields__)


def carregar_casos(caminho: str | Path) -> list[Caso]:
    casos, ids = [], set()
    for numero, linha in enumerate(Path(caminho).read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip() or linha.lstrip().startswith("//"):
            continue
        try:
            dados = json.loads(linha)
        except json.JSONDecodeError as e:
            raise ErroNosCasos(f"linha {numero}: JSON inválido ({e.msg})") from e
        for campo in ("id", "pergunta"):
            if not dados.get(campo):
                raise ErroNosCasos(f"linha {numero}: falta o campo '{campo}'")
        if dados["id"] in ids:
            raise ErroNosCasos(f"linha {numero}: id repetido '{dados['id']}'")
        esperado = dados.get("esperado", {})
        desconhecidos = set(esperado) - CAMPOS_ESPERADO
        if desconhecidos:
            raise ErroNosCasos(f"linha {numero}: campos desconhecidos em 'esperado': {sorted(desconhecidos)}")
        ids.add(dados["id"])
        casos.append(
            Caso(
                id=dados["id"],
                pergunta=dados["pergunta"],
                esperado=Esperado(**esperado),
                contexto=dados.get("contexto", {}),
                tags=dados.get("tags", []),
            )
        )
    if not casos:
        raise ErroNosCasos(f"nenhum caso em {caminho}")
    return casos
