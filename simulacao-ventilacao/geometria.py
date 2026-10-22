"""Funcoes de geometria compartilhadas: leitura/escrita de malhas, transformacoes e fechamento.

Malhas sao representadas como array numpy (n, 3, 3): n triangulos x 3 vertices x (x, y, z).
"""
import os
import struct

import numpy as np


# --------------------------------------------------------------------------- leitura

def ler_stl(caminho):
    with open(caminho, "rb") as f:
        dados = f.read()
    if dados[:5] == b"solid" and b"facet" in dados[:2000]:
        vs = [linha.split()[1:4] for linha in dados.split(b"\n") if linha.strip().startswith(b"vertex")]
        return np.array(vs, dtype=np.float64).reshape(-1, 3, 3)
    n = struct.unpack("<I", dados[80:84])[0]
    reg = np.frombuffer(dados, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                        count=n, offset=84)
    return reg["v"].astype(np.float64)


def ler_obj(caminho):
    vs, faces = [], []
    with open(caminho, "rb") as f:
        for linha in f:
            if linha[:2] == b"v ":
                vs.append(linha.split()[1:4])
            elif linha[:2] == b"f ":
                idx = [int(p.split(b"/")[0]) for p in linha.split()[1:]]
                for k in range(1, len(idx) - 1):  # poligonos viram leque de triangulos
                    faces.append((idx[0], idx[k], idx[k + 1]))
    v = np.array(vs, dtype=np.float64)
    f = np.array(faces, dtype=np.int64)
    f = np.where(f < 0, f + len(v), f - 1)  # OBJ comeca em 1; negativos sao relativos
    return v[f]


