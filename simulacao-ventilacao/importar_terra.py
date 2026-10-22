#!/usr/bin/env python3
"""Importa um galpao de um projeto do DJI Terra e prepara a simulacao.

Le o modelo 3D (malha OBJ/PLY) ou a nuvem de pontos (LAS/PLY) que o DJI Terra gera, acha o
galpao, mede comprimento, largura, altura do beiral e o perfil do telhado, e escreve:

  <saida>/galpao.stl          envoltoria fechada do galpao, ja no sistema de coordenadas da simulacao
  <saida>/config.json         configuracao pronta para o gerar_caso.py
  <saida>/visao_geral.png     mapa de alturas do terreno com as construcoes numeradas
  <saida>/perfil_telhado.png  corte transversal: pontos do drone + perfil adotado
  <saida>/transformacao.json  como voltar das coordenadas da simulacao para as do Terra

Uso (no Ubuntu/WSL, o disco C: fica em /mnt/c):
  python3 importar_terra.py "/mnt/c/Users/<voce>/Documents/DJI/DJI Terra/<conta>/<missao>"
  python3 importar_terra.py <pasta ou arquivo> --galpao 2 --exaustores-em inicio
  python3 importar_terra.py modelo.obj --saida modelos/aviario1 --altura-forro 2.8

Aceita: pasta da missao (procura terra_obj, terra_ply, terra_las...), arquivo .obj, .ply, .las.
Nao aceita B3DM/OSGB/S3MB: no Terra, marque tambem OBJ ou PLY (ou LAS) nos formatos de saida.
"""
import argparse
import copy
import glob
import json
import os
import struct
import sys

import numpy as np

MAX_PONTOS = 4_000_000
AQUI = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------- leitura

def ler_obj(caminho, passo=1):
    """Vertices de um OBJ; passo > 1 pula vertices (modelos do Terra podem ter dezenas de milhoes)."""
    pts = []
    k = 0
    with open(caminho, "rb") as f:
        for linha in f:
            if linha[:2] == b"v ":
                if k % passo == 0:
                    pts.append(linha.split()[1:4])
                k += 1
    return np.array(pts, dtype=np.float64)


