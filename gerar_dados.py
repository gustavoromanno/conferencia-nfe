"""Gera dados FICTÍCIOS de um restaurante: pedidos, itens, XMLs de notas e o gabarito das divergências.

Os erros são inseridos de propósito e anotados em gabarito.csv, para medir se o
conferidor encontra todos (e só eles) e se explica a causa certa.

Dois conjuntos:
  basico   : o conjunto original. Erros simples, cancelamento marcado no próprio XML.
  realista : o que aparece no dia a dia de quem confere nota:
             - número do pedido escrito de vários jeitos ("Ped. 48101", "#48101", "pedido 48101")
               e misturado ao texto de tributos aproximados (Lei da Transparência);
             - cancelamento como EVENTO separado (procEventoNFe), como a SEFAZ faz, inclusive
               cancelamento rejeitado por prazo;
             - desconto rateado entre os itens com arredondamento de centavos;
             - erros de item (lançado duas vezes, faltando, preço desatualizado no emissor);
             - número do pedido digitado errado ou ausente na nota;
             - armadilhas: o mesmo XML baixado duas vezes, diferença que coincide com o desconto.

Uso: python gerar_dados.py [pasta] [semente] [--realista]
"""
import argparse
import csv
import random
import shutil
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from conferencia.cruzamento import digito_verificador

CNPJ = "11222333000181"          # CNPJ de exemplo, não pertence a nenhum restaurante real
NOME = "Cantina Exemplo Ltda (fictícia)"

# Nome no aplicativo, nome no cadastro do emissor de notas, código e preço.
# Os nomes diferem de propósito: na vida real, o app e o emissor raramente usam o mesmo cadastro.
CARDAPIO = [
    ("X-Burguer", "XBURGUER TRADICIONAL", "101", "24.90"),
    ("X-Salada", "X SALADA", "102", "27.90"),
    ("Batata frita média", "PORCAO BATATA M", "201", "18.50"),
    ("Coca-Cola 2L", "REFRIG COCA COLA 2L", "301", "14.00"),
    ("Guaraná lata 350ml", "REFRIG GUARANA LT", "302", "6.50"),
    ("Suco de laranja 500ml", "SUCO LARANJA 500", "303", "9.90"),
    ("Água sem gás", "AGUA MINERAL S/GAS", "304", "4.00"),
    ("Pizza calabresa grande", "PIZZA CALABRESA G", "401", "54.90"),
    ("Pizza margherita média", "PIZZA MARGUERITA M", "402", "44.90"),
    ("Açaí 500ml", "ACAI 500ML", "501", "22.00"),
    ("Pudim", "SOBREMESA PUDIM", "502", "12.00"),
    ("Combo família", "COMBO FAMILIA", "601", "89.90"),
]

# Jeitos diferentes de escrever o número do pedido no campo de informações complementares.
FORMATOS_PEDIDO = [
    "Pedido #{id} - venda por aplicativo",
    "Ped. {id}",
    "#{id}",
    "pedido {id}",
    "PEDIDO Nº {id} - ENTREGA",
    "Pedido app: {id}",
]

XML = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe{chave}" versao="4.00">
      <ide><cUF>31</cUF><mod>65</mod><serie>1</serie><nNF>{numero}</nNF><dhEmi>{emissao}</dhEmi></ide>
      <emit><CNPJ>{cnpj}</CNPJ><xNome>{nome}</xNome></emit>
{dets}      <total><ICMSTot><vProd>{vprod}</vProd><vDesc>{vdesc}</vDesc><vFrete>{vfrete}</vFrete><vNF>{vnf}</vNF></ICMSTot></total>
      <infAdic><infCpl>{complemento}</infCpl></infAdic>
    </infNFe>
  </NFe>
  <protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><nProt>{nprot}</nProt><cStat>{cstat}</cStat></infProt></protNFe>
