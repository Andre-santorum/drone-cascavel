// Editor 3D de ventilacao. Coordenadas iguais as da simulacao: x = comprimento (exaustores no
// fim), y = largura, z = altura (para cima).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

const $ = (id) => document.getElementById(id);
const PAREDES = ["fundo", "esquerda", "direita", "frente"];
const COR = { exaustor: 0xe07a1f, entrada: 0x2f6fd6, item: 0x8d7b68, sel: 0x1e7a46 };

let cfg = null, proj = null, op = null;
let sel = null; // {tipo, i}
let resultado = null;

// ------------------------------------------------------------------ cena
const vista = $("vista");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
vista.appendChild(renderer.domElement);
const cena = new THREE.Scene();
const escuro = matchMedia("(prefers-color-scheme: dark)").matches;
cena.background = new THREE.Color(escuro ? 0x15191d : 0xeef1f4);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
const orbita = new OrbitControls(camera, renderer.domElement);
orbita.enableDamping = true;
cena.add(new THREE.HemisphereLight(0xffffff, 0x667766, 1.6));
const sol = new THREE.DirectionalLight(0xffffff, 1.4);
sol.position.set(60, -40, 120);
cena.add(sol);

const grpGalpao = new THREE.Group(), grpObjetos = new THREE.Group(), grpParedes = new THREE.Group();
const grpResultado = new THREE.Group();
cena.add(grpGalpao, grpObjetos, grpParedes, grpResultado);

const gizmo = new TransformControls(camera, renderer.domElement);
gizmo.setSize(0.8);
cena.add(gizmo);
gizmo.addEventListener("dragging-changed", (e) => { orbita.enabled = !e.value; if (!e.value) mudou(); });
gizmo.addEventListener("objectChange", () => {
  const o = gizmo.object;
  if (!o || !sel || sel.tipo !== "item") return;
  const it = cfg.itens[sel.i];
  it.posicao = [o.position.x, o.position.y, o.position.z].map((v) => +v.toFixed(3));
  it.rotacao_graus = [o.rotation.x, o.rotation.y, o.rotation.z].map((v) => +THREE.MathUtils.radToDeg(v).toFixed(1));
  it.escala = +o.scale.x.toFixed(3);
  painelItem();
});

function redimensionar() {
  const r = vista.getBoundingClientRect();
  renderer.setSize(r.width, r.height);
  camera.aspect = r.width / r.height;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", redimensionar);

function animar() {
  requestAnimationFrame(animar);
  orbita.update();
  renderer.render(cena, camera);
}

// ------------------------------------------------------------------ util
function aviso(txt, ms = 2500) {
  const a = $("aviso");
  a.textContent = txt;
  a.style.display = "block";
  clearTimeout(aviso.t);
  aviso.t = setTimeout(() => (a.style.display = "none"), ms);
}
async function api(url, corpo) {
  const r = await fetch(url, corpo === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: typeof corpo === "string" || corpo instanceof ArrayBuffer || corpo instanceof Blob ? corpo : JSON.stringify(corpo),
  });
  const j = await r.json();
  if (!r.ok || j.erro) throw new Error(j.erro || r.statusText);
  return j;
}
const num = (v, d = 2) => (v === null || v === undefined || v === "" ? "" : (+v).toFixed(d));
const fmt = (v) => Math.round(v).toLocaleString("pt-BR");
const dims = () => cfg.galpao;
let alturaMax = 3;

function campo(rotulo, valor, aoMudar, tipo = "number", extra = {}) {
  const l = document.createElement("label");
  l.textContent = rotulo;
  let el;
  if (tipo === "select") {
    el = document.createElement("select");
    for (const [v, t] of extra.opcoes) {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      if (String(v) === String(valor ?? "")) o.selected = true;
      el.appendChild(o);
    }
  } else if (tipo === "textarea") {
    el = document.createElement("textarea");
    el.value = valor ?? "";
  } else {
    el = document.createElement("input");
    el.type = tipo;
    if (tipo === "number") el.step = extra.step ?? "any";
    el.value = valor ?? "";
    if (extra.placeholder) el.placeholder = extra.placeholder;
  }
  el.addEventListener("change", () => {
    const v = el.value;
    aoMudar(tipo === "number" ? (v === "" ? null : +v) : v);
  });
  l.appendChild(el);
  return l;
}
function grade(...filhos) {
  const d = document.createElement("div");
  d.className = filhos.length === 3 ? "grade3" : "grade";
  filhos.forEach((f) => d.appendChild(f));
  return d;
}
function botao(txt, fn, classe = "b") {
  const b = document.createElement("button");
  b.className = classe; b.textContent = txt; b.onclick = fn;
  return b;
}

// ------------------------------------------------------------------ geometria das paredes
function pontoParede(parede, pos, z) {
  const { comprimento: L, largura: W } = dims();
  return { frente: [0, pos, z], fundo: [L, pos, z], esquerda: [pos, 0, z], direita: [pos, W, z] }[parede];
}
function normalParede(parede) {  // aponta para fora do galpao
  return { frente: [-1, 0, 0], fundo: [1, 0, 0], esquerda: [0, -1, 0], direita: [0, 1, 0] }[parede];
}
function posNaParede(parede, p) { return parede === "frente" || parede === "fundo" ? p.y : p.x; }

function montarParedes() {
  grpParedes.clear();
  const { comprimento: L, largura: W } = dims();
  const H = alturaMax + 1;
  const mat = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide });
  for (const p of PAREDES) {
    const larg = p === "frente" || p === "fundo" ? W : L;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(larg, H), mat);
    const c = pontoParede(p, larg / 2, H / 2);
    m.position.set(...c);
    m.lookAt(m.position.clone().add(new THREE.Vector3(...normalParede(p))));
    m.userData = { parede: p };
    grpParedes.add(m);
  }
}

