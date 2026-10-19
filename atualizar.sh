#!/usr/bin/env bash
#
# Atualiza o backup: baixa do Drive e compacta tudo em um .tar.gz.
#
# Roda os dois passos em sequencia. Se o backup falhar, a compactacao nao roda
# (o `set -e` interrompe na hora). Serve tanto para rodar na mao quanto no cron,
# veja o USERGUIDE.
#
# Uso:
#     ./atualizar.sh
#
# Requisitos: `uv` no PATH. Sem Python, troque os `uv run ...` pelos binarios
# autonomos de dist/ (agebackup-backup e agebackup-compactar).

set -euo pipefail

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$raiz"

echo ">> $(date '+%Y-%m-%d %H:%M:%S')  baixando o backup do Drive..."
uv run agebackup-backup

echo ">> $(date '+%Y-%m-%d %H:%M:%S')  compactando o backup em .tar.gz..."
uv run agebackup-compactar

echo ">> $(date '+%Y-%m-%d %H:%M:%S')  pronto."