def ler_ply(caminho):
    with open(caminho, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError(f"nao e PLY: {caminho}")
        formato, elementos = None, []
        while True:
            partes = f.readline().decode("ascii", "ignore").split()
            if not partes:
                continue
            if partes[0] == "format":
                formato = partes[1]
            elif partes[0] == "element":
                elementos.append([partes[1], int(partes[2]), []])
            elif partes[0] == "property":
                elementos[-1][2].append(partes[1:])
            elif partes[0] == "end_header":
                break
        tipos = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
                 "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
                 "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}
        ordem = "<" if formato == "binary_little_endian" else ">"
        verts, faces = None, []
        for nome, n, props in elementos:
            if nome == "vertex":
                nomes = [p[1] for p in props]
                if formato == "ascii":
                    d = np.array([f.readline().split() for _ in range(n)], dtype=np.float64)
                    verts = d[:, [nomes.index(c) for c in "xyz"]]
                else:
                    dt = np.dtype([(p[1], ordem + tipos[p[0]]) for p in props])
                    d = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
                    verts = np.stack([d[c].astype(np.float64) for c in "xyz"], axis=1)
            elif nome == "face":
                lista = props[0]  # property list <tipo contagem> <tipo indice> vertex_indices
                tc, ti = ordem + tipos[lista[1]], ordem + tipos[lista[2]]
                for _ in range(n):
                    if formato == "ascii":
                        p = [int(x) for x in f.readline().split()]
                        idx = p[1:1 + p[0]]
                    else:
                        k = int(np.frombuffer(f.read(np.dtype(tc).itemsize), dtype=tc)[0])
                        idx = np.frombuffer(f.read(k * np.dtype(ti).itemsize), dtype=ti).tolist()
                    for j in range(1, len(idx) - 1):
                        faces.append((idx[0], idx[j], idx[j + 1]))
            else:
                break  # elementos depois das faces nao interessam
    if not faces:
        raise ValueError("PLY sem faces (nuvem de pontos): gere a malha antes")
    return verts[np.array(faces)]


def ler_malha(caminho):
    ext = os.path.splitext(caminho)[1].lower()
    leitor = {".stl": ler_stl, ".obj": ler_obj, ".ply": ler_ply}.get(ext)
    if not leitor:
        raise ValueError(f"formato nao suportado: {ext} (use STL, OBJ ou PLY)")
    return leitor(caminho)


def escrever_stl(caminho, tris, nome="solido"):
    with open(caminho, "w") as f:
        f.write(f"solid {nome}\n")
        for t in tris:
            f.write(" facet normal 0 0 0\n  outer loop\n")
            for p in t:
                f.write(f"   vertex {p[0]:.5f} {p[1]:.5f} {p[2]:.5f}\n")
            f.write("  endloop\n endfacet\n")
        f.write(f"endsolid {nome}\n")


def limites(tris):
    v = tris.reshape(-1, 3)
    return v.min(axis=0), v.max(axis=0)


# --------------------------------------------------------------------------- transformacoes

def rotacao(graus_xyz):
    ax, ay, az = np.radians(graus_xyz)
    rx = np.array([[1, 0, 0], [0, np.cos(ax), -np.sin(ax)], [0, np.sin(ax), np.cos(ax)]])
    ry = np.array([[np.cos(ay), 0, np.sin(ay)], [0, 1, 0], [-np.sin(ay), 0, np.cos(ay)]])
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    return rz @ ry @ rx  # mesma ordem do three.js (Euler 'XYZ')


def transformar(tris, posicao=(0, 0, 0), rotacao_graus=(0, 0, 0), escala=1.0):
    """Escala, gira (em torno da origem do item) e move."""
    esc = np.broadcast_to(np.asarray(escala, dtype=float), (3,))
    v = tris.reshape(-1, 3) * esc
    v = v @ rotacao(rotacao_graus).T + np.asarray(posicao, dtype=float)
    return v.reshape(-1, 3, 3)


# --------------------------------------------------------------------------- fechamento (voxel)

def fechar_por_voxels(tris, voxel, fechar_base=True):
    """Transforma qualquer malha (aberta, com buracos, cheia de ruido) num solido fechado.

    1) marca os voxels tocados pela superficie; 2) inunda o espaco de fora;
    3) tudo o que nao foi inundado e solido; 4) devolve as faces da fronteira (estanque).
    Buracos menores que ~2 voxels sao fechados. fechar_base=True tampa o fundo (z minimo),
    porque scans de objetos apoiados no chao nunca tem a parte de baixo.
    """
    vmin, vmax = limites(tris)
    origem = vmin - 2 * voxel
    forma = np.ceil((vmax - vmin) / voxel).astype(int) + 5
    ocupado = np.zeros(forma, dtype=bool)

    # amostra cada triangulo com espacamento menor que meio voxel
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    tam = np.maximum(np.linalg.norm(b - a, axis=1), np.linalg.norm(c - a, axis=1))
    n_div = np.clip(np.ceil(tam / (0.5 * voxel)).astype(int), 1, 200)
    for n in np.unique(n_div):
        sel = n_div == n
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        ok = i + j <= n
        u, w = (i[ok] / n)[:, None, None], (j[ok] / n)[:, None, None]
        pts = (a[sel] + u * (b[sel] - a[sel]) + w * (c[sel] - a[sel])).reshape(-1, 3)
        idx = np.floor((pts - origem) / voxel).astype(int)
        ocupado[idx[:, 0], idx[:, 1], idx[:, 2]] = True

    if fechar_base:
        k0 = int(np.argmax(ocupado.any(axis=(0, 1))))
        sombra = ocupado.any(axis=2)
        for eixo in range(2):  # engrossa a sombra para fechar falhas no contorno
            sombra = sombra | np.roll(sombra, 1, axis=eixo) | np.roll(sombra, -1, axis=eixo)
        fora2 = np.zeros_like(sombra)
        fora2[0, :] = fora2[-1, :] = fora2[:, 0] = fora2[:, -1] = True
        fora2 &= ~sombra
        while True:
            novo = fora2 | np.roll(fora2, 1, 0) | np.roll(fora2, -1, 0) | np.roll(fora2, 1, 1) | np.roll(fora2, -1, 1)
            novo &= ~sombra
            if novo.sum() == fora2.sum():
                break
            fora2 = novo
        ocupado[:, :, k0] |= ~fora2

    # engrossa a casca em 1 voxel para fechar pequenas falhas
    casca = ocupado.copy()
    for eixo in range(3):
        casca |= np.roll(ocupado, 1, axis=eixo) | np.roll(ocupado, -1, axis=eixo)

    # inunda o exterior a partir do canto (camadas sucessivas ate estabilizar)
    fora = np.zeros_like(casca)
    fora[0, :, :] = fora[-1, :, :] = fora[:, 0, :] = fora[:, -1, :] = fora[:, :, 0] = fora[:, :, -1] = True
    fora &= ~casca
    while True:
        novo = fora.copy()
        for eixo in range(3):
            novo |= np.roll(fora, 1, axis=eixo) | np.roll(fora, -1, axis=eixo)
        novo &= ~casca
        if novo.sum() == fora.sum():
            break
        fora = novo
    solido = ~fora
    # desfaz o engrossamento (erosao de 1 voxel), mantendo o fechamento
    erodido = solido.copy()
    for eixo in range(3):
        erodido &= np.roll(solido, 1, axis=eixo) & np.roll(solido, -1, axis=eixo)
    solido = erodido | (solido & ocupado)

    return faces_de_voxels(solido, origem, voxel)


def faces_de_voxels(solido, origem, voxel):
    tris = []
    cantos = {  # face na direcao +eixo/-eixo: 4 cantos (anti-horario visto de fora)
        (0, 1): [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)],
        (0, -1): [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)],
        (1, 1): [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)],
        (1, -1): [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)],
        (2, 1): [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)],
        (2, -1): [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)],
    }
    s = np.pad(solido, 1)
    for (eixo, sinal), cs in cantos.items():
        vizinho = np.roll(s, -sinal, axis=eixo)
        idx = np.argwhere(s & ~vizinho) - 1
        if not len(idx):
            continue
        q = np.array(cs, dtype=float)
        p = (idx[:, None, :] + q[None]) * voxel + origem
        tris.append(p[:, [0, 1, 2]])
        tris.append(p[:, [0, 2, 3]])
    return np.concatenate(tris)
