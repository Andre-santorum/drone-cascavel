# Simulação de ventilação e temperatura em galpões (aviário / suínos)

Simulador CFD (dinâmica dos fluidos computacional) para galpões com **ventilação em túnel**:
você define quantos exaustores, a vazão de cada um, onde ficam as entradas de ar (pads,
cortinas, inlets), o calor dos animais e do telhado, e o programa calcula **por onde o ar
passa, com que velocidade e a que temperatura** em todo o volume do galpão.

Serve para qualquer galpão: aviário de corte, postura, terminação de suínos etc. O que muda
entre eles são só os números no arquivo de configuração.

Tudo aqui é **gratuito e de código aberto** (OpenFOAM 12 + Python + ParaView) e foi testado
de ponta a ponta antes de ser publicado (ver "Validação" no fim).

---

## 1. Roda no meu computador? (GTX 1650 4 GB + 24–28 GB RAM)

**Sim.** Mas é importante entender um ponto:

- **A placa de vídeo (GTX 1650) não é usada no cálculo.** O OpenFOAM, padrão da indústria
  para esse tipo de simulação, calcula no **processador (CPU)**. A GTX 1650 serve só para
  visualizar os resultados em 3D no ParaView, e para isso ela sobra.
- **A memória RAM é o que limita o tamanho da simulação**, e 24 GB é bastante:

| Tamanho da célula | Células (galpão 125 × 14 × 3 m) | RAM usada | Tempo aproximado* | Para quê |
|---|---|---|---|---|
| 0,50 m | ~45 mil | < 0,5 GB | 1–3 min | teste rápido de cenários |
| 0,40 m | ~90 mil | < 0,5 GB | 3–5 min | comparar quantidade de exaustores |
| **0,25 m** | ~340 mil | ~0,5 GB | **15–30 min** | **padrão, bom para decisão** |
| 0,15 m | ~1,6 milhão | ~2–3 GB | 2–4 h | detalhe fino |
| 0,10 m | ~5,3 milhões | ~6–8 GB | 8–15 h (deixar à noite) | máximo recomendado |

\* Tempos para um processador de 4 núcleos. **O processador é o que define o tempo** —
me diga qual é o seu (Gerenciador de Tarefas → Desempenho → CPU) que eu ajusto a tabela.
Se ele tiver 6 ou 8 núcleos, coloque esse número em `"nucleos_cpu"` na configuração.

Por que não usar a GPU? Existem simuladores por GPU (FluidX3D, por exemplo), mas: com 4 GB de
VRAM o tamanho fica limitado, o modelo de temperatura é menos maduro, a licença proíbe uso
comercial e não há condição de contorno pronta para exaustor com vazão definida. Para
ventilação de galpão com temperatura, o OpenFOAM na CPU é o caminho confiável.

---

## 2. O que precisa instalar (uma vez só)

No Windows 10/11:

1. **WSL2 com Ubuntu** (o Linux dentro do Windows). Abra o PowerShell **como administrador**:
   ```powershell
   wsl --install -d Ubuntu-24.04
   ```
   Reinicie o computador, abra "Ubuntu" no menu Iniciar e crie usuário e senha.
2. **Dê mais memória ao WSL** (por padrão ele usa só metade da RAM). Crie o arquivo
   `C:\Users\<seu usuario>\.wslconfig` com:
   ```ini
   [wsl2]
   memory=20GB
   processors=8      # coloque o número de núcleos lógicos do seu processador
   ```
   e rode `wsl --shutdown` no PowerShell.
3. **OpenFOAM + Python** — dentro do Ubuntu:
   ```bash
   git clone https://github.com/andre-santorum/drone-cascavel.git
   cd drone-cascavel/simulacao-ventilacao
   sh instalar_ubuntu.sh
   ```
4. **ParaView** (visualização 3D) no Windows: baixe em <https://www.paraview.org/download/>
   (versão Windows, instalador `.msi`). Ele usa a GTX 1650.

