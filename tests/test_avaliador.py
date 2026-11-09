import json
from types import SimpleNamespace

import pytest

from avaliador_llm import (
    Caso, Esperado, JuizLLM, Rodada, Saida, avaliar_caso, carregar_casos, carregar_sistema, comparar, rodar,
    verificar_deterministico,
)
from avaliador_llm.casos import ErroNosCasos
from avaliador_llm.cli import main
from avaliador_llm.relatorio import html_pagina, markdown


def caso(**esperado):
    return Caso(id="c1", pergunta="Quem matou o mosquito?", esperado=Esperado(**esperado), tags=["fato"])


# ---------- leitura dos casos ----------

def test_carregar_casos(tmp_path):
    arquivo = tmp_path / "casos.jsonl"
    arquivo.write_text(
        '{"id": "a", "pergunta": "P1", "esperado": {"deve_conter": ["x"]}, "tags": ["t"]}\n'
        "// comentário\n\n"
        '{"id": "b", "pergunta": "P2", "contexto": {"assistiu_ate": "xdq-01"}}\n',
        encoding="utf-8",
    )
    casos = carregar_casos(arquivo)
    assert [c.id for c in casos] == ["a", "b"]
    assert casos[1].contexto == {"assistiu_ate": "xdq-01"}


@pytest.mark.parametrize(
    "conteudo, mensagem",
    [
        ('{"id": "a"}', "pergunta"),
        ('{"id": "a", "pergunta": "x"}\n{"id": "a", "pergunta": "y"}', "repetido"),
        ('{"id": "a", "pergunta": "x", "esperado": {"deve_conte": ["x"]}}', "desconhecidos"),
        ("{quebrado", "JSON"),
    ],
)
def test_erros_nos_casos_sao_claros(tmp_path, conteudo, mensagem):
    arquivo = tmp_path / "casos.jsonl"
    arquivo.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ErroNosCasos, match=mensagem):
        carregar_casos(arquivo)


def test_casos_do_exemplo_sao_validos():
    casos = carregar_casos("dados/casos-equiverso.jsonl")
    assert len(casos) >= 10 and any("spoiler" in c.tags for c in casos)


# ---------- verificações ----------

def test_contem_ignora_acento_e_aceita_alternativas():
    v = verificar_deterministico(caso(deve_conter=["Benicio", "123|cento e vinte e três"]), Saida("BENÍCIO contou 123"))
    assert v[0].passou and v[0].nota == 1.0


def test_contem_da_nota_parcial():
    v = verificar_deterministico(caso(deve_conter=["Nina", "punhal"]), Saida("Foi a Nina."))[0]
    assert not v.passou and v.nota == 0.5 and "punhal" in v.detalhe


def test_nao_contem_pega_spoiler():
    v = verificar_deterministico(caso(nao_deve_conter=["Navarro"]), Saida("O nome dela é Ayla Navarro."))[0]
    assert not v.passou and "Navarro" in v.detalhe


def test_recusa_pelo_sinal_do_sistema_e_pelo_texto():
    assert verificar_deterministico(caso(deve_recusar=True), Saida("qualquer coisa", encontrou=False))[0].passou
    assert verificar_deterministico(caso(deve_recusar=True), Saida("Não encontrei isso na wiki."))[0].passou
    assert not verificar_deterministico(caso(deve_recusar=True), Saida("O Brasil ganhou."))[0].passou


def test_recusar_pergunta_com_resposta_e_falha():
    nomes = {v.nome: v.passou for v in verificar_deterministico(caso(deve_conter=["Nina"]), Saida("Não sei."))}
    assert nomes["respondeu"] is False


def test_fontes_esperadas_com_alternativas():
    v = verificar_deterministico(caso(fontes_esperadas=["xdq-01|mosquito"]), Saida("x", fontes=["mosquito-gigante"]))
    assert v[0].nome == "fontes" and v[0].passou


# ---------- execução ----------

def test_saida_aceita_varios_formatos():
    assert Saida.de("oi").resposta == "oi"
    s = Saida.de({"resposta": "oi", "fontes": ["a"], "encontrou": True, "tokens": 10})
    assert s.fontes == ["a"] and s.extras == {"tokens": 10}
    with pytest.raises(TypeError):
        Saida.de(42)


