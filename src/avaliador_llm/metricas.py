"""As verificações aplicadas a cada resposta.

Há dois tipos:

* **Determinísticas** (rápidas, grátis, sempre iguais): contém o que devia?
  evitou o que não devia (spoiler, informação errada)? recusou quando devia?
  citou as fontes certas?
* **Juiz LLM** (opcional): outro modelo lê a pergunta e a resposta e dá notas
  de 1 a 5 seguindo uma rubrica. Pega o que regras simples não pegam
  (resposta confusa, que "enrola", que contradiz a referência), mas custa
  dinheiro e varia um pouco entre rodadas, por isso fica desligado por padrão.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from .casos import Caso
from .sistemas import Saida

PADROES_RECUSA = re.compile(
    r"n[aã]o (sei|encontrei|achei|tenho (essa|esta|informa)|consigo responder|h[aá] informa)"
    r"|n[aã]o (est[aá]|aparece|consta) na wiki|fora do (escopo|assunto)|sem informa[cç][oõ]es",
    re.IGNORECASE,
)


@dataclass
class Verificacao:
    nome: str
    passou: bool
    nota: float  # de 0 a 1
    detalhe: str = ""


def normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento.lower())


def _tem(texto_normalizado: str, item: str) -> bool:
    """'a|b' -> aceita qualquer alternativa."""
    return any(normalizar(op).strip() in texto_normalizado for op in item.split("|"))


def recusou(saida: Saida) -> bool:
    if saida.encontrou is not None:
        return not saida.encontrou
    return bool(PADROES_RECUSA.search(saida.resposta))


def verificar_deterministico(caso: Caso, saida: Saida) -> list[Verificacao]:
    esperado = caso.esperado
    texto = normalizar(saida.resposta)
    resultado: list[Verificacao] = []

    if esperado.deve_recusar:
        ok = recusou(saida)
        resultado.append(Verificacao("recusa", ok, float(ok), "" if ok else "respondeu algo que devia recusar"))
        return resultado  # numa pergunta fora do escopo, as outras checagens não fazem sentido

    if esperado.deve_conter:
        faltando = [i for i in esperado.deve_conter if not _tem(texto, i)]
        nota = 1 - len(faltando) / len(esperado.deve_conter)
        resultado.append(Verificacao("contem", not faltando, nota, f"faltou: {faltando}" if faltando else ""))

    if esperado.nao_deve_conter:
        proibidos = [i for i in esperado.nao_deve_conter if _tem(texto, i)]
        resultado.append(
            Verificacao("nao_contem", not proibidos, float(not proibidos), f"apareceu: {proibidos}" if proibidos else "")
        )

    if esperado.fontes_esperadas:
        fontes = [normalizar(f) for f in saida.fontes]
        ausentes = [
            item for item in esperado.fontes_esperadas
            if not any(normalizar(op) in f for f in fontes for op in item.split("|"))
        ]
        nota = 1 - len(ausentes) / len(esperado.fontes_esperadas)
        resultado.append(Verificacao("fontes", not ausentes, nota, f"sem fonte: {ausentes}" if ausentes else ""))

    if not esperado.deve_recusar and recusou(saida) and (esperado.deve_conter or esperado.fontes_esperadas):
        resultado.append(Verificacao("respondeu", False, 0.0, "recusou uma pergunta que tinha resposta"))

    return resultado


# ---------------------------------------------------------------- juiz LLM

RUBRICA = """Você avalia respostas de um assistente de perguntas sobre uma wiki.
Dê duas notas inteiras de 1 a 5:
- fidelidade: a resposta só afirma coisas sustentadas pela referência e pelas fontes? (5 = nada inventado; 1 = afirmações falsas ou inventadas)
- utilidade: a resposta responde de fato à pergunta, de forma clara e direta? (5 = completa e clara; 1 = não responde)
Se não houver referência, julgue a fidelidade pela coerência e pela cautela da resposta.
Explique a nota em uma ou duas frases. Seja rigoroso e consistente."""

ESQUEMA_JUIZ = {
    "type": "object",
    "properties": {
        "fidelidade": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "utilidade": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "justificativa": {"type": "string"},
    },
    "required": ["fidelidade", "utilidade", "justificativa"],
    "additionalProperties": False,
}


class JuizLLM:
    def __init__(self, cliente, modelo: str = "claude-opus-5-5", nota_minima: float = 0.75):
        self.cliente = cliente
        self.modelo = modelo
        self.nota_minima = nota_minima

    def avaliar(self, caso: Caso, saida: Saida) -> Verificacao:
        partes = [f"<pergunta>{caso.pergunta}</pergunta>", f"<resposta>{saida.resposta}</resposta>"]
        if caso.esperado.resposta_referencia:
            partes.append(f"<referencia>{caso.esperado.resposta_referencia}</referencia>")
        if saida.fontes:
            partes.append(f"<fontes>{', '.join(saida.fontes)}</fontes>")
        r = self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=4000,
            system=RUBRICA,
            messages=[{"role": "user", "content": "\n".join(partes)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": ESQUEMA_JUIZ}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if r.stop_reason in {"refusal", "max_tokens"}:
            return Verificacao("juiz", False, 0.0, f"juiz não avaliou ({r.stop_reason})")
        try:
            dados = json.loads(next(b.text for b in r.content if b.type == "text"))
        except (StopIteration, json.JSONDecodeError):
            return Verificacao("juiz", False, 0.0, "resposta do juiz ilegível")
        # 1..5 -> 0..1, média das duas notas
        nota = ((dados["fidelidade"] - 1) + (dados["utilidade"] - 1)) / 8
        detalhe = f"fidelidade {dados['fidelidade']}/5, utilidade {dados['utilidade']}/5: {dados['justificativa']}"
        return Verificacao("juiz", nota >= self.nota_minima, round(nota, 3), detalhe)
