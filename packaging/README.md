# Empacotamento — executável autônomo

Esta pasta reúne o que o [PyInstaller](https://pyinstaller.org/) usa para gerar
os executáveis **autônomos** do AgeBackup: binários que rodam sem Python
instalado.

## Gerar os binários

Da raiz do projeto (ou de qualquer lugar):

```bash
./packaging/build.sh
```

Saída (em `dist/`, que é *gitignored*):

| Arquivo | Equivale a |
| --- | --- |
| `dist/agebackup-backup` | `uv run agebackup-backup` |
| `dist/agebackup-setup` | `uv run agebackup-setup` |
| `dist/agebackup-compactar` | `uv run agebackup-compactar` |
| `dist/agebackup-enviar` | `uv run agebackup-enviar` |

Os intermediários ficam em `build/pyinstaller/` (`build/` também é *gitignored*)
e podem ser apagados a qualquer momento.

Requisito único: `uv` no `PATH`. O PyInstaller faz parte do grupo de dependências
de desenvolvimento (`pyproject.toml`), então não é preciso ativar nada à mão.

## Por que quatro binários

O projeto declara quatro comandos reais — `agebackup-backup`, `agebackup-setup`,
`agebackup-compactar` e `agebackup-enviar` — e cada um vira um executável. O
entry point `agebackup` é apenas um *placeholder* que imprime uma saudação; por
isso **não** é empacotado.

## O que é embutido além do código

O PyInstaller encontra sozinho os módulos importados, mas não os *arquivos de
dados*. Os specs (`agebackup-backup.spec`, `agebackup-setup.spec`,
`agebackup-compactar.spec` e `agebackup-enviar.spec`) acrescentam:

| Item | Por quê |
| --- | --- |
| `pptx/templates/*` | o `python-pptx` carrega o template ao criar um `.pptx` |
| `docx/templates/*` | o `python-docx` carrega o template ao criar um `.docx` |
| `certifi/cacert.pem` | validação TLS das chamadas HTTPS |
| `googleapiclient/discovery_cache/documents/{drive.v3,slides.v1,docs.v1,sheets.v4}.json` | `googleapiclient.discovery.build` usa **descoberta estática** por padrão; sem esses JSONs o binário falha com `UnknownApiNameOrVersion`, pois não há *fallback* de rede |

O binário é **onefile** (um único arquivo, que se extrai para um diretório
temporário ao rodar) e usa `upx=False` — o UPX costuma não estar instalado e pode
corromper bibliotecas nativas.

## Arquivos

| Arquivo | Papel |
| --- | --- |
| `build.sh` | constrói os quatro executáveis |
| `agebackup-backup.spec` | spec do PyInstaller (backup) |
| `agebackup-setup.spec` | spec do PyInstaller (setup) |
| `agebackup-compactar.spec` | spec do PyInstaller (compactação) |
| `entry_backup.py` | script de entrada congelado (backup) |
| `entry_setup.py` | script de entrada congelado (setup) |
| `entry_compactar.py` | script de entrada congelado (compactação) |
| `agebackup-enviar.spec` | spec do PyInstaller (envio FTP) |
| `entry_enviar.py` | script de entrada congelado (envio FTP) |

Os specs resolvem os caminhos via `SPECPATH`, então o build funciona de qualquer
diretório de trabalho.

## Limitações

- O `onefile` continua dependendo da **glibc** do sistema (não é um binário
  estático). Gerado e testado neste ambiente: Ubuntu 26.04.1 LTS, glibc 2.43,
  Python 3.14.4, PyInstaller 6.22.3.
- Cerca de **49 MB** por binário.
- O binário é específico da plataforma: um executável gerado no Linux não roda
  no Windows/macOS (é preciso empacotar em cada sistema).
