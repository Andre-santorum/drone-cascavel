#!/usr/bin/env python3
"""Le os resultados de um caso e gera relatorio + mapas (pasta resultados/ dentro do caso).

Uso:  python3 pos_processar.py casos/<nome>

Gera:
  resultados/relatorio.md            numeros principais (velocidade, temperatura, vazao)
  resultados/velocidade_animais.png  mapa de velocidade do ar na altura dos animais (vista de cima)
  resultados/temperatura_animais.png mapa de temperatura na altura dos animais
  resultados/corte_longitudinal.png  velocidade e temperatura no corte pelo meio do galpao
Para visualizacao 3D completa (linhas de corrente, etc.) abra caso.foam no ParaView.
"""
import json
import os
import sys

import numpy as np


def ultima_pasta(caminho):
    tempos = [d for d in os.listdir(caminho) if d.replace(".", "", 1).isdigit()]
    return os.path.join(caminho, max(tempos, key=float))


def ultimo_valor(caso, nome):
    pasta = os.path.join(caso, "postProcessing", nome)
    if not os.path.isdir(pasta):
        return None
    valor = None
    for t in sorted(os.listdir(pasta), key=float):
        with open(os.path.join(pasta, t, "surfaceFieldValue.dat")) as f:
            for linha in f:
                if not linha.startswith("#") and linha.strip():
                    valor = float(linha.split()[1])
    return valor


def carregar(arquivo):
    d = np.loadtxt(arquivo, comments="#")
    return d[:, 0:3], np.linalg.norm(d[:, 3:6], axis=1), d[:, 6] - 273.15


