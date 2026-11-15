"""Explicação das divergências.

O código já decidiu O QUE está errado (cruzamento.py). Aqui a IA entra para dizer
POR QUE provavelmente aconteceu, quão urgente é e o que o dono do restaurante deve fazer,
em linguagem simples. Sem chave de API, um modo por regras gera a mesma estrutura.
"""
import json
import os
import time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from .modelos import TIPOS, Divergencia

MODELO = os.environ.get("CONFERENCIA_MODELO", "claude-opus-5-5")

# US$ por milhão de tokens (entrada, saída), tabela pública da Anthropic em nov/2026.
PRECOS = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


def medir_uso(usage, modelo: str, segundos: float) -> dict:
    """Tokens, custo estimado e tempo de uma chamada. Custo None se o modelo não está na tabela."""
    entrada, saida = usage.input_tokens, usage.output_tokens
    preco = PRECOS.get(modelo)
    custo = (entrada * preco[0] + saida * preco[1]) / 1_000_000 if preco else None
    return {"modelo": modelo, "tokens_entrada": entrada, "tokens_saida": saida,
            "custo_usd": custo, "segundos": round(segundos, 2)}

Causa = Literal[
    "desconto_fora_da_nota",
    "taxa_entrega_fora_da_nota",
    "nota_nao_emitida",
    "nota_cancelada_sem_substituta",
    "emissao_em_duplicidade",
    "nota_sem_vinculo_com_pedido",
    "pedido_cancelado_apos_emissao",
    "chave_digitada_ou_gerada_errada",
    # causas que só aparecem no conjunto realista; as regras não sabem identificá-las
    "desconto_e_taxa_fora_da_nota",
    "arredondamento_no_rateio",
    "item_lancado_em_duplicidade",
    "item_faltando_na_nota",
    "preco_desatualizado_no_emissor",
    "numero_do_pedido_errado_na_nota",
    "cancelamento_rejeitado_pela_sefaz",
    "outra",
]


class Explicacao(BaseModel):
    divergencia_id: str
    prioridade: Literal["alta", "media", "baixa"]
    causa_provavel: Causa
    explicacao: str
    acao: str


class Resposta(BaseModel):
    explicacoes: list[Explicacao]


INSTRUCOES = """Você ajuda donos de restaurante a entender problemas nas notas fiscais (NF-e/NFC-e) \
das vendas por aplicativo de delivery. Um sistema já cruzou pedidos e notas e encontrou as divergências \
abaixo; os números nos "fatos" estão corretos e foram calculados por código.

Para cada divergência:
- causa_provavel: a causa mais provável, usando os números. Em VALOR_DIVERGENTE, compare a diferença \
com o desconto e com a taxa de entrega antes de escolher. Depois compare os itens do pedido com os da \
nota: os nomes vêm de sistemas diferentes (app e emissor) e não são iguais, então pareie pelo sentido e \
pelo preço. Um produto do pedido repetido na nota ou com quantidade maior é \
"item_lancado_em_duplicidade"; um produto do pedido que não está na nota é "item_faltando_na_nota"; o \
mesmo produto com preço unitário diferente é "preco_desatualizado_no_emissor". A diferença pode \
coincidir com o desconto ou a taxa por acaso: se os itens mostram outra causa, fique com os itens. Use \
"outra" se nada disso explicar a diferença, inclusive quando a nota tem um produto que não existe no pedido.
  Em PEDIDO_SEM_NOTA e NOTA_SEM_PEDIDO, olhe as divergências em conjunto: um pedido sem nota e uma nota \
sem pedido com o mesmo valor e horários próximos (a nota sai pouco depois do pedido) são a mesma venda, \
cuja nota saiu com o número do pedido errado ou sem número. Nesse caso, use \
"numero_do_pedido_errado_na_nota" nas duas, inclusive quando a nota não traz número nenhum, e cite o par \
na explicação. Uma nota sem pedido que não forma par com nenhum pedido (por exemplo, venda de balcão ou \
de outro canal) é "nota_sem_vinculo_com_pedido", não "outra"; um pedido sem nota sem par é \
"nota_nao_emitida".
- prioridade: "alta" quando há risco fiscal (venda sem nota, nota a mais, valor errado), "media" quando \
afeta o controle mas não o imposto, "baixa" para o resto.
- explicacao: 1 ou 2 frases curtas, sem jargão, citando o pedido e os valores no formato R$ 1.234,56.
- acao: o próximo passo concreto (por exemplo, emitir nota complementar, cancelar a nota em duplicidade, \
falar com o contador).

Responda uma explicação para cada divergência, usando o mesmo divergencia_id. Não invente números."""


def _para_json(divergencias: list[Divergencia]) -> str:
    def conv(v):
        return str(v) if isinstance(v, Decimal) else v
    dados = [{"divergencia_id": d.id, "tipo": d.tipo, "descricao_tipo": TIPOS[d.tipo],
              "pedido_id": d.pedido_id, "chaves": d.chaves,
              "fatos": {k: conv(v) for k, v in d.fatos.items()}} for d in divergencias]
    return json.dumps(dados, ensure_ascii=False, indent=1, default=conv)


