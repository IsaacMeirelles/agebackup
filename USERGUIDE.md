# Guia do Usuário — AgeBackup

Guia para colocar o `agebackup` em uso do zero. Siga na ordem.

## O que é

Ferramenta de backup do Google Drive. Baixa os arquivos da sua conta para uma
pasta local e, em execuções seguintes, só rebaixa o que mudou.

---

## Passo 0 — Pré-requisitos

Você precisa de:

- Python 3.14 — já instalado neste projeto
- **gcloud CLI** (opcional) — só para o método de autenticação ADC

Instalar o gcloud:

```sh
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y google-cloud-cli

# ou baixe o instalador em
# https://cloud.google.com/sdk/docs/install
```

Verifique:

```sh
gcloud --version
```

> Você pode usar o AgeBackup **sem gcloud**, escolhendo o método **Service
> Account** no assistente (não abre navegador).

---

## Passo 1 — Escolher como autenticar

Você tem dois métodos:

| Método | Navegador? | Quando usar |
| --- | --- | --- |
| **ADC via gcloud** | Sim (ou copiar URL no WSL) | Conta Google pessoal |
| **Service Account** | **Não** | Servidor, WSL sem navegador, automação |

**No dia a dia**, deixe o próprio `agebackup-setup` cuidar disso (ele roda o
`application-default login` e já pede os escopos certos). Se preferir fazer
antes na mão:

```sh
gcloud auth application-default login \
  --scopes https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

Se aparecer aviso de app não verificado, escolha **Avançado** → **Acessar o
agebackup (não seguro)**.

> **No WSL**, o navegador não abre sozinho. O agebackup usa `--no-launch-browser`:
> copie a URL, autorize no navegador do Windows, e cole o código de volta.

---

## Passo 2 — Configurar o AgeBackup

```sh
cd ~/projetos/agebackup
uv run agebackup-setup
```

O assistente faz 4 passos:

1. **Conta e credenciais** — escolhe o método e autentica
2. **Destino e escopo** — pergunta a pasta local e se quer só uma pasta do
   Drive ou o Drive inteiro. A pasta escolhida é copiada **com as subpastas**,
   espelhando a árvore do Drive no disco
3. **Teste de conexão** — faz uma chamada real à API e confirma a conta
4. **Rotação e retenção** — por quanto tempo guardar os logs antigos

Respostas sugeridas para começar:

| Pergunta | Sugestão |
| --- | --- |
| Usar a configuração existente? | `s` (ou `n` para começar do zero) |
| Método de autenticação | `1` (ADC) ou `2` (Service Account) |
| Destino local | `~/agebackup` ou outra pasta |
| ID da pasta no Drive | deixe em branco para o Drive inteiro |
| Incluir shared drives? | `n` por enquanto |

O escopo pedido é **somente leitura**:

```
https://www.googleapis.com/auth/drive.readonly
```

Isso é suficiente para backup e evita a burocracia de verificação do Google.

### Conferindo a configuração

```sh
uv run agebackup-setup --status   # mostra o estado atual
uv run agebackup-setup --test     # testa a conexão
uv run agebackup-setup --logs     # edita apenas a política de logs
```

O arquivo fica em `~/.config/agebackup/config.json`, com permissão `600`.

---

## Passo 3 — Simular antes de baixar

**Comece sempre pelo dry-run.** Ele lista o que seria baixado sem gravar nada:

```sh
uv run agebackup-backup --dry-run
```

Você verá algo assim:

```
  baixaria     relatorio.pdf (2.0KB)
  baixaria     planilha (0B)
```

Se a lista estiver correta, siga para o passo 4.

---

## Passo 4 — Executar o backup

```sh
uv run agebackup-backup
```

Saída típica:

```
==============================================================
  Backup do Google Drive
==============================================================
  Conta    : usuario@exemplo.com
  Destino  : /home/isaac/agebackup
  Escopo   : Drive inteiro
  Modo     : real

  baixando     relatorio.pdf...
  ok           relatorio.pdf