async function montarGalpao() {
  grpGalpao.clear();
  const { comprimento: L, largura: W, altura: H } = dims();
  const mat = new THREE.MeshStandardMaterial({ color: 0xb9c2cc, transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false });
  const linhas = new THREE.LineBasicMaterial({ color: escuro ? 0x8794a1 : 0x5d6873 });
  let geo;
  if (proj.envoltoria_url) {
    geo = await new Promise((ok, erro) => new STLLoader().load(proj.envoltoria_url, ok, undefined, erro));
    geo.computeBoundingBox();
    alturaMax = geo.boundingBox.max.z;
  } else {
    geo = new THREE.BoxGeometry(L, W, H);
    geo.translate(L / 2, W / 2, H / 2);
    alturaMax = H;
  }
  grpGalpao.add(new THREE.Mesh(geo, mat));
  grpGalpao.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25), linhas));
  const piso = new THREE.Mesh(new THREE.PlaneGeometry(L, W), new THREE.MeshStandardMaterial({ color: 0x9fbf9a, transparent: true, opacity: 0.35 }));
  piso.position.set(L / 2, W / 2, -0.01);
  grpGalpao.add(piso);
  const pts = [];
  for (let x = 0; x <= L; x += 10) pts.push(x, 0, 0, x, W, 0);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  grpGalpao.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x7a8a7a, transparent: true, opacity: 0.5 })));
  montarParedes();
}

function enquadrar(deCima = false) {
  const { comprimento: L, largura: W } = dims();
  orbita.target.set(L / 2, W / 2, 1);
  // distancia para o galpao inteiro caber na tela (esfera envolvente)
  const raioG = Math.hypot(L, W) / 2;
  const fovH = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * camera.aspect);
  const dist = raioG / Math.sin(Math.min(THREE.MathUtils.degToRad(camera.fov), fovH) / 2) * 1.05;
  const dir = deCima ? new THREE.Vector3(0, -0.001, 1) : new THREE.Vector3(0.25, -0.75, 0.6).normalize();
  camera.position.copy(orbita.target).addScaledVector(dir, dist);
  camera.lookAt(orbita.target);
}

// ------------------------------------------------------------------ objetos (exaustores, entradas, itens)
const cacheStl = new Map();
function carregarStl(url) {
  if (!cacheStl.has(url)) cacheStl.set(url, new Promise((ok, erro) => new STLLoader().load(url, ok, undefined, erro)));
  return cacheStl.get(url);
}
function etiqueta(texto, cor) {
  const c = document.createElement("canvas");
  c.width = 64; c.height = 64;
  const x = c.getContext("2d");
  x.fillStyle = cor; x.beginPath(); x.arc(32, 32, 30, 0, 7); x.fill();
  x.fillStyle = "#fff"; x.font = "bold 30px sans-serif"; x.textAlign = "center"; x.textBaseline = "middle";
  x.fillText(texto, 32, 34);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
  s.scale.set(0.8, 0.8, 1);
  return s;
}
function ladoExaustor(i) {
  const e = cfg.exaustores.posicoes_manuais[i];
  const m = cfg.modelos_exaustor?.[e.modelo];
  if (m) return m.moldura_m || +(m.helice_diametro_m * 1.087).toFixed(2);
  return cfg.exaustores.lado_m;
}

let geracao = 0;
async function montarObjetos() {
  const ger = ++geracao;  // chamadas rapidas em sequencia: so a ultima termina de montar
  gizmo.detach();
  grpObjetos.clear();
  cfg.exaustores.posicoes_manuais.forEach((e, i) => {
    const lado = ladoExaustor(i);
    const ehSel = sel?.tipo === "exaustor" && sel.i === i;
    const frontal = e.parede === "frente" || e.parede === "fundo";
    const g = new THREE.Group();
    const caixa = new THREE.Mesh(
      frontal ? new THREE.BoxGeometry(0.25, lado, lado) : new THREE.BoxGeometry(lado, 0.25, lado),
      new THREE.MeshStandardMaterial({ color: ehSel ? COR.sel : COR.exaustor, transparent: true, opacity: 0.85 }));
    const m = cfg.modelos_exaustor?.[e.modelo];
    const r = (m?.helice_diametro_m ?? lado * 0.92) / 2;
    const helice = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 0.3, 40),
      new THREE.MeshStandardMaterial({ color: 0x333333 }));
    if (frontal) helice.rotation.z = Math.PI / 2;
    const n = normalParede(e.parede);
    const seta = new THREE.ArrowHelper(new THREE.Vector3(...n), new THREE.Vector3(...n).multiplyScalar(0.2), 1.6, COR.exaustor, 0.4, 0.3);
    const rot = etiqueta(String(i + 1), ehSel ? "#1e7a46" : "#e07a1f");
    rot.position.set(0, 0, lado / 2 + 0.5);
    g.add(caixa, helice, seta, rot);
    g.position.set(...pontoParede(e.parede, e.posicao, e.altura));
    caixa.userData = helice.userData = { tipo: "exaustor", i };
    grpObjetos.add(g);
  });
  cfg.entradas_ar.forEach((e, i) => {
    const ehSel = sel?.tipo === "entrada" && sel.i === i;
    const larg = e.fim - e.inicio, alt = e.z_max - e.z_min;
    const frontal = e.parede === "frente" || e.parede === "fundo";
    const m = new THREE.Mesh(
      frontal ? new THREE.BoxGeometry(0.12, larg, alt) : new THREE.BoxGeometry(larg, 0.12, alt),
      new THREE.MeshStandardMaterial({ color: ehSel ? COR.sel : COR.entrada, transparent: true, opacity: 0.55 }));
    m.position.set(...pontoParede(e.parede, (e.inicio + e.fim) / 2, (e.z_min + e.z_max) / 2));
    m.userData = { tipo: "entrada", i };
    grpObjetos.add(m);
  });
  for (const [i, it] of (cfg.itens || []).entries()) {
    const url = "/arquivo?c=" + encodeURIComponent(it.arquivo);
    let geo;
    try { geo = await carregarStl(url); } catch { aviso(`Nao achei ${it.arquivo}`); continue; }
    if (ger !== geracao) return;
    const ehSel = sel?.tipo === "item" && sel.i === i;
    const m = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: ehSel ? COR.sel : COR.item }));
    m.position.set(...(it.posicao || [0, 0, 0]));
    const r = (it.rotacao_graus || [0, 0, 0]).map(THREE.MathUtils.degToRad);
    m.rotation.set(r[0], r[1], r[2], "XYZ");
    const esc = Array.isArray(it.escala) ? it.escala : [it.escala ?? 1, it.escala ?? 1, it.escala ?? 1];
    m.scale.set(...esc);
    m.userData = { tipo: "item", i };
    grpObjetos.add(m);
    if (ehSel) gizmo.attach(m);
  }
}