def ler_ply(caminho):
    with open(caminho, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError(f"nao e PLY: {caminho}")
        formato, elementos = None, []
        while True:
            linha = f.readline().decode("ascii", "ignore").strip()
            partes = linha.split()
            if not partes:
                continue
            if partes[0] == "format":
                formato = partes[1]
            elif partes[0] == "element":
                elementos.append([partes[1], int(partes[2]), []])
            elif partes[0] == "property" and elementos:
                elementos[-1][2].append(partes[1:])
            elif partes[0] == "end_header":
                break
        tipos = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
                 "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
                 "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}
        nome, n, props = elementos[0]
        if nome != "vertex" or any(p[0] == "list" for p in props):
            raise ValueError("PLY sem bloco de vertices no inicio")
        nomes = [p[1] for p in props]
        if formato == "ascii":
            dados = np.loadtxt(f, max_rows=n)
            return dados[:, [nomes.index(c) for c in "xyz"]].astype(np.float64)
        ordem = "<" if formato == "binary_little_endian" else ">"
        dtype = np.dtype([(p[1], ordem + tipos[p[0]]) for p in props])
        dados = np.frombuffer(f.read(n * dtype.itemsize), dtype=dtype, count=n)
        return np.stack([dados[c].astype(np.float64) for c in "xyz"], axis=1)


def ler_las(caminho):
    if caminho.lower().endswith(".laz"):
        try:
            import laspy
        except ImportError:
            sys.exit("Arquivo .laz precisa do laspy:  pip install 'laspy[lazrs]'  (ou exporte .las no Terra)")
        las = laspy.read(caminho)
        return np.stack([las.x, las.y, las.z], axis=1)
    with open(caminho, "rb") as f:
        cab = f.read(375)
        if cab[:4] != b"LASF":
            raise ValueError(f"nao e LAS: {caminho}")
        versao = cab[25]
        offset_pts = struct.unpack("<I", cab[96:100])[0]
        tam_reg = struct.unpack("<H", cab[105:107])[0]
        n = struct.unpack("<I", cab[107:111])[0]
        if n == 0 and versao >= 4:
            n = struct.unpack("<Q", cab[247:255])[0]
        escala = np.array(struct.unpack("<3d", cab[131:155]))
        origem = np.array(struct.unpack("<3d", cab[155:179]))
        f.seek(offset_pts)
        passo = max(1, n // MAX_PONTOS)
        bruto = np.fromfile(f, dtype=np.uint8, count=n * tam_reg).reshape(n, tam_reg)[::passo]
    xyz = bruto[:, :12].copy().view("<i4").astype(np.float64)
    return xyz * escala + origem


def achar_arquivos(entrada):
    if os.path.isfile(entrada):
        return [entrada]
    preferencia = ["**/terra_obj/**/*.obj", "**/terra_ply/**/*.ply", "**/terra_las/**/*.las",
                   "**/*.obj", "**/*.ply", "**/*.las", "**/*.laz"]
    for padrao in preferencia:
        achados = sorted(glob.glob(os.path.join(entrada, padrao), recursive=True))
        if achados:
            return achados
    outros = glob.glob(os.path.join(entrada, "**/*.b3dm"), recursive=True) + \
        glob.glob(os.path.join(entrada, "**/*.osgb"), recursive=True)
    if outros:
        sys.exit("So encontrei B3DM/OSGB. No DJI Terra, refaca a saida marcando OBJ ou PLY "
                 "(ou a nuvem de pontos em LAS) e rode de novo.")
    sys.exit(f"Nenhum modelo 3D (.obj/.ply/.las) encontrado em: {entrada}")


def carregar(entrada):
    arquivos = achar_arquivos(entrada)
    print(f"Lendo {len(arquivos)} arquivo(s)... (ex.: {arquivos[0]})")
    # ~60 bytes por vertice num OBJ (contando faces e coordenadas de textura)
    bytes_obj = sum(os.path.getsize(a) for a in arquivos if a.lower().endswith(".obj"))
    passo_obj = max(1, int(bytes_obj / 60 / MAX_PONTOS))
    partes = []
    for a in arquivos:
        ext = os.path.splitext(a)[1].lower()
        if ext == ".obj":
            partes.append(ler_obj(a, passo_obj))
        else:
            partes.append({".ply": ler_ply, ".las": ler_las, ".laz": ler_las}[ext](a))
    pts = np.concatenate(partes)
    if len(pts) > MAX_PONTOS:
        pts = pts[np.random.default_rng(0).choice(len(pts), MAX_PONTOS, replace=False)]
    print(f"{len(pts):,} pontos carregados")
    return pts


# --------------------------------------------------------------------------- analise

def orientar_vertical(pts, eixo):
    if eixo == "auto":
        # num levantamento de drone o eixo de menor extensao e o vertical
        extensao = np.percentile(pts, 99, axis=0) - np.percentile(pts, 1, axis=0)
        eixo = "xyz"[int(np.argmin(extensao))]
        print(f"Eixo vertical detectado: {eixo}")
    if eixo == "y":  # Y para cima (algumas exportacoes OBJ): (x, y, z) -> (x, -z, y)
        pts = np.stack([pts[:, 0], -pts[:, 2], pts[:, 1]], axis=1)
    elif eixo == "x":
        pts = pts[:, [1, 2, 0]]
    return pts


def grade_alturas(pts, celula):
    xy0 = pts[:, :2].min(axis=0)
    ij = np.floor((pts[:, :2] - xy0) / celula).astype(int)
    forma = tuple(ij.max(axis=0) + 1)
    zmax = np.full(forma, -np.inf)
    zmin = np.full(forma, np.inf)
    np.maximum.at(zmax, (ij[:, 0], ij[:, 1]), pts[:, 2])
    np.minimum.at(zmin, (ij[:, 0], ij[:, 1]), pts[:, 2])
    return xy0, ij, zmax, zmin


def componentes(mascara):
    """Rotula regioes conectadas (vizinhanca 8) de uma mascara 2D."""
    rotulos = np.zeros(mascara.shape, dtype=int)
    atual = 0
    ni, nj = mascara.shape
    for i0, j0 in zip(*np.nonzero(mascara)):
        if rotulos[i0, j0]:
            continue
        atual += 1
        rotulos[i0, j0] = atual
        pilha = [(i0, j0)]
        while pilha:
            i, j = pilha.pop()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    a, b = i + di, j + dj
                    if 0 <= a < ni and 0 <= b < nj and mascara[a, b] and not rotulos[a, b]:
                        rotulos[a, b] = atual
                        pilha.append((a, b))
    return rotulos, atual


def terreno(zmin, raio):
    """Cota do terreno por celula: minimo local numa janela grande (filtro morfologico simples)."""
    z = np.where(np.isfinite(zmin), zmin, np.nanmax(zmin[np.isfinite(zmin)]))
    ni, nj = z.shape
    passo = max(1, raio)
    # minimo em blocos e interpolacao do bloco: suficiente para galpoes em terreno pouco inclinado
    bi, bj = (ni + passo - 1) // passo, (nj + passo - 1) // passo
    blocos = np.full((bi, bj), np.inf)
    for a in range(bi):
        for b in range(bj):
            blocos[a, b] = np.percentile(z[a * passo:(a + 1) * passo, b * passo:(b + 1) * passo], 5)
    return np.kron(blocos, np.ones((passo, passo)))[:ni, :nj]


def detectar_construcoes(pts, celula, altura_min, area_min):
    xy0, ij, zmax, zmin = grade_alturas(pts, celula)
    chao = terreno(zmin, int(30 / celula))
    altura = np.where(np.isfinite(zmax), zmax - chao, 0.0)
    mascara = altura > altura_min
    rotulos, n = componentes(mascara)
    areas = np.bincount(rotulos.ravel(), minlength=n + 1) * celula ** 2
    validos = [r for r in range(1, n + 1) if areas[r] >= area_min]
    validos.sort(key=lambda r: -areas[r])
    return xy0, ij, altura, zmin, rotulos, validos, areas


def dilatar(mascara, passos):
    m = mascara.copy()
    for _ in range(max(1, passos)):
        n = m.copy()
        n[1:] |= m[:-1]
        n[:-1] |= m[1:]
        n[:, 1:] |= m[:, :-1]
        n[:, :-1] |= m[:, 1:]
        m = n
    return m


def perfil_telhado(v, z, largura, n_bins):
    bordas = np.linspace(0, largura, n_bins + 1)
    perfil = np.full(n_bins, np.nan)
    for k in range(n_bins):
        sel = (v >= bordas[k]) & (v < bordas[k + 1])
        if sel.sum() >= 5:
            perfil[k] = np.percentile(z[sel], 75)
    validos = np.isfinite(perfil)
    centros = 0.5 * (bordas[1:] + bordas[:-1])
    perfil = np.interp(centros, centros[validos], perfil[validos])
    # suaviza (media movel de 3)
    perfil = np.convolve(np.pad(perfil, 1, mode="edge"), np.ones(3) / 3, mode="valid")
    return centros, perfil


def stl_extrusao(caminho, comprimento, ys, zs):
    """STL fechado: secao {0 <= z <= telhado(y)} extrudada em x de 0 a comprimento.

    ys/zs: pontos do telhado da parede y=0 ate y=largura. As tampas sao divididas em
    trapezios verticais, o que vale para qualquer formato de telhado (lanternim, arco...).
    """
    n = len(ys)
    secao = [(y, 0.0) for y in ys] + [(ys[k], zs[k]) for k in range(n - 1, -1, -1)]
    tris = []
    m = len(secao)
    for i in range(m):  # faces longitudinais
        (ya, za), (yb, zb) = secao[i], secao[(i + 1) % m]
        a0, b0, a1, b1 = (0.0, ya, za), (0.0, yb, zb), (comprimento, ya, za), (comprimento, yb, zb)
        tris += [(a0, a1, b1), (a0, b1, b0)]
    for k in range(n - 1):  # tampas
        for x, inv in ((0.0, True), (comprimento, False)):
            p00, p10 = (x, ys[k], 0.0), (x, ys[k + 1], 0.0)
            p11, p01 = (x, ys[k + 1], zs[k + 1]), (x, ys[k], zs[k])
            t = [(p00, p10, p11), (p00, p11, p01)]
            tris += [(c, b, a) for a, b, c in t] if inv else t
    with open(caminho, "w") as f:
        f.write("solid galpao\n")
        for t in tris:
            f.write(" facet normal 0 0 0\n  outer loop\n")
            for p in t:
                f.write(f"   vertex {p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
            f.write("  endloop\n endfacet\n")
        f.write("endsolid galpao\n")


# --------------------------------------------------------------------------- figuras

def figuras(saida, xy0, celula, altura, rotulos, validos, escolhido, v_c, perfil, v_pts, z_pts, secao,
            ponta_a, ponta_b, exaustores_em):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("(matplotlib ausente: figuras nao geradas)")
        return
    fig, ax = plt.subplots(figsize=(10, 8))
    ext = [xy0[0], xy0[0] + altura.shape[0] * celula, xy0[1], xy0[1] + altura.shape[1] * celula]
    im = ax.imshow(np.clip(altura, 0, None).T, origin="lower", extent=ext, cmap="terrain")
    fig.colorbar(im, ax=ax, label="altura acima do terreno (m)")
    for k, r in enumerate(validos[:15], 1):
        i, j = np.nonzero(rotulos == r)
        cor = "red" if r == escolhido else "black"
        ax.text(xy0[0] + i.mean() * celula, xy0[1] + j.mean() * celula, str(k), color=cor,
                fontsize=14, weight="bold", ha="center", va="center",
                bbox=dict(facecolor="white", alpha=0.7, edgecolor=cor))
    for rotulo, p in (("A", ponta_a), ("B", ponta_b)):
        ex = (rotulo == "B") == (exaustores_em == "fim")
        ax.annotate(f"{rotulo}{' (exaustores)' if ex else ''}", p, color="red", fontsize=11, weight="bold",
                    ha="center", bbox=dict(facecolor="yellow", alpha=0.8))
    ax.set_title("Construcoes detectadas (vermelho = usada). Escolha outra com --galpao N")
    ax.set_xlabel("x do Terra (m)")
    ax.set_ylabel("y do Terra (m)")
    fig.tight_layout()
    fig.savefig(os.path.join(saida, "visao_geral.png"), dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(v_pts, z_pts, ",", color="0.6", label="pontos do drone")
    ax.plot(v_c, perfil, "b-", lw=1, label="perfil medido")
    ys, zs = zip(*(secao + [secao[0]]))
    ax.plot(ys, zs, "r-", lw=2, label="envoltoria usada na simulacao")
    ax.set_aspect("equal")
    ax.set_xlabel("largura (m)")
    ax.set_ylabel("altura (m)")
    ax.legend(loc="lower center", fontsize=8)
    ax.set_title("Corte transversal do galpao")
    fig.tight_layout()
    fig.savefig(os.path.join(saida, "perfil_telhado.png"), dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada", help="pasta da missao do DJI Terra ou arquivo .obj/.ply/.las")
    ap.add_argument("--saida", help="pasta de saida (padrao: modelos/<nome da missao>)")
    ap.add_argument("--galpao", type=int, default=1, help="numero da construcao no visao_geral.png (1 = a maior)")
    ap.add_argument("--exaustores-em", choices=["fim", "inicio"], default="fim",
                    help="em qual ponta ficam os exaustores (veja as letras A/B no perfil impresso)")
    ap.add_argument("--vertical", choices=["auto", "x", "y", "z"], default="auto")
    ap.add_argument("--beiral", type=float, default=0.0,
                    help="beiral (m) a descontar de cada lado: o drone ve o telhado, que e maior que as paredes")
    ap.add_argument("--altura-forro", type=float,
                    help="se o galpao tem forro, a altura dele (m): o ar circula so abaixo do forro")
    ap.add_argument("--base", default=os.path.join(AQUI, "config_exemplo.json"),
                    help="config de onde vem exaustores, pads, clima etc.")
    ap.add_argument("--celula", type=float, default=0.5, help="resolucao da analise (m)")
    args = ap.parse_args()

    nome = os.path.basename(os.path.normpath(args.entrada))
    nome = os.path.splitext(nome)[0].replace(" ", "_") or "galpao"
    saida = args.saida or os.path.join(AQUI, "modelos", nome)
    os.makedirs(saida, exist_ok=True)
    os.makedirs(os.path.join(AQUI, "modelos"), exist_ok=True)

    pts = orientar_vertical(carregar(args.entrada), args.vertical)
    xy0, ij, altura, altura_abs_min, rotulos, validos, areas = detectar_construcoes(pts, args.celula, 1.5, 100.0)
    if not validos:
        sys.exit("Nenhuma construcao com mais de 100 m2 e 1,5 m de altura foi encontrada no modelo.")
    print("Construcoes encontradas (area de projecao):")
    for k, r in enumerate(validos[:10], 1):
        print(f"  {k}: {areas[r]:.0f} m2")
    if args.galpao > len(validos):
        sys.exit(f"--galpao {args.galpao} nao existe (ha {len(validos)} construcoes)")
    escolhido = validos[args.galpao - 1]

    # pontos do galpao escolhido e cota do terreno em volta
    sel = rotulos[ij[:, 0], ij[:, 1]] == escolhido
    gp = pts[sel]
    # terreno: plano ajustado nas celulas de chao num anel de ~2 a ~10 m em volta do galpao
    mascara = rotulos == escolhido
    perto, longe = dilatar(mascara, int(2 / args.celula)), dilatar(mascara, int(10 / args.celula))
    anel = longe & ~perto & (altura < 0.5)
    ia, ja = np.nonzero(anel)
    xa = xy0[0] + (ia + 0.5) * args.celula
    ya = xy0[1] + (ja + 0.5) * args.celula
    za = altura_abs_min[ia, ja]
    coef = np.linalg.lstsq(np.c_[np.ones_like(xa), xa - xa.mean(), ya - ya.mean()], za, rcond=None)[0]
    plano = lambda px, py: coef[0] + coef[1] * (px - xa.mean()) + coef[2] * (py - ya.mean())
    cota_chao = float(plano(*gp[:, :2].mean(axis=0)))
    # descarta pontos de chao que cairam nas celulas da borda do galpao
    gp = gp[gp[:, 2] - plano(gp[:, 0], gp[:, 1]) > 1.0]

    # orientacao: eixo principal (PCA) = comprimento
    centro = gp[:, :2].mean(axis=0)
    cov = np.cov((gp[:, :2] - centro).T)
    autoval, autovet = np.linalg.eigh(cov)
    eixo_u = autovet[:, np.argmax(autoval)]
    # ajuste fino do angulo: o certo e o que deixa o galpao mais estreito
    d = gp[:, :2] - centro
    ang0 = np.arctan2(eixo_u[1], eixo_u[0])
    larguras = []
    for da in np.radians(np.arange(-3, 3.001, 0.02)):
        n = np.array([-np.sin(ang0 + da), np.cos(ang0 + da)])
        larguras.append((np.subtract(*np.percentile(d @ n, [99.95, 0.05])), da))
    ang = ang0 + min(larguras)[1]
    eixo_u = np.array([np.cos(ang), np.sin(ang)])
    eixo_v = np.array([-eixo_u[1], eixo_u[0]])
    u = (gp[:, :2] - centro) @ eixo_u
    v = (gp[:, :2] - centro) @ eixo_v
    z = gp[:, 2] - plano(gp[:, 0], gp[:, 1])
    u0, u1 = np.percentile(u, [0.05, 99.95])
    v0, v1 = np.percentile(v, [0.05, 99.95])
    u0, u1 = u0 + args.beiral, u1 - args.beiral
    v0, v1 = v0 + args.beiral, v1 - args.beiral
    comprimento, largura = u1 - u0, v1 - v0

    # sistema da simulacao: x = 0 na frente (pads), x = comprimento nos exaustores
    if args.exaustores_em == "fim":
        x = u - u0
        origem_u, sentido = u0, 1.0
    else:
        x = u1 - u
        origem_u, sentido = u1, -1.0
    y = v - v0

    centro_long = (x > 0.1 * comprimento) & (x < 0.9 * comprimento) & (y >= 0) & (y <= largura)
    n_bins = int(np.clip(largura / 0.5, 8, 60))
    v_c, perfil = perfil_telhado(y[centro_long], z[centro_long], largura, n_bins)
    if args.altura_forro:
        perfil = np.minimum(perfil, args.altura_forro)
    beiral_alt = float(min(perfil[0], perfil[-1]))
    cumeeira = float(perfil.max())

    ys = [0.0] + [float(c) for c in v_c] + [largura]
    zs = [float(perfil[0])] + [float(p) for p in perfil] + [float(perfil[-1])]
    stl_extrusao(os.path.join(saida, "galpao.stl"), comprimento, ys, zs)
    secao = [(0.0, 0.0), (largura, 0.0)] + list(zip(ys[::-1], zs[::-1]))

    with open(args.base, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg = copy.deepcopy(cfg)
    cfg["nome"] = nome
    cfg["galpao"] = {"comprimento": round(comprimento, 2), "largura": round(largura, 2),
                     "altura": round(beiral_alt, 2)}
    cfg["envoltoria_stl"] = "galpao.stl"
    cfg["ponto_no_ar"] = [comprimento * 0.5 + 0.0123, largura * 0.5 + 0.0123, beiral_alt * 0.5 + 0.0123]
    cfg["obstaculos_stl"] = []
    for e in cfg["entradas_ar"]:
        e["fim"] = min(e["fim"], comprimento - 1.0)
        e["z_max"] = min(e["z_max"], beiral_alt - 0.2)
    cfg["exaustores"]["altura_centro_m"] = min(cfg["exaustores"]["altura_centro_m"],
                                               beiral_alt - cfg["exaustores"]["lado_m"] / 2 - 0.1)
    with open(os.path.join(saida, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    transf = {
        "_explicacao": "ponto_terra_xy = centro + (origem_u + sentido*x_sim)*eixo_u + (v0 + y_sim)*eixo_v ; "
                       "z_terra = z_sim + cota_chao",
        "centro": centro.tolist(), "eixo_u": eixo_u.tolist(), "eixo_v": eixo_v.tolist(),
        "origem_u": float(origem_u), "sentido": sentido, "v0": float(v0), "cota_chao": cota_chao,
    }
    with open(os.path.join(saida, "transformacao.json"), "w", encoding="utf-8") as f:
        json.dump(transf, f, indent=2)

    a, b = centro + u0 * eixo_u, centro + u1 * eixo_u
    figuras(saida, xy0, args.celula, altura, rotulos, validos, escolhido, v_c, perfil, y[centro_long],
            z[centro_long], secao, a, b, args.exaustores_em)

    print(f"\nGalpao {args.galpao}: comprimento {comprimento:.1f} m, largura {largura:.1f} m, "
          f"beiral {beiral_alt:.2f} m, cumeeira {cumeeira:.2f} m")
    print(f"  ponta A (inicio) em x={a[0]:.1f} y={a[1]:.1f}   "
          f"ponta B (fim) em x={b[0]:.1f} y={b[1]:.1f}  (coordenadas do Terra)")
    print(f"  exaustores na ponta {'B' if args.exaustores_em == 'fim' else 'A'} "
          f"(mude com --exaustores-em {'inicio' if args.exaustores_em == 'fim' else 'fim'})")
    print("  CONFIRA as medidas com a trena: o drone mede o telhado (com beiral). "
          "Se precisar, use --beiral 0.5 etc.")
    with open(os.path.join(AQUI, "modelos", "ultimo_importado.txt"), "w") as f:
        f.write(os.path.abspath(saida) + "\n")
    print(f"\nArquivos em {saida}:  galpao.stl, config.json, visao_geral.png, perfil_telhado.png")
    print(f"Proximo passo:  python3 {os.path.join(AQUI, 'gerar_caso.py')} {os.path.join(saida, 'config.json')}")


if __name__ == "__main__":
    main()
