#!/usr/bin/env bash
#
# Gera os executáveis autônomos (standalone) do AgeBackup com o PyInstaller.
#
# Saída:  dist/agebackup-backup  e  dist/agebackup-setup  (binários únicos)
# Trabalho: build/pyinstaller/  (intermediários; pode ser apagado)
#
# Uso (da raiz do projeto ou de qualquer lugar):
#     ./packaging/build.sh
#
# Requisitos: `uv` no PATH. As dependências (incluindo o PyInstaller) vêm do
# grupo de desenvolvimento do pyproject.toml — não é preciso ativar o venv.

set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$raiz"

echo ">> Construindo executáveis em dist/ ..."

for spec in packaging/agebackup-backup.spec packaging/agebackup-setup.spec; do
    echo ">> $spec"
    uv run pyinstaller \
        --noconfirm \
        --clean \
        --distpath dist \
        --workpath build/pyinstaller \
        "$spec"
done

echo
echo ">> Pronto. Executáveis gerados:"
ls -lh dist/agebackup-backup dist/agebackup-setup