// ------------------------------------------------------------------ interacao no 3D
const raio = new THREE.Raycaster();
const mouse = new THREE.Vector2();
let modo = null;          // "addExaustor" | "addEntrada" | null
let arrasto = null;       // {tipo, i, parede, desloc}
let clique0 = null;

function apontar(ev, objetos) {
  const r = renderer.domElement.getBoundingClientRect();
  mouse.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  raio.setFromCamera(mouse, camera);
  return raio.intersectObjects(objetos, true);
}
function paredeAtingida(ev, parede = null) {
  const alvos = grpParedes.children.filter((m) => !parede || m.userData.parede === parede);
  const h = apontar(ev, alvos)[0];
  return h ? { parede: h.object.userData.parede, p: h.point } : null;
}

function definirModo(m) {
  modo = modo === m ? null : m;
  $("mAddExaustor").classList.toggle("ligado", modo === "addExaustor");
  $("mAddEntrada").classList.toggle("ligado", modo === "addEntrada");
  renderer.domElement.style.cursor = modo ? "crosshair" : "";
}

renderer.domElement.addEventListener("pointerdown", (ev) => {
  clique0 = [ev.clientX, ev.clientY];
  if (modo || gizmo.dragging || ev.button !== 0) return;
  const h = apontar(ev, grpObjetos.children)[0];
  const ud = h?.object.userData;
  if (ud && sel && ud.tipo === sel.tipo && ud.i === sel.i && ud.tipo !== "item") {
    const lista = ud.tipo === "exaustor" ? cfg.exaustores.posicoes_manuais : cfg.entradas_ar;
    const o = lista[ud.i];
    const w = paredeAtingida(ev, o.parede);
    if (w) {
      const centro = ud.tipo === "exaustor" ? o.posicao : (o.inicio + o.fim) / 2;
      const zc = ud.tipo === "exaustor" ? o.altura : (o.z_min + o.z_max) / 2;
      arrasto = { ...ud, parede: o.parede, dpos: posNaParede(o.parede, w.p) - centro, dz: w.p.z - zc };
      orbita.enabled = false;
    }
  }
});
renderer.domElement.addEventListener("pointermove", (ev) => {
  if (!arrasto) return;
  const w = paredeAtingida(ev, arrasto.parede);
  if (!w) return;
  const pos = posNaParede(arrasto.parede, w.p) - arrasto.dpos, z = Math.max(0, w.p.z - arrasto.dz);
  if (arrasto.tipo === "exaustor") {
    const e = cfg.exaustores.posicoes_manuais[arrasto.i];
    e.posicao = +pos.toFixed(2); e.altura = +z.toFixed(2);
  } else {
    const e = cfg.entradas_ar[arrasto.i];
    const larg = e.fim - e.inicio, alt = e.z_max - e.z_min;
    e.inicio = +(pos - larg / 2).toFixed(2); e.fim = +(pos + larg / 2).toFixed(2);
    e.z_min = +Math.max(0, z - alt / 2).toFixed(2); e.z_max = +(e.z_min + alt).toFixed(2);
  }
  montarObjetos();
});
renderer.domElement.addEventListener("pointerup", (ev) => {
  if (arrasto) { arrasto = null; orbita.enabled = true; mudou(); return; }
  if (!clique0 || Math.hypot(ev.clientX - clique0[0], ev.clientY - clique0[1]) > 5 || ev.button !== 0) return;
  if (gizmo.dragging) return;
  if (modo) {
    const w = paredeAtingida(ev);
    if (!w) return;
    const pos = +posNaParede(w.parede, w.p).toFixed(2);
    if (modo === "addExaustor") {
      cfg.exaustores.posicoes_manuais.push({ parede: w.parede, posicao: pos, altura: +w.p.z.toFixed(2), modelo: cfg.exaustores.modelo || null });
      selecionar("exaustor", cfg.exaustores.posicoes_manuais.length - 1);
    } else {
      cfg.entradas_ar.push({ nome: `entrada_${cfg.entradas_ar.length + 1}`, parede: w.parede, inicio: +(pos - 5).toFixed(2),
        fim: +(pos + 5).toFixed(2), z_min: 0.4, z_max: Math.min(2.0, dims().altura - 0.2), tipo: "pad", espessura_mm: 150 });
      selecionar("entrada", cfg.entradas_ar.length - 1);
    }
    if (!ev.shiftKey) definirModo(null);  // Shift mantem o modo para varios cliques
    mudou();
    return;
  }
  const h = apontar(ev, grpObjetos.children)[0];
  const ud = h?.object.userData;
  if (ud?.tipo) selecionar(ud.tipo, ud.i);
  else selecionar(null);
});
window.addEventListener("keydown", (ev) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
  if (ev.key === "g" || ev.key === "G") gizmo.setMode("translate");
  if (ev.key === "r" || ev.key === "R") gizmo.setMode("rotate");
  if (ev.key === "Escape") { definirModo(null); selecionar(null); }
  if (ev.key === "Delete" && sel) excluirSelecionado();
});

