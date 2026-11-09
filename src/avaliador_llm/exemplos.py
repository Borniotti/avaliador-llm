"""Sistemas de exemplo para avaliar.

* ``eco``: devolve a própria pergunta. Serve para ver o avaliador funcionando
  e mostra como é uma nota ruim.
* ``RagEquiverso``: adaptador para o projeto rag-wiki-equiverso
  (https://github.com/Borniotti/rag-wiki-equiverso). Precisa dele instalado.
"""

from __future__ import annotations

import os

from .sistemas import Saida


def eco(pergunta: str, contexto: dict) -> Saida:
    return Saida(resposta=pergunta)


class RagEquiverso:
    """Liga o avaliador ao assistente da wiki.

    Variáveis de ambiente:
      RAG_INDICE             caminho do índice (padrão: indice.json)
      RAG_COBERTURA_MINIMA   abaixo disso o assistente diz "não sei" (padrão: 0.5)
    O episódio assistido vem de ``contexto["assistiu_ate"]`` em cada caso.
    """

    def __init__(self):
        from rag_equiverso import Assistente, Episodio, IndiceBM25

        self._episodio = Episodio
        cliente = None
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            import anthropic

            cliente = anthropic.Anthropic()
        indice = IndiceBM25.carregar(os.environ.get("RAG_INDICE", "indice.json"))
        cobertura = float(os.environ.get("RAG_COBERTURA_MINIMA", "0.5"))
        self._assistente = Assistente(indice, cliente, cobertura_minima=cobertura)

    def __call__(self, pergunta: str, contexto: dict) -> Saida:
        ate = contexto.get("assistiu_ate")
        r = self._assistente.perguntar(pergunta, self._episodio.de_codigo(ate) if ate else None)
        return Saida(
            resposta=r.texto,
            fontes=[f.trecho.pagina for f in r.fontes],
            encontrou=r.encontrou,
            extras={"modo": r.modo, "tokens": r.uso},
        )
