#!/usr/bin/env python3
"""Editor 3D do projeto: abre no navegador para posicionar exaustores, entradas de ar e itens,
editar os dados dos exaustores (motor, polias, helice), rodar a simulacao e ver o resultado.

Uso:
  python3 editor.py modelos/<missao>/config.json      # projeto importado do DJI Terra
  python3 editor.py config_exemplo.json               # galpao so com dimensoes
Depois abra no navegador (Windows tambem):  http://localhost:8765

Tudo fica salvo no proprio config.json do projeto (com copia .bak a cada gravacao).
"""
import argparse
import copy
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import exaustor as modelo_exaustor
import gerar_caso
import preparar_item

AQUI = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(AQUI, "editor")
BIBLIOTECA = preparar_item.BIBLIOTECA

estado = {"config": None, "base": None, "job": None}
trava = threading.Lock()


# --------------------------------------------------------------------------- utilidades

def ler_config():
    with open(estado["config"], encoding="utf-8") as f:
        return json.load(f)


def salvar_config(cfg):
    if os.path.exists(estado["config"]):
        shutil.copy(estado["config"], estado["config"] + ".bak")
    with open(estado["config"], "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def cfg_absoluta(cfg):
    """Copia com caminhos absolutos, para chamar as funcoes do gerador."""
    c = copy.deepcopy(cfg)
    base = estado["base"]
    if c.get("envoltoria_stl"):
        c["envoltoria_stl"] = os.path.join(base, c["envoltoria_stl"])
    return c


def caminho_seguro(rel):
    """So entrega arquivos de dentro da pasta do projeto ou da pasta do simulador."""
    raizes = [os.path.realpath(r) + os.sep for r in (estado["base"], AQUI)]
    for raiz in (estado["base"], AQUI):
        p = os.path.realpath(os.path.join(raiz, rel))
        if any(p.startswith(r) for r in raizes) and os.path.isfile(p):
            return p
    return None


def biblioteca():
    itens = []
    for js in sorted(glob_json(BIBLIOTECA)):
        with open(js, encoding="utf-8") as f:
            ficha = json.load(f)
        stl = os.path.join(BIBLIOTECA, ficha["nome"] + ".stl")
        ficha["arquivo"] = os.path.relpath(stl, estado["base"])
        ficha["url"] = "/arquivo?c=" + urllib.parse.quote(ficha["arquivo"])
        itens.append(ficha)
    return itens


def glob_json(pasta):
    if not os.path.isdir(pasta):
        return []
    return [os.path.join(pasta, f) for f in os.listdir(pasta) if f.endswith(".json")]


def operacao(cfg):
    c = cfg_absoluta(cfg)
    lista = gerar_caso.posicionar_exaustores(c)
    p, qs = modelo_exaustor.resolver(c, [e["exaustor"] for e in lista])
    return {
        "pressao_Pa": round(p, 1),
        "vazao_total_m3h": round(sum(qs) * 3600),
        "exaustores": [{"parede": e["parede"], "posicao": round(e["centro"], 3), "altura": round(e["z"], 3),
                        "modelo": e["modelo"], "lado": e["lado"], "vazao_m3h": round(q * 3600)}
                       for e, q in zip(lista, qs)],
    }


def ficha_modelo(cfg, nome):
    mods = modelo_exaustor.modelos(cfg)
    if nome not in mods:
        return None
    mod = mods[nome]
    try:
        op = operacao(cfg)
        p = op["pressao_Pa"]
    except Exception:
        p = None
    curva = []
    passo = max(1.0, mod.pmax / 30)
    pp = 0.0
    while pp < mod.pmax:
        curva.append([round(pp, 1), round(mod.vazao(pp) * 3600)])
        pp += passo
    return {"ficha": mod.ficha(p), "curva": curva, "rpm_helice": round(mod.rpm), "moldura_m": mod.moldura,
            "pressao_Pa": p}


# --------------------------------------------------------------------------- tarefas em segundo plano

def iniciar_job(tipo, comando, ao_terminar=None):
    with trava:
        if estado["job"] and estado["job"]["proc"].poll() is None:
            return False
        log = os.path.join(AQUI, f"editor_{tipo}.log")
        f = open(log, "w")
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(["bash", "-c", comando], stdout=f, stderr=subprocess.STDOUT, cwd=AQUI, env=env)
        estado["job"] = {"tipo": tipo, "proc": proc, "log": log, "inicio": time.time(), "fim": ao_terminar,
                         "arquivo": f}
    return True


def status_job():
    job = estado["job"]
    if not job:
        return {"rodando": False}
    rodando = job["proc"].poll() is None
    with open(job["log"], encoding="utf-8", errors="replace") as f:
        texto = f.read()
    r = {"tipo": job["tipo"], "rodando": rodando, "codigo": job["proc"].returncode,
         "segundos": round(time.time() - job["inicio"]), "log": texto[-6000:]}
    m = re.findall(r"^Time = (\d+)", texto, re.M)
    if job["tipo"] == "simulacao":
        caso = job.get("caso")
        logrun = os.path.join(caso, "log.foamRun") if caso else None
        if logrun and os.path.exists(logrun):
            with open(logrun, errors="replace") as f2:
                m = re.findall(r"^Time = (\d+)", f2.read(), re.M)
        if m:
            r["iteracao"] = int(m[-1])
        r["iteracoes"] = job.get("iteracoes")
        r["caso"] = caso and os.path.relpath(caso, AQUI)
    return r


# --------------------------------------------------------------------------- HTTP

class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def responder(self, obj, codigo=200):
        dados = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def arquivo(self, caminho):
        if not caminho or not os.path.isfile(caminho):
            self.send_error(404)
            return
        tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
        with open(caminho, "rb") as f:
            dados = f.read()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def corpo(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path in ("/", "/index.html"):
            return self.arquivo(os.path.join(WEB, "index.html"))
        if url.path.startswith("/web/"):
            p = os.path.realpath(os.path.join(WEB, url.path[5:]))
            return self.arquivo(p if p.startswith(os.path.realpath(WEB)) else None)
        if url.path == "/arquivo":
            return self.arquivo(caminho_seguro(q.get("c", [""])[0]))
        if url.path == "/api/projeto":
            cfg = ler_config()
            env = cfg.get("envoltoria_stl")
            try:
                op = operacao(cfg)
                erro = None
            except BaseException as e:  # SystemExit de modelo inexistente, etc.
                op, erro = None, str(e)
            return self.responder({
                "config": cfg, "arquivo": estado["config"],
                "envoltoria_url": "/arquivo?c=" + urllib.parse.quote(env) if env else None,
                "biblioteca": biblioteca(), "operacao": op, "erro": erro,
            })
        if url.path == "/api/status":
            return self.responder(status_job())
        if url.path == "/api/resultado":
            return self.responder(resultado(q.get("caso", [""])[0]))
        self.send_error(404)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/api/salvar":
                cfg = json.loads(self.corpo())
                salvar_config(cfg)
                return self.responder({"ok": True, "operacao": operacao(cfg)})
            if url.path == "/api/operacao":
                return self.responder(operacao(json.loads(self.corpo())))
            if url.path == "/api/exaustor":
                d = json.loads(self.corpo())
                return self.responder(ficha_modelo(d["config"], d["modelo"]) or {"erro": "modelo inexistente"})
            if url.path == "/api/simular":
                return self.simular(json.loads(self.corpo()))
            if url.path == "/api/item":
                return self.receber_item(q)
            if url.path == "/api/foto":
                return self.receber_foto(q)
            if url.path == "/api/fotos/processar":
                return self.processar_fotos(json.loads(self.corpo()))
        except BaseException as e:
            return self.responder({"erro": str(e)}, 400)
        self.send_error(404)

    # ---- acoes
    def simular(self, d):
        cfg = d["config"]
        salvar_config(cfg)
        nome = re.sub(r"[^\w.-]", "_", cfg.get("nome", "projeto"))
        caso = os.path.join(AQUI, "casos", nome)
        args = [f'--saida "{caso}"']
        for chave, opc in (("celula", "--celula"), ("iteracoes", "--iteracoes"), ("nucleos", "--nucleos")):
            if d.get(chave):
                args.append(f"{opc} {float(d[chave]) if chave == 'celula' else int(d[chave])}")
        fonte = '[ -n "$WM_PROJECT_DIR" ] || . /opt/openfoam12/etc/bashrc; '
        cmd = (fonte + f'"{sys.executable}" gerar_caso.py "{estado["config"]}" {" ".join(args)} '
               f'&& "{caso}/Allrun"')
        if not iniciar_job("simulacao", cmd):
            return self.responder({"erro": "ja existe uma tarefa rodando"}, 409)
        estado["job"]["caso"] = caso
        estado["job"]["iteracoes"] = int(d.get("iteracoes") or cfg["solver"]["iteracoes"])
        return self.responder({"ok": True, "caso": os.path.relpath(caso, AQUI)})

    def receber_item(self, q):
        nome = re.sub(r"[^\w-]", "_", q["nome"][0])
        arq = os.path.basename(q["arquivo"][0])
        destino = os.path.join(BIBLIOTECA, "originais", nome + os.path.splitext(arq)[1].lower())
        os.makedirs(os.path.dirname(destino), exist_ok=True)
        with open(destino, "wb") as f:
            f.write(self.corpo())
        ficha = preparar_item.preparar(destino, nome, q.get("medida", [None])[0] or None,
                                       float(q["escala"][0]) if q.get("escala", [""])[0] else None,
                                       q.get("vertical", ["auto"])[0])
        return self.responder(ficha)

    def receber_foto(self, q):
        lote = re.sub(r"[^\w-]", "_", q["lote"][0])
        pasta = os.path.join(AQUI, "fotogrametria", lote, "fotos")
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, os.path.basename(q["arquivo"][0])), "wb") as f:
            f.write(self.corpo())
        return self.responder({"ok": True, "total": len(os.listdir(pasta))})

    def processar_fotos(self, d):
        lote = re.sub(r"[^\w-]", "_", d["nome"])
        pasta = os.path.join(AQUI, "fotogrametria", lote, "fotos")
        cmd = f'"{sys.executable}" fotos_para_3d.py "{pasta}" --nome {lote}'
        if d.get("medida"):
            cmd += f' --medida "{d["medida"]}"'
        if d.get("rapido"):
            cmd += " --rapido"
        if not iniciar_job("fotos", cmd):
            return self.responder({"erro": "ja existe uma tarefa rodando"}, 409)
        return self.responder({"ok": True})


