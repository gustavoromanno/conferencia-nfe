"""Mede o conferidor contra o gabarito.

1. Detecção (código): das divergências plantadas, quantas foram encontradas (recall)
   e quantas das encontradas eram reais (precisão).
2. Explicação (IA ou regras): para as divergências encontradas, quantas causas prováveis
   batem com a causa real plantada. Mostra o acerto por causa e lista cada erro.

Uso: python avaliar.py --dados dados --saida saida [--json metricas.json]
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

POR_CHAVE = {"CHAVE_INVALIDA", "NOTA_SEM_PEDIDO"}   # tipos identificados pela chave, não pelo pedido


def identificador(tipo: str, pedido_id: str | None, chave: str | None) -> tuple:
    return (tipo, chave) if tipo in POR_CHAVE else (tipo, pedido_id or "")


def avaliar(dados: Path, saida: Path) -> dict:
    with open(dados / "gabarito.csv", encoding="utf-8") as f:
        gabarito = {identificador(l["tipo"], l["pedido_id"], l["chave"]): l["causa"] for l in csv.DictReader(f)}

    resultado = json.loads((saida / "resultado.json").read_text(encoding="utf-8"))
    causas = {e["divergencia_id"]: e["causa_provavel"] for e in resultado["explicacoes"]}
    encontrados = {}
    for d in resultado["divergencias"]:
        encontrados[identificador(d["tipo"], d["pedido_id"], d["chaves"][0] if d["chaves"] else None)] = causas.get(d["id"])

    por_tipo = defaultdict(lambda: {"plantadas": 0, "achadas": 0, "falsos": 0})
    por_causa = defaultdict(lambda: {"total": 0, "acertos": 0})
    for ident, causa in gabarito.items():
        por_tipo[ident[0]]["plantadas"] += 1
        if ident in encontrados:
            por_tipo[ident[0]]["achadas"] += 1
            por_causa[causa]["total"] += 1
            por_causa[causa]["acertos"] += encontrados[ident] == causa
    falsos_positivos = [i for i in encontrados if i not in gabarito]
    for ident in falsos_positivos:
        por_tipo[ident[0]]["falsos"] += 1

    certas = [i for i in gabarito if i in encontrados]
    erros_causa = [{"tipo": i[0], "id": i[1], "esperado": gabarito[i], "respondido": encontrados[i]}
                   for i in certas if encontrados[i] != gabarito[i]]
    vp, fp = len(certas), len(falsos_positivos)
    return {
        "origem_explicacoes": resultado["origem_explicacoes"],
        "uso": resultado.get("uso"),
        "plantadas": len(gabarito),
        "recall": vp / len(gabarito) if gabarito else 1.0,
        "precisao": vp / (vp + fp) if vp + fp else 1.0,
        "verdadeiros": vp,
        "falsos_positivos": fp,
        "causa_certa": vp - len(erros_causa),
        "por_tipo": dict(por_tipo),
        "por_causa": dict(por_causa),
        "erros_causa": erros_causa,
        "nao_encontradas": [list(i) for i in gabarito if i not in encontrados],
    }


def imprimir(m: dict) -> None:
    print(f"Explicações avaliadas: {m['origem_explicacoes']}\n")
    print(f"{'Tipo':<24}{'Plantadas':>10}{'Achadas':>9}{'Falsos +':>10}")
    for tipo, v in sorted(m["por_tipo"].items()):
        print(f"{tipo:<24}{v['plantadas']:>10}{v['achadas']:>9}{v['falsos']:>10}")

    print(f"\n{'Causa plantada':<36}{'Acertos':>10}")
    for causa, v in sorted(m["por_causa"].items()):
        print(f"{causa:<36}{v['acertos']:>6}/{v['total']}")

    vp = m["verdadeiros"]
    print(f"\nDetecção  → recall {m['recall']:.0%} ({vp}/{m['plantadas']}), "
          f"precisão {m['precisao']:.0%} ({vp}/{vp + m['falsos_positivos']})")
    if vp:
        print(f"Explicação → causa certa em {m['causa_certa']}/{vp} ({m['causa_certa'] / vp:.0%})")
    if m.get("uso"):
        u = m["uso"]
        custo = f"US$ {u['custo_usd']:.4f}" if u.get("custo_usd") is not None else "custo desconhecido"
        print(f"Custo      → {u['tokens_entrada']} tokens de entrada, {u['tokens_saida']} de saída, "
              f"{custo}, {u['segundos']:.1f} s")
    if m["erros_causa"]:
        print("\nOnde a causa errou:")
        for e in m["erros_causa"]:
            print(f"  {e['tipo']:<22} {e['id'][:20]:<21} esperado {e['esperado']:<34} respondeu {e['respondido']}")
    if m["nao_encontradas"]:
        print("\nNão encontradas:", m["nao_encontradas"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", type=Path, default=Path("dados"))
    ap.add_argument("--saida", type=Path, default=Path("saida"))
    ap.add_argument("--json", type=Path, help="grava as métricas neste arquivo")
    args = ap.parse_args()
    metricas = avaliar(args.dados, args.saida)
    imprimir(metricas)
    if args.json:
        args.json.write_text(json.dumps(metricas, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