==============================================================
  Resumo
==============================================================
  42 arquivos, 42 baixados, 0 inalterados, 87.3MB novos
```

### Opções

| Opção | Efeito |
| --- | --- |
| `--dry-run` | Só lista, não grava nada |
| `--verbose` / `-v` | Mostra também os arquivos inalterados |
| `--falhas` | Mostra as últimas falhas registradas |
| `--logs` | Lista os logs e os arquivos comprimidos |
| `--help` | Não implementado; use as opções acima |

O comando retorna **código de saída 1** se algum arquivo falhou, 0 caso
contrário — útil para agendar com cron.

---

## Passo 5 — Backup incremental

Rode o mesmo comando novamente:

```sh
uv run agebackup-backup
```

Arquivos que não mudaram no Drive são pulados:

```
  42 arquivos, 0 baixados, 42 inalterados
```

O agebackup compara a data de modificação do Drive com a do arquivo local. Só
rebaixa o que mudou.

---

## Passo 6 — Log de arquivos removidos na origem

A cada execução, o AgeBackup verifica quais arquivos que ele já baixou **sumiram do
Drive** e registra isso em um log.

```
==============================================================
  Backup do Google Drive
==============================================================
  ...
  removido    notas-antigas.txt
  excluido    contrato-2025.pdf
  sem acesso  relatorio.pdf
  registrado em /home/isaac/agebackup/logs/.agebackup-removidos.log

==============================================================
  Resumo
==============================================================
  40 arquivos, 0 baixados, 40 inalterados, 2 removidos na origem, 1 sem acesso (fora do escopo)
```

O AgeBackup consulta cada arquivo que sumiu para dizer **por que** ele saiu:

| Rótulo | O que aconteceu |
| --- | --- |
| `removido` | Ainda existe no Drive, mas saiu da listagem (caso raro) |
| `excluido` | Foi para a lixeira do Drive |
| `sem acesso` | Foi movido para uma pasta **não compartilhada** com a conta do backup (a API responde 403/404) |

O `sem acesso` é o caso mais comum quando você **cria uma pasta fora da pasta
compartilhada** (por exemplo, na raiz do *Meu Drive*) e move arquivos para lá. A
conta de backup deixa de enxergá-los. Para voltarem a ser copiados, mantenha a
pasta **dentro** da pasta compartilhada ou compartilhe-a com a conta do backup.

### O que o AgeBackup **não** faz

**O arquivo removido continua no seu computador.** O agebackup apenas registra.
Nada é apagado do disco — a decisão de apagar é sempre sua. Isso vale inclusive
para `sem acesso`: se você trazer os arquivos de volta ao escopo, eles são
reconhecidos de novo.

### O arquivo de log

Local: `.agebackup-removidos.log`, dentro de `logs/` na pasta de backup.

```
2026-10-12T12:39:38+00:00	removido	notas-antigas.txt
2026-10-12T12:41:02+00:00	excluido	contrato-2025.pdf
2026-10-12T12:45:10+00:00	sem_acesso	relatorio.pdf
```

Formato: `data e hora<TAB>motivo<TAB>caminho`. Uma linha por arquivo, com data e
hora do momento em que a remoção foi detectada. O log **acumula** — nada é
sobrescrito, então você tem o histórico.

### Como ele sabe o que foi removido

O agebackup mantém um manifesto (`.agebackup-manifest.json`, escondido) registrando
qual arquivo local veio de qual arquivo do Drive. Isso evita falsos positivos:

| Situação | É reportado como removido? |
| --- | --- |
| Baixou `a.pdf`, foi deletado do Drive | **sim** (`excluido`) |
| Foi movido para pasta não compartilhada | não (`sem acesso`) |
| Você mesmo colocou `nota.txt` na pasta | não |
| Arquivo que o AgeBackup nunca baixou | não |
| Listagem do Drive falhou no meio | não (não sabe o que sumiu) |
| Arquivo já limpo do disco antes | não |

### Conferir o log

```sh
cat ~/agebackup/logs/.agebackup-removidos.log

