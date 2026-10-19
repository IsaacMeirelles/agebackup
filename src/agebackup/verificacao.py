"""Verificação offline de integridade do backup (``--check``).

Compara o que o manifesto diz que existe com o que existe no disco. Não usa a
internet nem a API do Drive: serve para conferir se o destino (HD, cópia,
restore) está completo e íntegro, por exemplo depois de um repentim.

O que é erro de verdade (sai com código 1):

- entrada do manifesto sem arquivo local (``faltando``);
- arquivo com tamanho diferente do registrado (``tamanho_divergente``);
- manifesto ausente ou ilegível (não há o que conferir).

O que é aviso (código 0):

- ``*.tmp`` residuais de uma execução interrompida;
- arquivos no destino que ninguém baixou (``fora_do_manifesto``, só
  informativo: podem ser seus, sidecars ou sobras de renomeações antigas).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agebackup import manifest as manifest_mod
from agebackup.backup import companheiras
from agebackup.falhas import FALHAS_NAME
from agebackup.manifest import MANIFEST_NAME, REMOCIDOS_NAME
from agebackup.rotacao import MARCA_NAME

# Extensão dos parciais gravados por manifest.salvar e downloads interrompidos.
SUFIXO_TMP = ".tmp"


@dataclass
class ResultadoCheck:
    """Resultado da conferência do manifesto contra o disco."""

    manifesto_inutilizavel: bool = False
    verificados: int = 0
    faltando: list[str] = field(default_factory=list)
    tamanho_divergente: list[tuple[str, int, int]] = field(default_factory=list)
    tmp_orfaos: list[str] = field(default_factory=list)
    fora_do_manifesto: list[str] = field(default_factory=list)

    @property
    def problemas(self) -> bool:
        """Diz se há erro de verdade (o ``--check`` sai com código 1)."""
        return bool(
            self.manifesto_inutilizavel or self.faltando or self.tamanho_divergente
        )


def _manifesto_inutilizavel(destino: Path) -> bool:
    """Diz se não dá para confiar no manifesto (ausente, ruim ou de outra versão)."""
    arquivo = manifest_mod.caminho_manifesto(destino)
    if not arquivo.exists():
        return True
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return True
    return dados.get("version") != manifest_mod.MANIFEST_VERSION


def _interno(nome: str) -> bool:
    """Arquivos internos do AgeBackup: nunca são arquivo "fora do manifesto"."""
    if nome in (MANIFEST_NAME, REMOCIDOS_NAME, FALHAS_NAME, MARCA_NAME):
        return True
    # Logs de meses anteriores, comprimidos pela rotação.
    return nome.startswith((f"{REMOCIDOS_NAME}.", f"{FALHAS_NAME}."))


def verificar(destino: Path) -> ResultadoCheck:
    """Confere o manifesto contra o que existe no disco, sem rede.

    Args:
        destino: pasta local do backup.

    Returns:
        Contagens e listas do que divergiu. Ordenadas para saída estável.
    """
    resultado = ResultadoCheck()
    resultado.manifesto_inutilizavel = _manifesto_inutilizavel(destino)
    registros = manifest_mod.carregar(destino)

    for caminho, registro in registros.items():
        resultado.verificados += 1
        arquivo = destino / caminho
        if not arquivo.is_file():
            resultado.faltando.append(caminho)
            continue
        tamanho = arquivo.stat().st_size
        if tamanho != registro.tamanho:
            resultado.tamanho_divergente.append((caminho, registro.tamanho, tamanho))

    caminhos_registrados = set(registros)
    irmas = {
        str(irma.relative_to(destino))
        for caminho in registros
        for irma in companheiras(destino / caminho)
    }

    for arquivo in destino.rglob("*"):
        if not arquivo.is_file():
            continue
        nome = arquivo.name
        if nome.endswith(SUFIXO_TMP):
            resultado.tmp_orfaos.append(str(arquivo.relative_to(destino)))
            continue
        if _interno(nome):
            continue
        caminho = str(arquivo.relative_to(destino))
        if caminho in caminhos_registrados or caminho in irmas:
            continue
        resultado.fora_do_manifesto.append(caminho)

    resultado.faltando.sort()
    resultado.tmp_orfaos.sort()
    resultado.fora_do_manifesto.sort()
    resultado.tamanho_divergente.sort()
    return resultado