def brl(valor: Decimal) -> str:
    """Formata no padrão brasileiro: 1234.5 -> 'R$ 1.234,50'."""
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def explicar_por_regras(d: Divergencia) -> Explicacao:
    f = d.fatos
    pid = d.pedido_id or "sem número"
    if d.tipo == "VALOR_DIVERGENTE":
        dif = f["diferenca"]
        if dif == f["desconto_pedido"] and dif > 0:
            causa, txt = "desconto_fora_da_nota", f"A nota do pedido {pid} saiu {brl(dif)} acima do valor pago, exatamente o desconto dado ao cliente."
            acao = "Conferir com o contador como corrigir; o imposto foi calculado sobre um valor maior."
        elif -dif == f["taxa_entrega_pedido"] and dif < 0:
            causa, txt = "taxa_entrega_fora_da_nota", f"A nota do pedido {pid} ficou {brl(-dif)} abaixo do pago, o valor da taxa de entrega."
            acao = "Emitir nota complementar ou ajustar o emissor para incluir a taxa de entrega."
        else:
            causa, txt = "outra", f"A nota do pedido {pid} tem diferença de {brl(dif)} que não bate com desconto nem taxa."
            acao = "Abrir o pedido e a nota lado a lado e conferir os itens."
        return Explicacao(divergencia_id=d.id, prioridade="alta", causa_provavel=causa, explicacao=txt, acao=acao)

    tabela = {
        "PEDIDO_SEM_NOTA": ("alta", "nota_nao_emitida", f"O pedido {pid} foi entregue e não tem nota.", "Emitir a nota da venda."),
        "NOTA_CANCELADA": ("alta", "nota_cancelada_sem_substituta", f"A nota do pedido {pid} foi cancelada e nenhuma outra foi emitida.", "Emitir uma nova nota para o pedido."),
        "NOTA_DUPLICADA": ("alta", "emissao_em_duplicidade", f"O pedido {pid} tem {f.get('qtd_notas', 2)} notas autorizadas.", "Cancelar a nota em duplicidade dentro do prazo."),
        "NOTA_SEM_PEDIDO": ("media", "nota_sem_vinculo_com_pedido", "Existe uma nota autorizada que não aponta para nenhum pedido.", "Descobrir a que venda a nota se refere."),
        "NOTA_PEDIDO_CANCELADO": ("alta", "pedido_cancelado_apos_emissao", f"O pedido {pid} foi cancelado, mas a nota continua autorizada.", "Cancelar a nota."),
        "CHAVE_INVALIDA": ("media", "chave_digitada_ou_gerada_errada", "A chave de acesso desta nota tem o dígito verificador errado.", "Conferir o XML original no portal da SEFAZ."),
    }
    prio, causa, txt, acao = tabela[d.tipo]
    return Explicacao(divergencia_id=d.id, prioridade=prio, causa_provavel=causa, explicacao=txt, acao=acao)


def explicar_com_ia(divergencias: list[Divergencia]) -> tuple[list[Explicacao], str, dict | None]:
    """Uma única chamada ao Claude para todas as divergências. Volta às regras se algo falhar."""
    import anthropic

    def regras(motivo):
        return [explicar_por_regras(d) for d in divergencias], f"regras ({motivo})", None

    inicio = time.perf_counter()
    try:
        client = anthropic.Anthropic()
        resposta = client.messages.parse(
            model=MODELO,
            max_tokens=16000,
            output_config={"effort": "low"},
            system=INSTRUCOES,
            messages=[{"role": "user", "content": _para_json(divergencias)}],
            output_format=Resposta,
        )
    except TypeError as e:
        # A biblioteca levanta TypeError quando não encontra nenhuma credencial.
        if "authentication" not in str(e):
            raise
        return regras("nenhuma chave de API configurada")
    except anthropic.AuthenticationError:
        return regras("chave de API inválida")
    except anthropic.APIConnectionError as e:
        return regras(f"sem conexão com a API: {e}")
    except anthropic.RateLimitError:
        return regras("limite de uso da API")
    except anthropic.APIStatusError as e:
        return regras(f"erro {e.status_code} da API")
    uso = medir_uso(resposta.usage, MODELO, time.perf_counter() - inicio)

    if resposta.stop_reason == "refusal" or resposta.parsed_output is None:
        final, origem, _ = regras("a IA não respondeu")
        return final, origem, uso

    recebidas = {e.divergencia_id: e for e in resposta.parsed_output.explicacoes}
    # Garante uma explicação por divergência, mesmo que a IA pule alguma.
    final = [recebidas.get(d.id) or explicar_por_regras(d) for d in divergencias]
    faltaram = sum(1 for d in divergencias if d.id not in recebidas)
    origem = f"IA ({MODELO})" + (f", {faltaram} completadas por regras" if faltaram else "")
    return final, origem, uso


def explicar(divergencias: list[Divergencia], usar_ia: bool) -> tuple[list[Explicacao], str, dict | None]:
    """Devolve (explicações, origem, uso). `uso` traz tokens, custo e tempo quando a IA foi chamada."""
    if not divergencias:
        return [], "nenhuma divergência", None
    if usar_ia:
        return explicar_com_ia(divergencias)
    return [explicar_por_regras(d) for d in divergencias], "regras", None