# só o que saiu na última execução
tail -5 ~/agebackup/logs/.agebackup-removidos.log

# contar quantos foram removidos
wc -l < ~/agebackup/logs/.agebackup-removidos.log
```

### Apagar o log

```sh
rm ~/agebackup/logs/.agebackup-removidos.log
```

Ele é recriado na próxima detecção. O manifesto continua válido.

> Os arquivos `.agebackup-manifest.json` e `.agebackup-removidos.log` começam com
> ponto e não são baixados do Drive: o AgeBackup os ignora ao listar.

---

## Passo 7 — Log de falhas de download

Arquivos que o AgeBackup **não conseguiu baixar** vão para um log separado, com a
categoria da falha:

```
  bloqueado     contrato-restrito.pdf
  temporaria    video-grande.mp4

  Log de falhas
  Arquivo: /home/isaac/agebackup/logs/.agebackup-falhas.log
  Total: 2 bloqueado, 1 temporaria

  Últimas:
  2026-10-12T09:14:22  contrato-restrito.pdf  (bloqueado)
```

### Categorias

| Categoria | Significado | O que fazer |
| --- | --- | --- |
| `operacao_longa` | Só baixa via `files.download` (LRO) | Ainda não suportado |
| `bloqueado` | O dono restringiu o download | Nada a fazer |
| `permissao` | Sem permissão de leitura | Verifique a conta |
| `inexistente` | Sumiu do Drive durante o backup | Normal |
| `cota_excedida` | Limite de requisições da API | Espere ou peça mais cota |
| `temporaria` | Erro 429/500/503 | Repita; já tentou 3x sozinho |
| `erro_local` | Disco cheio, permissão de pasta | Verifique o destino |
| `erro_api` | Outro erro da API | Veja o detalhe no log |
| `listagem` | A listagem do Drive parou no meio | Repita o backup |

### Arquivos que exigem operação de longa duração

Alguns arquivos **não podem ser baixados** pelo método normal. São detectados
antes de qualquer requisição e registrados com a categoria `operacao_longa`:

| Caso | Por quê |
| --- | --- |
| **Google Vids** (`application/vnd.google-apps.video`) | A API responde `fileNotExportable`: *"Google Vids does not support files.export. Use files.download"* |
| **Documentos do Workspace acima de 10 MB** | O `files.export` tem limite de 10 MB |

A alternativa seria `files.download`, uma **operação de longa duração** (LRO):
um POST que devolve um ID, depois polling até ficar pronto, e só então o
download pela URL de conteúdo. O agebackup **ainda não executa LRO**, então esses
arquivos ficam apenas registrados.

```
  requer LRO   gravacao-da-reuniao.mp4

  Resumo
  128 arquivos, 96 baixados, 30 inalterados, 2 exigem operação longa
```

Eles **não contam como falha temporária** — repetir não mudaria o resultado.
Mas o comando retorna código de saída 1, porque houve arquivo que não foi
copiado.

Ver todos os arquivos pendentes:

```sh
awk -F'\t' '$3=="operacao_longa" {print $2}' ~/agebackup/logs/.agebackup-falhas.log
```

### O arquivo de log

Local: `.agebackup-falhas.log`. Formato TSV, uma linha por falha:

```
data<TAB>nome<TAB>categoria<TAB>tentativas<TAB>drive_id<TAB>detalhe
```

### Consultar

```sh
uv run agebackup-backup --falhas    # mostra as últimas, agrupadas por categoria

# só as falhas de hoje
grep "^2026-10-12" ~/agebackup/logs/.agebackup-falhas.log

# quantas falhas de cada tipo
awk -F'\t' '{print $3}' ~/agebackup/logs/.agebackup-falhas.log | sort | uniq -c

