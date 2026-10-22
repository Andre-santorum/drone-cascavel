#!/bin/sh
# Instala tudo o que a simulacao precisa dentro do Ubuntu 24.04 (WSL2 no Windows ou Linux nativo).
# Uso:  sh instalar_ubuntu.sh
set -e
sudo apt-get update
sudo apt-get install -y curl ca-certificates python3 python3-numpy python3-matplotlib git
sudo sh -c "curl -s https://dl.openfoam.org/gpg.key > /etc/apt/trusted.gpg.d/openfoam.asc"
echo "deb http://dl.openfoam.org/ubuntu noble main" | sudo tee /etc/apt/sources.list.d/openfoam.list
sudo apt-get update
sudo apt-get install -y openfoam12
if ! grep -q "openfoam12/etc/bashrc" "$HOME/.bashrc"; then
    echo ". /opt/openfoam12/etc/bashrc" >> "$HOME/.bashrc"
fi
echo
echo "Pronto. Feche e abra o terminal do Ubuntu e teste com:  foamRun -help"