function excluirSelecionado() {
  if (!sel) return;
  const lista = { exaustor: cfg.exaustores.posicoes_manuais, entrada: cfg.entradas_ar, item: cfg.itens }[sel.tipo];
  lista.splice(sel.i, 1);
  selecionar(null);
  mudou();
}

function selecionar(tipo, i) {
  sel = tipo ? { tipo, i } : null;
  const aba = { exaustor: "exaustores", entrada: "entradas", item: "itens" }[tipo];
  if (aba) mostrarAba(aba);
  montarObjetos();
  atualizarPaineis();
}

// ------------------------------------------------------------------ paineis
function mostrarAba(nome) {
  document.querySelectorAll("#abas button").forEach((b) => b.classList.toggle("ativo", b.dataset.aba === nome));
  document.querySelectorAll(".aba").forEach((s) => s.classList.toggle("ativa", s.id === "aba-" + nome));
}
document.querySelectorAll("#abas button").forEach((b) => (b.onclick = () => mostrarAba(b.dataset.aba)));

const opcoesModelo = () => [["", "(vazão fixa)"], ...Object.keys(cfg.modelos_exaustor || {}).map((k) => [k, k])];
const opcoesParede = (comFundo = true) => PAREDES.filter((p) => comFundo || p !== "fundo").map((p) => [p, p]);

function atualizarPaineis() {
  painelResumo();
  painelExaustores();
  painelEntradas();
  painelItens();
}

function painelResumo() {
  const d = $("resumoOperacao");
  if (!op) { d.innerHTML = `<span class="dica">${proj.erro || "calculando..."}</span>`; return; }
  const g = dims();
  const vel = op.vazao_total_m3h / 3600 / (g.largura * g.altura);
  d.innerHTML = `<div class="grade"><div><div class="dica">Vazão total</div><div class="kpi">${fmt(op.vazao_total_m3h)}</div><div class="dica">m³/h</div></div>
    <div><div class="dica">Velocidade média no túnel</div><div class="kpi">${vel.toFixed(2)}</div><div class="dica">m/s (alvo ${cfg.analise.velocidade_alvo_m_s})</div></div></div>
    <div class="dica" style="margin-top:6px">Pressão estática de operação: <b>${num(op.pressao_Pa, 1)} Pa</b> · ${op.exaustores.length} exaustores</div>`;
}

function painelExaustores() {
  const l = $("listaExaustores");
  l.innerHTML = "";
  cfg.exaustores.posicoes_manuais.forEach((e, i) => {
    const d = document.createElement("div");
    if (sel?.tipo === "exaustor" && sel.i === i) d.className = "sel";
    const q = op?.exaustores[i]?.vazao_m3h;
    d.innerHTML = `<span><b>${i + 1}</b> · ${e.parede} ${num(e.posicao)} m · alt ${num(e.altura)} m</span><small>${e.modelo || "vazão fixa"}${q ? " · " + fmt(q) + " m³/h" : ""}</small>`;
    d.onclick = () => selecionar("exaustor", i);
    l.appendChild(d);
  });
  const ed = $("editExaustor");
  ed.innerHTML = "";
  if (sel?.tipo !== "exaustor") return;
  const e = cfg.exaustores.posicoes_manuais[sel.i];
  ed.appendChild(Object.assign(document.createElement("h2"), { textContent: `Exaustor ${sel.i + 1}` }));
  ed.appendChild(grade(
    campo("Parede", e.parede, (v) => { e.parede = v; mudou(); }, "select", { opcoes: opcoesParede() }),
    campo("Modelo", e.modelo || "", (v) => { e.modelo = v || null; mudou(); }, "select", { opcoes: opcoesModelo() })));
  ed.appendChild(grade(
    campo("Posição ao longo da parede (m)", e.posicao, (v) => { e.posicao = v; mudou(); }),
    campo("Altura do centro (m)", e.altura, (v) => { e.altura = v; mudou(); })));
  const a = document.createElement("div");
  a.className = "acoes";
  a.append(botao("Duplicar ao lado", () => {
    const n = { ...e, posicao: +(e.posicao + ladoExaustor(sel.i) + 0.25).toFixed(2) };
    cfg.exaustores.posicoes_manuais.push(n);
    selecionar("exaustor", cfg.exaustores.posicoes_manuais.length - 1); mudou();
  }), botao("Excluir", excluirSelecionado, "b perigo"));
  ed.appendChild(a);
  ed.appendChild(Object.assign(document.createElement("p"), { className: "dica", textContent: "Dica: com o exaustor selecionado, arraste-o na parede." }));
}

function painelEntradas() {
  const l = $("listaEntradas");
  l.innerHTML = "";
  cfg.entradas_ar.forEach((e, i) => {
    const d = document.createElement("div");
    if (sel?.tipo === "entrada" && sel.i === i) d.className = "sel";
    d.innerHTML = `<span><b>${e.nome}</b> · ${e.parede}</span><small>${num(e.fim - e.inicio, 1)} × ${num(e.z_max - e.z_min, 1)} m · ${e.tipo || "pad"}</small>`;
    d.onclick = () => selecionar("entrada", i);
    l.appendChild(d);
  });
  const ed = $("editEntrada");
  ed.innerHTML = "";
  if (sel?.tipo !== "entrada") return;
  const e = cfg.entradas_ar[sel.i];
  ed.appendChild(Object.assign(document.createElement("h2"), { textContent: e.nome }));
  ed.appendChild(grade(campo("Nome", e.nome, (v) => { e.nome = v.replace(/\W/g, "_"); mudou(); }, "text"),
    campo("Parede", e.parede, (v) => { e.parede = v; mudou(); }, "select", { opcoes: opcoesParede() })));
  ed.appendChild(grade(campo("Início (m)", e.inicio, (v) => { e.inicio = v; mudou(); }),
    campo("Fim (m)", e.fim, (v) => { e.fim = v; mudou(); })));
  ed.appendChild(grade(campo("Altura inferior (m)", e.z_min, (v) => { e.z_min = v; mudou(); }),
    campo("Altura superior (m)", e.z_max, (v) => { e.z_max = v; mudou(); })));
  ed.appendChild(grade(campo("Tipo", e.tipo || "pad", (v) => { e.tipo = v; mudou(); }, "select", { opcoes: [["pad", "pad evaporativo"], ["abertura", "abertura / cortina"]] }),
    campo("Espessura do pad (mm)", e.espessura_mm ?? 150, (v) => { e.espessura_mm = v; mudou(); })));
  const a = document.createElement("div");
  a.className = "acoes";
  a.append(botao("Excluir", excluirSelecionado, "b perigo"));
  ed.appendChild(a);
}

