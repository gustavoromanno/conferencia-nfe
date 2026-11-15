"""Compara a causa provável pelas regras e pela IA nos dois conjuntos, em várias sementes.

Para cada conjunto (básico e realista) e cada semente: gera os dados, confere, explica
pelas regras e pela IA e mede contra o gabarito. No fim, imprime a tabela do README.

Uso:
  python comparar.py                      # só regras (não precisa de chave)
  python comparar.py --ia                 # regras e IA (precisa de ANTHROPIC_API_KEY)
  python comparar.py --ia --sementes 1 2 3 --json comparacao.json
"""
import argparse
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import gerar_dados
from avaliar import avaliar
from conferencia.cruzamento import conferir
from conferencia.explicacao import MODELO, explicar
from conferencia.leitura import ler_notas, ler_pedidos

CONJUNTOS = {"basico": False, "realista": True}


def rodar(dados: Path, saida: Path, usar_ia: bool) -> dict:
    divergencias = conferir(ler_pedidos(dados / "pedidos.csv"), ler_notas(dados / "notas"))
    explicacoes, origem, uso = explicar(divergencias, usar_ia=usar_ia)
    if usar_ia and not origem.startswith("IA"):
        raise SystemExit(f"A IA não respondeu em {dados}: {origem}")
    saida.mkdir(parents=True, exist_ok=True)
    resultado = {"origem_explicacoes": origem, "uso": uso,
                 "divergencias": [asdict(d) for d in divergencias],
                 "explicacoes": [e.model_dump() for e in explicacoes]}
    (saida / "resultado.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=1,
                   default=lambda v: str(v) if isinstance(v, Decimal) else v), encoding="utf-8")
    return avaliar(dados, saida)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ia", action="store_true", help="também roda a IA")
    ap.add_argument("--sementes", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--pasta", type=Path, default=Path("saida_comparacao"))
    ap.add_argument("--json", type=Path, help="grava as métricas por semente neste arquivo")
    args = ap.parse_args()

    modos = ["regras", "ia"] if args.ia else ["regras"]
    linhas = []
    for nome, realista in CONJUNTOS.items():
        for semente in args.sementes:
            dados = args.pasta / f"dados_{nome}_{semente}"
            gerar_dados.main(dados, semente, realista)
            for modo in modos:
                m = rodar(dados, args.pasta / f"saida_{nome}_{semente}_{modo}", modo == "ia")
                linhas.append({"conjunto": nome, "semente": semente, "modo": modo, **m})
                uso = m["uso"] or {}
                extra = (f"  US$ {uso['custo_usd']:.4f}  {uso['segundos']:.1f} s"
                         if uso.get("custo_usd") is not None else "")
                print(f"{nome:<9} semente {semente}  {modo:<6} recall {m['recall']:.0%}  precisão {m['precisao']:.0%}"
                      f"  causa {m['causa_certa']}/{m['verdadeiros']}{extra}", flush=True)

    def total(conjunto, modo):
        ls = [l for l in linhas if l["conjunto"] == conjunto and l["modo"] == modo]
        return ls, sum(l["causa_certa"] for l in ls), sum(l["verdadeiros"] for l in ls)

    print(f"\nTabela ({len(args.sementes)} sementes, soma das divergências)\n")
    print("| | Básico | Realista |\n|---|---|---|")
    for modo, rotulo in [("regras", "regras"), ("ia", "IA")]:
        if modo not in modos:
            continue
        cel = []
        for conjunto in CONJUNTOS:
            _, certo, n = total(conjunto, modo)
            cel.append(f"{certo}/{n} ({certo / n:.0%})")
        print(f"| Causa provável pelas **{rotulo}** | {cel[0]} | {cel[1]} |")
    if args.ia:
        custos, tempos, tokens = [], [], []
        for conjunto in CONJUNTOS:
            ls, _, _ = total(conjunto, "ia")
            custos.append(sum(l["uso"]["custo_usd"] for l in ls) / len(ls))
            tempos.append(sum(l["uso"]["segundos"] for l in ls) / len(ls))
            tokens.append((sum(l["uso"]["tokens_entrada"] for l in ls) // len(ls),
                           sum(l["uso"]["tokens_saida"] for l in ls) // len(ls)))
        print(f"| Custo da IA por conferência ({MODELO}) | US$ {custos[0]:.3f} | US$ {custos[1]:.3f} |")
        print(f"| Tempo da IA por conferência | {tempos[0]:.0f} s | {tempos[1]:.0f} s |")
        print(f"| Tokens por conferência (entrada / saída) | {tokens[0][0]} / {tokens[0][1]} "
              f"| {tokens[1][0]} / {tokens[1][1]} |")

        print("\nOnde a IA errou a causa:")
        for l in linhas:
            if l["modo"] == "ia":
                for e in l["erros_causa"]:
                    print(f"  {l['conjunto']:<9} {l['semente']}  {e['tipo']:<22} esperado {e['esperado']:<34} "
                          f"respondeu {e['respondido']}")

    if args.json:
        args.json.write_text(json.dumps(linhas, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
