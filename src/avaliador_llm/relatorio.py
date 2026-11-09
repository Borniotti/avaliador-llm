"""Relatórios: resumo por categoria, falhas detalhadas e comparação entre rodadas.

A comparação é a parte que mais importa no dia a dia: ao mudar o prompt, o
modelo ou a busca, você quer saber **o que piorou** (regressões), e não só
se a média subiu.
"""

from __future__ import annotations

import html
import statistics
from collections import defaultdict
from dataclasses import dataclass

from .executor import Rodada


def _pct(valor: float) -> str:
    return f"{valor * 100:.0f}%"


def resumo_por_tag(rodada: Rodada) -> dict[str, tuple[int, int]]:
    """tag -> (acertos, total)"""
    contagem: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rodada.resultados:
        for tag in r.tags or ["(sem tag)"]:
            contagem[tag][0] += r.passou
            contagem[tag][1] += 1
    return {tag: (a, t) for tag, (a, t) in sorted(contagem.items())}


def _latencias(rodada: Rodada) -> tuple[float, float]:
    tempos = sorted(r.segundos for r in rodada.resultados)
    if not tempos:
        return 0.0, 0.0
    p90 = tempos[min(len(tempos) - 1, int(round(0.9 * (len(tempos) - 1))))]
    return statistics.median(tempos), p90


def markdown(rodada: Rodada) -> str:
    acertos = sum(r.passou for r in rodada.resultados)
    mediana, p90 = _latencias(rodada)
    linhas = [
        f"# Avaliação: `{rodada.sistema}`",
        "",
        f"Rodada de {rodada.inicio}: **{acertos}/{len(rodada.resultados)} casos passaram ({_pct(rodada.taxa_acerto)})**. "
        f"Tempo por caso: mediana {mediana:.2f}s, p90 {p90:.2f}s.",
        "",
        "## Por categoria",
        "",
        "| Categoria | Passaram | Taxa |",
        "|---|---|---|",
    ]
    for tag, (a, t) in resumo_por_tag(rodada).items():
        linhas.append(f"| {tag} | {a}/{t} | {_pct(a / t)} |")

    falhas = [r for r in rodada.resultados if not r.passou]
    linhas += ["", "## Falhas", ""]
    if not falhas:
        linhas.append("Nenhuma falha. 🎉")
    for r in falhas:
        linhas.append(f"### {r.id}: {r.pergunta}")
        if r.erro:
            linhas.append(f"- **Erro do sistema:** `{r.erro}`")
        for v in r.verificacoes:
            if not v.passou:
                linhas.append(f"- **{v.nome}** ({_pct(v.nota)}): {v.detalhe}")
        if r.resposta:
            resposta = r.resposta.replace("\n", " ")
            linhas.append(f"- Resposta: {resposta[:300]}{'…' if len(resposta) > 300 else ''}")
        linhas.append("")
    return "\n".join(linhas)


def html_pagina(rodada: Rodada) -> str:
    """Relatório em HTML de arquivo único, para abrir no navegador ou anexar num PR."""
    e = html.escape
    linhas_tabela = []
    for r in rodada.resultados:
        detalhes = "; ".join(f"{v.nome}: {v.detalhe}" for v in r.verificacoes if not v.passou) or r.erro
        classe = "ok" if r.passou else "falha"
        linhas_tabela.append(
            f"<tr class='{classe}'><td>{e(r.id)}</td><td>{e(r.pergunta)}</td>"
            f"<td>{'✔' if r.passou else '✘'}</td><td>{_pct(r.nota)}</td><td>{r.segundos:.2f}s</td>"
            f"<td>{e(detalhes)}</td></tr>"
        )
    categorias = "".join(
        f"<li><b>{e(tag)}</b>: {a}/{t} ({_pct(a / t)})</li>" for tag, (a, t) in resumo_por_tag(rodada).items()
    )
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avaliação {e(rodada.sistema)}</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:24px;color:#1d1d1f;background:#fafafa}}
 table{{border-collapse:collapse;width:100%;background:#fff}} td,th{{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}}
 tr.ok td:nth-child(3){{color:#1a7f37}} tr.falha td:nth-child(3){{color:#cf222e;font-weight:bold}}
 .placar{{font-size:2rem;font-weight:bold}}
</style></head><body>
<h1>Avaliação: {e(rodada.sistema)}</h1>
<p class="placar">{_pct(rodada.taxa_acerto)} dos casos passaram</p>
<p>Rodada de {e(rodada.inicio)}</p>
<h2>Por categoria</h2><ul>{categorias}</ul>
<h2>Casos</h2>
<table><tr><th>Caso</th><th>Pergunta</th><th>Passou</th><th>Nota</th><th>Tempo</th><th>O que falhou</th></tr>
{''.join(linhas_tabela)}</table></body></html>"""


@dataclass
class Comparacao:
    regressoes: list[str]  # passava e agora falha
    melhorias: list[str]  # falhava e agora passa
    novos: list[str]
    removidos: list[str]
    taxa_antes: float
    taxa_depois: float

    @property
    def piorou(self) -> bool:
        return bool(self.regressoes)


def comparar(antes: Rodada, depois: Rodada) -> Comparacao:
    a = {r.id: r.passou for r in antes.resultados}
    d = {r.id: r.passou for r in depois.resultados}
    comuns = a.keys() & d.keys()
    return Comparacao(
        regressoes=sorted(i for i in comuns if a[i] and not d[i]),
        melhorias=sorted(i for i in comuns if not a[i] and d[i]),
        novos=sorted(d.keys() - a.keys()),
        removidos=sorted(a.keys() - d.keys()),
        taxa_antes=antes.taxa_acerto,
        taxa_depois=depois.taxa_acerto,
    )


def markdown_comparacao(c: Comparacao) -> str:
    seta = "📈" if c.taxa_depois > c.taxa_antes else "📉" if c.taxa_depois < c.taxa_antes else "➡️"
    linhas = [f"# Comparação {seta} {_pct(c.taxa_antes)} → {_pct(c.taxa_depois)}", ""]
    for titulo, itens in (("Regressões (passava, agora falha)", c.regressoes), ("Melhorias", c.melhorias),
                          ("Casos novos", c.novos), ("Casos removidos", c.removidos)):
        linhas.append(f"**{titulo}:** {', '.join(itens) if itens else 'nenhum'}")
        linhas.append("")
    return "\n".join(linhas)