Alternativa sem linha de comando: **FreeCAD + bancada CfdOF** (interface gráfica para o
mesmo OpenFOAM). É bom para aprender, mas para comparar 6, 8, 10, 12 exaustores rapidamente
os scripts daqui são muito mais práticos.

---

## 3. Como usar

```bash
cd ~/drone-cascavel/simulacao-ventilacao

# 1) Conta rápida (segundos): quantos exaustores para a velocidade-alvo?
python3 calculo_rapido.py config_exemplo.json --exaustores 6 8 10 12

# 2) Gera o caso CFD
python3 gerar_caso.py config_exemplo.json

# 3) Roda (malha + cálculo + relatório)
cd casos/aviario_8_exaustores
./Allrun
```

Resultado em `casos/<nome>/resultados/`:

- `relatorio.md` – velocidade média/mínima na altura dos animais, % da área abaixo do alvo,
  temperatura média/máxima, vazão total, temperatura na saída, tabela a cada 10 m;
- `velocidade_animais.png`, `temperatura_animais.png` – mapas vistos de cima;
- `corte_longitudinal*.png` – corte pelo meio do galpão.

Para ver em 3D (linhas de corrente, cortes em qualquer lugar): no ParaView do Windows abra
`\\wsl$\Ubuntu-24.04\home\<usuario>\drone-cascavel\simulacao-ventilacao\casos\<nome>\caso.foam`.

### Comparar cenários (mais ou menos exaustores)

```bash
for n in 6 8 10 12; do
  python3 gerar_caso.py config_exemplo.json --exaustores $n --celula 0.4
  (cd casos/aviario_8_exaustores_${n}ex && ./Allrun)
done
```

Quando não cabem todos na parede do fundo, os exaustores extras vão automaticamente para as
laterais, perto do fundo, alternando os lados (como se faz na prática). Para posições exatas
use `"posicoes_manuais"`:

```json
"posicoes_manuais": [
  {"parede": "fundo",    "posicao": 2.0,   "altura": 1.2},
  {"parede": "esquerda", "posicao": 122.0, "altura": 1.2}
]
```

(`posicao` = distância ao longo da parede: em y para frente/fundo, em x para as laterais.)

---

## 3A. Projetos do DJI Terra (o jeito mais fácil)

Se o barracão foi levantado com drone e processado no **DJI Terra**, um único comando faz
tudo: lê o modelo 3D, acha o barracão, mede comprimento, largura, altura do beiral e o
formato do telhado, gera a malha, roda a simulação e faz o relatório.

