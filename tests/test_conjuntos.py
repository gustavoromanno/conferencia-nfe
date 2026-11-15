"""Ponta a ponta: gera os dois conjuntos e mede a detecção contra o gabarito.

A detecção é regra fiscal e precisa ser exata nos dois conjuntos. A causa provável
pelas regras só precisa ser perfeita no básico: o realista existe justamente para
mostrar onde as regras não bastam.
"""
import csv

import pytest

import gerar_dados
from conferencia.cruzamento import conferir
from conferencia.explicacao import explicar
from conferencia.leitura import ler_notas, ler_pedidos

POR_CHAVE = {"CHAVE_INVALIDA", "NOTA_SEM_PEDIDO"}


def _ident(tipo, pedido, chave):
    return (tipo, chave) if tipo in POR_CHAVE else (tipo, pedido or "")


def _rodar(pasta, semente, realista):
    gerar_dados.main(pasta, semente, realista)
    with open(pasta / "gabarito.csv", encoding="utf-8") as f:
        gabarito = {_ident(l["tipo"], l["pedido_id"], l["chave"]): l["causa"] for l in csv.DictReader(f)}
    divs = conferir(ler_pedidos(pasta / "pedidos.csv"), ler_notas(pasta / "notas"))
    explicacoes, _, _ = explicar(divs, usar_ia=False)
    causas = {e.divergencia_id: e.causa_provavel for e in explicacoes}
    achados = {_ident(d.tipo, d.pedido_id, d.chaves[0] if d.chaves else None): causas[d.id] for d in divs}
    return gabarito, achados


@pytest.mark.parametrize("realista", [False, True])
@pytest.mark.parametrize("semente", [1, 7, 42])
def test_deteccao_exata(tmp_path, semente, realista):
    gabarito, achados = _rodar(tmp_path / "d", semente, realista)
    assert set(achados) == set(gabarito)


@pytest.mark.parametrize("semente", [1, 7, 42])
def test_regras_acertam_todas_as_causas_no_basico(tmp_path, semente):
    gabarito, achados = _rodar(tmp_path / "d", semente, realista=False)
    assert all(achados[i] == c for i, c in gabarito.items())
