#!/bin/bash
# Faz tudo de uma vez: importa o galpao do DJI Terra, gera o caso, roda e faz o relatorio.
#
# Uso:
#   ./simular_terra.sh "/mnt/c/Users/<voce>/Documents/DJI/DJI Terra/<conta>/<missao>" [opcoes]
# Opcoes (as mesmas do importar_terra.py), por exemplo:
#   --galpao 2  --exaustores-em inicio  --beiral 0.5  --altura-forro 2.8
# Para mudar quantidade de exaustores, celula etc. sem reimportar:
#   EXAUSTORES=10 CELULA=0.4 ./simular_terra.sh ...
set -e
AQUI="$(cd "$(dirname "$0")" && pwd)"
[ -n "$WM_PROJECT_DIR" ] || . /opt/openfoam12/etc/bashrc

python3 "$AQUI/importar_terra.py" "$@"
modelo="$(cat "$AQUI/modelos/ultimo_importado.txt")"
caso="$AQUI/casos/$(basename "$modelo")${EXAUSTORES:+_${EXAUSTORES}ex}"

python3 "$AQUI/gerar_caso.py" "$modelo/config.json" --saida "$caso" \
    ${EXAUSTORES:+--exaustores $EXAUSTORES} ${CELULA:+--celula $CELULA}
"$caso/Allrun"
echo
echo "Relatorio: $caso/resultados/relatorio.md"
echo "Visualizacao 3D: abra $caso/caso.foam no ParaView"
