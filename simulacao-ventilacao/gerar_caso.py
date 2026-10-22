#!/usr/bin/env python3
"""Gera um caso OpenFOAM 12 de ventilacao em tunel para galpao (aviario ou suinos).

O caso simula, em regime permanente:
  - o escoamento do ar puxado pelos exaustores (quantidade, vazao e posicao configuraveis);
  - a entrada de ar pelos pads/cortinas/inlets;
  - a temperatura, com o calor liberado pelos animais e o ganho solar do telhado;
  - o empuxo (ar quente sobe), via aproximacao de Boussinesq;
  - obstaculos internos opcionais vindos do seu modelo 3D (.stl).

Uso:
  python3 gerar_caso.py config_exemplo.json            # cria a pasta casos/<nome>
  python3 gerar_caso.py config.json --exaustores 10    # mesma config, outra quantidade
  python3 gerar_caso.py config.json --saida casos/teste --celula 0.5

Depois:  cd casos/<nome> && ./Allrun
"""
import argparse
import copy
import json
import os
import shutil
import stat

import exaustor as modelo_exaustor
import geometria

CABECALHO = """/*--------------------------------*- C++ -*----------------------------------*\\
  Gerado por gerar_caso.py (simulacao-ventilacao) - OpenFOAM 12
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       {classe};
    object      {objeto};
}}

"""

PAREDES = ("frente", "fundo", "esquerda", "direita", "piso", "telhado")
RHO = 1.16
CP = 1005.0


def escrever(caso, caminho, classe, conteudo):
    destino = os.path.join(caso, caminho)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    objeto = os.path.basename(caminho)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(CABECALHO.format(classe=classe, objeto=objeto))
        f.write(conteudo.strip() + "\n")


def vec(v):
    return "(" + " ".join(f"{c:.6g}" for c in v) + ")"


# --------------------------------------------------------------------------- geometria

def limites_stl(caminho):
    """(min, max) dos vertices de um STL ASCII ou binario."""
    import struct
    with open(caminho, "rb") as f:
        dados = f.read()
    pts = []
    if dados[:5] == b"solid" and b"facet" in dados[:1000]:
        for linha in dados.decode("utf-8", "ignore").splitlines():
            linha = linha.strip()
            if linha.startswith("vertex"):
                pts.append(tuple(float(v) for v in linha.split()[1:4]))
    else:
        n = struct.unpack("<I", dados[80:84])[0]
        for i in range(n):
            base = 84 + i * 50 + 12
            for k in range(3):
                pts.append(struct.unpack("<3f", dados[base + 12 * k: base + 12 * k + 12]))
    if not pts:
        raise ValueError(f"STL sem vertices: {caminho}")
    return tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3))


def posicionar_exaustores(cfg):
    """Lista de exaustores: dict(nome, parede, centro, z, lado, modelo, exaustor).

    'exaustor' e o objeto que da a vazao em funcao da pressao: o modelo calculado a partir de
    motor/polias/helice (modelos_exaustor) ou, sem modelo, a vazao fixa vazao_m3h_cada.
    """
    lista = _posicoes(cfg)
    modelos = modelo_exaustor.modelos(cfg)
    padrao = cfg["exaustores"].get("modelo")
    for e in lista:
        e["modelo"] = e.get("modelo") or padrao
        if e["modelo"]:
            if e["modelo"] not in modelos:
                raise SystemExit(f"modelo de exaustor '{e['modelo']}' nao existe em modelos_exaustor")
            e["exaustor"] = modelos[e["modelo"]]
            e["lado"] = e["exaustor"].moldura
        else:
            e["exaustor"] = modelo_exaustor.VazaoFixa(cfg["exaustores"]["vazao_m3h_cada"], e["lado"])
    return lista