function painelItens() {
  cfg.itens = cfg.itens || [];
  const l = $("listaItens");
  l.innerHTML = cfg.itens.length ? "" : `<div><small>Nenhum item. Clique num item da biblioteca.</small></div>`;
  cfg.itens.forEach((it, i) => {
    const d = document.createElement("div");
    if (sel?.tipo === "item" && sel.i === i) d.className = "sel";
    d.innerHTML = `<span><b>${it.nome}</b></span><small>(${(it.posicao || []).map((v) => num(v, 1)).join(", ")})</small>`;
    d.onclick = () => selecionar("item", i);
    l.appendChild(d);
  });
  const b = $("listaBiblioteca");
  b.innerHTML = proj.biblioteca.length ? "" : `<div><small>Biblioteca vazia: importe um modelo ou crie a partir de fotos.</small></div>`;
  for (const f of proj.biblioteca) {
    const d = document.createElement("div");
    d.innerHTML = `<span>${f.nome}</span><small>${f.dimensoes_m.map((v) => num(v)).join(" × ")} m</small>`;
    d.onclick = () => {
      const g = dims();
      cfg.itens.push({ nome: f.nome, arquivo: f.arquivo, posicao: [g.comprimento / 2, g.largura / 2, 0], rotacao_graus: [0, 0, 0], escala: 1 });
      selecionar("item", cfg.itens.length - 1);
      mudou();
    };
    b.appendChild(d);
  }
  painelItem();
}

function painelItem() {
  const ed = $("editItem");
  ed.innerHTML = "";
  if (sel?.tipo !== "item") return;
  const it = cfg.itens[sel.i];
  const p = it.posicao, r = it.rotacao_graus;
  const mexe = (fn) => (v) => { fn(v); montarObjetos(); mudou(); };
  ed.appendChild(Object.assign(document.createElement("h2"), { textContent: it.nome }));
  ed.appendChild(grade(campo("x (m)", num(p[0]), mexe((v) => (p[0] = v))), campo("y (m)", num(p[1]), mexe((v) => (p[1] = v))), campo("z (m)", num(p[2]), mexe((v) => (p[2] = v)))));
  ed.appendChild(grade(campo("Giro x (°)", num(r[0], 0), mexe((v) => (r[0] = v))), campo("Giro y (°)", num(r[1], 0), mexe((v) => (r[1] = v))), campo("Giro z (°)", num(r[2], 0), mexe((v) => (r[2] = v)))));
  ed.appendChild(grade(campo("Escala", it.escala ?? 1, mexe((v) => (it.escala = v))), campo("Nome", it.nome, (v) => { it.nome = v; mudou(); }, "text")));
  const a = document.createElement("div");
  a.className = "acoes";
  a.append(botao("Duplicar", () => {
    cfg.itens.push(JSON.parse(JSON.stringify({ ...it, posicao: [p[0] + 2, p[1], p[2]] })));
    selecionar("item", cfg.itens.length - 1); mudou();
  }), botao("Excluir", excluirSelecionado, "b perigo"));
  ed.appendChild(a);
  ed.appendChild(Object.assign(document.createElement("p"), { className: "dica", textContent: "No 3D: G = mover, R = girar, Delete = excluir." }));
}