# só as bloqueadas
awk -F'\t' '$3=="bloqueado"' ~/agebackup/logs/.agebackup-falhas.log
```

O comando retorna **código de saída 1** se houve qualquer falha, o que
permite alertar em cron.

---

## Passo 8 — Rotação e retenção dos logs

Os dois logs (falhas e remoções) são comprimidos automaticamente quando o mês
vira. O arquivo do mês corrente é sempre `.agebackup-<nome>.log`; os meses
anteriores viram `.agebackup-<nome>.AAAA-MM.log.gz`.

```
~/agebackup/logs/
├── .agebackup-falhas.log              # outubro (texto)
├── .agebackup-falhas.2026-09.log.gz   # setembro (comprimido)
├── .agebackup-removidos.log
├── .agebackup-removidos.2026-09.log.gz
└── .agebackup-mes                     # marca do mês corrente
```

Ler um log compactado:

```sh
zcat ~/agebackup/logs/.agebackup-falhas.2026-09.log.gz | less
```

Listar os logs, a política ativa e os arquivos comprimidos:

```sh
uv run agebackup-backup --logs
```

### Configurar a retenção

A retenção define por quanto tempo os arquivos comprimidos são mantidos antes
de serem apagados.

```sh
uv run agebackup-setup --logs
```

```
  Politica de rotacao dos logs

  Retencao atual: 12 meses
  Alterar a retencao? [n/S]: s
  0 = guardar todos os meses, sem apagar nada
  1 a 120 = quantos meses manter
  Meses de retencao [12]: 6
  Comprimir os logs antigos com gzip? [S/n]:
```

Para mudar de volta, edite `~/.config/agebackup/config.json`:

```json
"logs": {
  "enabled": true,
  "keep_months": 6,
  "compress": true
}
```

| Campo | Valores | Efeito |
| --- | --- | --- |
| `keep_months` | `0` a `120` | `0` = guardar tudo; N = manter N meses |
| `compress` | `true` / `false` | `false` deixa os logs antigos em texto |
| `enabled` | `true` / `false` | Desativa a rotação |

Valores fora do intervalo são ajustados ao máximo (120). O padrão é
**12 meses**.

### Exemplo com 6 meses de retenção

Em outubro, com `keep_months: 6`, o AgeBackup mantém arquivos de abril a outubro.
Março e anteriores são apagados.

> A retenção só apaga arquivos **comprimidos** (`.gz`) de meses anteriores.
> O log do mês corrente nunca é apagado, nem arquivos com nome inesperado.

### Como a virada é detectada

O agebackup guarda o mês corrente num arquivo de marca, `.agebackup-mes`. Isso é
deliberado: usar a data de modificação do log seria impreciso, porque gravar no
mês corrente atualiza essa data e poderia esconder um log antigo, juntando meses
diferentes no mesmo arquivo.

A rotação acontece uma vez por execução do backup e é idempotente: rodar
várias vezes no mesmo mês não faz nada além do necessário. Se um arquivo de
mês antigo ficar pendente (execução anterior falhou), ele é comprimido na
próxima execução, mesmo dentro do mesmo mês.

### Economia de espaço

O gzip costuma reduzir logs de texto em 80% ou mais, porque o formato TSV é
muito repetitivo. Logs de 12 meses raramente passam de poucos MB.

---

## Agendar execução automática

Edite o crontab:

```sh
crontab -e
```

Backup todo dia às 3h da manhã:

```cron
0 3 * * * cd /home/isaac/projetos/agebackup && /home/isaac/projetos/agebackup/.venv/bin/python -m agebackup.cli >> /home/isaac/agebackup-backup.log 2>&1
```

Verifique que funcionou:

```sh
tail -20 ~/agebackup-backup.log
```

---

## O que o backup faz e o que não faz

**Faz:**

- Baixa arquivos binários (PDF, imagens, vídeo, planilha exportada)
- Exporta Google Docs, Sheets e Slides para PDF
- Ignora arquivos na lixeira
- Pula arquivos inalterados
- Grava de forma atômica: escreve num `.tmp` e renomeia no fim, para nunca
  deixar arquivo pela metade com aparência de completo
- **Registra em log os arquivos locais que sumiram do Drive** (sem apagá-los)
- **Registra em log os arquivos que não conseguiu baixar**, com a categoria
  da falha (bloqueado, permissão, temporária, erro local...)
- **Comprime os logs antigos automaticamente** quando o mês vira

**Não faz (ainda):**

- **Não sincroniza de volta** — é somente leitura
- **Não apaga** arquivos locais: apenas registra a remoção no log
- **Não executa operações de longa duração** — Google Vids e documentos do
  Workspace acima de 10 MB ficam registrados como `operacao_longa`
- **Não baixa versões anteriores** de arquivos
- **Não agenda sozinho** — use cron

---

## Problemas comuns

### "gcloud CLI não encontrado"

O gcloud não está instalado. Instale-o (veja o
[Passo 0](#passo-0--pré-requisitos)) **ou** use o método Service Account, que
não precisa dele: rode `uv run agebackup-setup` e escolha a opção `2`.

### "cloud-platform scope is required but not requested"

Versões recentes do gcloud exigem o escopo `cloud-platform` junto com o do
Drive. O agebackup já pede os dois. Se rodar o gcloud na mão, inclua-o:

```sh
gcloud auth application-default login \
  --scopes https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

