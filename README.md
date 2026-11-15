# Conferência de notas fiscais para restaurantes

[![testes](https://github.com/gustavoromanno/conferencia-nfe/actions/workflows/testes.yml/badge.svg)](https://github.com/gustavoromanno/conferencia-nfe/actions/workflows/testes.yml)

Agente que cruza os **pedidos de delivery** de um restaurante com os **XMLs das notas fiscais (NFC-e)** emitidas, encontra o que não bate e explica cada problema em linguagem simples, com prioridade e próximo passo.

> Todos os dados são **fictícios**, gerados por `gerar_dados.py`.

## O problema

O restaurante precisa emitir nota de cada venda. Conferir pedido por pedido se toda venda tem nota, com o valor certo e sem duplicidade, é trabalho manual. Quando um erro passa, vira problema com o fisco ou com o contador.

## Como funciona

```
pedidos.csv ─┐
             ├─► cruzamento.py ─► divergências + fatos ─► explicacao.py ─► relatório HTML
notas/*.xml ─┘    (regras em código)   (números calculados)   (Claude ou regras)
```

1. **Leitura** (`leitura.py`): lê o CSV de pedidos (e dos itens) e os XMLs no layout da NF-e 4.00: chave de acesso, itens (`det/prod`), valores do `ICMSTot`, situação no `protNFe` e número do pedido no `infCpl`, escrito de vários jeitos ("Ped. 48101", "#48101", "PEDIDO Nº 48101"). Também lê os **eventos de cancelamento** (`procEventoNFe`), que a SEFAZ devolve em arquivo separado, e conta o mesmo XML baixado duas vezes como uma nota só.
2. **Cruzamento** (`cruzamento.py`): regras determinísticas que encontram 7 tipos de divergência:

   | Tipo | Quando |
   |---|---|
   | `PEDIDO_SEM_NOTA` | pedido concluído sem nota autorizada |
   | `NOTA_CANCELADA` | a única nota do pedido está cancelada |
   | `VALOR_DIVERGENTE` | valor da nota ≠ valor pago (a partir de R$ 0,01) |
   | `NOTA_DUPLICADA` | duas ou mais notas autorizadas para o mesmo pedido |
   | `NOTA_SEM_PEDIDO` | nota autorizada que não aponta para nenhum pedido |
   | `NOTA_PEDIDO_CANCELADO` | pedido cancelado com nota ainda autorizada |
   | `CHAVE_INVALIDA` | dígito verificador da chave (módulo 11) não confere |

3. **Explicação** (`explicacao.py`): para cada divergência, o Claude devolve **causa provável, prioridade, explicação e ação**, em saída estruturada validada por Pydantic. Sem chave de API, um modo por regras gera a mesma estrutura.

### Onde a IA entra, e onde não entra

A IA **não decide** se existe divergência: isso é regra fiscal e precisa ser exato, então fica no código e tem testes. A IA entra onde texto e julgamento ajudam: explicar o problema para quem não é contador, sugerir a causa a partir dos números e dizer o que fazer.

Proteções:
- os números vão prontos para a IA, e o prompt proíbe inventar valores;
- uma única chamada para todas as divergências, com `effort: low` (tarefa simples, custo baixo);
- se a IA recusar, falhar ou pular alguma divergência, o código completa com as regras: o relatório nunca fica incompleto.

## Avaliação

`gerar_dados.py` planta erros conhecidos e grava o gabarito. `avaliar.py` mede:
- **detecção**: recall e precisão por tipo de divergência;
- **explicação**: em quantas divergências encontradas a causa provável bate com a causa plantada, com o acerto por causa e a lista de cada erro.

São dois conjuntos de dados fictícios:

| | Básico | Realista |
|---|---|---|
| Pedidos / notas | 120 / ~122 | 116 / ~118 (+ eventos) |
| Divergências plantadas | 21 | 33 |
| Número do pedido na nota | sempre "Pedido #48101" | 6 formatos, misturados ao texto de tributos aproximados (IBPT) |
| Cancelamento | `cStat 101` no próprio XML | evento separado (`procEventoNFe`), inclusive cancelamento **rejeitado** por prazo |
| Itens na nota | sim | sim, com desconto rateado entre os itens |
| Erros novos | — | arredondamento no rateio, item lançado duas vezes, item faltando, preço desatualizado no emissor, nota sem desconto e sem taxa, número do pedido errado ou ausente |
| Armadilhas (não são erro) | nota cancelada e substituída; pedido e nota cancelados | as do básico + o mesmo XML baixado duas vezes + diferença que coincide com o desconto, mas é um item a mais |

### O que o conjunto realista revelou

Rodei o código **antes de qualquer correção** no conjunto realista:

- o programa **quebrava** ao encontrar um XML de evento de cancelamento;
- sem os eventos, a detecção caía para **recall 36% e precisão 6%**: 195 alarmes para 33 problemas reais, porque a leitura só entendia o formato "Pedido #48101".

Corrigi a **leitura** (formatos do número do pedido, eventos da SEFAZ, XML repetido) e não mudei as regras de detecção. Depois da correção, nas sementes 1 a 5 de cada conjunto:

| | Básico | Realista |
|---|---|---|
| Detecção (recall) | 100% | 100% |
| Detecção (precisão) | 100% | 100% |
| Causa provável pelas **regras** | 21/21 | **17/33** |
| Causa provável pela **IA** | *pendente* | *pendente* |

### Onde as regras erram (de propósito)

As regras que sugerem a causa foram **congeladas** na versão do conjunto básico: comparam a diferença com o desconto e com a taxa de entrega, e só. Não acrescentei uma regra para cada erro novo, porque o objetivo do conjunto realista é medir o que acontece com um caso que ninguém previu. Na semente 1, as regras erram em 16 de 33:

| Causa real | Regras | Por quê |
|---|---|---|
| Número do pedido errado ou ausente na nota | 0/4 | viram duas divergências soltas (nota sem pedido e pedido sem nota); ligar as duas exige olhar valor e horário |
| Item lançado duas vezes | 0/3 | numa delas, o item custa exatamente o valor do desconto, e a regra conclui "desconto fora da nota" |
| Preço desatualizado no emissor | 0/2 | numa delas, a diferença coincide com a taxa de entrega |
| Item faltando, arredondamento, desconto e taxa juntos | 0/6 | a regra responde "outra" |
| Cancelamento rejeitado pela SEFAZ | 0/1 | a regra não olha os eventos |

Parte disso daria para resolver com mais regras (desconto e taxa juntos, arredondamento de 1 centavo). A outra parte pede investigação: abrir os itens da nota e do pedido, que usam nomes diferentes ("Coca-Cola 2L" no app, "REFRIG COCA COLA 2L" no emissor), ou cruzar divergências entre si. É aí que a IA precisa provar que vale o custo, e é o que a próxima etapa mede.

**Limites, com honestidade:** os dois conjuntos são sintéticos e foram escritos por quem escreveu as regras. O conjunto realista tem casos que as regras de causa não foram ajustadas para ver, mas ainda é um gerador meu. O próximo passo é testar com XMLs reais anonimizados.

## Como rodar

```bash
pip install -r requirements.txt
python gerar_dados.py dados                 # conjunto básico
python gerar_dados.py dados 7 --realista    # conjunto realista (mais difícil)
python conferir.py --dados dados            # explicações por regras
python avaliar.py                           # mede contra o gabarito
python -m pytest                            # testes

# com o Claude
export ANTHROPIC_API_KEY=...
python conferir.py --dados dados --ia        # mostra tokens, custo e tempo
python avaliar.py
```

O relatório fica em `saida/relatorio.html`.

## Simplificações

- XML reduzido aos campos usados na conferência, no namespace oficial da NF-e.
- No conjunto básico, o cancelamento é o `cStat 101` no próprio arquivo; no realista, vem como evento separado, como na SEFAZ.
- O número do pedido é lido do campo de informações complementares (`infCpl`).

## Como foi construído

Desenvolvi este projeto em par com o **Claude** (Anthropic), usando o **Claude Code**.

- **O problema e as regras vêm da minha experiência.** No suporte do Omie ERP, resolvo divergências entre notas, SEFAZ e extratos bancários; antes, cuidei do faturamento de uma cooperativa. Os tipos de erro e as armadilhas do gerador de dados são situações que eu vejo na prática.
- **O Claude foi meu par de programação.** Com ele estruturei a arquitetura e escrevi o código, os testes e esta documentação.
- **O agente segue a mesma divisão de papéis.** O que precisa ser exato (as regras fiscais) fica no código, com testes. A IA entra onde explicar e priorizar ajuda quem não é contador.

Usar IA para construir software faz parte de como eu trabalho. O cuidado está em saber o que delegar e em medir o resultado.

## Stack

Python 3.13 · SDK da Anthropic (Claude, saída estruturada) · Pydantic · pytest
