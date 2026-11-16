"""O motor do painel (painel/motor.js) dá o mesmo resultado que o Python?

Roda o motor num Chromium de verdade (Playwright) e compara, divergência por divergência,
tipo, pedido, chaves, prioridade, causa, explicação e ação. Pulado se não houver Playwright.
"""
import os
from decimal import Decimal
from pathlib import Path

import pytest

import gerar_dados
from conferencia.cruzamento import conferir
from conferencia.explicacao import explicar
from conferencia.leitura import ler_notas, ler_pedidos

playwright = pytest.importorskip("playwright.sync_api")
MOTOR = (Path(__file__).resolve().parent.parent / "painel" / "motor.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pagina():
    with playwright.sync_playwright() as p:
        try:
            navegador = p.chromium.launch()
        except Exception:
            # Versão do Playwright diferente do navegador instalado: usa o Chromium da máquina.
            alternativo = os.environ.get("CHROMIUM", "/opt/pw-browsers/chromium")
            if not Path(alternativo).exists():
                pytest.skip("Chromium indisponível")
            navegador = p.chromium.launch(executable_path=alternativo)
        pg = navegador.new_page()
        pg.set_content("<html><body></body></html>")
        pg.add_script_tag(content=MOTOR)
        yield pg
        navegador.close()


def _arquivos(pasta: Path) -> list[dict]:
    arqs = [{"nome": n, "conteudo": (pasta / n).read_text(encoding="utf-8")}
            for n in ("pedidos.csv", "itens_pedidos.csv", "gabarito.csv")]
    arqs += [{"nome": x.name, "conteudo": x.read_text(encoding="utf-8")} for x in (pasta / "notas").glob("*.xml")]
    return arqs


def _centavos(v) -> int:
    return int(Decimal(str(v)) * 100)


@pytest.mark.parametrize("realista", [False, True])
@pytest.mark.parametrize("semente", [1, 7, 42])
def test_motor_js_igual_ao_python(pagina, tmp_path, semente, realista):
    pasta = tmp_path / "d"
    gerar_dados.main(pasta, semente, realista)
    divs = conferir(ler_pedidos(pasta / "pedidos.csv"), ler_notas(pasta / "notas"))
    explicacoes, _, _ = explicar(divs, usar_ia=False)
    esperado = [{"id": d.id, "tipo": d.tipo, "pedido": d.pedido_id, "chaves": d.chaves,
                 "diferenca": _centavos(d.fatos["diferenca"]) if "diferenca" in d.fatos else None,
                 "prioridade": e.prioridade, "causa": e.causa_provavel, "explicacao": e.explicacao, "acao": e.acao}
                for d, e in zip(divs, explicacoes)]

    obtido = pagina.evaluate("""arquivos => {
        const r = Conferencia.rodar(arquivos);
        return r.divergencias.map((d, i) => ({
            id: d.id, tipo: d.tipo, pedido: d.pedidoId, chaves: d.chaves,
            diferenca: d.fatos.diferenca ?? null,
            prioridade: r.explicacoes[i].prioridade, causa: r.explicacoes[i].causa_provavel,
            explicacao: r.explicacoes[i].explicacao, acao: r.explicacoes[i].acao }));
    }""", _arquivos(pasta))

    assert obtido == esperado


def test_avaliacao_js_igual_ao_avaliar_py(pagina, tmp_path):
    pasta = tmp_path / "d"
    gerar_dados.main(pasta, 7, realista=True)
    r = pagina.evaluate("a => { const r = Conferencia.rodar(a); return r.avaliacao; }", _arquivos(pasta))
    assert (r["plantadas"], r["verdadeiros"], r["falsosPositivos"], r["causaCerta"]) == (33, 33, 0, 17)


def test_csv_do_excel_em_portugues(pagina):
    """Ponto e vírgula e vírgula decimal, como o Excel salva no Brasil."""
    csv = ("pedido_id;data_hora;subtotal;desconto_loja;taxa_entrega;valor_total;status\n"
           "1;2026-11-02T11:00:00;1.234,50;0,00;5,00;1.239,50;CONCLUIDO\n")
    r = pagina.evaluate("a => Conferencia.rodar(a)", [{"nome": "pedidos.csv", "conteudo": csv}])
    assert r["pedidos"][0]["valorTotal"] == 123950
    assert [d["tipo"] for d in r["divergencias"]] == ["PEDIDO_SEM_NOTA"]