// ---- modelos de exaustor
const CAMPOS_MODELO = [
  ["motor_cv", "Motor (CV)"], ["motor_rpm", "Rotação do motor (rpm)"],
  ["polia_motor_mm", "Polia do motor (mm)"], ["polia_helice_mm", "Polia da hélice (mm)"],
  ["correia", "Correia (ex.: A-62, B-50)", "text"], ["helice_diametro_m", "Hélice ponta a ponta (m)"],
  ["pas", "Número de pás"], ["angulo_pas_graus", "Ângulo das pás (°)"],
  ["moldura_m", "Moldura / abertura na parede (m)"], ["rpm_helice", "Rotação medida da hélice (opcional)"],
];
let modeloAtual = null;
function painelModelos() {
  cfg.modelos_exaustor = cfg.modelos_exaustor || {};
  const nomes = Object.keys(cfg.modelos_exaustor);
  if (!nomes.includes(modeloAtual)) modeloAtual = nomes[0] || null;
  const s = $("selModelo");
  s.innerHTML = nomes.map((n) => `<option ${n === modeloAtual ? "selected" : ""}>${n}</option>`).join("");
  s.onchange = () => { modeloAtual = s.value; painelModelos(); };
  const f = $("formModelo");
  f.innerHTML = "";
  if (!modeloAtual) { f.innerHTML = `<p class="dica">Nenhum modelo. Clique em Novo.</p>`; return; }
  const m = cfg.modelos_exaustor[modeloAtual];
  f.appendChild(campo("Modelo padrão para exaustores novos", cfg.exaustores.modelo || "", (v) => { cfg.exaustores.modelo = v || null; mudou(); }, "select", { opcoes: opcoesModelo() }));
  f.appendChild(campo("Nome do modelo", modeloAtual, (v) => {
    v = v.replace(/\W/g, "_");
    if (!v || cfg.modelos_exaustor[v]) return;
    cfg.modelos_exaustor[v] = m; delete cfg.modelos_exaustor[modeloAtual];
    cfg.exaustores.posicoes_manuais.forEach((e) => { if (e.modelo === modeloAtual) e.modelo = v; });
    if (cfg.exaustores.modelo === modeloAtual) cfg.exaustores.modelo = v;
    modeloAtual = v; painelModelos(); mudou();
  }, "text"));
  for (let k = 0; k < CAMPOS_MODELO.length; k += 2) {
    f.appendChild(grade(...CAMPOS_MODELO.slice(k, k + 2).map(([chave, rot, tipo]) =>
      campo(rot, m[chave], (v) => { if (v === null || v === "") delete m[chave]; else m[chave] = v; calcularModelo(); mudou(); }, tipo || "number"))));
  }
  const curva = (m.curva_fabricante || []).map(([p, q]) => `${p}; ${q}`).join("\n");
  f.appendChild(grade(
    campo("Curva do fabricante (opcional): pressão Pa; vazão m³/h — uma por linha", curva, (v) => {
      m.curva_fabricante = v.split("\n").map((l) => l.split(/[;\t ]+/).map(Number)).filter((a) => a.length === 2 && a.every(isFinite));
      calcularModelo(); mudou();
    }, "textarea"),
    campo("Rotação da curva (rpm)", m.curva_rpm, (v) => { if (v) m.curva_rpm = v; else delete m.curva_rpm; calcularModelo(); mudou(); })));
  calcularModelo();
}
async function calcularModelo() {
  if (!modeloAtual) return;
  try {
    const r = await api("/api/exaustor", { config: cfg, modelo: modeloAtual });
    $("fichaModelo").textContent = r.ficha;
    desenharCurva(r.curva, r.pressao_Pa);
  } catch (e) { $("fichaModelo").textContent = "Erro: " + e.message; }
}
function desenharCurva(curva, pOp) {
  const c = $("graficoCurva"), x = c.getContext("2d");
  const W = c.width, H = c.height, m = { l: 48, r: 10, t: 12, b: 30 };
  x.clearRect(0, 0, W, H);
  const cs = getComputedStyle(document.body);
  const corTxt = cs.getPropertyValue("--sec"), corLinha = cs.getPropertyValue("--borda");
  if (!curva?.length) return;
  const qMax = Math.max(...curva.map((p) => p[1])) * 1.05, pMax = Math.max(...curva.map((p) => p[0])) * 1.05 || 1;
  const X = (q) => m.l + (q / qMax) * (W - m.l - m.r), Y = (p) => H - m.b - (p / pMax) * (H - m.t - m.b);
  x.font = "11px system-ui"; x.fillStyle = corTxt; x.strokeStyle = corLinha;
  for (let i = 0; i <= 4; i++) {
    const p = (pMax * i) / 4, y = Y(p);
    x.beginPath(); x.moveTo(m.l, y); x.lineTo(W - m.r, y); x.stroke();
    x.fillText(p.toFixed(0), 8, y + 4);
  }
  for (let i = 0; i <= 4; i++) { const q = (qMax * i) / 4; x.fillText((q / 1000).toFixed(0) + "k", X(q) - 8, H - 12); }
  x.fillText("Pa", 8, 10); x.fillText("m³/h", W - 36, H - 2);
  x.strokeStyle = "#e07a1f"; x.lineWidth = 2; x.beginPath();
  curva.forEach(([p, q], k) => (k ? x.lineTo(X(q), Y(p)) : x.moveTo(X(q), Y(p))));
  x.stroke(); x.lineWidth = 1;
  if (pOp != null) {
    x.strokeStyle = "#2f6fd6"; x.setLineDash([4, 3]);
    x.beginPath(); x.moveTo(m.l, Y(pOp)); x.lineTo(W - m.r, Y(pOp)); x.stroke(); x.setLineDash([]);
    x.fillStyle = "#2f6fd6"; x.fillText(`operação ${pOp.toFixed(0)} Pa`, m.l + 4, Y(pOp) - 4);
  }
}
$("novoModelo").onclick = () => {
  let n = 1; while (cfg.modelos_exaustor[`exaustor_${n}`]) n++;
  cfg.modelos_exaustor[`exaustor_${n}`] = { motor_cv: 1.5, motor_rpm: 1720, polia_motor_mm: 100, polia_helice_mm: 390, correia: "A-62",
    helice_diametro_m: 1.27, pas: 6, angulo_pas_graus: 30, moldura_m: 1.38, curva_fabricante: [] };
  modeloAtual = `exaustor_${n}`; painelModelos(); mudou();
};
$("dupModelo").onclick = () => {
  if (!modeloAtual) return;
  let n = 2; while (cfg.modelos_exaustor[`${modeloAtual}_${n}`]) n++;
  cfg.modelos_exaustor[`${modeloAtual}_${n}`] = JSON.parse(JSON.stringify(cfg.modelos_exaustor[modeloAtual]));
  modeloAtual = `${modeloAtual}_${n}`; painelModelos(); mudou();
};

