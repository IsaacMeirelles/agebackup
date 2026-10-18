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

> **Sem Python?** Existem executáveis autônomos (`agebackup-setup` e
> `agebackup-backup`) que dispensam Python e `uv` — basta trocar
> `uv run agebackup-setup` por `./agebackup-setup` (e assim por diante). Veja
> [packaging/README.md](packaging/README.md) para gerá-los.

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
  Pasta    : Drive inteiro
  Drives   : apenas o meu
  Modo     : real
  Logs     : /home/isaac/agebackup/logs

  Consultando o Drive...
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
| `--listar-grandes` | Lista os grandes que ainda estão só em PDF (esconde os já recuperados) |
| `--reconstruir-grandes` | Baixa o original/editável dos grandes já salvos em PDF |
| `--logs` | Lista os logs e os arquivos comprimidos |
| `--help` | Mostra a ajuda do comando |

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
| `operacao_longa` | Tipo que só o `files.download` (LRO) entrega (ex.: Google Vids) e cujo download falhou | Repita; se persistir, baixe pela web |
| `grande_demais` | Passou de 10 MB e nem o `files.download`, nem o PDF, nem o editável deram certo | Baixe o original pela web |
| `bloqueado` | O dono restringiu o download | Nada a fazer |
| `permissao` | Sem permissão de leitura | Verifique a conta |
| `inexistente` | Sumiu do Drive durante o backup | Normal |
| `cota_excedida` | Limite de requisições da API | Espere ou peça mais cota |
| `temporaria` | Erro 429/500/503 ou queda de rede | Repita; já tentou 3x sozinho |
| `erro_local` | Disco cheio, permissão de pasta | Verifique o destino |
| `erro_api` | Outro erro da API | Veja o detalhe no log |
| `listagem` | A listagem do Drive parou no meio | Repita o backup |

### Documentos do Google

Arquivos nativos do Google (Docs, Sheets, Slides, Desenhos) são exportados para um
formato comum e ganham a extensão no nome:

| Tipo no Drive | Exportado como |
| --- | --- |
| Documento | `.docx` |
| Planilha | `.xlsx` |
| Apresentação | `.pptx` |
| Desenho | `.pdf` |
| Vídeo (Google Vids) | `.mp4` (via `files.download`, não `files.export`) |

O `files.export` tem **limite de 10 MB por requisição**. Quando o formato
principal não cabe (comum em apresentações cheias de imagens), o AgeBackup
recorre ao `files.download` — uma **operação de longa duração** que monta o
arquivo no servidor e devolve uma URL, **sem esse limite**. O resultado é o
**próprio original editável**, com o nome normal:

```
  baixando     Proposta de consultoria...
    download direto indisponível (HTTP 403 (fileNotExportable))
    export grande demais, repetindo em Proposta de consultoria.pdf
    reconstruído Proposta de consultoria.reconstruido.pptx
  ok           Proposta de consultoria
```

No caso comum, o `files.download` funciona e você recebe o `.pptx` (ou `.docx`,
`.xlsx`) fiel — **sem** precisar habilitar as APIs nativas e **sem** PDF:

```
  baixando     Proposta de consultoria...
    original salvo Proposta de consultoria.pptx
  ok           Proposta de consultoria
```

Só se o `files.download` falhar o AgeBackup cai para o **PDF** (que comprime as
mídias) e, se a API nativa (Slides, Docs ou Sheets) estiver habilitada, ainda
**reconstrói o formato editável** como um arquivo extra `.reconstruido`:

```
    export grande demais, repetindo em Proposta de consultoria.pdf
    reconstruído Proposta de consultoria.reconstruido.pptx
```

A reconstrução preserva o conteúdo (texto, imagens, tabelas, células e
fórmulas), mas **não** o tema, as transições, as animações nem a mídia embutida
(vídeo) — por isso o arquivo tem o sufixo `.reconstruido`, para nunca se passar
por um export fiel. Já o arquivo vindo do `files.download` é um export fiel e
leva o nome normal.

Um **Google Docs** grande ganha um caso a mais: mesmo com a Docs API
desabilitada, ele é salvo como `Nome.reconstruido.md` pelo export de texto do
Drive (`text/markdown`) — pequeno, editável e sem depender da API nativa.

Planilhas gigantes são lidas em blocos (`'Aba'!A1:Z5000`, `'Aba'!A5001:Z10000`,
...) para não estourar o tamanho da resposta nem a memória.

O conteúdo visível fica **sempre** garantido: no original editável quando o
`files.download` funciona, ou no PDF como reserva. Se o PDF for usado e a API
nativa estiver desabilitada ou a reconstrução falhar, o PDF é mantido e o backup
segue normal (sem contar como falha). E se nem o PDF couber, o próprio editável
reconstruído (ou o `.md` de um Doc) é usado como o arquivo salvo, para o backup
não ficar vazio.

Para ver o que ainda ficou em PDF e o link do original (o comando esconde os
arquivos cujo original já foi recuperado):

```sh
uv run agebackup-backup --listar-grandes

#   Originais grandes (baixar pela web)
#   Log: /home/isaac/agebackup/logs/.agebackup-falhas.log
#
#   Proposta de consultoria
#       https://drive.google.com/file/d/<id>/view
#
#   1 arquivo(s). Abra o link e use Arquivo > Fazer download.
```

