#!/usr/bin/env python3
"""Modelo do exaustor a partir dos dados de motor, polias, correia e helice.

Calcula:
  - rotacao da helice (relacao de polias, com escorregamento da correia);
  - velocidade da correia e distancia entre centros (a partir do codigo da correia, ex. "A-62");
  - curva vazao x pressao estatica do exaustor;
  - ponto de operacao no galpao (cruzamento com a perda de carga dos pads/aberturas);
  - potencia exigida na helice x potencia do motor (sobrecarga).

Sem curva do fabricante, a curva e ESTIMADA pelas leis de semelhanca de ventiladores, a partir
de um exaustor de referencia de 50" tipico de aviario (1,27 m, 440 rpm, ~38.000 m3/h livre,
~101 Pa de pressao maxima, ~1 kW no eixo). Diferencas de projeto de pa podem dar +-15 %.
Se tiver a tabela do fabricante, informe "curva_fabricante" e ela passa a valer.

Uso:  python3 exaustor.py config.json          # ficha de cada modelo e ponto de operacao
"""
import json
import math
import re
import sys

RHO = 1.16
G = 9.81

# referencia (exaustor 50" de aviario, valores tipicos de catalogo)
REF = {"D": 1.27, "rpm": 440.0, "Q0": 38000 / 3600, "pmax": 101.0, "P_eixo": 1000.0,
       "angulo": 30.0, "pas": 6}
_U_REF = math.pi * REF["D"] * REF["rpm"] / 60
_A_REF = math.pi * REF["D"] ** 2 / 4
PHI0 = REF["Q0"] / (_A_REF * _U_REF)                 # coeficiente de vazao livre
PSI0 = REF["pmax"] / (RHO * _U_REF ** 2)            # coeficiente de pressao maxima
LAMBDA = REF["P_eixo"] / (RHO * (REF["rpm"] / 60) ** 3 * REF["D"] ** 5)  # coef. de potencia

# acrescimo do comprimento interno para o primitivo, em polegadas (perfis classicos)
PERFIS_CORREIA = {"A": 1.3, "B": 1.8, "C": 2.9, "D": 3.3, "Z": 0.9}


def fator_pas(m):
    """Efeito aproximado do angulo e do numero de pas em relacao a referencia."""
    ang = m.get("angulo_pas_graus", REF["angulo"])
    pas = m.get("pas", REF["pas"])
    f_ang = math.tan(math.radians(ang)) / math.tan(math.radians(REF["angulo"]))
    f_pas = (pas / REF["pas"]) ** 0.25
    return f_ang, f_pas


def correia(m, rpm_motor):
    """Dados da correia: velocidade (m/s) e distancia entre centros (m), se o codigo for conhecido."""
    d, D = m["polia_motor_mm"] / 1000, m["polia_helice_mm"] / 1000
    info = {"velocidade_m_s": math.pi * d * rpm_motor / 60}
    cod = re.match(r"\s*([A-Za-z])\s*-?\s*(\d+(?:[.,]\d+)?)", str(m.get("correia", "")))
    if cod and cod.group(1).upper() in PERFIS_CORREIA:
        perfil = cod.group(1).upper()
        interno_pol = float(cod.group(2).replace(",", "."))
        L = (interno_pol + PERFIS_CORREIA[perfil]) * 0.0254  # comprimento primitivo (m)
        b = 2 * L - math.pi * (D + d)
        disc = b * b - 8 * (D - d) ** 2
        if disc > 0:
            info["centros_m"] = (b + math.sqrt(disc)) / 8
        info["perfil"] = perfil
        info["comprimento_primitivo_m"] = L
    return info