def resultado(caso_rel):
    caso = os.path.realpath(os.path.join(AQUI, caso_rel))
    if not caso.startswith(os.path.realpath(AQUI)) or not os.path.isdir(caso):
        return {"erro": "caso nao encontrado"}
    r = {"imagens": [], "relatorio": None, "plano": None}
    res = os.path.join(caso, "resultados")
    if os.path.isdir(res):
        r["imagens"] = ["/arquivo?c=" + urllib.parse.quote(os.path.relpath(os.path.join(res, f), AQUI))
                        for f in sorted(os.listdir(res)) if f.endswith(".png")]
        rel = os.path.join(res, "relatorio.md")
        if os.path.exists(rel):
            with open(rel, encoding="utf-8") as f:
                r["relatorio"] = f.read()
    pp = os.path.join(caso, "postProcessing", "planos")
    if os.path.isdir(pp):
        tempos = [t for t in os.listdir(pp) if t.replace(".", "", 1).isdigit()]
        if tempos:
            arq = os.path.join(pp, max(tempos, key=float), "alturaAnimais.xy")
            if os.path.exists(arq):
                import numpy as np
                d = np.loadtxt(arq, comments="#")
                if len(d) > 60000:
                    d = d[:: len(d) // 60000 + 1]
                vel = np.linalg.norm(d[:, 3:6], axis=1)
                r["plano"] = {"x": d[:, 0].round(3).tolist(), "y": d[:, 1].round(3).tolist(),
                              "z": d[:, 2].round(3).tolist(), "vel": vel.round(3).tolist(),
                              "T": (d[:, 6] - 273.15).round(2).tolist()}
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="config.json do projeto")
    ap.add_argument("--porta", type=int, default=8765)
    args = ap.parse_args()
    estado["config"] = os.path.abspath(args.config)
    estado["base"] = os.path.dirname(estado["config"])
    servidor = ThreadingHTTPServer(("0.0.0.0", args.porta), Manipulador)
    print(f"Editor do projeto {estado['config']}")
    print(f"Abra no navegador:  http://localhost:{args.porta}   (Ctrl+C para sair)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