// ---- galpao e clima
function painelGalpao() {
  const f = $("formGalpao");
  f.innerHTML = "";
  const sec = (t) => f.appendChild(Object.assign(document.createElement("h2"), { textContent: t }));
  const n = (obj, chave, rot, refazer = false) => campo(rot, obj[chave], (v) => { obj[chave] = v; if (refazer) recarregarGeometria(); mudou(); });
  sec("Projeto");
  f.appendChild(campo("Nome", cfg.nome, (v) => { cfg.nome = v.replace(/[^\w.-]/g, "_"); mudou(); }, "text"));
  sec("Galpão");
  if (cfg.envoltoria_stl) f.appendChild(Object.assign(document.createElement("p"), { className: "dica", textContent: `Forma vinda do modelo 3D (${cfg.envoltoria_stl}). As medidas abaixo servem para posicionar paredes e cálculos.` }));
  const g = cfg.galpao;
  f.appendChild(grade(n(g, "comprimento", "Comprimento (m)", true), n(g, "largura", "Largura (m)", true), n(g, "altura", "Pé-direito (m)", true)));
  sec("Clima e calor");
  f.appendChild(grade(n(cfg.clima, "temperatura_entrada_C", "Ar que entra (°C)"), n(cfg.clima, "temperatura_inicial_C", "Inicial (°C)")));
  f.appendChild(grade(n(cfg.cargas_termicas, "calor_animais_W_m2", "Calor dos animais (W/m²)"), n(cfg.cargas_termicas, "calor_telhado_W_m2", "Calor do telhado (W/m²)")));
  sec("Análise");
  f.appendChild(grade(n(cfg.analise, "altura_animais_m", "Altura dos animais (m)"), n(cfg.analise, "velocidade_alvo_m_s", "Velocidade alvo (m/s)")));
  sec("Pressão estática");
  cfg.sistema = cfg.sistema || {};
  f.appendChild(grade(n(cfg.sistema, "pressao_estatica_Pa", "Medida no manômetro (Pa, vazio = calcular)"), n(cfg.sistema, "perda_extra_Pa", "Perdas extras (Pa)")));
}
async function recarregarGeometria() {
  if (!cfg.envoltoria_stl) { await montarGalpao(); montarObjetos(); }
}

// ------------------------------------------------------------------ calculo, salvar, simular
let tCalc = null;
function mudou() {
  painelExaustores(); painelEntradas(); painelItens();
  clearTimeout(tCalc);
  tCalc = setTimeout(async () => {
    try { op = await api("/api/operacao", cfg); proj.erro = null; }
    catch (e) { op = null; proj.erro = e.message; }
    painelResumo(); painelExaustores();
  }, 350);
}

$("salvar").onclick = async () => {
  try { await api("/api/salvar", cfg); aviso("Projeto salvo"); } catch (e) { aviso("Erro: " + e.message, 5000); }
};
$("simular").onclick = async () => {
  try {
    const r = await api("/api/simular", { config: cfg, celula: +$("simCelula").value || null, iteracoes: +$("simIter").value || null, nucleos: +$("simNucleos").value || null });
    aviso("Simulação iniciada");
    acompanhar(r.caso);
  } catch (e) { aviso("Erro: " + e.message, 5000); }
};

async function acompanhar(caso) {
  $("simProgresso").style.display = "block";
  $("simLog").style.display = "block";
  const passo = async () => {
    const s = await api("/api/status");
    $("simLog").textContent = s.log || "";
    $("simLog").scrollTop = 1e9;
    if (s.tipo === "simulacao") {
      $("simProgresso").max = s.iteracoes || 1;
      $("simProgresso").value = s.iteracao || 0;
      $("simEstado").textContent = s.rodando
        ? `Rodando há ${Math.round(s.segundos / 60)} min · iteração ${s.iteracao || 0} de ${s.iteracoes}`
        : (s.codigo === 0 ? `Concluída em ${Math.round(s.segundos / 60)} min` : "A simulação falhou: veja o registro abaixo");
    } else if (s.tipo === "fotos") {
      $("simEstado").textContent = s.rodando ? `Gerando 3D a partir das fotos (${Math.round(s.segundos / 60)} min)...` : (s.codigo === 0 ? "Modelo 3D pronto" : "A reconstrução falhou: veja o registro");
    }
    if (s.rodando) return setTimeout(passo, 2000);
    $("simProgresso").style.display = "none";
    if (s.tipo === "simulacao" && s.codigo === 0) mostrarResultado(caso || s.caso);
    if (s.tipo === "fotos") { proj = await api("/api/projeto"); painelItens(); }
  };
  passo();
}

const RAMPA = [[0, [68, 1, 84]], [0.25, [59, 82, 139]], [0.5, [33, 145, 140]], [0.75, [94, 201, 98]], [1, [253, 231, 37]]];
function corRampa(t) {
  t = Math.min(1, Math.max(0, t));
  for (let k = 1; k < RAMPA.length; k++) {
    if (t <= RAMPA[k][0]) {
      const [t0, c0] = RAMPA[k - 1], [t1, c1] = RAMPA[k], f = (t - t0) / (t1 - t0);
      return c0.map((v, j) => (v + f * (c1[j] - v)) / 255);
    }
  }
  return RAMPA[RAMPA.length - 1][1].map((v) => v / 255);
}
async function mostrarResultado(caso) {
  resultado = await api("/api/resultado?caso=" + encodeURIComponent(caso));
  const d = $("resultados");
  d.innerHTML = "";
  if (resultado.relatorio) d.appendChild(Object.assign(document.createElement("pre"), { textContent: resultado.relatorio.split("## Mapas")[0] }));
  for (const src of resultado.imagens) d.appendChild(Object.assign(document.createElement("img"), { src: src + "&t=" + Date.now(), className: "res" }));
  desenharPlano();
}
function desenharPlano() {
  grpResultado.clear();
  const pl = resultado?.plano;
  $("barraResultado").style.display = pl ? "block" : "none";
  $("mResultado").style.display = pl ? "inline-block" : "none";
  if (!pl) return;
  const campoR = $("campoResultado").value;
  const vals = pl[campoR];
  const ord = [...vals].sort((a, b) => a - b);
  const vMin = campoR === "vel" ? 0 : ord[Math.floor(ord.length * 0.01)], vMax = ord[Math.floor(ord.length * 0.99)];
  const pos = new Float32Array(vals.length * 3), cor = new Float32Array(vals.length * 3);
  vals.forEach((v, k) => {
    pos.set([pl.x[k], pl.y[k], pl.z[k]], 3 * k);
    cor.set(corRampa((v - vMin) / (vMax - vMin || 1)), 3 * k);
  });
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("color", new THREE.BufferAttribute(cor, 3));
  const pontos = new THREE.Points(g, new THREE.PointsMaterial({ size: Math.max(0.15, cfg.malha.tamanho_celula * 0.9), vertexColors: true, depthTest: false }));
  pontos.renderOrder = 10;  // por cima do telhado transparente
  grpResultado.add(pontos);
  const esc = $("escala").getContext("2d");
  for (let i = 0; i < 160; i++) { esc.fillStyle = `rgb(${corRampa(i / 159).map((c) => c * 255).join(",")})`; esc.fillRect(i, 0, 1, 10); }
  $("escMin").textContent = vMin.toFixed(1);
  $("escMax").textContent = vMax.toFixed(1) + (campoR === "vel" ? " m/s" : " °C");
}
$("campoResultado").onchange = desenharPlano;
$("mResultado").onclick = () => {
  grpResultado.visible = !grpResultado.visible;
  $("mResultado").textContent = grpResultado.visible ? "Ocultar resultado" : "Mostrar resultado";
};