class Exaustor:
    def __init__(self, nome, m):
        self.nome = nome
        self.m = m
        self.escorregamento = m.get("escorregamento_correia", 0.03)
        if "rpm_helice" in m:
            self.rpm = float(m["rpm_helice"])
        elif "polia_motor_mm" in m and "polia_helice_mm" in m:
            self.rpm = m["motor_rpm"] * m["polia_motor_mm"] / m["polia_helice_mm"] * (1 - self.escorregamento)
        else:
            self.rpm = m["motor_rpm"]  # acionamento direto
        self.D = m["helice_diametro_m"]
        self.moldura = m.get("moldura_m", round(self.D * 1.087, 2))
        self.potencia_motor_W = m.get("motor_cv", 0) * 735.5
        self.u_tip = math.pi * self.D * self.rpm / 60
        self.area = math.pi * self.D ** 2 / 4
        f_ang, f_pas = fator_pas(m)
        cal = m.get("fator_calibracao", 1.0)
        self.q0 = PHI0 * f_ang * cal * self.area * self.u_tip            # m3/s a 0 Pa
        self.pmax = PSI0 * f_ang * f_pas * RHO * self.u_tip ** 2           # Pa (vazao zero)
        self.p_eixo_ref = LAMBDA * f_ang * f_pas * RHO * (self.rpm / 60) ** 3 * self.D ** 5
        self.curva_fab = None
        if m.get("curva_fabricante"):
            # pontos [pressao_Pa, vazao_m3h] medidos na rotacao curva_rpm (padrao: rotacao calculada)
            r = self.rpm / m.get("curva_rpm", self.rpm)
            pts = sorted((p * r * r, q * r / 3600) for p, q in m["curva_fabricante"])
            self.curva_fab = pts
            self.q0 = max(q for _, q in pts)
            (p1, q1), (p2, q2) = pts[-2], pts[-1]
            # alem do ultimo ponto, prolonga a reta dos dois ultimos ate vazao zero
            self.pmax = p2 + (p2 - p1) * q2 / (q1 - q2) if q2 > 0 and q1 > q2 else p2

    def vazao(self, p):
        """Vazao (m3/s) a uma pressao estatica p (Pa)."""
        if p >= self.pmax:
            return 0.0
        if self.curva_fab:
            ps = [x for x, _ in self.curva_fab]
            qs = [y for _, y in self.curva_fab]
            if p <= ps[-1]:
                for i in range(len(ps) - 1):
                    if ps[i] <= p <= ps[i + 1]:
                        t = (p - ps[i]) / (ps[i + 1] - ps[i])
                        return qs[i] + t * (qs[i + 1] - qs[i])
                return qs[0]
            # alem do ultimo ponto: cai ate zero em pmax
            t = (p - ps[-1]) / (self.pmax - ps[-1])
            return qs[-1] * (1 - t)
        return self.q0 * math.sqrt(max(0.0, 1 - p / self.pmax))

    def potencia_eixo(self, q, p):
        """Potencia na helice (W): estimativa por semelhanca, corrigida pelo ponto de operacao."""
        # perto da vazao livre a potencia e a de referencia; com pressao sobe ate ~20 %
        return self.p_eixo_ref * (1 + 0.2 * p / self.pmax)

    def ficha(self, p_op=None):
        linhas = [f"Exaustor '{self.nome}'"]
        m = self.m
        if "polia_motor_mm" in m:
            linhas.append(f"  Motor {m.get('motor_cv', '?')} CV a {m['motor_rpm']} rpm, polias "
                          f"{m['polia_motor_mm']}/{m['polia_helice_mm']} mm "
                          f"(relacao {m['polia_helice_mm'] / m['polia_motor_mm']:.2f}:1)")
            c = correia(m, m["motor_rpm"])
            txt = f"  Correia {m.get('correia', '-')}: velocidade {c['velocidade_m_s']:.1f} m/s"
            if "centros_m" in c:
                txt += f", distancia entre centros {c['centros_m'] * 1000:.0f} mm"
            linhas.append(txt)
            if c["velocidade_m_s"] > 30:
                linhas.append("  AVISO: correia acima de 30 m/s (limite usual de correias em V)")
        linhas.append(f"  Helice {self.D:.2f} m, {m.get('pas', REF['pas'])} pas a "
                      f"{m.get('angulo_pas_graus', REF['angulo'])} graus, {self.rpm:.0f} rpm, "
                      f"ponta da pa a {self.u_tip:.1f} m/s")
        origem = "curva do fabricante" if self.curva_fab else "ESTIMADA por semelhanca (+-15 %)"
        linhas.append(f"  Curva ({origem}):")
        for p in (0, 10, 20, 30, 40, 50, 60):
            if p < self.pmax:
                linhas.append(f"    {p:>3} Pa -> {self.vazao(p) * 3600:>7,.0f} m3/h")
        if p_op is not None:
            q = self.vazao(p_op)
            pe = self.potencia_eixo(q, p_op)
            linhas.append(f"  No galpao ({p_op:.0f} Pa): {q * 3600:,.0f} m3/h por exaustor")
            if self.potencia_motor_W:
                carga = pe / 0.95 / self.potencia_motor_W  # 95 % de rendimento da transmissao
                linhas.append(f"  Potencia na helice ~{pe / 1000:.2f} kW; carga do motor ~{100 * carga:.0f} %"
                              + ("  <-- SOBRECARGA: motor pequeno para essa relacao de polias"
                                 if carga > 1.0 else ""))
        return "\n".join(linhas)


