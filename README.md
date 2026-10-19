# AgeBackup

Backup automático e somente-leitura do Google Drive para o seu computador.

O **AgeBackup** espelha recursivamente uma pasta do Google Drive (ou a conta
inteira) para uma pasta local, rebaixando apenas o que mudou desde a última
execução. Documentos Google são exportados com a extensão correta
(`.docx`, `.xlsx`, `.pptx`), transferências instáveis são repetidas
automaticamente e os logs giram mensalmente com retenção configurável.

## Funcionalidades

- **Espelhamento recursivo** — replica a árvore de pastas do Drive no disco,
  com ou sem `folder_id` (raiz da conta).
- **Incremental** — arquivos inalterados não são rebaixados; o manifesto
  `.agebackup-manifest.json` mapeia cada arquivo do Drive ao seu caminho local.
- **Segue renomeações e movimentações** — quando um arquivo muda de nome ou de
  pasta no Drive, a cópia local é movida para a nova posição (sem rebaixar) e o
  manifesto é reenquadrado; a cópia órfã não fica mais para trás.
- **`--check` de integridade** — confere o backup local contra o manifesto sem
  tocar na API (faltantes, tamanhos divergentes, temporários e órfãos).
- **Nunca sobrescreve** — conflitos de nome ganham sufixo numérico; nada
  existente é substituído.
- **Exportação de documentos Google** — Docs → `.docx`, Planilhas → `.xlsx`,
  Apresentações → `.pptx`, Desenhos → `.pdf`. Documentos que passam do limite de
  10 MB por exportação são obtidos pelo `files.download` (operação de longa
  duração), que **não tem esse limite** nem precisa das APIs nativas: o próprio
  original editável é salvo. O mesmo método entrega os **Google Vids** (que
  recusam `files.export`) como `.mp4`. Só se o `files.download` falhar o AgeBackup
  cai para `.pdf` (que comprime as mídias) e, se a API nativa estiver habilitada,
  para a reconstrução editável `.reconstruido` (um Google Docs grande ainda ganha
  um `.reconstruido.md`, export de texto do Drive). O link para baixar o original
  pela web fica em `agebackup-backup --listar-grandes`, e os pendentes já salvos
  em PDF são recuperados com `agebackup-backup --reconstruir-grandes`.
- **Arquivos grandes (acima de 10 MB)** — só os documentos *nativos* do Google
  têm o limite de exportação; arquivos enviados (`.md`, `.txt`, `.xlsx`, PDFs,
  imagens, vídeos, de qualquer tamanho) são baixados em blocos, direto para o
  disco, sem esse limite. Para os nativos, o `files.download` dispensa o teto.
- **Retry configurável** — repetição automática de falhas temporárias de
  transferência (1 a 10 tentativas, padrão 3).
- **Logs com rotação mensal** — falhas e remoções registrados em
  `destino/logs/`, comprimidos em `.log.gz` e retidos por X meses.
- **Dois modos de autenticação** — Application Default Credentials (conta
  pessoal/gestor) ou Service Account (compartilhando a pasta por e-mail).

## Requisitos

- Python 3.14+ (gerenciado pelo [uv](https://docs.astral.sh/uv/))
- Uma conta Google com a **Google Drive API** habilitada
- Credenciais: OAuth (ADC) **ou** chave de Service Account (JSON)

## Instalação

```bash
git clone git@github.com:IsaacMeirelles/agebackup.git
cd agebackup
uv sync
```

## Uso

```bash
uv run agebackup-setup    # assistente de configuração e autenticação
uv run agebackup-setup --test   # testa credenciais e acesso à pasta
uv run agebackup-backup --dry-run   # simula, sem gravar
uv run agebackup-backup             # executa o backup
```

Parâmetros úteis de `agebackup-backup`:

| Flag | Efeito |
| --- | --- |
| `--dry-run` | Lista o que seria baixado, sem gravar |
| `--verbose` | Detalha cada arquivo processado |
| `--falhas` | Lista as últimas falhas registradas |
| `--listar-grandes` | Lista os grandes ainda só em PDF (com link) |
| `--reconstruir-grandes` | Baixa o original/editável dos grandes já em PDF |
| `--logs` | Mostra os logs e a política de rotação |
| `--check` | Confere o backup local contra o manifesto (offline, sem API) |
| `-h`, `--help` | Mostra a ajuda |

A configuração fica em `~/.config/agebackup/config.json` e o assistente
(`agebackup-setup`) reapresenta os valores atuais a cada execução, pedindo
confirmação — nada precisa ser reescrito do zero.

## Executável autônomo

Para rodar **sem Python instalado**, o projeto gera binários únicos com o
[PyInstaller](https://pyinstaller.org/):

```bash
./packaging/build.sh
# dist/agebackup-backup   dist/agebackup-setup   (~49 MB cada)
```

Cada binário embute o interpretador, as dependências e os dados necessários
(templates `.pptx`/`.docx`, `cacert.pem` e os discovery docs da API), funcionando
offline para montar o cliente. Detalhes em [packaging/README.md](packaging/README.md).

## Estrutura do backup

```
destino/
├── .agebackup-manifest.json   # mapa Drive → caminho local
├── Pastas...                  # espelho da árvore do Drive
└── logs/
    ├── .agebackup-falhas.log        # mês corrente
    ├── .agebackup-falhas.2026-09.log.gz   # meses fechados
    └── .agebackup-removidos.log     # arquivos removidos do Drive
```

## Documentação

| Documento | Conteúdo |
| --- | --- |
| [REQUISITOS.md](REQUISITOS.md) | Requisitos e manual completo, do zero à produção |
| [USERGUIDE.md](USERGUIDE.md) | Guia rápido de uso passo a passo |
| [packaging/README.md](packaging/README.md) | Executável autônomo (PyInstaller) |

## Desenvolvimento

```bash
uv run python -m pytest   # 350 testes (nenhum chama a API real)
uv run black .            # formatação
uv run ruff check .       # lint
./packaging/build.sh      # executáveis autônomos (ver packaging/README.md)
```

A suíte usa um servidor HTTP local que emula a Drive API — não há chamadas
de rede nos testes.

## Roadmap

> **Fase B concluída.** A tabela abaixo lista as fases restantes — os itens
> marcados como pendentes **não existem** no código atual.

| Fase | O que traz |
| --- | --- |
| ~~**B**~~ | **Concluída:** detecção de renomeações/movimentações via manifesto (sem cópia órfã no nome antigo) + `--check` — verificação offline de integridade |
| **A** | CLI com `argparse` (flag inválida vira erro, em vez de cair no fluxo do backup; `--version`) + CI no GitHub Actions (ruff, black, pytest) |
| **C** | Downloads paralelos com `--workers` (padrão 4) e progresso/ETA por arquivo |
| **D** | Suíte opt-in contra a API real (`pytest -m real`, com credenciais) |

## Licença

GPL-3.0 — veja [LICENSE](LICENSE).
