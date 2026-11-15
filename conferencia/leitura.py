"""Leitura do CSV de pedidos, dos XMLs das notas e dos XMLs de eventos da SEFAZ."""
import csv
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .modelos import Item, Nota, Pedido

NS = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

# Número do pedido no texto livre do infCpl. Aceita "Pedido #48101", "Ped. 48101", "#48101",
# "pedido 48101", "PEDIDO Nº 48101", "Pedido app: 48101". Exige ao menos 4 dígitos para não
# confundir com "Mesa 12" ou com o valor de tributos ("Trib aprox R$ 5,32").
PADRAO_PEDIDO = re.compile(r"(?:\bped(?:ido)?\b\.?|#)[^\d\n|]{0,15}?(\d{4,})", re.IGNORECASE)

# Evento de cancelamento (tpEvento 110111) aceito pela SEFAZ: 135 (registrado e vinculado)
# ou 155 (cancelamento homologado fora de prazo). Qualquer outro cStat é rejeição.
CANCELAMENTO = "110111"
EVENTO_ACEITO = {"135", "155"}


def extrair_pedido(texto: str) -> str | None:
    achado = PADRAO_PEDIDO.search(texto or "")
    return achado.group(1) if achado else None


def ler_pedidos(caminho: Path) -> list[Pedido]:
    """Lê pedidos.csv e, se existir ao lado, itens_pedidos.csv."""
    itens: dict[str, list[Item]] = defaultdict(list)
    arquivo_itens = caminho.with_name("itens_pedidos.csv")
    if arquivo_itens.exists():
        with open(arquivo_itens, newline="", encoding="utf-8") as f:
            for linha in csv.DictReader(f):
                qtd, unit = Decimal(linha["quantidade"]), Decimal(linha["valor_unitario"])
                itens[linha["pedido_id"]].append(Item(linha["item"], qtd, unit, (qtd * unit).quantize(Decimal("0.01"))))

    pedidos = []
    with open(caminho, newline="", encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            pedidos.append(Pedido(
                pedido_id=linha["pedido_id"],
                data_hora=datetime.fromisoformat(linha["data_hora"]),
                subtotal=Decimal(linha["subtotal"]),
                desconto_loja=Decimal(linha["desconto_loja"]),
                taxa_entrega=Decimal(linha["taxa_entrega"]),
                valor_total=Decimal(linha["valor_total"]),
                status=linha["status"],
                itens=itens.get(linha["pedido_id"], []),
            ))
    return pedidos


def _texto(raiz, caminho: str, padrao: str = "") -> str:
    elem = raiz.find(caminho, NS)
    return elem.text.strip() if elem is not None and elem.text else padrao


def _tipo_xml(raiz) -> str:
    return raiz.tag.split("}")[-1]       # "nfeProc", "NFe", "procEventoNFe", ...


def ler_nota(arquivo: Path, raiz=None) -> Nota:
    raiz = raiz if raiz is not None else ET.parse(arquivo).getroot()
    inf = raiz.find(".//nfe:infNFe", NS)
    complemento = _texto(inf, "nfe:infAdic/nfe:infCpl")
    status = _texto(raiz, ".//nfe:protNFe/nfe:infProt/nfe:cStat")
    itens = [Item(codigo=_texto(prod, "nfe:cProd"), descricao=_texto(prod, "nfe:xProd"),
                  quantidade=Decimal(_texto(prod, "nfe:qCom", "0")),
                  valor_unitario=Decimal(_texto(prod, "nfe:vUnCom", "0")).normalize(),
                  valor_total=Decimal(_texto(prod, "nfe:vProd", "0")))
             for prod in inf.findall("nfe:det/nfe:prod", NS)]
    return Nota(
        chave=inf.get("Id", "").removeprefix("NFe"),
        numero=int(_texto(inf, "nfe:ide/nfe:nNF", "0")),
        emissao=datetime.fromisoformat(_texto(inf, "nfe:ide/nfe:dhEmi")),
        valor=Decimal(_texto(inf, "nfe:total/nfe:ICMSTot/nfe:vNF", "0")),
        desconto=Decimal(_texto(inf, "nfe:total/nfe:ICMSTot/nfe:vDesc", "0")),
        frete=Decimal(_texto(inf, "nfe:total/nfe:ICMSTot/nfe:vFrete", "0")),
        pedido_id=extrair_pedido(complemento),
        situacao="AUTORIZADA" if status == "100" else "CANCELADA" if status == "101" else f"OUTRA({status})",
        arquivo=arquivo.name,
        itens=itens,
        texto_complementar=complemento,
    )


def ler_evento(raiz) -> dict:
    ret = raiz.find(".//nfe:retEvento/nfe:infEvento", NS)
    inf = raiz.find(".//nfe:evento/nfe:infEvento", NS)
    return {
        "chave": _texto(inf, "nfe:chNFe"),
        "tipo": _texto(inf, "nfe:tpEvento"),
        "descricao": _texto(inf, "nfe:detEvento/nfe:descEvento"),
        "data": _texto(inf, "nfe:dhEvento"),
        "cstat": _texto(ret, "nfe:cStat") if ret is not None else "",
        "motivo": _texto(ret, "nfe:xMotivo") if ret is not None else "",
    }


def ler_notas(pasta: Path) -> list[Nota]:
    """Lê todos os XMLs da pasta: notas e eventos.

    - O mesmo XML salvo duas vezes (ex.: "nfce_1001 (1).xml") conta como UMA nota, pela chave.
    - Eventos de cancelamento aceitos pela SEFAZ mudam a situação da nota para CANCELADA;
      rejeitados ficam registrados na nota, mas ela continua autorizada.
    """
    notas: dict[str, Nota] = {}
    eventos = []
    for arquivo in sorted(pasta.glob("*.xml")):
        raiz = ET.parse(arquivo).getroot()
        tipo = _tipo_xml(raiz)
        if tipo == "procEventoNFe":
            eventos.append(ler_evento(raiz))
        elif tipo in {"nfeProc", "NFe"}:
            nota = ler_nota(arquivo, raiz)
            if nota.chave in notas:
                notas[nota.chave].arquivos_repetidos.append(arquivo.name)
            else:
                notas[nota.chave] = nota

    for evento in eventos:
        nota = notas.get(evento["chave"])
        if nota is None:
            continue                    # evento de nota que não está na pasta
        nota.eventos.append(evento)
        if evento["tipo"] == CANCELAMENTO and evento["cstat"] in EVENTO_ACEITO:
            nota.situacao = "CANCELADA"

    return list(notas.values())
