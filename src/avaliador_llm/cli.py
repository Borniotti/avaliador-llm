"""Linha de comando.

    avaliador rodar dados/casos-equiverso.jsonl --sistema avaliador_llm.exemplos:RagEquiverso
    avaliador rodar casos.jsonl --sistema meu_modulo:funcao --juiz --minimo 0.8
    avaliador comparar resultados/antes.json resultados/depois.json

O comando ``rodar`` termina com código de saída 1 se a taxa de acerto ficar
abaixo de ``--minimo``, e ``comparar`` termina com 1 se houver regressão.
Assim dá para colocar a avaliação no CI e barrar mudanças que pioram o sistema.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .casos import carregar_casos
from .executor import Rodada, rodar
from .metricas import JuizLLM
from .relatorio import comparar, html_pagina, markdown, markdown_comparacao
from .sistemas import carregar_sistema


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="avaliador", description="Avaliação automática de sistemas com LLM.")
    sub = p.add_subparsers(dest="comando", required=True)

    r = sub.add_parser("rodar", help="roda os casos contra um sistema")
    r.add_argument("casos", type=Path)
    r.add_argument("--sistema", required=True, help="modulo:funcao")
    r.add_argument("--saida", type=Path, default=Path("resultados"))
    r.add_argument("--nome", help="nome da rodada (padrão: data e hora)")
    r.add_argument("--juiz", action="store_true", help="usa um LLM como juiz (custa tokens)")
    r.add_argument("--modelo-juiz", default="claude-opus-5-5")
    r.add_argument("--paralelo", type=int, default=4)
    r.add_argument("--tag", action="append", help="roda só os casos com esta tag (pode repetir)")
    r.add_argument("--minimo", type=float, default=0.0, help="taxa mínima de acerto (0 a 1)")

    c = sub.add_parser("comparar", help="compara duas rodadas salvas")
    c.add_argument("antes", type=Path)
    c.add_argument("depois", type=Path)

    a = p.parse_args(argv)

    if a.comando == "comparar":
        antes = Rodada.de_dict(json.loads(a.antes.read_text(encoding="utf-8")))
        depois = Rodada.de_dict(json.loads(a.depois.read_text(encoding="utf-8")))
        comparacao = comparar(antes, depois)
        print(markdown_comparacao(comparacao))
        return 1 if comparacao.piorou else 0

    casos = carregar_casos(a.casos)
    if a.tag:
        casos = [caso for caso in casos if set(caso.tags) & set(a.tag)]
        if not casos:
            sys.exit(f"nenhum caso com as tags {a.tag}")

    juiz = None
    if a.juiz:
        import anthropic

        juiz = JuizLLM(anthropic.Anthropic(), modelo=a.modelo_juiz)

    rodada = rodar(casos, carregar_sistema(a.sistema), a.sistema, juiz=juiz, paralelo=a.paralelo)

    a.saida.mkdir(parents=True, exist_ok=True)
    nome = a.nome or rodada.inicio.replace(":", "-")
    (a.saida / f"{nome}.json").write_text(json.dumps(rodada.para_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (a.saida / f"{nome}.md").write_text(markdown(rodada), encoding="utf-8")
    (a.saida / f"{nome}.html").write_text(html_pagina(rodada), encoding="utf-8")

    print(markdown(rodada))
    print(f"\nArquivos salvos em {a.saida}/{nome}.(json|md|html)")
    return 0 if rodada.taxa_acerto >= a.minimo else 1


if __name__ == "__main__":
    sys.exit(main())
