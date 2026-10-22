#!/usr/bin/env python3
"""Prepara um objeto 3D (de fotos, SketchUp, Blender, celular...) para a biblioteca de itens.

O que faz:
  1. le a malha (STL, OBJ ou PLY);
  2. coloca em pe (eixo vertical escolhido), apoia no chao (z = 0) e centraliza em x/y;
  3. poe na escala real a partir de UMA medida feita com trena (fotos nao tem escala);
  4. fecha buracos e o fundo (scans nunca pegam a parte de baixo), gerando um solido
     estanque que a malha da simulacao aceita;
  5. salva em biblioteca/<nome>.stl, com uma ficha .json e uma figura de conferencia.

Uso:
  python3 preparar_item.py exaustor_scan.obj --nome exaustor_50 --medida largura=1.38
  python3 preparar_item.py silo.stl --nome silo --escala 0.001          # modelo em mm
  python3 preparar_item.py comedouro.ply --nome comedouro --vertical y --medida comprimento=2.0

--medida aceita: largura (x), profundidade (y), altura (z), comprimento ou maior (maior lado).
"""
import argparse
import json
import os

import numpy as np

import geometria

AQUI = os.path.dirname(os.path.abspath(__file__))
BIBLIOTECA = os.path.join(AQUI, "biblioteca")


def por_em_pe(tris, vertical):
    v = tris.reshape(-1, 3)
    if vertical == "auto":
        # objeto de fotos costuma vir com Y para cima (Meshroom, celular)
        vertical = "y"
    sinal = -1 if vertical.startswith("-") else 1
    eixo = vertical[-1]
    if eixo == "y":
        v = np.stack([v[:, 0], -sinal * v[:, 2], sinal * v[:, 1]], axis=1)
    elif eixo == "x":
        v = np.stack([-sinal * v[:, 2], v[:, 1], sinal * v[:, 0]], axis=1)
    elif sinal < 0:
        v = np.stack([v[:, 0], -v[:, 1], -v[:, 2]], axis=1)
    return v.reshape(-1, 3, 3)


def alinhar_planta(tris):
    """Gira em torno de z para o maior lado ficar em x (menor caixa envolvente)."""
    xy = tris.reshape(-1, 3)[:, :2]
    xy = xy - xy.mean(axis=0)
    melhor = min(((np.ptp(xy @ [np.cos(a), np.sin(a)]) * np.ptp(xy @ [-np.sin(a), np.cos(a)]), a)
                  for a in np.radians(np.arange(0, 90, 1.0))))[1]
    tris = geometria.transformar(tris, rotacao_graus=(0, 0, -np.degrees(melhor)))
    vmin, vmax = geometria.limites(tris)
    if vmax[1] - vmin[1] > vmax[0] - vmin[0]:
        tris = geometria.transformar(tris, rotacao_graus=(0, 0, 90))
    return tris


def apoiar(tris):
    vmin, vmax = geometria.limites(tris)
    centro = np.array([(vmin[0] + vmax[0]) / 2, (vmin[1] + vmax[1]) / 2, vmin[2]])
    return tris - centro


def remover_soltos(tris, voxel):
    """Remove pedacos pequenos soltos (chao, sujeira) mantendo o maior conjunto conectado."""
    centros = tris.mean(axis=1)
    chave = np.floor(centros / (2 * voxel)).astype(np.int64)
    celulas, inv = np.unique(chave, axis=0, return_inverse=True)
    idx = {tuple(c): i for i, c in enumerate(celulas)}
    rotulo = -np.ones(len(celulas), dtype=int)
    atual = 0
    for i0 in range(len(celulas)):
        if rotulo[i0] >= 0:
            continue
        rotulo[i0] = atual
        pilha = [i0]
        while pilha:
            c = celulas[pilha.pop()]
            for d in np.ndindex(3, 3, 3):
                j = idx.get((c[0] + d[0] - 1, c[1] + d[1] - 1, c[2] + d[2] - 1))
                if j is not None and rotulo[j] < 0:
                    rotulo[j] = atual
                    pilha.append(j)
        atual += 1
    maior = np.bincount(rotulo[inv.ravel()]).argmax()
    return tris[rotulo[inv.ravel()] == maior]