def _posicoes(cfg):
    g = cfg["galpao"]
    ex = cfg["exaustores"]
    lado = ex["lado_m"]
    z = ex["altura_centro_m"]
    if ex.get("posicoes_manuais"):
        return [
            {"nome": f"exaustor_{i + 1:02d}", "parede": p["parede"], "centro": p["posicao"],
             "z": p.get("altura", z), "lado": lado, "modelo": p.get("modelo")}
            for i, p in enumerate(ex["posicoes_manuais"])
        ]

    n = ex["quantidade"]
    folga = 0.25
    cabem_fundo = max(1, int((g["largura"] - folga) // (lado + folga)))
    no_fundo = min(n, cabem_fundo)
    lista = []
    passo = g["largura"] / no_fundo
    for i in range(no_fundo):
        lista.append({"parede": "fundo", "centro": passo * (i + 0.5), "z": z, "lado": lado})
    # o que nao couber no fundo vai para as laterais, perto do fundo, alternando os lados
    for j in range(n - no_fundo):
        parede = "esquerda" if j % 2 == 0 else "direita"
        k = j // 2
        centro = g["comprimento"] - (lado / 2 + folga) - k * (lado + folga)
        lista.append({"parede": parede, "centro": centro, "z": z, "lado": lado})
    for i, e in enumerate(lista):
        e["nome"] = f"exaustor_{i + 1:02d}"
    return lista


def caixa_na_parede(g, parede, a0, a1, z0, z1, eps):
    """Caixa fina (min, max) que pega so as faces da parede indicada."""
    L, W, H = g["comprimento"], g["largura"], g["altura"]
    if parede == "fundo":
        return (L - eps, a0, z0), (L + eps, a1, z1)
    if parede == "frente":
        return (-eps, a0, z0), (eps, a1, z1)
    if parede == "esquerda":
        return (a0, -eps, z0), (a1, eps, z1)
    if parede == "direita":
        return (a0, W - eps, z0), (a1, W + eps, z1)
    if parede == "telhado":  # a0/a1 em x, z0/z1 usados como y
        return (a0, z0, H - eps), (a1, z1, H + eps)
    raise ValueError(f"parede desconhecida: {parede}")


def aberturas(cfg, dx):
    """Lista (nome_patch, parede, caixa) para exaustores e entradas de ar."""
    g = cfg["galpao"]
    eps = dx * (0.75 if cfg.get("envoltoria_stl") else 0.25)
    lista = []
    for e in posicionar_exaustores(cfg):
        meio = e["lado"] / 2
        caixa = caixa_na_parede(g, e["parede"], e["centro"] - meio, e["centro"] + meio,
                                e["z"] - meio, e["z"] + meio, eps)
        lista.append((e["nome"], e["parede"], caixa, "exaustor"))
    for ent in cfg["entradas_ar"]:
        caixa = caixa_na_parede(g, ent["parede"], ent["inicio"], ent["fim"],
                                ent["z_min"], ent["z_max"], eps)
        lista.append(("entrada_" + ent["nome"], ent["parede"], caixa, "entrada"))
    return lista


# --------------------------------------------------------------------------- arquivos

def block_mesh(caso, cfg, dx):
    g = cfg["galpao"]
    if cfg.get("envoltoria_stl"):
        # caixa de fundo um pouco maior que o modelo; o snappyHexMesh recorta o interior
        pmin, pmax = limites_stl(cfg["envoltoria_stl"])
        pmin = [c - 2 * dx for c in pmin]
        pmax = [c + 2 * dx for c in pmax]
    else:
        pmin, pmax = [0.0, 0.0, 0.0], [g["comprimento"], g["largura"], g["altura"]]
    (x0, y0, z0), (x1, y1, z1) = pmin, pmax
    nx, ny, nz = (max(2, round((b - a) / dx)) for a, b in zip(pmin, pmax))
    escrever(caso, "system/blockMeshDict", "dictionary", f"""
convertToMeters 1;

vertices
(
    ({x0} {y0} {z0}) ({x1} {y0} {z0}) ({x1} {y1} {z0}) ({x0} {y1} {z0})
    ({x0} {y0} {z1}) ({x1} {y0} {z1}) ({x1} {y1} {z1}) ({x0} {y1} {z1})
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

boundary
(
    frente   {{ type wall; faces ((0 4 7 3)); }}
    fundo    {{ type wall; faces ((1 2 6 5)); }}
    esquerda {{ type wall; faces ((0 1 5 4)); }}
    direita  {{ type wall; faces ((3 7 6 2)); }}
    piso     {{ type wall; faces ((0 3 2 1)); }}
    telhado  {{ type wall; faces ((4 5 6 7)); }}
);
""")
    return nx * ny * nz


def snappy(caso, cfg, dx):
    stls = cfg.get("obstaculos_stl") or []
    itens = cfg.get("itens") or []
    envoltoria = cfg.get("envoltoria_stl")
    if not stls and not envoltoria and not itens:
        return False
    os.makedirs(os.path.join(caso, "constant/geometry"), exist_ok=True)
    geom, refin = [], []
    if envoltoria:
        shutil.copy(envoltoria, os.path.join(caso, "constant/geometry/envoltoria.stl"))
        geom.append('    envoltoria { type triSurfaceMesh; file "envoltoria.stl"; }')
        refin.append("        envoltoria { level (0 0); patchInfo { type wall; } }")
    for i, origem in enumerate(stls):
        nome = f"obstaculo_{i + 1:02d}"
        shutil.copy(origem, os.path.join(caso, "constant/geometry", nome + ".stl"))
        geom.append(f"    {nome} {{ type triSurfaceMesh; file \"{nome}.stl\"; }}")
        refin.append(f"        {nome} {{ level (1 1); patchInfo {{ type wall; }} }}")
    for i, item in enumerate(itens):
        # itens da biblioteca, ja posicionados/girados/escalados como no editor
        nome = f"item_{i + 1:02d}"
        tris = geometria.transformar(geometria.ler_malha(item["arquivo"]), item.get("posicao", (0, 0, 0)),
                                     item.get("rotacao_graus", (0, 0, 0)), item.get("escala", 1.0))
        geometria.escrever_stl(os.path.join(caso, "constant/geometry", nome + ".stl"), tris, nome)
        geom.append(f"    {nome} {{ type triSurfaceMesh; file \"{nome}.stl\"; }}")
        refin.append(f"        {nome} {{ level (1 1); patchInfo {{ type wall; }} }}")
    g = cfg["galpao"]
    # ponto que com certeza esta no ar, dentro do galpao (fora dos obstaculos)
    ponto = cfg.get("ponto_no_ar") or [g["comprimento"] * 0.5 + 0.0123, g["largura"] * 0.5 + 0.0123,
                                       g["altura"] * 0.85 + 0.0123]
    escrever(caso, "system/snappyHexMeshDict", "dictionary", f"""
castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
{chr(10).join(geom)}
}}

castellatedMeshControls
{{
    maxLocalCells       2000000;
    maxGlobalCells      20000000;
    minRefinementCells  0;
    nCellsBetweenLevels 2;
    features            ();
    refinementSurfaces
    {{
{chr(10).join(refin)}
    }}
    resolveFeatureAngle 30;
    refinementRegions   {{}}
    insidePoint         {vec(ponto)};
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch 3;
    tolerance 2.0;
    nSolveIter 50;
    nRelaxIter 5;
}}

addLayersControls
{{
    relativeSizes true;
    layers {{}}
    expansionRatio 1.2;
    finalLayerThickness 0.5;
    minThickness 0.1;
}}

meshQualityControls
{{
    #includeEtc "caseDicts/mesh/generation/meshQualityDict"
}}

mergeTolerance 1e-6;
""")
    return True


def topo_set_e_patches(caso, cfg, dx):
    g = cfg["galpao"]
    acoes, patches = [], []
    for nome, parede, (cmin, cmax), _ in aberturas(cfg, dx):
        origem = "envoltoria" if cfg.get("envoltoria_stl") else parede
        acoes.append(f"""    {{ name {nome}; type faceSet; action new; source patchToFace; patch {origem}; }}
    {{ name {nome}; type faceSet; action subset; source boxToFace; box {vec(cmin)} {vec(cmax)}; }}""")
        patches.append(f"    {{ name {nome}; patchInfo {{ type patch; }} constructFrom set; set {nome}; }}")

    alt_animais = cfg["analise"]["altura_animais_m"]
    camada_animais = max(alt_animais, 1.5 * dx)
    camada_telhado = 1.5 * dx
    L, W, H = g["comprimento"], g["largura"], g["altura"]
    acoes.append(f"""    {{ name animais; type cellSet; action new; source boxToCell; box (-1 -1 -1) ({L + 1} {W + 1} {camada_animais}); }}
    {{ name animais; type cellZoneSet; action new; source setToCellZone; set animais; }}
    {{ name telhado; type cellSet; action new; source boxToCell; box (-1 -1 {H - camada_telhado}) ({L + 1} {W + 1} {H + 1}); }}
    {{ name telhado; type cellZoneSet; action new; source setToCellZone; set telhado; }}""")

    escrever(caso, "system/topoSetDict", "dictionary", "actions\n(\n" + "\n".join(acoes) + "\n);")
    escrever(caso, "system/createPatchDict", "dictionary",
             "pointSync false;\n\npatches\n(\n" + "\n".join(patches) + "\n);")


def campos(caso, cfg, vazoes):
    """vazoes: {nome_do_patch: m3/s} de cada exaustor."""
    t_in = cfg["clima"]["temperatura_entrada_C"] + 273.15
    t_0 = cfg["clima"].get("temperatura_inicial_C", cfg["clima"]["temperatura_entrada_C"]) + 273.15
    parede = "wall"
    exaust = '"exaustor_.*"'
    entrada = '"entrada_.*"'

    def bf(itens):
        return "boundaryField\n{\n" + "\n".join(
            f"    {k}\n    {{\n" + "\n".join(f"        {l}" for l in v) + "\n    }" for k, v in itens
        ) + "\n}"

    escrever(caso, "0/U", "volVectorField", "dimensions [0 1 -1 0 0 0 0];\ninternalField uniform (0 0 0);\n" + bf([
        (parede, ["type noSlip;"]),
    ] + [
        (nome, ["type flowRateOutletVelocity;", f"volumetricFlowRate {q:.6g};", "value uniform (0 0 0);"])
        for nome, q in vazoes.items()
    ] + [
        (entrada, ["type pressureInletOutletVelocity;", "value uniform (0 0 0);"]),
    ]))
    escrever(caso, "0/p_rgh", "volScalarField", "dimensions [1 -1 -2 0 0 0 0];\ninternalField uniform 0;\n" + bf([
        (parede, ["type fixedFluxPressure;", "value $internalField;"]),
        (exaust, ["type fixedFluxPressure;", "value $internalField;"]),
        (entrada, ["type prghTotalPressure;", "p0 uniform 0;", "value $internalField;"]),
    ]))
    escrever(caso, "0/p", "volScalarField", "dimensions [1 -1 -2 0 0 0 0];\ninternalField uniform 0;\n" + bf([
        ('".*"', ["type calculated;", "value $internalField;"]),
    ]))
    escrever(caso, "0/T", "volScalarField", f"dimensions [0 0 0 1 0 0 0];\ninternalField uniform {t_0:.2f};\n" + bf([
        (parede, ["type zeroGradient;"]),
        (exaust, ["type inletOutlet;", f"inletValue uniform {t_in:.2f};", "value $internalField;"]),
        (entrada, ["type inletOutlet;", f"inletValue uniform {t_in:.2f};", f"value uniform {t_in:.2f};"]),
    ]))
    escrever(caso, "0/k", "volScalarField", "dimensions [0 2 -2 0 0 0 0];\ninternalField uniform 0.01;\n" + bf([
        (parede, ["type kqRWallFunction;", "value $internalField;"]),
        (exaust, ["type inletOutlet;", "inletValue $internalField;", "value $internalField;"]),
        (entrada, ["type turbulentIntensityKineticEnergyInlet;", "intensity 0.05;", "value $internalField;"]),
    ]))
    escrever(caso, "0/epsilon", "volScalarField", "dimensions [0 2 -3 0 0 0 0];\ninternalField uniform 0.001;\n" + bf([
        (parede, ["type epsilonWallFunction;", "value $internalField;"]),
        (exaust, ["type inletOutlet;", "inletValue $internalField;", "value $internalField;"]),
        (entrada, ["type turbulentMixingLengthDissipationRateInlet;", "mixingLength 0.1;", "value $internalField;"]),
    ]))
    escrever(caso, "0/nut", "volScalarField", "dimensions [0 2 -1 0 0 0 0];\ninternalField uniform 0;\n" + bf([
        (parede, ["type nutkWallFunction;", "value uniform 0;"]),
        ('"(exaustor|entrada)_.*"', ["type calculated;", "value uniform 0;"]),
    ]))
    escrever(caso, "0/alphat", "volScalarField", "dimensions [1 -1 -1 0 0 0 0];\ninternalField uniform 0;\n" + bf([
        (parede, ["type compressible::alphatJayatillekeWallFunction;", "Prt 0.85;", "value uniform 0;"]),
        ('"(exaustor|entrada)_.*"', ["type calculated;", "value uniform 0;"]),
    ]))


def constantes(caso, cfg):
    t_in = cfg["clima"]["temperatura_entrada_C"] + 273.15
    escrever(caso, "constant/g", "uniformDimensionedVectorField",
             "dimensions [0 1 -2 0 0 0 0];\nvalue (0 0 -9.81);")
    escrever(caso, "constant/momentumTransport", "dictionary",
             "simulationType RAS;\n\nRAS\n{\n    model realizableKE;\n    turbulence on;\n    printCoeffs on;\n}")
    escrever(caso, "constant/physicalProperties", "dictionary", f"""
thermoType
{{
    type            heRhoThermo;
    mixture         pureMixture;
    transport       const;
    thermo          hConst;
    equationOfState Boussinesq;
    specie          specie;
    energy          sensibleEnthalpy;
}}

mixture
{{
    specie          {{ molWeight 28.96; }}
    equationOfState {{ rho0 {RHO}; T0 {t_in:.2f}; beta {1.0 / t_in:.6g}; }}
    thermodynamics  {{ Cp {CP}; hf 0; }}
    transport       {{ mu 1.85e-05; Pr 0.71; }}
}}
""")
    g = cfg["galpao"]
    area = g["comprimento"] * g["largura"]
    c = cfg["cargas_termicas"]
    escrever(caso, "constant/fvModels", "dictionary", f"""
calorAnimais
{{
    type        heatSource;
    select      cellZone;
    cellZone    animais;
    Q           {c['calor_animais_W_m2'] * area:.6g};   // W  ({c['calor_animais_W_m2']} W/m2 x {area:.0f} m2)
}}

calorTelhado
{{
    type        heatSource;
    select      cellZone;
    cellZone    telhado;
    Q           {c['calor_telhado_W_m2'] * area:.6g};   // W  ({c['calor_telhado_W_m2']} W/m2 x {area:.0f} m2)
}}
""")


def sistema(caso, cfg, dx):
    s = cfg["solver"]
    g = cfg["galpao"]
    n_iter = s["iteracoes"]
    # intervalo de gravacao que divide n_iter, para a ultima iteracao sempre ser gravada
    intervalo = next(d for d in (500, 250, 200, 100, 50, 10, 1) if n_iter % d == 0)
    z_animais = cfg["analise"]["altura_animais_m"]
    escrever(caso, "system/controlDict", "dictionary", f"""
application     foamRun;
solver          fluid;

startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {n_iter};
deltaT          1;
writeControl    timeStep;
writeInterval   {intervalo};
purgeWrite      2;
writeFormat     binary;
writePrecision  7;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    vazaoExaustores
    {{
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    timeStep;
        writeInterval   10;
        log             false;
        writeFields     false;
        select          patches;
        patches         ("exaustor_.*");
        operation       sum;
        fields          (phi);
    }}

    vazaoEntradas
    {{
        $vazaoExaustores;
        patches         ("entrada_.*");
    }}

    temperaturaExaustores
    {{
        type            surfaceFieldValue;
        libs            ("libfieldFunctionObjects.so");
        writeControl    timeStep;
        writeInterval   10;
        log             false;
        writeFields     false;
        select          patches;
        patches         ("exaustor_.*");
        operation       areaAverage;
        fields          (T);
    }}

    planos
    {{
        type            surfaces;
        libs            ("libsampling.so");
        writeControl    writeTime;
        interpolationScheme cellPoint;
        surfaceFormat   raw;
        fields          (U T);
        surfaces
        (
            alturaAnimais
            {{
                type        cuttingPlane;
                planeType   pointAndNormal;
                point       (0 0 {z_animais});
                normal      (0 0 1);
                interpolate true;
            }}
            corteLongitudinal
            {{
                type        cuttingPlane;
                planeType   pointAndNormal;
                point       (0 {g['largura'] / 2 + 1e-3} 0);
                normal      (0 1 0);
                interpolate true;
            }}
        );
    }}
}}
""")
    escrever(caso, "system/fvSchemes", "dictionary", """
ddtSchemes      { default steadyState; }
gradSchemes     { default Gauss linear; limited cellLimited Gauss linear 1; grad(U) $limited; grad(k) $limited; grad(epsilon) $limited; }
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss linearUpwindV limited;
    div(phi,h)      bounded Gauss linearUpwind limited;
    div(phi,k)      bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div(phi,K)      bounded Gauss linear;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear limited corrected 0.5; }
interpolationSchemes { default linear; }
snGradSchemes   { default limited corrected 0.5; }
wallDist        { method meshWave; }
""")
    escrever(caso, "system/fvSolution", "dictionary", """
solvers
{
    p_rgh
    {
        solver          GAMG;
        smoother        DIC;
        tolerance       1e-6;
        relTol          0.05;
    }
    "(U|h|k|epsilon)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-7;
        relTol          0.1;
    }
}

PIMPLE
{
    momentumPredictor yes;
    residualControl
    {
        p_rgh           1e-3;
        U               1e-4;
        h               1e-4;
        "(k|epsilon)"   1e-4;
    }
}

relaxationFactors
{
    fields      { p_rgh 0.3; }
    equations   { U 0.5; h 0.5; "(k|epsilon)" 0.5; }
}
""")
    escrever(caso, "system/decomposeParDict", "dictionary",
             f"numberOfSubdomains {s['nucleos_cpu']};\n\ndecomposer scotch;")


def allrun(caso, cfg, tem_stl):
    n = cfg["solver"]["nucleos_cpu"]
    mesh_stl = "runApplication snappyHexMesh -overwrite || falhou snappyHexMesh\n" if tem_stl else ""
    if n > 1:
        rodar = ("runApplication decomposePar -force || falhou decomposePar\n"
                 "runParallel foamRun || falhou foamRun\n"
                 "runApplication reconstructPar -latestTime || falhou reconstructPar\n")
    else:
        rodar = "runApplication foamRun || falhou foamRun\n"
    texto = f"""#!/bin/sh
cd "${{0%/*}}" || exit 1
. $WM_PROJECT_DIR/bin/tools/RunFunctions

falhou() {{ echo "ERRO em $1 - veja o arquivo log.$1 nesta pasta"; exit 1; }}

runApplication blockMesh || falhou blockMesh
{mesh_stl}runApplication topoSet || falhou topoSet
runApplication createPatch -overwrite || falhou createPatch
runApplication checkMesh || falhou checkMesh
{rodar}
touch caso.foam
python3 "{os.path.abspath(os.path.join(os.path.dirname(__file__), 'pos_processar.py'))}" .
"""
    caminho = os.path.join(caso, "Allrun")
    with open(caminho, "w") as f:
        f.write(texto)
    os.chmod(caminho, os.stat(caminho).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--saida", help="pasta do caso (padrao: casos/<nome>)")
    ap.add_argument("--exaustores", type=int, help="sobrescreve a quantidade de exaustores")
    ap.add_argument("--celula", type=float, help="sobrescreve o tamanho de celula (m)")
    ap.add_argument("--iteracoes", type=int)
    ap.add_argument("--nucleos", type=int)
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg = copy.deepcopy(cfg)
    base = os.path.dirname(os.path.abspath(args.config))
    cfg["obstaculos_stl"] = [os.path.join(base, p) for p in cfg.get("obstaculos_stl", [])]
    if cfg.get("envoltoria_stl"):
        cfg["envoltoria_stl"] = os.path.join(base, cfg["envoltoria_stl"])
    for item in cfg.get("itens", []):
        item["arquivo"] = os.path.join(base, item["arquivo"])
    if args.exaustores:
        cfg["exaustores"]["quantidade"] = args.exaustores
        cfg["exaustores"]["posicoes_manuais"] = []
        cfg["nome"] = f"{cfg['nome']}_{args.exaustores}ex"
    if args.celula:
        cfg["malha"]["tamanho_celula"] = args.celula
    if args.iteracoes:
        cfg["solver"]["iteracoes"] = args.iteracoes
    if args.nucleos:
        cfg["solver"]["nucleos_cpu"] = args.nucleos

    dx = cfg["malha"]["tamanho_celula"]
    dx_max = cfg["galpao"]["altura"] / 8
    if (cfg.get("envoltoria_stl") or cfg.get("itens") or cfg.get("obstaculos_stl")) and dx > dx_max:
        # com o modelo 3D, menos de 8 celulas na altura deixa a malha ruim e o calculo diverge
        print(f"AVISO: celula {dx} m e grossa demais para o pe-direito de {cfg['galpao']['altura']} m; "
              f"usando {dx_max:.2f} m.")
        dx = cfg["malha"]["tamanho_celula"] = round(dx_max, 2)
    caso = args.saida or os.path.join("casos", cfg["nome"])
    if os.path.exists(caso):
        shutil.rmtree(caso)
    os.makedirs(caso)

    lista = posicionar_exaustores(cfg)
    lado = min(e["lado"] for e in lista)
    if lado / dx < 3:
        print(f"AVISO: exaustor de {lado} m com celula de {dx} m fica com menos de 3 celulas "
              f"de lado; use celula <= {lado / 3:.2f} m para resultados confiaveis.")
    # ponto de operacao: pressao em que a vazao dos exaustores passa pelos pads/entradas
    p_op, qs = modelo_exaustor.resolver(cfg, [e["exaustor"] for e in lista])
    vazoes = {e["nome"]: q for e, q in zip(lista, qs)}
    cfg["operacao"] = {"pressao_estatica_Pa": round(p_op, 1),
                       "vazao_total_m3h": round(sum(qs) * 3600),
                       "exaustores": [{"nome": e["nome"], "modelo": e["modelo"], "parede": e["parede"],
                                       "centro": e["centro"], "altura": e["z"], "lado": e["lado"],
                                       "vazao_m3h": round(q * 3600)} for e, q in zip(lista, qs)]}

    n_cel = block_mesh(caso, cfg, dx)
    tem_stl = snappy(caso, cfg, dx)
    topo_set_e_patches(caso, cfg, dx)
    campos(caso, cfg, vazoes)
    constantes(caso, cfg)
    sistema(caso, cfg, dx)
    allrun(caso, cfg, tem_stl)
    with open(os.path.join(caso, "config_usada.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

    ram_gb = n_cel * 1.2e-6 * (1.3 if tem_stl else 1.0)
    print(f"Caso criado em: {caso}")
    print(f"Celulas: ~{n_cel / 1e6:.2f} milhoes  ->  RAM estimada ~{ram_gb:.1f} GB")
    print(f"Pressao estatica de operacao: {p_op:.1f} Pa  |  vazao total {sum(qs) * 3600:,.0f} m3/h")
    for e, q in zip(lista, qs):
        print(f"  {e['nome']}: parede {e['parede']}, centro {e['centro']:.2f} m, altura {e['z']:.2f} m, "
              f"{q * 3600:,.0f} m3/h" + (f" (modelo {e['modelo']})" if e["modelo"] else ""))
    print(f"Para rodar: cd {caso} && ./Allrun")


if __name__ == "__main__":
    main()