### O navegador não abre (WSL, servidor, SSH)

O agebackup detecta o WSL e usa `--no-launch-browser`, imprimindo uma URL para você
copiar. Se nem isso funcionar, use o **Service Account** (opção `2`), que não
precisa de navegador.

### "Credenciais ausentes"

```sh
gcloud auth application-default login
uv run agebackup-setup
```

Ou, sem gcloud, escolha o método Service Account no assistente.

### App "não verificado" no navegador

Escolha **Avançado** → **Acessar o AgeBackup (não seguro)**. O Google mostra esse
aviso para qualquer app próprio fora da lista de verificados.

### Arquivos aparecem com nome "arquivo (1).ext"

A pasta local já tem um arquivo com esse nome. O agebackup não sobrescreve: cria um
novo com sufixo.

### Download bloqueado

Alguns arquivos têm download restringido pelo dono (`capabilities.canDownload`
é `false`). Aparecem como `bloqueado` no resumo. Não há como contornar.

### Falhas temporárias

Erros 429/500/503 são repetidos automaticamente até 3 vezes, com espera
crescente.

### `build-essential` ausente

Só é necessário se alguma dependência compilar código nativo. Não afeta o uso
normal. Se precisar:

```sh
sudo apt-get update && sudo apt-get install -y build-essential
```

---

## Referência rápida

```sh
cd ~/projetos/agebackup

uv run agebackup-setup            # configurar
uv run agebackup-setup --status   # ver estado
uv run agebackup-setup --test     # testar conexão
uv run agebackup-setup --logs     # editar retenção dos logs
uv run agebackup-setup --reset    # apagar configuração

uv run agebackup-backup --dry-run # simular
uv run agebackup-backup           # executar
uv run agebackup-backup --falhas  # ver falhas registradas
uv run agebackup-backup --logs    # ver logs e arquivos comprimidos
```

## Arquivos do projeto

```
~/projetos/agebackup/
├── src/agebackup/
│   ├── backup.py      # motor do backup
│   ├── cli.py         # comando agebackup-backup
│   ├── config.py      # configuração, credenciais e política de logs
│   ├── drive.py       # cliente da Drive API e download
│   ├── falhas.py      # log de falhas
│   ├── manifest.py    # manifesto e log de remoções
│   ├── rotacao.py     # rotação mensal e retenção dos logs
│   └── setup.py       # tela de configuração
├── tests/             # 248 testes
└── .opencode/skills/  # documentação de referência
```

## Referência da API

- [Visão geral da Drive API](https://developers.google.com/workspace/drive/api/guides/about-sdk)
- [Download e export](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Escolha de escopos](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Erros comuns](https://developers.google.com/workspace/drive/api/guides/handle-errors)