def perda_entradas(cfg, q_total):
    """Perda de carga (Pa) das entradas para a vazao total q_total (m3/s)."""
    entradas = cfg["entradas_ar"]
    area_total = sum((e["fim"] - e["inicio"]) * (e["z_max"] - e["z_min"]) for e in entradas)
    if area_total <= 0:
        return 0.0
    v = q_total / area_total
    dp = 0.0
    for e in entradas:
        a = (e["fim"] - e["inicio"]) * (e["z_max"] - e["z_min"])
        if e.get("tipo", "pad") == "pad":
            # pad celulose: ~25 Pa a 1,8 m/s com 150 mm (proporcional a espessura)
            dp_e = 7.7 * (e.get("espessura_mm", 150) / 150) * v ** 2
        else:
            dp_e = 0.5 * RHO * (v / 0.6) ** 2  # abertura/cortina, Cd = 0,6
        dp += dp_e * a / area_total
    return dp + cfg.get("sistema", {}).get("perda_extra_Pa", 3.0)  # galpao, telas, curvas


def resolver(cfg, exaustores):
    """Pressao estatica de operacao (Pa) e vazao de cada exaustor (m3/s).

    exaustores: lista de objetos Exaustor (um por exaustor instalado).
    """
    medida = cfg.get("sistema", {}).get("pressao_estatica_Pa")
    if medida is not None:
        return float(medida), [e.vazao(medida) for e in exaustores]
    lo, hi = 0.0, min(e.pmax for e in exaustores) if exaustores else 0.0
    for _ in range(60):  # bissecao: vazao dos exaustores = vazao que as entradas deixam passar
        p = 0.5 * (lo + hi)
        q = sum(e.vazao(p) for e in exaustores)
        if perda_entradas(cfg, q) > p:
            lo = p
        else:
            hi = p
    p = 0.5 * (lo + hi)
    return p, [e.vazao(p) for e in exaustores]


class VazaoFixa:
    """Exaustor sem modelo: vazao informada direto (vazao_m3h_cada), nao depende da pressao."""
    pmax = 1000.0

    def __init__(self, q_m3h, lado):
        self.q = q_m3h / 3600
        self.moldura = lado

    def vazao(self, p):
        return self.q


def modelos(cfg):
    return {nome: Exaustor(nome, m) for nome, m in cfg.get("modelos_exaustor", {}).items()}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        cfg = json.load(f)
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from gerar_caso import posicionar_exaustores
    lista = posicionar_exaustores(cfg)
    instalados = [e["exaustor"] for e in lista if e.get("exaustor")]
    p, qs = resolver(cfg, instalados) if instalados else (None, [])
    for mod in modelos(cfg).values():
        print(mod.ficha(p))
        print()
    if instalados:
        total = sum(qs) * 3600
        g = cfg["galpao"]
        print(f"Galpao: {len(instalados)} exaustores, pressao estatica {p:.1f} Pa, vazao total {total:,.0f} m3/h, "
              f"velocidade media {total / 3600 / (g['largura'] * g['altura']):.2f} m/s")


if __name__ == "__main__":
    main()
