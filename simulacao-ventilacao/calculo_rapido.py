#!/usr/bin/env python3
"""Calculo rapido (sem CFD) da ventilacao em tunel de um galpao.

Roda em segundos, em qualquer computador, e serve para:
  - estimar quantos exaustores sao necessarios para uma velocidade-alvo;
  - conferir os resultados do CFD (a media do CFD deve ficar perto destes numeros).

Uso:
  python3 calculo_rapido.py config_exemplo.json
  python3 calculo_rapido.py config_exemplo.json --exaustores 6 8 10 12
"""
import argparse
import json
import math

RHO_AR = 1.16   # kg/m3 a ~30 C
CP_AR = 1005.0  # J/(kg K)


def calcular(cfg, n_exaustores):
    g = cfg["galpao"]
    ex = cfg["exaustores"]
    cargas = cfg["cargas_termicas"]
    secao = g["largura"] * g["altura"]
    volume = secao * g["comprimento"]
    area_piso = g["largura"] * g["comprimento"]

    vazao_m3s = n_exaustores * ex["vazao_m3h_cada"] / 3600.0
    velocidade = vazao_m3s / secao
    troca_s = volume / vazao_m3s if vazao_m3s > 0 else math.inf
    calor_w = (cargas["calor_animais_W_m2"] + cargas["calor_telhado_W_m2"]) * area_piso
    delta_t = calor_w / (RHO_AR * CP_AR * vazao_m3s) if vazao_m3s > 0 else math.inf
    area_entrada = sum((e["fim"] - e["inicio"]) * (e["z_max"] - e["z_min"])
                       for e in cfg["entradas_ar"])
    vel_entrada = vazao_m3s / area_entrada if area_entrada > 0 else math.inf
    return {
        "exaustores": n_exaustores,
        "vazao_m3h": vazao_m3s * 3600,
        "velocidade_m_s": velocidade,
        "troca_ar_s": troca_s,
        "delta_t_C": delta_t,
        "t_saida_C": cfg["clima"]["temperatura_entrada_C"] + delta_t,
        "vel_entrada_m_s": vel_entrada,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--exaustores", type=int, nargs="*", help="quantidades para comparar")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)

    g = cfg["galpao"]
    alvo = cfg["analise"]["velocidade_alvo_m_s"]
    secao = g["largura"] * g["altura"]
    necessarios = math.ceil(alvo * secao * 3600 / cfg["exaustores"]["vazao_m3h_cada"])

    quantidades = args.exaustores or sorted({cfg["exaustores"]["quantidade"], necessarios})
    print(f"Galpao {g['comprimento']} x {g['largura']} x {g['altura']} m "
          f"(secao {secao:.1f} m2, volume {secao * g['comprimento']:.0f} m3)")
    print(f"Exaustor: {cfg['exaustores']['vazao_m3h_cada']:.0f} m3/h cada")
    print(f"Para {alvo} m/s de velocidade media sao necessarios ~{necessarios} exaustores.\n")
    print(f"{'Exaust.':>7} {'Vazao m3/h':>11} {'Vel. m/s':>9} {'Troca ar s':>11} "
          f"{'dT C':>6} {'T saida C':>10} {'Vel. pad m/s':>13}")
    for n in quantidades:
        r = calcular(cfg, n)
        print(f"{r['exaustores']:>7} {r['vazao_m3h']:>11.0f} {r['velocidade_m_s']:>9.2f} "
              f"{r['troca_ar_s']:>11.0f} {r['delta_t_C']:>6.2f} {r['t_saida_C']:>10.1f} "
              f"{r['vel_entrada_m_s']:>13.2f}")
    print("\nReferencias: troca de ar <= 60 s em tunel; velocidade no pad ~1,8-2,0 m/s "
          "(acima disso o pad perde eficiencia e arrasta agua).")


if __name__ == "__main__":
    main()
