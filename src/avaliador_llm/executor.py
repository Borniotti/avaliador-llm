"""Roda todos os casos contra o sistema e junta os resultados.

Os casos rodam em paralelo (sistemas de IA passam a maior parte do tempo
esperando a rede). Se um caso der erro, ele é registrado como falha e os
outros continuam: uma avaliação nunca deve morrer no meio.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .casos import Caso
from .metricas import JuizLLM, Verificacao, verificar_deterministico
from .sistemas import Saida, Sistema


@dataclass
class ResultadoCaso:
    id: str
    pergunta: str
    tags: list[str]
    passou: bool
    nota: float
    segundos: float
    resposta: str = ""
    fontes: list[str] = field(default_factory=list)
    verificacoes: list[Verificacao] = field(default_factory=list)
    erro: str = ""


@dataclass
class Rodada:
    sistema: str
    inicio: str
    resultados: list[ResultadoCaso]

    @property
    def taxa_acerto(self) -> float:
        return sum(r.passou for r in self.resultados) / len(self.resultados) if self.resultados else 0.0

    def para_dict(self) -> dict:
        return {"sistema": self.sistema, "inicio": self.inicio, "taxa_acerto": self.taxa_acerto,
                "resultados": [asdict(r) for r in self.resultados]}

    @classmethod
    def de_dict(cls, dados: dict) -> "Rodada":
        resultados = []
        for r in dados["resultados"]:
            r = dict(r)
            r["verificacoes"] = [Verificacao(**v) for v in r.get("verificacoes", [])]
            resultados.append(ResultadoCaso(**r))
        return cls(dados["sistema"], dados["inicio"], resultados)


def avaliar_caso(caso: Caso, sistema: Sistema, juiz: JuizLLM | None = None) -> ResultadoCaso:
    inicio = time.perf_counter()
    try:
        saida = Saida.de(sistema(caso.pergunta, dict(caso.contexto)))
    except Exception as erro:  # o sistema avaliado pode falhar de qualquer jeito
        return ResultadoCaso(caso.id, caso.pergunta, caso.tags, False, 0.0,
                             round(time.perf_counter() - inicio, 3), erro=f"{type(erro).__name__}: {erro}")
    segundos = round(time.perf_counter() - inicio, 3)

    verificacoes = verificar_deterministico(caso, saida)
    if juiz is not None and not caso.esperado.deve_recusar:
        try:
            verificacoes.append(juiz.avaliar(caso, saida))
        except Exception as erro:
            verificacoes.append(Verificacao("juiz", False, 0.0, f"erro no juiz: {erro}"))

    passou = bool(verificacoes) and all(v.passou for v in verificacoes)
    nota = sum(v.nota for v in verificacoes) / len(verificacoes) if verificacoes else 0.0
    return ResultadoCaso(caso.id, caso.pergunta, caso.tags, passou, round(nota, 3), segundos,
                         saida.resposta, saida.fontes, verificacoes)


def rodar(casos: list[Caso], sistema: Sistema, nome_sistema: str, juiz: JuizLLM | None = None,
          paralelo: int = 4) -> Rodada:
    inicio = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as pool:
        resultados = list(pool.map(lambda c: avaliar_caso(c, sistema, juiz), casos))  # mantém a ordem dos casos
    return Rodada(nome_sistema, inicio, resultados)