</nfeProc>
"""

DET = ('      <det nItem="{n}"><prod><cProd>{codigo}</cProd><cEAN>SEM GTIN</cEAN><xProd>{xprod}</xProd>'
       '<NCM>21069090</NCM><CFOP>5102</CFOP><uCom>UN</uCom><qCom>{q}.0000</qCom>'
       '<vUnCom>{vun:.10f}</vUnCom><vProd>{vprod}</vProd>{vdesc}</prod></det>\n')

EVENTO = """<?xml version="1.0" encoding="UTF-8"?>
<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <evento versao="1.00">
    <infEvento Id="ID110111{chave}01"><cOrgao>31</cOrgao><tpAmb>1</tpAmb><CNPJ>{cnpj}</CNPJ><chNFe>{chave}</chNFe><dhEvento>{quando}</dhEvento><tpEvento>110111</tpEvento><nSeqEvento>1</nSeqEvento><verEvento>1.00</verEvento>
      <detEvento versao="1.00"><descEvento>Cancelamento</descEvento><nProt>{nprot}</nProt><xJust>{justificativa}</xJust></detEvento>
    </infEvento>
  </evento>
  <retEvento versao="1.00"><infEvento><tpAmb>1</tpAmb><cStat>{cstat}</cStat><xMotivo>{motivo}</xMotivo><chNFe>{chave}</chNFe><tpEvento>110111</tpEvento></infEvento></retEvento>