// ---- importacao de itens e fotos
$("impEnviar").onclick = async () => {
  const arq = $("impArquivo").files[0], nome = $("impNome").value.trim();
  if (!arq || !nome) return aviso("Escolha o arquivo e dê um nome");
  aviso("Importando... (objetos grandes podem levar um minuto)", 60000);
  try {
    const q = new URLSearchParams({ nome, arquivo: arq.name, medida: $("impMedida").value.trim(), vertical: $("impVertical").value });
    const r = await fetch("/api/item?" + q, { method: "POST", body: arq });
    const j = await r.json();
    if (!r.ok || j.erro) throw new Error(j.erro);
    proj = await api("/api/projeto");
    painelItens();
    aviso(`'${j.nome}' importado: ${j.dimensoes_m.map((v) => v.toFixed(2)).join(" × ")} m`, 5000);
  } catch (e) { aviso("Erro: " + e.message, 6000); }
};
$("fotEnviar").onclick = async () => {
  const fotos = [...$("fotArquivos").files], nome = $("fotNome").value.trim().replace(/\W/g, "_");
  if (!nome || fotos.length < 20) return aviso("Dê um nome e escolha pelo menos 20 fotos (ideal 40+)", 4000);
  const pr = $("fotProgresso");
  pr.style.display = "block"; pr.max = fotos.length; pr.value = 0;
  try {
    for (const f of fotos) {
      const r = await fetch(`/api/foto?lote=${encodeURIComponent(nome)}&arquivo=${encodeURIComponent(f.name)}`, { method: "POST", body: f });
      if (!r.ok) throw new Error("falha ao enviar " + f.name);
      pr.value++;
    }
    await api("/api/fotos/processar", { nome, medida: $("fotMedida").value.trim(), rapido: $("fotRapido").checked });
    mostrarAba("simular");
    aviso("Fotos enviadas; reconstrução 3D iniciada");
    acompanhar(null);
  } catch (e) { aviso("Erro: " + e.message, 6000); }
  pr.style.display = "none";
};

// ---- botoes da vista
$("mAddExaustor").onclick = () => definirModo("addExaustor");
$("mAddEntrada").onclick = () => definirModo("addEntrada");
$("addExaustor").onclick = () => { definirModo("addExaustor"); aviso("Clique numa parede (Shift mantém para vários)"); };
$("addEntrada").onclick = () => { definirModo("addEntrada"); aviso("Clique numa parede"); };
$("mMover").onclick = () => gizmo.setMode("translate");
$("mGirar").onclick = () => gizmo.setMode("rotate");
let deCima = false;
$("mVista").onclick = () => { deCima = !deCima; enquadrar(deCima); $("mVista").textContent = deCima ? "Vista 3D" : "Vista de cima"; };
$("distribuir").onclick = async () => {
  const n = +prompt("Quantos exaustores distribuir (fundo primeiro, depois laterais)?", cfg.exaustores.posicoes_manuais.length || cfg.exaustores.quantidade);
  if (!n) return;
  cfg.exaustores.quantidade = n;
  cfg.exaustores.posicoes_manuais = [];
  op = await api("/api/operacao", cfg);
  cfg.exaustores.posicoes_manuais = op.exaustores.map((e) => ({ parede: e.parede, posicao: e.posicao, altura: e.altura, modelo: e.modelo }));
  selecionar(null); mudou();
};

// ------------------------------------------------------------------ inicio
async function iniciar() {
  redimensionar();
  proj = await api("/api/projeto");
  cfg = proj.config;
  op = proj.operacao;
  $("arquivo").textContent = proj.arquivo;
  cfg.itens = cfg.itens || [];
  cfg.modelos_exaustor = cfg.modelos_exaustor || {};
  if (!cfg.exaustores.posicoes_manuais?.length && op) {
    // o editor trabalha sempre com a lista explicita de exaustores
    cfg.exaustores.posicoes_manuais = op.exaustores.map((e) => ({ parede: e.parede, posicao: e.posicao, altura: e.altura, modelo: e.modelo }));
  }
  $("simCelula").value = cfg.malha.tamanho_celula;
  $("simIter").value = cfg.solver.iteracoes;
  $("simNucleos").value = cfg.solver.nucleos_cpu;
  await montarGalpao();
  enquadrar();
  await montarObjetos();
  atualizarPaineis();
  painelModelos();
  painelGalpao();
  animar();
  const s = await api("/api/status");
  if (s.rodando) { mostrarAba("simular"); acompanhar(s.caso); }
  else if (s.tipo === "simulacao" && s.codigo === 0 && s.caso) mostrarResultado(s.caso);
}
// acesso para testes automaticos e depuracao no console do navegador
window.editor = { camera, cfg: () => cfg, op: () => op, paraTela: (x, y, z) => {
  const v = new THREE.Vector3(x, y, z).project(camera), r = renderer.domElement.getBoundingClientRect();
  return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height];
} };
iniciar().catch((e) => aviso("Erro ao abrir o projeto: " + e.message, 10000));
