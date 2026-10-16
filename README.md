# gback

Ambiente de desenvolvimento Python 3.14 gerenciado com [uv](https://docs.astral.sh/uv/).

## Requisitos

- Python 3.14.4
- uv 0.13.0 (instalado em `~/.local/bin/uv`)

## Uso

Ative o ambiente virtual:

```bash
cd ~/projetos/gback
source .venv/bin/activate
```

Ou use o `uv run` diretamente, que ativa o ambiente automaticamente:

```bash
uv run gback-setup      # assistente de configuração
uv run gback-backup     # executar backup
```

### Comandos comuns

| Comando | Descrição |
| --- | --- |
| `uv run python <arquivo>` | Executa um script no ambiente |
| `uv add <pacote>` | Adiciona dependência |
| `uv add --dev <pacote>` | Adiciona dependência de desenvolvimento |
| `uv remove <pacote>` | Remove dependência |
| `uv sync` | Sincroniza o ambiente com o `pyproject.toml` |
| `uv lock` | Atualiza o `uv.lock` |
| `uv pip list` | Lista pacotes instalados |

### Formatação e lint

```bash
uv run black .
uv run ruff check .
uv run ruff check --fix .
```

## Estrutura

```
gback/
├── .python-version        # versão do Python (3.14)
├── pyproject.toml         # metadados e dependências
├── uv.lock                # versões travadas das dependências
└── src/gback/       # código do pacote
```

## Pendência

Instalar as ferramentas de compilação do sistema (necessário apenas para
dependências que compilam código nativo a partir do fonte):

```bash
sudo apt-get update && sudo apt-get install -y build-essential
```

O `git` já está instalado (2.53.0).