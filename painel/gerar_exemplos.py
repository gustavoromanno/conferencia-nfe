"""Gera os dados de exemplo do painel (painel/exemplos.js) e os arquivos-modelo (modelos/).

Os exemplos vêm do mesmo gerador usado na avaliação, com a mesma semente, para o painel
mostrar exatamente o que o README mede. Uso: python painel/gerar_exemplos.py
"""
import csv
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import gerar_dados  # noqa: E402
from conferencia.leitura import ler_nota  # noqa: E402

SEMENTE = 7


def arquivos_do_conjunto(pasta: Path) -> list[dict]:
    arquivos = [{"nome": n, "conteudo": (pasta / n).read_text(encoding="utf-8")}
                for n in ("pedidos.csv", "itens_pedidos.csv", "gabarito.csv")]
    for xml in sorted((pasta / "notas").glob("*.xml")):
        arquivos.append({"nome": xml.name, "conteudo": xml.read_text(encoding="utf-8")})
    return arquivos


def recortar_csv(texto: str, manter) -> str:
    linhas = list(csv.reader(io.StringIO(texto)))
    saida = io.StringIO()
    w = csv.writer(saida, lineterminator="\n")
    w.writerow(linhas[0])
    w.writerows(l for l in linhas[1:] if manter(l))
    return saida.getvalue()


def gerar_modelos(pasta: Path, destino: Path) -> None:
    """Mini-conjunto coerente tirado do realista: os 4 primeiros pedidos, seus itens, suas notas,
    o gabarito só desses pedidos e um evento de cancelamento como referência de formato."""
    if destino.exists():
        shutil.rmtree(destino)
    destino.mkdir()
    pedidos = (pasta / "pedidos.csv").read_text(encoding="utf-8")
    ids = {l[0] for l in list(csv.reader(io.StringIO(pedidos)))[1:5]}
    for nome in ("pedidos.csv", "itens_pedidos.csv"):
        texto = (pasta / nome).read_text(encoding="utf-8")
        (destino / nome).write_text(recortar_csv(texto, lambda l: l[0] in ids), encoding="utf-8")
    gabarito = (pasta / "gabarito.csv").read_text(encoding="utf-8")
    (destino / "gabarito.csv").write_text(recortar_csv(gabarito, lambda l: l[1] in ids), encoding="utf-8")
    for xml in sorted((pasta / "notas").glob("nfce_*.xml")):
        if ler_nota(xml).pedido_id in ids:
            shutil.copy(xml, destino / xml.name)
    evento = next(iter(sorted((pasta / "notas").glob("*procEventoNFe.xml"))))
    shutil.copy(evento, destino / "evento_cancelamento_exemplo.xml")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        gerar_dados.main(tmp / "basico", SEMENTE, realista=False)
        gerar_dados.main(tmp / "realista", SEMENTE, realista=True)
        exemplos = {
            "realista": {"rotulo": "Exemplo realista", "semente": SEMENTE,
                         "arquivos": arquivos_do_conjunto(tmp / "realista")},
            "basico": {"rotulo": "Exemplo básico", "semente": SEMENTE,
                       "arquivos": arquivos_do_conjunto(tmp / "basico")},
        }
        gerar_modelos(tmp / "realista", RAIZ / "modelos")

    modelos = [{"nome": p.name, "conteudo": p.read_text(encoding="utf-8")}
               for p in sorted((RAIZ / "modelos").iterdir()) if p.suffix in {".csv", ".xml"}]
    js = ("// Gerado por painel/gerar_exemplos.py. Não edite à mão.\n"
          f"window.EXEMPLOS = {json.dumps(exemplos, ensure_ascii=False)};\n"
          f"window.MODELOS = {json.dumps(modelos, ensure_ascii=False)};\n")
    (RAIZ / "painel" / "exemplos.js").write_text(js, encoding="utf-8")
    print(f"painel/exemplos.js: {len(js) // 1024} KB; modelos/: {len(modelos)} arquivos")


if __name__ == "__main__":
    main()
