"""Ponto de entrada congelado do ``agebackup-enviar`` (usado pelo PyInstaller).

Não faz parte do pacote instalável: existe apenas para dar ao PyInstaller um
script concreto para congelar. O binário resultante se comporta exatamente como
o comando ``agebackup-enviar``.
"""

from __future__ import annotations

import sys

from agebackup.ftp import main

if __name__ == "__main__":
    sys.exit(main())