def figura(caminho, tris, titulo):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    v = tris.reshape(-1, 3)
    fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
    for ax, (i, j, nome) in zip(axs, ((0, 1, "planta (x, y)"), (0, 2, "frente (x, z)"), (1, 2, "lado (y, z)"))):
        ax.plot(v[:, i], v[:, j], ",", color="0.25")
        ax.set_aspect("equal")
        ax.set_title(nome)
        ax.grid(alpha=0.3)
    fig.suptitle(titulo)
    fig.tight_layout()
    fig.savefig(caminho, dpi=100)
    plt.close(fig)


def preparar(entrada, nome, medida=None, escala=None, vertical="auto", voxel=None, fechar=True,
             alinhar=True, limpar=True):
    tris = geometria.ler_malha(entrada)
    tris = por_em_pe(tris, vertical)
    if limpar:  # antes de medir: sujeira solta distorce o tamanho
        vmin, vmax = geometria.limites(tris)
        tris = remover_soltos(tris, float((vmax - vmin).max()) / 80)
    if alinhar:
        tris = alinhar_planta(tris)
    if escala:
        tris = tris * escala
    if medida:
        chave, valor = medida.split("=")
        vmin, vmax = geometria.limites(tris)
        tam = vmax - vmin
        atual = {"largura": tam[0], "comprimento": tam[0], "profundidade": tam[1], "altura": tam[2],
                 "maior": tam.max()}[chave.strip().lower()]
        tris = tris * (float(valor.replace(",", ".")) / atual)
    vmin, vmax = geometria.limites(tris)
    voxel = voxel or max(0.01, float((vmax - vmin).max()) / 80)
    tris = apoiar(tris)
    if fechar:
        antes = np.subtract(*geometria.limites(tris)[::-1])
        tris = apoiar(geometria.fechar_por_voxels(tris, voxel))
        # o fechamento por voxels engorda o objeto ~1 voxel por lado: volta as medidas originais
        depois = np.subtract(*geometria.limites(tris)[::-1])
        tris = tris * (antes / depois)

    os.makedirs(BIBLIOTECA, exist_ok=True)
    stl = os.path.join(BIBLIOTECA, nome + ".stl")
    geometria.escrever_stl(stl, tris, nome)
    vmin, vmax = geometria.limites(tris)
    tam = vmax - vmin
    ficha = {"nome": nome, "arquivo": os.path.relpath(stl, AQUI), "origem": os.path.abspath(entrada),
             "dimensoes_m": [round(float(t), 3) for t in tam], "voxel_m": round(voxel, 4),
             "triangulos": int(len(tris))}
    with open(os.path.join(BIBLIOTECA, nome + ".json"), "w", encoding="utf-8") as f:
        json.dump(ficha, f, indent=2, ensure_ascii=False)
    figura(os.path.join(BIBLIOTECA, nome + ".png"), tris,
           f"{nome}: {tam[0]:.2f} x {tam[1]:.2f} x {tam[2]:.2f} m (largura x profundidade x altura)")
    return ficha


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", help="malha .stl/.obj/.ply")
    ap.add_argument("--nome", required=True, help="nome do item na biblioteca (sem espacos)")
    ap.add_argument("--medida", help="uma medida real, ex.: largura=1.38 ou altura=1.5 (em metros)")
    ap.add_argument("--escala", type=float, help="fator de escala fixo (ex.: 0.001 para mm -> m)")
    ap.add_argument("--vertical", default="auto", choices=["auto", "x", "y", "z", "-x", "-y", "-z"],
                    help="eixo que aponta para cima no arquivo (fotos: normalmente y)")
    ap.add_argument("--voxel", type=float, help="detalhe minimo em m (padrao: maior lado / 80)")
    ap.add_argument("--sem-fechar", action="store_true", help="nao fechar (malha ja e solida)")
    ap.add_argument("--sem-alinhar", action="store_true", help="nao girar o maior lado para x")
    args = ap.parse_args()
    ficha = preparar(args.entrada, args.nome, args.medida, args.escala, args.vertical, args.voxel,
                     not args.sem_fechar, not args.sem_alinhar)
    d = ficha["dimensoes_m"]
    print(f"Item '{ficha['nome']}' salvo em {ficha['arquivo']}")
    print(f"  dimensoes: {d[0]:.2f} x {d[1]:.2f} x {d[2]:.2f} m (largura x profundidade x altura)")
    print(f"  confira a figura biblioteca/{ficha['nome']}.png; se estiver deitado, use --vertical z (ou -y, x...)")


if __name__ == "__main__":
    main()
