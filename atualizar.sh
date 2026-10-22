#!/usr/bin/env bash
#
# Atualiza o backup: baixa do Drive, compacta e envia para o FTP.
#
# Roda os passos em sequencia. Falhas parciais de download (arquivos com
# download bloqueado pelo dono, por exemplo) NAO impedem a compactacao nem o
# envio: o codigo de saida de cada passo e guardado e reportado no fim. Serve
# tanto para rodar na mao quanto no cron, veja o USERGUIDE.
#
# Uso:
#     ./atualizar.sh
#
# Requisitos: `uv` no PATH. Sem Python, troque os `uv run ...` pelos binarios
# autonomos de dist/ (agebackup-backup, agebackup-compactar, agebackup-enviar).

set -euo pipefail

# Cron e shells minimos nao trazem ~/.local/bin no PATH; garante o `uv`.
export PATH="$HOME/.local/bin:$PATH"

# Uma execucao por vez: se o backup anterior ainda roda, sai sem fazer nada.
lock="${XDG_CACHE_HOME:-$HOME/.cache}/agebackup.lock"
mkdir -p "$(dirname "$lock")"
exec 9>"$lock"
if ! flock -n 9; then
    echo ">> $(date '+%Y-%m-%d %H:%M:%S')  ja existe uma execucao em andamento; saindo."
    exit 0
fi

raiz="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$raiz"
mkdir -p logs

rc_backup=0
echo ">> $(date '+%Y-%m-%d %H:%M:%S')  baixando o backup do Drive..."
uv run agebackup-backup 2>&1 | tee -a logs/backup.log || rc_backup=$?

echo ">> $(date '+%Y-%m-%d %H:%M:%S')  compactando o backup em .tar.gz..."
rc_compact=0
uv run agebackup-compactar 2>&1 | tee -a logs/compactacao.log || rc_compact=$?

echo ">> $(date '+%Y-%m-%d %H:%M:%S')  enviando para o FTP..."
rc_envio=0
uv run agebackup-enviar 2>&1 | tee -a logs/envio.log || rc_envio=$?

echo ">> $(date '+%Y-%m-%d %H:%M:%S')  pronto (backup=$rc_backup, compactacao=$rc_compact, envio=$rc_envio)."

# exit 1 se qualquer passo falhou; falhas parciais de download (1) ja saem
# listadas no resumo do backup e no log.
exit $((rc_backup || rc_compact || rc_envio))