**No DJI Terra**, na reconstrução 3D, marque nos formatos de saída **OBJ** (ou PLY). Se for
nuvem de pontos (LiDAR/L1/L2), use **LAS**. Os formatos B3DM/OSGB/S3MB não servem, porque são só
para visualização. O Terra grava em
`<pasta de missões>\<usuário>\<missão>\models\pc\0\terra_obj\` (a pasta de missões aparece
nas Configurações do Terra).

**No Ubuntu (WSL)** — o disco C: do Windows aparece como `/mnt/c`:

```bash
cd ~/drone-cascavel/simulacao-ventilacao
./simular_terra.sh "/mnt/c/Users/<voce>/Documents/DJI/DJI Terra/<conta>/<missao>"
```

Pode passar a pasta da missão inteira; o programa encontra os arquivos sozinho. Depois confira
as duas figuras que ele cria em `modelos/<missao>/`:

- `visao_geral.png` – mapa de alturas com as construções numeradas. Se o terreno tiver mais
  de um barracão, a maior é a nº 1; para usar outra, acrescente `--galpao 2`. As pontas
  **A** e **B** do barracão estão marcadas: os exaustores ficam na **B**. Se estiverem do
  outro lado, use `--exaustores-em inicio`;
- `perfil_telhado.png` – corte transversal com os pontos do drone e a forma adotada.

Ajustes comuns:

| Situação | Opção |
|---|---|
| O drone vê o telhado, que é maior que as paredes por causa do **beiral** | `--beiral 0.6` (desconta 0,6 m de cada lado) |
| Galpão com **forro** (o ar só circula abaixo dele) | `--altura-forro 2.8` |
| Testar outra quantidade de exaustores | `EXAUSTORES=10 ./simular_terra.sh ...` |
| Teste rápido | `CELULA=0.5 ./simular_terra.sh ...` |

Exaustores, pads, clima e calor vêm do `config_exemplo.json`. Edite esse arquivo antes, ou
edite `modelos/<missao>/config.json` depois e rode só `python3 gerar_caso.py
modelos/<missao>/config.json`.

**Sempre confira com a trena** o comprimento, a largura e o pé-direito que o programa
imprime. No teste com um barracão de 125 × 14 m (beiral 3,0 m, cumeeira 4,5 m), ele mediu
124,8 × 13,8 m, beiral 3,1 m e cumeeira 4,4 m.

---

## 3B. Editor 3D: exaustores, entradas de ar e itens

Para posicionar tudo com o mouse e rodar a simulação de novo:

```bash
cd ~/drone-cascavel/simulacao-ventilacao
python3 editor.py modelos/<missao>/config.json     # ou config_exemplo.json
```

Abra **http://localhost:8765** no navegador do Windows (Chrome ou Edge). O editor funciona sem
internet.

- **Exaustores:** use **+ Exaustor** e clique na parede (com Shift, coloca vários seguidos).
  Clique num exaustor para editar parede, posição, altura e modelo. Com ele selecionado, dá
  para arrastá-lo pela parede. **Redistribuir** espalha N exaustores no fundo; os que não
  cabem vão para as laterais. A vazão de cada um aparece na lista e o total no topo.
- **Entradas de ar:** use **+ Entrada de ar** (pad ou cortina) e clique na parede. Depois
  ajuste início, fim, altura, tipo (pad/abertura) e espessura do pad.
- **Itens:** clique num item da **Biblioteca** para colocá-lo no galpão. Mova com **G**, gire
  com **R** ou digite x, y, z, giro e escala. **Delete** exclui.
- **Motor/hélice:** veja a seção 3C.
- **Galpão:** medidas, clima, calor dos animais e do telhado, pressão estática medida.
- **Simular:** salva o projeto, gera a malha, roda e mostra o progresso. No fim, os mapas
  aparecem no painel e a velocidade (ou temperatura) na altura dos animais aparece colorida
  dentro do 3D.

Tudo é salvo no `config.json` do projeto, com cópia `.bak` da versão anterior. Para refazer a
simulação depois de mudar algo, é só clicar em **Salvar e simular** de novo.

---

## 3C. Exaustor a partir do motor, polias, correia e hélice

Na aba **Motor/hélice** (ou em `modelos_exaustor` no JSON) informe para cada modelo de exaustor:

| Campo | Exemplo |
|---|---|
| Motor | 1,5 CV, 1720 rpm |
| Polia do motor / polia da hélice | 100 mm / 390 mm |
| Correia | A-62 (perfil A, 62" internas) |
| Hélice de ponta a ponta | 1,27 m, 6 pás, ângulo 30° |
| Moldura (abertura na parede) | 1,38 m |
| Rotação medida da hélice (opcional) | com tacômetro, substitui o cálculo pelas polias |
| Curva do fabricante (opcional) | pares "pressão Pa; vazão m³/h" do catálogo |

O programa calcula:

- **a rotação da hélice** pela relação de polias (descontando 3 % de escorregamento da correia);
- **a correia:** velocidade e distância entre centros que o código da correia permite;
- **a curva vazão × pressão do exaustor.** Se você informar a curva do catálogo, vale a do
  fabricante. Senão, é estimada pelas leis de semelhança de ventiladores, a partir de um
  exaustor de 50" típico (erro de ±15 %);
- **o ponto de operação:** a pressão em que a vazão dos exaustores é igual à que os pads
  deixam passar. Mais exaustores ou pad mais grosso aumentam a pressão e cada exaustor
  passa a puxar menos;
- **a carga do motor:** avisa **SOBRECARGA** quando a polia escolhida exige mais do que o motor.

Cada exaustor pode ter um modelo diferente, e a simulação usa a vazão real de cada um.
Pelo terminal: `python3 exaustor.py config.json` imprime a ficha de cada modelo.

> Exemplo (config de exemplo): trocar a polia da hélice de 390 para 350 mm sobe a hélice de
> 428 para 477 rpm e a vazão de 32.700 para 36.550 m³/h por exaustor. Mas o motor de 1,5 CV
> vai a ~126 % de carga e o programa avisa a sobrecarga.

---

## 3D. Criar itens: arquivos 3D e fotos

**Arquivo 3D pronto** (SketchUp, Blender, catálogo do fabricante, app de celular): na aba
**Itens → Importar modelo 3D** ou pelo terminal:

```bash
python3 preparar_item.py silo.obj --nome silo --medida altura=6.2
```

O programa põe o objeto em pé, apoia no chão, coloca na escala da medida informada, fecha
buracos e o fundo (exigência da malha) e salva em `biblioteca/`. Confira a figura
`biblioteca/<nome>.png`. Se o objeto ficar deitado, troque o "eixo para cima".

**A partir de fotos** (ex.: fotografar um exaustor por todos os lados): na aba
**Itens → Criar a partir de fotos**, ou:

```bash
python3 fotos_para_3d.py /mnt/c/Users/<voce>/Pictures/exaustor --nome exaustor_50 --medida largura=1.38
```

A reconstrução usa o **Meshroom** (gratuito, AliceVision), que roda na GTX 1650. Baixe em
<https://github.com/alicevision/Meshroom/releases>, descompacte em `C:\` e pronto: o script
o encontra sozinho. Leva de 20 minutos a algumas horas, conforme o número de fotos.

Como fotografar:
- tire de **40 a 150 fotos** dando a volta completa, em 2 ou 3 alturas, com cada foto
  cobrindo ~70 % da anterior;
- use luz uniforme (dia nublado/sombra), sem flash, foco nítido e sem zoom;
- chapa galvanizada brilhante reconstrói mal: fita crepe ou pó fosco em alguns pontos ajudam;
- **meça uma dimensão com a trena**, porque fotos não têm escala.

Sem placa NVIDIA, marque **modo rápido** (`--rapido`), que dá menos detalhe. Também dá para
fazer o 3D num app de celular (RealityScan, Polycam, KIRI Engine), exportar OBJ e importar.

Importante: na simulação, o que define o ar puxado é a **vazão** do exaustor (seção 3C), não o
desenho dele. O modelo 3D do exaustor serve para visualização e para obstáculos próximos.
O desenho conta mesmo para silos, comedouros, baias e pilares, que desviam o ar.

---

## 4. Usando o seu modelo 3D

Sistema de coordenadas usado (o mesmo que o modelo precisa ter):

- **x** = comprimento. `x = 0` é a frente (lado dos pads/entradas), `x = comprimento` é a
  parede dos exaustores;
- **y** = largura (`y = 0` é a parede "esquerda");
- **z** = altura (`z = 0` é o piso);
- **unidade: metros**. Origem no canto interno frente-esquerda-piso.

Há três níveis de detalhe — comece pelo primeiro:

1. **Só dimensões** (padrão): galpão retangular com comprimento/largura/altura do JSON.
   Já dá a resposta de "quantos exaustores" e "onde o ar fica parado".
2. **Envoltória do seu modelo** (`"envoltoria_stl": "modelos/galpao.stl"`): usa a forma
   real do galpão — telhado em duas águas, forro, lanternim etc. O STL precisa ser uma
   **superfície fechada** (estanque) representando o volume de ar interno. Os exaustores e
   entradas continuam sendo posicionados pelo JSON (não precisa desenhar os furos).
3. **Obstáculos** (`"obstaculos_stl": ["modelos/comedouros.stl", "modelos/baias.stl"]`):
   pilares, linhas de comedouro/bebedouro, muretas de baia, silos internos. Cada um deve ser
   um sólido fechado. Detalhes menores que 2 células são ignorados pela malha.

Como exportar STL:

- **SketchUp**: Arquivo → Exportar → Modelo 3D → STL (unidade "metros"). Exporte cada grupo
  (envoltória, obstáculos) separado, com "exportar só a seleção".
- **Blender**: File → Export → STL, marque "Selection Only", "Scale 1.0",
  Forward = Y, Up = Z. Antes, verifique com o add-on *3D-Print Toolbox* se é "manifold".
- **Revit / AutoCAD**: exporte para FBX/OBJ, abra no Blender e exporte STL como acima.

Coloque os arquivos numa pasta `modelos/` ao lado do JSON. O caminho no JSON é relativo ao JSON.

---

## 5. Parâmetros da configuração (`config_exemplo.json`)

| Campo | O que é | Valores típicos |
|---|---|---|
| `galpao` | comprimento, largura, altura (pé-direito) em m | aviário 125–150 × 12–16 × 2,8–3,2 |
| `malha.tamanho_celula` | precisão × tempo (ver tabela acima) | 0,25 |
| `exaustores.vazao_m3h_cada` | **vazão na pressão estática de trabalho** (curva do fabricante) | 50": 30–40 mil m³/h a 25–30 Pa |
| `exaustores.lado_m` | lado da abertura quadrada do exaustor | 50" ≈ 1,38 m |
| `entradas_ar` | aberturas: parede (`frente`, `esquerda`, `direita`), início/fim ao longo da parede, z mín/máx | pads de 15 m em cada lateral |
| `clima.temperatura_entrada_C` | temperatura do ar que entra. **Com pad, use a temperatura depois do pad** | 24–28 °C |
| `cargas_termicas.calor_animais_W_m2` | calor sensível dos animais por m² de piso | frango final 60–90; suíno terminação 40–70 |
| `cargas_termicas.calor_telhado_W_m2` | calor que passa pelo telhado/forro | 5–15 com forro; 30–60 sem |
| `analise.altura_animais_m` | altura do plano analisado | aves 0,3; suínos 0,6 |
| `analise.velocidade_alvo_m_s` | velocidade desejada | frango final 2,5–3,0; suínos 1,0–1,5 |
| `solver.nucleos_cpu` | núcleos usados em paralelo | nº de núcleos físicos |

---

## 6. O que o modelo considera (e o que não considera)

Considera:
- escoamento turbulento 3D em regime permanente (modelo k-ε realizável);
- empuxo térmico (ar quente sobe) pela aproximação de Boussinesq;
- calor dos animais distribuído na camada do piso até a altura dos animais, e ganho solar
  numa camada sob o telhado;
- vazão imposta em cada exaustor e entrada de ar livre pelas aberturas;
- forma real do galpão e obstáculos (se fornecidos em STL).

Não considera (limitações — dá para acrescentar depois, se necessário):
- **curva do exaustor**: a vazão é fixa. Use a vazão da curva na pressão estática que você
  mede no galpão (manômetro). Pads sujos/estreitos aumentam a pressão e reduzem a vazão real;
- **perda de carga e resfriamento do pad**: o pad é uma abertura livre; informe a temperatura
  já resfriada na entrada;
- **umidade** e ITU/entalpia (pode ser acrescentado como campo extra);
- **resistência dos próprios animais** ao escoamento (as aves formam uma "camada porosa"; dá
  para modelar como meio poroso numa segunda etapa);
- **vento externo** e cortinas abertas parcialmente (ventilação natural).

**Valide sempre com medições**: anemômetro a 0,3 m (aves) ou 0,6 m (suínos) a cada 10 m ao
longo do galpão, com o mesmo número de exaustores ligados. Se a média medida diferir muito, o
primeiro suspeito é a vazão real dos exaustores.

---

## 7. Arquivos

| Arquivo | Função |
|---|---|
| `editor.py` + `editor/` | editor 3D no navegador (exaustores, entradas, itens, motor, simulação) |
| `exaustor.py` | modelo do exaustor: polias, correia, curva, ponto de operação, carga do motor |
| `preparar_item.py` | coloca qualquer malha 3D em escala, fecha e salva na biblioteca |
| `fotos_para_3d.py` | fotos → Meshroom → item da biblioteca |
| `geometria.py` | leitura/escrita de STL/OBJ/PLY, transformações, fechamento de malhas |
| `simular_terra.sh` | um comando: importa do DJI Terra, gera, roda e faz o relatório |
| `importar_terra.py` | lê OBJ/PLY/LAS do DJI Terra, acha e mede o barracão, gera `galpao.stl` + `config.json` |
| `calculo_rapido.py` | conta analítica: velocidade média, troca de ar, ΔT, velocidade no pad |
| `gerar_caso.py` | gera o caso OpenFOAM a partir do JSON |
| `pos_processar.py` | gera relatório e mapas (chamado automaticamente pelo `Allrun`) |
| `config_exemplo.json` | configuração de exemplo (aviário 125 × 14 × 3 m, 8 exaustores de 50") |
| `instalar_ubuntu.sh` | instala OpenFOAM 12, Python e dependências no Ubuntu/WSL |

---

## 8. Validação feita

Testado com OpenFOAM 12 no Ubuntu 24.04 (o mesmo que você vai instalar):

- galpão retangular, 8 exaustores de 35.000 m³/h, malha 0,4 m, 1500 iterações em 4 núcleos:
  **~3 minutos**. Vazão total 278.600 m³/h (esperado 280.000), erro de massa 0,00 %,
  temperatura de saída 27,49 °C contra 27,45 °C da conta analítica — o balanço de energia fecha;
- mesmo galpão com a malha padrão (0,25 m, 340 mil células): **12 minutos** em 4 núcleos;
  velocidade média a 0,3 m do piso 1,87 m/s (conta analítica: 1,85 m/s), saída a 27,43 °C.
  Relatório e mapas desse caso estão em [`exemplo_resultados/`](exemplo_resultados/relatorio.md);
- projeto simulado do DJI Terra (terreno inclinado, barracão girado 35° em coordenadas UTM,
  outro galpão e árvores ao redor), em OBJ, PLY e LAS: barracão certo encontrado e medido,
  simulação completa rodou com erro de massa de 0,00 %;
- editor 3D testado num navegador automático: exaustor colocado clicando na parede lateral
  e arrastado 3 m, item da biblioteca posicionado, polia trocada no painel do motor (o
  aviso de sobrecarga apareceu), simulação disparada pelo editor e concluída em 10 min (projeto
  importado do Terra, 9 exaustores), com os mapas e o plano colorido no 3D;
- preparo de item: um "scan" aberto, com ruído, de lado, em escala errada e com sujeira
  solta saiu em pé e fechado, com 1,38 × 0,61 × 1,38 m (real: 1,38 × 0,60 × 1,38 m). A
  reconstrução pelo Meshroom não pôde ser testada aqui (precisa da placa NVIDIA);
- 12 exaustores (8 no fundo + 4 nas laterais), obstáculos STL (linhas de comedouro) e
  envoltória STL com telhado em duas águas: malha gerada com "Mesh OK" e cálculo estável.