Se um arquivo já tiver sido salvo em PDF (ele fica "inalterado" e não seria
rebaixado sozinho), recupere o original com:

```sh
uv run agebackup-backup --reconstruir-grandes
```

Esse comando tenta, para cada pendente, o **original verdadeiro** via
`files.download` (gravado com o nome normal, ex.: `Proposta de consultoria.pptx`)
e, se não der, a **reconstrução** editável (`.reconstruido`). O PDF antigo é
mantido; apague-o quando quiser.

Só se nem o `files.download`, nem o PDF, nem o editável derem certo é que o
arquivo entra no log como `grande_demais` **sem** nada salvo — e continua intacto
no Drive.

### Google Vids (operação de longa duração)

O **Google Vids** (`application/vnd.google-apps.video`) não aceita `files.export`
— a API responde `fileNotExportable`: *"Google Vids does not support files.export.
Use files.download"*. O único caminho é o `files.download`, uma **operação de
longa duração** (LRO): um POST que devolve uma operação e, quando pronta, a URL do
conteúdo. O AgeBackup o baixa assim, como **MP4** (nome normal, sem sufixo):

```
  baixando     gravacao-da-reuniao...
  ok           gravacao-da-reuniao

  Resumo
  128 arquivos, 97 baixados, 30 inalterados, 1 por operação longa
```

O mesmo `files.download` é usado para os documentos do Workspace que estouram os
10 MB — ali ele traz o próprio original editável e ainda tem o PDF como reserva.
Para o Vids **não** há export alternativo: se o `files.download` falhar (mesmo
após as repetições automáticas), o arquivo é registrado como falha, com a
categoria do erro da API, e o backup continua. Uma queda de rede no meio costuma
resolver na repetição.

Ver todos os arquivos que falharam por exigir operação longa:

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
- Exporta Google Docs para `.docx`, Sheets para `.xlsx`, Slides para `.pptx`
  (e, quando o formato principal passa de 10 MB, usa o `files.download` para
  trazer o próprio original editável; se falhar, cai para `.pdf` e reconstrói o
  formato editável como `.reconstruido` quando a API nativa está habilitada;
  Docs grandes também saem como `.md` pelo export do Drive)
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

### "download direto indisponível" ou "original editável indisponível"

Um arquivo nativo do Google (Slides, Docs, Sheets) passou de 10 MB. O AgeBackup
tenta primeiro o **original verdadeiro** via `files.download` (operação de longa
duração, sem o limite de 10 MB e sem precisar de API nativa). Se aparecer
"download direto indisponível", essa etapa falhou (rede, cota ou permissão) e ele
seguiu para o PDF; se aparecer "original editável indisponível", o PDF foi salvo
e a **reconstrução** pela API nativa também não funcionou (API desabilitada ou
sem permissão).

O conteúdo está garantido no PDF. Para tentar de novo o original verdadeiro e,
se preciso, a reconstrução, rode:

```sh
uv run agebackup-backup --reconstruir-grandes
```

Se ainda faltar o `.reconstruido`, habilite a API nativa no mesmo projeto Google
das credenciais:

| Tipo | API a habilitar |
| --- | --- |
| Apresentações | [Slides API](https://console.cloud.google.com/apis/library/slides.googleapis.com) |
| Documentos | [Docs API](https://console.cloud.google.com/apis/library/docs.googleapis.com) |
| Planilhas | [Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com) |

Um **Google Docs** não fica sem editável: mesmo sem a Docs API, ele sai como
`Nome.reconstruido.md` (export de texto do Drive).

Alternativa sempre disponível: `uv run agebackup-backup --listar-grandes` mostra
o link para baixar o original pela web (Arquivo → Fazer download).

### Download bloqueado

Alguns arquivos têm download restringido pelo dono (`capabilities.canDownload`
é `false`). Aparecem como `bloqueado` no resumo. Não há como contornar.

### Falhas temporárias

Erros 429/500/503 são repetidos automaticamente até 3 vezes, com espera
crescente. O mesmo vale para **quedas de rede no meio do download** (conexão
reiniciada, *broken pipe*, timeout, corpo incompleto): são tratadas como
temporárias e repetidas, em vez de virarem `erro_local`.

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
uv run agebackup-backup --listar-grandes  # originais grandes guardados em PDF
uv run agebackup-backup --reconstruir-grandes  # baixa o original dos pendentes
uv run agebackup-backup --logs    # ver logs e arquivos comprimidos
```

> Para rodar **sem Python** (`uv`), gere os executáveis autônomos com
> `./packaging/build.sh` — a saída vai para `dist/`. Detalhes em
> [packaging/README.md](packaging/README.md).

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
│   ├── reconstruir.py # reconstrói .pptx/.docx/.xlsx de nativos grandes
│   ├── rotacao.py     # rotação mensal e retenção dos logs
│   └── setup.py       # tela de configuração
├── packaging/         # executável autônomo (PyInstaller)
├── tests/             # 323 testes
└── .opencode/skills/  # documentação de referência
```

## Referência da API

- [Visão geral da Drive API](https://developers.google.com/workspace/drive/api/guides/about-sdk)
- [Download e export](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Escolha de escopos](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Erros comuns](https://developers.google.com/workspace/drive/api/guides/handle-errors)