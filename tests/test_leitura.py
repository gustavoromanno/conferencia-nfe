"""Leitura de XMLs do jeito que chegam na vida real."""
import shutil
from pathlib import Path

import pytest

from conferencia.leitura import extrair_pedido, ler_notas

import gerar_dados


@pytest.mark.parametrize("texto", [
    "Pedido #48101 - venda por aplicativo",
    "Ped. 48101",
    "#48101",
    "pedido 48101",
    "PEDIDO Nº 48101 - ENTREGA",
    "Pedido app: 48101",
    "Trib aprox R$ 7,10 Fed e Est. Fonte: IBPT. Ped. 48101",
    "Ped. 48101 | Trib aprox R$ 12,34 Fed e Est. Fonte: IBPT",
])
def test_numero_do_pedido_em_varios_formatos(texto):
    assert extrair_pedido(texto) == "48101"


@pytest.mark.parametrize("texto", [
    "Venda balcão",
    "Entrega | Trib aprox R$ 4,10 Fed e Est. Fonte: IBPT",
    "Mesa 12",
    "",
])
def test_texto_sem_numero_de_pedido(texto):
    assert extrair_pedido(texto) is None


def _uma_nota(tmp_path: Path, pedido: str = "48101") -> Path:
    """Gera um conjunto pequeno e devolve o XML de uma nota autorizada do pedido."""
    gerar_dados.main(tmp_path / "d", semente=3, realista=True)
    for arq in sorted((tmp_path / "d" / "notas").glob("nfce_*.xml")):
        if "Evento" not in arq.name:
            return arq
    raise AssertionError("nenhuma nota gerada")


def test_mesmo_xml_duas_vezes_conta_como_uma_nota(tmp_path):
    origem = _uma_nota(tmp_path)
    pasta = tmp_path / "so_uma"
    pasta.mkdir()
    shutil.copy(origem, pasta / "nota.xml")
    shutil.copy(origem, pasta / "nota (1).xml")
    [nota] = ler_notas(pasta)
    assert nota.arquivos_repetidos == ["nota.xml"] or nota.arquivos_repetidos == ["nota (1).xml"]


def test_evento_de_cancelamento_aceito_e_rejeitado(tmp_path):
    origem = _uma_nota(tmp_path)
    pasta = tmp_path / "ev"
    pasta.mkdir()
    shutil.copy(origem, pasta / "nota.xml")
    chave = ler_notas(pasta)[0].chave
    modelo = gerar_dados.EVENTO.format(chave=chave, cnpj=gerar_dados.CNPJ, quando="2026-11-02T12:00:00",
                                       nprot="1", justificativa="teste", cstat="{cstat}", motivo="x")

    (pasta / "ev.xml").write_text(modelo.replace("{cstat}", "501"), encoding="utf-8")
    [nota] = ler_notas(pasta)
    assert nota.situacao == "AUTORIZADA"          # rejeitado: a nota continua valendo
    assert nota.eventos[0]["cstat"] == "501"

    (pasta / "ev.xml").write_text(modelo.replace("{cstat}", "135"), encoding="utf-8")
    assert ler_notas(pasta)[0].situacao == "CANCELADA"


def test_itens_da_nota_sao_lidos(tmp_path):
    pasta = tmp_path / "it"
    pasta.mkdir()
    shutil.copy(_uma_nota(tmp_path), pasta / "nota.xml")
    [nota] = ler_notas(pasta)
    assert nota.itens
    assert sum(i.valor_total for i in nota.itens) - nota.desconto + nota.frete == nota.valor