</procEventoNFe>
"""

PLANO_BASICO = {
    "ok": 96, "sem_nota": 4, "cancelada": 2, "desconto": 3, "taxa": 3, "outra": 1, "duplicada": 2,
    "pedido_cancelado_com_nota": 2, "chave_errada": 2, "substituida": 2, "pedido_cancelado_ok": 3,
}
PLANO_REALISTA = {
    "ok": 80, "sem_nota": 3, "cancelada": 2, "desconto": 2, "taxa": 2, "duplicada": 2,
    "pedido_cancelado_com_nota": 2, "chave_errada": 2, "substituida": 2, "pedido_cancelado_ok": 3,
    # casos novos
    "arredondamento": 2, "item_duplicado": 2, "item_faltando": 2, "preco_desatualizado": 2,
    "desconto_e_taxa": 2, "coincide_com_desconto": 1, "numero_errado": 1, "numero_ausente": 1,
    "xml_baixado_duas_vezes": 2, "cancelamento_rejeitado": 1,
}


def dinheiro(valor) -> Decimal:
    return Decimal(str(valor)).quantize(Decimal("0.01"))


def montar_chave(numero: int, emissao: datetime, rnd: random.Random) -> str:
    base = f"31{emissao:%y%m}{CNPJ}65001{numero:09d}1{rnd.randint(0, 99999999):08d}"
    return base + str(digito_verificador(base))


def ratear(desconto: Decimal, valores: list[Decimal], ajustar_sobra: bool) -> list[Decimal]:
    """Divide o desconto entre os itens, proporcional ao valor de cada um.

    O jeito certo joga a sobra do arredondamento no último item. Um emissor mal feito
    só arredonda cada parte, e a soma pode ficar um centavo acima ou abaixo do desconto.
    """
    total = sum(valores)
    partes = [dinheiro(desconto * v / total) for v in valores]
    if ajustar_sobra:
        partes[-1] += desconto - sum(partes)
    return partes


def main(pasta: Path, semente: int = 7, realista: bool = False) -> None:
    rnd = random.Random(semente)
    if pasta.exists():
        shutil.rmtree(pasta)
    (pasta / "notas").mkdir(parents=True)

    pedidos, itens_pedidos, gabarito = [], [], []
    numero_nota = 1000
    inicio = datetime(2026, 11, 2, 11, 0)

    def texto_pedido(pid: str) -> str:
        if not realista:
            return f"Pedido #{pid} - venda por aplicativo"
        texto = rnd.choice(FORMATOS_PEDIDO).format(id=pid)
        tributos = f"Trib aprox R$ {rnd.randint(2, 15)},{rnd.randint(0, 99):02d} Fed e Est. Fonte: IBPT"
        return f"{texto} | {tributos}" if rnd.random() < 0.7 else f"{tributos}. {texto}"

    def cancelar(chave: str, quando: datetime, aceito: bool = True):
        """Grava o evento de cancelamento como arquivo separado, como vem da SEFAZ."""
        cstat, motivo = ("135", "Evento registrado e vinculado a NF-e") if aceito else \
            ("501", "Rejeicao: Prazo de cancelamento superior ao previsto na Legislacao")
        (pasta / "notas" / f"110111{chave}01-procEventoNFe.xml").write_text(EVENTO.format(
            chave=chave, cnpj=CNPJ, quando=quando.isoformat(), nprot=f"1312600000{rnd.randint(0, 99999):05d}",
            justificativa="Pedido cancelado pelo cliente no aplicativo", cstat=cstat, motivo=motivo),
            encoding="utf-8")

    def emitir(pedido, itens, *, vdesc, vfrete, cancelada=False, complemento=None,
               chave_errada=False, rateio_com_sobra=True) -> tuple[str, Path]:
        """Emite uma nota com os itens dados: lista de (codigo, descricao_emissor, qtd, valor_unitario)."""
        nonlocal numero_nota
        numero_nota += 1
        emissao = pedido["data_hora"] + timedelta(minutes=rnd.randint(1, 20))
        chave = montar_chave(numero_nota, emissao, rnd)
        if chave_errada:
            chave = chave[:43] + str((int(chave[43]) + 1) % 10)

        valores = [dinheiro(q * vun) for _, _, q, vun in itens]
        descontos = ratear(vdesc, valores, rateio_com_sobra) if vdesc > 0 else [Decimal("0.00")] * len(itens)
        dets = "".join(DET.format(n=i, codigo=cod, xprod=desc, q=q, vun=vun, vprod=v,
                                  vdesc=f"<vDesc>{d}</vDesc>" if d > 0 else "")
                       for i, ((cod, desc, q, vun), v, d) in enumerate(zip(itens, valores, descontos), start=1))
        vprod, vdesc_total = sum(valores), sum(descontos)
        cstat = "101" if cancelada and not realista else "100"
        arquivo = pasta / "notas" / f"nfce_{numero_nota}.xml"
        arquivo.write_text(XML.format(
            chave=chave, numero=numero_nota, emissao=emissao.isoformat(), cnpj=CNPJ, nome=NOME, dets=dets,
            vprod=vprod, vdesc=vdesc_total, vfrete=vfrete, vnf=vprod - vdesc_total + vfrete,
            complemento=complemento if complemento is not None else texto_pedido(pedido["pedido_id"]),
            nprot=f"1312600000{rnd.randint(0, 99999):05d}", cstat=cstat), encoding="utf-8")
        if cancelada and realista:
            cancelar(chave, emissao + timedelta(minutes=rnd.randint(5, 90)))
        return chave, arquivo

    def itens_nota(p):
        return [(c["codigo"], c["emissor"], q, c["preco"]) for c, q in p["itens"]]

    def nota_correta(p, **extra):
        return emitir(p, itens_nota(p), vdesc=p["desconto_loja"], vfrete=p["taxa_entrega"], **extra)

    def sortear_itens(minimo=1):
        escolhidos = rnd.sample(CARDAPIO, rnd.randint(minimo, 4))
        return [({"app": a, "emissor": e, "codigo": c, "preco": Decimal(v)}, rnd.choice([1, 1, 1, 2, 3]))
                for a, e, c, v in escolhidos]

    plano = [caso for caso, qtd in (PLANO_REALISTA if realista else PLANO_BASICO).items() for _ in range(qtd)]
    rnd.shuffle(plano)

    for i, caso in enumerate(plano):
        precisa_varios = caso in {"item_faltando", "arredondamento", "coincide_com_desconto"}
        taxa = dinheiro(rnd.choice([0, 4.99, 6.99, 7.5, 9.9]))
        if caso in {"taxa", "desconto_e_taxa"}:
            taxa = dinheiro(rnd.choice([5.99, 7.99, 8.5]))
        # Sorteia itens e desconto até o desconto ficar razoável (no máximo metade do subtotal).
        for _ in range(500):
            itens = sortear_itens(minimo=2 if precisa_varios else 1)
            subtotal = sum(dinheiro(q * c["preco"]) for c, q in itens)
            desconto = dinheiro(rnd.choice([0, 0, 0, 5, 8, 10, 12.5]))
            if caso in {"desconto", "desconto_e_taxa"}:
                desconto = dinheiro(rnd.choice([5, 10, 15]))
            if caso == "arredondamento":
                desconto = dinheiro(rnd.choice([5, 7, 8, 10, 12.5, 13]))
            if caso == "coincide_com_desconto":
                # O desconto tem exatamente o valor de um dos itens; a nota traz o desconto certo,
                # mas lança esse item duas vezes. A diferença "parece" desconto, mas não é.
                desconto = itens[0][0]["preco"]
            if desconto * 2 > subtotal:
                continue
            if caso == "arredondamento":
                # Precisa de um rateio que, sem ajustar a sobra, não feche no centavo.
                valores = [dinheiro(q * c["preco"]) for c, q in itens]
                if sum(ratear(desconto, valores, ajustar_sobra=False)) == desconto:
                    continue
            break

        p = {
            "pedido_id": f"{48100 + i}",
            "data_hora": inicio + timedelta(days=i // 18, minutes=(i % 18) * 37),
            "itens": itens,
            "subtotal": subtotal, "desconto_loja": desconto, "taxa_entrega": taxa,
            "valor_total": subtotal - desconto + taxa,
            "status": "CANCELADO" if caso.startswith("pedido_cancelado") or caso == "cancelamento_rejeitado"
            else "CONCLUIDO",
        }
        pedidos.append(p)
        pid = p["pedido_id"]

        if caso == "ok":
            nota_correta(p)
        elif caso == "sem_nota":
            gabarito.append(("PEDIDO_SEM_NOTA", pid, "", "nota_nao_emitida"))
        elif caso == "cancelada":
            nota_correta(p, cancelada=True)
            gabarito.append(("NOTA_CANCELADA", pid, "", "nota_cancelada_sem_substituta"))
        elif caso == "substituida":          # armadilha: cancelou e emitiu outra. Está correto.
            nota_correta(p, cancelada=True)
            nota_correta(p)
        elif caso == "desconto":             # nota ignorou o desconto: sai mais cara
            emitir(p, itens_nota(p), vdesc=Decimal("0.00"), vfrete=taxa)
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "desconto_fora_da_nota"))
        elif caso == "taxa":                 # nota sem a taxa de entrega: sai mais barata
            emitir(p, itens_nota(p), vdesc=desconto, vfrete=Decimal("0.00"))
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "taxa_entrega_fora_da_nota"))
        elif caso == "desconto_e_taxa":      # nota sem desconto E sem taxa: diferença = desconto - taxa
            emitir(p, itens_nota(p), vdesc=Decimal("0.00"), vfrete=Decimal("0.00"))
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "desconto_e_taxa_fora_da_nota"))
        elif caso == "outra":                # item a mais digitado no emissor
            emitir(p, itens_nota(p) + [("999", "ADICIONAL", 1, Decimal("3.50"))], vdesc=desconto, vfrete=taxa)
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "outra"))
        elif caso in {"item_duplicado", "coincide_com_desconto"}:
            linhas = itens_nota(p)
            repetido = linhas[0] if caso == "coincide_com_desconto" else rnd.choice(linhas)
            emitir(p, linhas + [(repetido[0], repetido[1], 1, repetido[3])], vdesc=desconto, vfrete=taxa)
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "item_lancado_em_duplicidade"))
        elif caso == "item_faltando":
            linhas = itens_nota(p)
            linhas.pop(rnd.randrange(len(linhas)))
            emitir(p, linhas, vdesc=desconto, vfrete=taxa)
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "item_faltando_na_nota"))
        elif caso == "preco_desatualizado":  # emissor com o preço antigo de um item
            linhas = itens_nota(p)
            k = rnd.randrange(len(linhas))
            cod, desc, q, vun = linhas[k]
            linhas[k] = (cod, desc, q, vun - dinheiro(rnd.choice([1, 1.5, 2, 2.5])))
            emitir(p, linhas, vdesc=desconto, vfrete=taxa)
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "preco_desatualizado_no_emissor"))
        elif caso == "arredondamento":
            nota_correta(p, rateio_com_sobra=False)
            gabarito.append(("VALOR_DIVERGENTE", pid, "", "arredondamento_no_rateio"))
        elif caso == "duplicada":
            nota_correta(p)
            nota_correta(p)
            gabarito.append(("NOTA_DUPLICADA", pid, "", "emissao_em_duplicidade"))
        elif caso == "pedido_cancelado_com_nota":
            nota_correta(p)
            gabarito.append(("NOTA_PEDIDO_CANCELADO", pid, "", "pedido_cancelado_apos_emissao"))
        elif caso == "cancelamento_rejeitado":  # tentou cancelar fora do prazo: a nota continua valendo
            chave, _ = nota_correta(p)
            cancelar(chave, p["data_hora"] + timedelta(days=9), aceito=False)
            gabarito.append(("NOTA_PEDIDO_CANCELADO", pid, "", "cancelamento_rejeitado_pela_sefaz"))
        elif caso == "pedido_cancelado_ok":  # armadilha: pedido e nota cancelados. Está correto.
            if rnd.random() < 0.5:
                nota_correta(p, cancelada=True)
        elif caso == "chave_errada":
            chave, _ = nota_correta(p, chave_errada=True)
            gabarito.append(("CHAVE_INVALIDA", pid, chave, "chave_digitada_ou_gerada_errada"))
        elif caso in {"numero_errado", "numero_ausente"}:
            # A nota existe, mas não aponta para o pedido: aparece como nota sem pedido E pedido sem nota.
            if caso == "numero_errado":
                complemento = f"Ped. {pid[:2] + pid[3:]} | Trib aprox R$ 4,10 Fed e Est. Fonte: IBPT"
            else:
                complemento = "Entrega | Trib aprox R$ 4,10 Fed e Est. Fonte: IBPT"
            chave, _ = nota_correta(p, complemento=complemento)
            gabarito.append(("NOTA_SEM_PEDIDO", "", chave, "numero_do_pedido_errado_na_nota"))
            gabarito.append(("PEDIDO_SEM_NOTA", pid, "", "numero_do_pedido_errado_na_nota"))
        elif caso == "xml_baixado_duas_vezes":  # armadilha: o mesmo arquivo duas vezes não é nota duplicada
            _, arquivo = nota_correta(p)
            shutil.copy(arquivo, arquivo.with_name(f"{arquivo.stem} (1).xml"))
        else:
            raise ValueError(caso)

    # Duas notas avulsas (venda de balcão) sem pedido correspondente.
    for _ in range(2):
        falso = {"pedido_id": "", "data_hora": inicio + timedelta(days=rnd.randint(0, 5), hours=3)}
        c = rnd.choice(CARDAPIO)
        chave, _ = emitir(falso, [(c[2], c[1], rnd.randint(1, 3), Decimal(c[3]))],
                          vdesc=Decimal("0.00"), vfrete=Decimal("0.00"), complemento="Venda balcão")
        gabarito.append(("NOTA_SEM_PEDIDO", "", chave, "nota_sem_vinculo_com_pedido"))

    with open(pasta / "pedidos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pedido_id", "data_hora", "subtotal", "desconto_loja", "taxa_entrega", "valor_total", "status"])
        for p in pedidos:
            w.writerow([p["pedido_id"], p["data_hora"].isoformat(), p["subtotal"], p["desconto_loja"],
                        p["taxa_entrega"], p["valor_total"], p["status"]])

    with open(pasta / "itens_pedidos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pedido_id", "item", "quantidade", "valor_unitario"])
        for p in pedidos:
            for c, q in p["itens"]:
                w.writerow([p["pedido_id"], c["app"], q, c["preco"]])

    with open(pasta / "gabarito.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tipo", "pedido_id", "chave", "causa"])
        w.writerows(gabarito)

    conjunto = "realista" if realista else "basico"
    print(f"[{conjunto}] {len(pedidos)} pedidos, {numero_nota - 1000} notas e "
          f"{len(gabarito)} divergências plantadas em {pasta}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta", nargs="?", type=Path, default=Path("dados"))
    ap.add_argument("semente", nargs="?", type=int, default=7)
    ap.add_argument("--realista", action="store_true", help="gera o conjunto realista (mais difícil)")
    args = ap.parse_args()
    main(args.pasta, args.semente, args.realista)
