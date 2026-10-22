#!/usr/bin/env python3
"""Transforma uma pasta de fotos de um objeto (exaustor, comedouro, silo...) em item 3D.

Usa o Meshroom (AliceVision), que e gratuito e roda na GTX 1650 (CUDA). Depois chama o
preparar_item.py para por em escala, fechar e salvar na biblioteca.

Como fotografar (o resultado depende 90 % disso):
  - 40 a 150 fotos, dando a volta completa no objeto em 2 ou 3 alturas diferentes;
  - cada foto deve ter ~70 % de area em comum com a anterior (passos pequenos);
  - luz uniforme (dia nublado ou sombra), sem flash, sem contra-luz;
  - objeto parado, nada se mexendo no fundo; foco nitido; nao use zoom;
  - superficies brilhantes/lisas (chapa galvanizada) reconstroem mal: um po fosco ou fita
    crepe em alguns pontos ajuda;
  - MECA UMA MEDIDA com trena (ex.: largura da moldura): as fotos nao tem escala.

Uso (no Ubuntu/WSL ou no proprio Windows):
  python3 fotos_para_3d.py /mnt/c/Users/<voce>/Pictures/exaustor --nome exaustor_50 --medida largura=1.38
  python3 fotos_para_3d.py fotos/silo --nome silo --medida altura=6.2 --rapido   # sem CUDA, mais grosseiro

Onde o Meshroom esta: detectado em C:\\Meshroom*, C:\\Program Files\\Meshroom* ou na variavel
MESHROOM; ou informe --meshroom "/mnt/c/Meshroom-2023.3.0/meshroom_batch.exe".
Download: https://github.com/alicevision/Meshroom/releases (zip, nao precisa instalar).

Alternativa sem Meshroom: apps de celular (RealityScan, Polycam, KIRI Engine) geram o modelo
das fotos; exporte em OBJ e rode so o preparar_item.py.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys

import preparar_item

AQUI = os.path.dirname(os.path.abspath(__file__))
EXTENSOES = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".dng")


def achar_meshroom(informado):
    candidatos = [informado, os.environ.get("MESHROOM")]
    for raiz in ("/mnt/c", "C:/", "/mnt/c/Program Files", "C:/Program Files", os.path.expanduser("~")):
        candidatos += sorted(glob.glob(os.path.join(raiz, "Meshroom*", "meshroom_batch*")), reverse=True)
    candidatos.append(shutil.which("meshroom_batch"))
    for c in candidatos:
        if c and os.path.isfile(c):
            return c
    return None


def caminho_para(meshroom, caminho):
    """Caminho no formato que o Meshroom entende (Windows, se ele for .exe chamado do WSL)."""
    caminho = os.path.abspath(caminho)
    if meshroom.lower().endswith(".exe") and caminho.startswith("/") and shutil.which("wslpath"):
        return subprocess.check_output(["wslpath", "-w", caminho], text=True).strip()
    return caminho


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fotos", help="pasta com as fotos do objeto")
    ap.add_argument("--nome", required=True, help="nome do item na biblioteca")
    ap.add_argument("--medida", help="medida real feita com trena, ex.: largura=1.38")
    ap.add_argument("--vertical", default="auto", choices=["auto", "x", "y", "z", "-x", "-y", "-z"])
    ap.add_argument("--meshroom", help="caminho do meshroom_batch(.exe)")
    ap.add_argument("--rapido", action="store_true",
                    help="pipeline 'draft' do Meshroom: funciona sem placa NVIDIA, menos detalhe")
    args = ap.parse_args()

    fotos = [f for f in os.listdir(args.fotos) if f.lower().endswith(EXTENSOES)]
    if len(fotos) < 20:
        sys.exit(f"So {len(fotos)} fotos em {args.fotos}. Tire pelo menos 40, dando a volta no objeto.")
    if not args.medida:
        print("AVISO: sem --medida o item fica em escala arbitraria. Meca algo com trena!")

    meshroom = achar_meshroom(args.meshroom)
    if not meshroom:
        sys.exit("Meshroom nao encontrado. Baixe em https://github.com/alicevision/Meshroom/releases, "
                 "descompacte em C:\\ e rode de novo (ou use --meshroom <caminho>).")

    trabalho = os.path.join(AQUI, "fotogrametria", args.nome)
    saida = os.path.join(trabalho, "saida")
    os.makedirs(saida, exist_ok=True)
    cmd = [meshroom, "--input", caminho_para(meshroom, args.fotos),
           "--output", caminho_para(meshroom, saida),
           "--cache", caminho_para(meshroom, os.path.join(trabalho, "cache"))]
    if args.rapido:
        cmd += ["--pipeline", "photogrammetryDraft"]
    print(f"Reconstruindo {len(fotos)} fotos com o Meshroom (pode levar de 20 min a algumas horas)...")
    print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
    with open(os.path.join(trabalho, "meshroom.log"), "w") as log:
        r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        sys.exit(f"Meshroom falhou (codigo {r.returncode}); veja {os.path.join(trabalho, 'meshroom.log')}")

    malhas = sorted(glob.glob(os.path.join(saida, "**", "*.obj"), recursive=True), key=os.path.getsize)
    if not malhas:
        sys.exit(f"O Meshroom terminou sem gerar malha; veja {os.path.join(trabalho, 'meshroom.log')}")
    print(f"Malha gerada: {malhas[-1]}")
    ficha = preparar_item.preparar(malhas[-1], args.nome, args.medida, vertical=args.vertical)
    d = ficha["dimensoes_m"]
    print(f"Item '{args.nome}' na biblioteca: {d[0]:.2f} x {d[1]:.2f} x {d[2]:.2f} m. "
          f"Confira biblioteca/{args.nome}.png (se estiver deitado, rode preparar_item.py com outro --vertical).")


if __name__ == "__main__":
    main()