def mapa(px, py, valores, dx, titulo, rotulo, cmap, arquivo, xlabel, ylabel, limites=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.tri as mtri

    tri = mtri.Triangulation(px, py)
    # esconde triangulos que atravessam obstaculos (arestas muito longas)
    a = np.stack([px[tri.triangles], py[tri.triangles]], axis=-1)
    arestas = np.linalg.norm(a - np.roll(a, 1, axis=1), axis=-1).max(axis=1)
    tri.set_mask(arestas > 3 * dx)

    largura = px.max() - px.min()
    altura = py.max() - py.min()
    # cortes muito achatados (galpao longo e baixo) ficam com escala vertical exagerada
    proporcional = altura / largura > 0.08
    fig, ax = plt.subplots(figsize=(14, 14 * altura / largura * 2.2 if proporcional else 3.5))
    niveis = np.linspace(*(limites or (valores.min(), valores.max())), 21)
    cf = ax.tricontourf(tri, valores, levels=niveis, cmap=cmap, extend="both")
    fig.colorbar(cf, ax=ax, label=rotulo, pad=0.01)
    if proporcional:
        ax.set_aspect("equal")
    else:
        titulo += " (escala vertical exagerada)"
    ax.set_title(titulo)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.tight_layout()
    fig.savefig(arquivo, dpi=130)
    plt.close(fig)


def main():
    caso = sys.argv[1] if len(sys.argv) > 1 else "."
    with open(os.path.join(caso, "config_usada.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    g, an = cfg["galpao"], cfg["analise"]
    dx = cfg["malha"]["tamanho_celula"]
    alvo = an["velocidade_alvo_m_s"]
    saida = os.path.join(caso, "resultados")
    os.makedirs(saida, exist_ok=True)

    planos = ultima_pasta(os.path.join(caso, "postProcessing", "planos"))
    p, u, t = carregar(os.path.join(planos, "alturaAnimais.xy"))
    dentro = (p[:, 0] > 0) & (p[:, 0] < g["comprimento"]) & (p[:, 1] > 0) & (p[:, 1] < g["largura"])
    p, u, t = p[dentro], u[dentro], t[dentro]

    q_ex = ultimo_valor(caso, "vazaoExaustores")
    q_in = ultimo_valor(caso, "vazaoEntradas")
    t_ex = ultimo_valor(caso, "temperaturaExaustores")
    rho = 1.16

    linhas = [
        f"# Resultado da simulacao: {cfg['nome']}",
        "",
        f"Iteracao final: {os.path.basename(planos)}  |  celula {dx} m  |  "
        f"{cfg['exaustores']['quantidade'] if not cfg['exaustores'].get('posicoes_manuais') else len(cfg['exaustores']['posicoes_manuais'])} exaustores "
        f"de {cfg['exaustores']['vazao_m3h_cada']:.0f} m3/h",
        "",
        f"## Na altura dos animais ({an['altura_animais_m']} m)",
        "",
        "| Indicador | Valor |",
        "|---|---|",
        f"| Velocidade media do ar | {u.mean():.2f} m/s |",
        f"| Velocidade minima / maxima | {u.min():.2f} / {u.max():.2f} m/s |",
        f"| Area com velocidade abaixo de {0.8 * alvo:.2f} m/s (80% do alvo {alvo}) | {100 * (u < 0.8 * alvo).mean():.0f} % |",
        f"| Area com velocidade abaixo de 0,5 m/s (ar parado) | {100 * (u < 0.5).mean():.0f} % |",
        f"| Temperatura media | {t.mean():.1f} C |",
        f"| Temperatura maxima | {t.max():.1f} C |",
        f"| Temperatura de entrada | {cfg['clima']['temperatura_entrada_C']:.1f} C |",
        "",
        "## Balanco",
        "",
    ]
    if q_ex is not None:
        linhas.append(f"- Vazao total nos exaustores: {q_ex / rho * 3600:,.0f} m3/h ({q_ex:.1f} kg/s)")
    if q_in is not None and q_ex:
        linhas.append(f"- Erro de conservacao de massa: {100 * abs(q_ex + q_in) / abs(q_ex):.2f} % (bom se < 1 %)")
    if t_ex is not None:
        linhas.append(f"- Temperatura media do ar saindo pelos exaustores: {t_ex - 273.15:.2f} C")

    linhas += ["", "## Ao longo do galpao (faixas de 10 m)", "",
               "| Trecho (m) | Vel. media (m/s) | Vel. minima (m/s) | Temp. media (C) |", "|---|---|---|---|"]
    for x0 in np.arange(0, g["comprimento"], 10.0):
        m = (p[:, 0] >= x0) & (p[:, 0] < x0 + 10)
        if m.any():
            linhas.append(f"| {x0:.0f}-{min(x0 + 10, g['comprimento']):.0f} | {u[m].mean():.2f} | "
                          f"{u[m].min():.2f} | {t[m].mean():.1f} |")

    try:
        mapa(p[:, 0], p[:, 1], u, dx, f"Velocidade do ar a {an['altura_animais_m']} m do piso",
             "m/s", "viridis", os.path.join(saida, "velocidade_animais.png"),
             "comprimento x (m) - exaustores a direita", "largura y (m)", (0, max(alvo * 1.4, u.max())))
        mapa(p[:, 0], p[:, 1], t, dx, f"Temperatura a {an['altura_animais_m']} m do piso",
             "C", "coolwarm", os.path.join(saida, "temperatura_animais.png"),
             "comprimento x (m) - exaustores a direita", "largura y (m)")
        pc, uc, tc = carregar(os.path.join(planos, "corteLongitudinal.xy"))
        mapa(pc[:, 0], pc[:, 2], uc, dx, "Velocidade - corte longitudinal no meio do galpao", "m/s",
             "viridis", os.path.join(saida, "corte_longitudinal.png"), "comprimento x (m)", "altura z (m)")
        mapa(pc[:, 0], pc[:, 2], tc, dx, "Temperatura - corte longitudinal no meio do galpao", "C",
             "coolwarm", os.path.join(saida, "corte_longitudinal_temperatura.png"), "comprimento x (m)", "altura z (m)")
        linhas += ["", "## Mapas", "", "![velocidade](velocidade_animais.png)", "",
                   "![temperatura](temperatura_animais.png)", "", "![corte](corte_longitudinal.png)", "",
                   "![corte temperatura](corte_longitudinal_temperatura.png)"]
    except ImportError:
        linhas += ["", "(matplotlib nao instalado: sudo apt install python3-matplotlib para gerar os mapas)"]

    texto = "\n".join(linhas) + "\n"
    with open(os.path.join(saida, "relatorio.md"), "w", encoding="utf-8") as f:
        f.write(texto)
    print(texto)
    print(f"Arquivos em: {saida}")


if __name__ == "__main__":
    main()