def test_erro_do_sistema_vira_falha_e_nao_derruba_a_rodada():
    def quebra(pergunta, contexto):
        raise RuntimeError("caiu")

    rodada = rodar([caso(deve_conter=["x"])], quebra, "quebra")
    assert not rodada.resultados[0].passou and "RuntimeError" in rodada.resultados[0].erro


def test_rodada_mantem_ordem_e_calcula_taxa():
    casos = [Caso(id=f"c{i}", pergunta=str(i), esperado=Esperado(deve_conter=["par"] if i % 2 else [])) for i in range(6)]
    rodada = rodar(casos, lambda p, c: "par" if int(p) % 2 else "", "teste", paralelo=3)
    assert [r.id for r in rodada.resultados] == [f"c{i}" for i in range(6)]
    assert rodada.taxa_acerto == 0.5  # casos sem nenhuma verificação não contam como acerto


def test_carregar_sistema():
    assert carregar_sistema("avaliador_llm.exemplos:eco")("oi", {}).resposta == "oi"
    with pytest.raises(ValueError):
        carregar_sistema("sem_dois_pontos")


# ---------- juiz LLM (com cliente falso) ----------

class ClienteFalso:
    def __init__(self, conteudo, stop_reason="end_turn"):
        self.chamadas = []
        self._r = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=json.dumps(conteudo))])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.chamadas.append(kwargs)
        return self._r


def test_juiz_converte_notas():
    juiz = JuizLLM(ClienteFalso({"fidelidade": 5, "utilidade": 4, "justificativa": "boa"}))
    v = juiz.avaliar(caso(), Saida("Foi a Nina."))
    assert v.nota == 0.875 and v.passou
    pedido = juiz.cliente.chamadas[0]
    assert pedido["output_config"]["format"]["type"] == "json_schema"
    assert "<resposta>Foi a Nina.</resposta>" in pedido["messages"][0]["content"]


def test_juiz_reprova_nota_baixa_e_recusa():
    assert not JuizLLM(ClienteFalso({"fidelidade": 2, "utilidade": 3, "justificativa": "x"})).avaliar(caso(), Saida("x")).passou
    assert not JuizLLM(ClienteFalso({}, stop_reason="refusal")).avaliar(caso(), Saida("x")).passou


def test_juiz_entra_na_nota_do_caso():
    juiz = JuizLLM(ClienteFalso({"fidelidade": 1, "utilidade": 1, "justificativa": "inventou"}))
    r = avaliar_caso(caso(deve_conter=["Nina"]), lambda p, c: "Foi a Nina.", juiz)
    assert not r.passou and r.nota == 0.5  # contém = 1.0, juiz = 0.0


# ---------- relatórios e comparação ----------

def _rodada(nome, resultados):
    casos = [Caso(id=i, pergunta=i, esperado=Esperado(deve_conter=["ok"]), tags=["t"]) for i in resultados]
    return rodar(casos, lambda p, c: "ok" if resultados[p] else "", nome)


def test_comparar_acha_regressoes_e_melhorias():
    antes = _rodada("antes", {"a": True, "b": False, "c": True})
    depois = _rodada("depois", {"a": True, "b": True, "c": False})
    c = comparar(antes, depois)
    assert c.regressoes == ["c"] and c.melhorias == ["b"] and c.piorou


def test_relatorios_e_ida_e_volta_em_json():
    rodada = _rodada("x", {"a": True, "b": False})
    assert "1/2 casos passaram" in markdown(rodada)
    assert "<table>" in html_pagina(rodada)
    copia = Rodada.de_dict(json.loads(json.dumps(rodada.para_dict())))
    assert copia.taxa_acerto == rodada.taxa_acerto and copia.resultados[1].verificacoes[0].nome == "contem"


def test_cli_rodar_e_comparar(tmp_path, capsys):
    casos = tmp_path / "casos.jsonl"
    casos.write_text('{"id": "a", "pergunta": "oi", "esperado": {"deve_conter": ["oi"]}}\n', encoding="utf-8")
    args = ["rodar", str(casos), "--sistema", "avaliador_llm.exemplos:eco", "--saida", str(tmp_path)]
    assert main([*args, "--nome", "r1", "--minimo", "1"]) == 0
    assert (tmp_path / "r1.html").exists()
    assert main(["comparar", str(tmp_path / "r1.json"), str(tmp_path / "r1.json")]) == 0
