# Guia do Usuário — AgeBackup

Guia para colocar o `agebackup` em uso do zero. Siga na ordem.

## O que é

Ferramenta de backup do Google Drive. Baixa os arquivos da sua conta para uma
pasta local e, em execuções seguintes, só rebaixa o que mudou.

O AgeBackup tem duas formas de uso — as duas fazem exatamente as mesmas coisas:

| Forma | Quando usar |
| --- | --- |
| **Aplicativo (interface gráfica)** | Dia a dia: configura, executa, compacta, envia, restaura e lê os logs numa janela só |
| **Linha de comando** | Automação, cron, servidores e diagnóstico |

> A configuração é **a mesma** para as duas formas: um arquivo `agebackup.json`
> guardado **junto ao aplicativo/binário**. Configure pela janela e o cron usa
> o que foi salvo, e vice-versa.

---

## Aplicativo gráfico (janela única)

O comando é:

```sh
cd ~/projetos/agebackup
uv run agebackup-gui
```

Ou, se estiver usando o executável autônomo:

```sh
./agebackup-gui
```

### Pré-requisito: Tkinter

A janela usa o Tkinter, que em algumas distribuições não vem com o Python:

```sh
# Debian / Ubuntu / WSL
sudo apt update && sudo apt install -y python3-tk
```

Confira:

```sh
python3 -c "import tkinter; print('tkinter OK')"
```

> Em WSL, a janela aparece pelo WSLg (WSL2 atualizado). Se nada abrir, veja a
> seção [Problemas comuns](#problemas-comuns).

### As abas

| Aba | Para que serve |
| --- | --- |
| **Início/Status** | Resumo do que está configurado (conta, destino, compactação, logs, FTP) e atalhos para as outras abas |
| **Configuração** | Todos os campos de conta, backup, compactação, logs e envio, em sub-abas |
| **Backup** | Executa o backup com o log aparecendo em tempo real (com caminho completo dos arquivos) |
| **Compactação** | Lista os `.tar.gz`, segue a política automática, força FULL/INCREMENTAL e aplica a retenção |
| **Upload Manual** | Envia um `.tar.gz` ou os logs sob demanda |
| **Restaurar** | Restaura um arquivo individual de dentro do `.tar.gz` ou o arquivo completo |
| **Log** | Abre os logs com filtro de texto e caminho completo |
| **Ajuda** | Guia detalhado da aba aberta: finalidade, cada campo e o que cada botão faz (atalho **F1**) |

### Atalhos

| Atalho | Ação |
| --- | --- |
| `F1` | Abre o guia detalhado da aba em que você está |
| `Ctrl+S` | Salva a configuração (na aba Configuração) |
| `Ctrl+Q` | Fecha o aplicativo |

### Ajuda dentro do programa

A tecla **F1** (ou o botão **Ajuda da aba (F1)**, no topo) abre um guia da aba
que está aberta. Cada guia explica:

- **para que serve a aba** e o que ela não faz;
- **cada campo**: o que preencher, o que acontece se ficar vazio e como o valor
  é usado;
- **cada botão**: o que acontece ao clicar, o que é validado e onde o resultado
  aparece;
- erros comuns, dicas e o passo a passo das tarefas.

No topo da janela de ajuda há uma lista **Guia da aba** para trocar de guia sem
fechar a janela. A ajuda também está disponível na aba **Início/Status**, pelo
botão **Abrir Ajuda (F1)**.

### Configuração junto ao aplicativo

A configuração fica em **`agebackup.json` na mesma pasta do executável** (em
desenvolvimento, na raiz do projeto). Na primeira execução, o AgeBackup migra
automaticamente o antigo `~/.config/agebackup/config.json`, se ele existir.

> As credenciais ficam **criptografadas** nesse arquivo: a senha do FTP
> (`ftp.senha_criptografada`), o JSON da Service Account
> (`account.service_account_json_criptografado`) e o token ADC
> (`account.adc_json_criptografado`). A chave usada para cifrar fica num
> arquivo separado, `.agebackup-ftp.key`, com permissão restrita. Copie o
> `agebackup.json` e essa chave juntos.

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

> **Sem Python?** Existem executáveis autônomos (`agebackup-gui`,
> `agebackup-setup`, `agebackup-backup`, `agebackup-compactar` e
> `agebackup-enviar`) que dispensam Python e `uv` — basta trocar
> `uv run agebackup-setup` por `./agebackup-setup` (e assim por diante). Veja
> [packaging/README.md](packaging/README.md) para gerá-los e
> [DEPLOY.md](DEPLOY.md) para transferi-los a outro servidor.

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

O assistente faz 5 passos:

1. **Conta e credenciais** — escolhe o método e autentica
2. **Destino e escopo** — pergunta a pasta local e se quer só uma pasta do
   Drive ou o Drive inteiro. A pasta escolhida é copiada **com as subpastas**,
   espelhando a árvore do Drive no disco
3. **Teste de conexão** — faz uma chamada real à API e confirma a conta
4. **Rotação e retenção** — por quanto tempo guardar os logs antigos
5. **Política de compactação** — pasta, retenção, prefixo e de quantos em
   quantos dias fazer um full

> A mesma configuração pode ser feita pela janela (aba **Configuração**), que
> tem uma sub-aba para cada uma dessas seções.

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
uv run agebackup-setup --status        # mostra o estado atual
uv run agebackup-setup --test          # testa a conexão
uv run agebackup-setup --logs          # edita apenas a política de logs
uv run agebackup-setup --compactacao   # edita apenas a política de compactação
```

O arquivo fica em **`agebackup.json`, junto ao aplicativo** (com permissão
`600`). Ele contém **todas** as seções usadas pelo backup, compactação, logs e
envio:

```json
{
  "account":     { "email": "...", "auth_method": "service_account", "...": "..." },
  "backup":      { "destination": "/home/isaac/bkps", "folder_id": "...", "include_shared_drives": true },
  "logs":        { "enabled": true, "keep_logs": 7, "compress": true, "directory": "logs" },
  "retry":       { "attempts": 3 },
  "compactacao": { "destino": "/mnt/c/backups", "manter": 7, "prefixo": "RSKO", "full_a_cada": 7 },
  "envio":       { "credenciais": "", "manter": 7, "pasta_remota": "" },
  "ftp":         { "host": "...", "porta": 21, "usuario": "...", "senha_criptografada": "...", "pasta_remota": "", "tls": true }
}
```

> Quem já usava a versão antiga não perde nada: o `config.json` de
> `~/.config/agebackup/` é copiado para junto do aplicativo na primeira
> execução (o original é preservado como `config.json.bak`).

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
| `--check` | Confere o backup local contra o manifesto, sem tocar na API |
| `--help` | Mostra a ajuda do comando |

O comando retorna **código de saída 1** se algum arquivo falhou, 0 caso
contrário — útil para agendar com cron. O `--check` retorna 1 só para erros
de integridade (arquivo faltando ou tamanho divergente); avisos isolados
saem com 0.

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
data<TAB>nome<TAB>categoria<TAB>tentativas<TAB>drive_id<TAB>detalhe<TAB>caminho<TAB>modificado
```

As duas últimas colunas são o **caminho local completo** onde o arquivo deveria
estar e a **data de modificação no Drive** (ISO 8601), para localizar o item sem
precisar procurá-lo pelo nome. Logs gravados por versões anteriores têm só as
seis primeiras colunas e continuam legíveis.

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

Cada execução começa um log novo, com **data e hora no nome**. Quando a execução
seguinte começa, o log anterior é fechado e comprimido; o arquivo da execução em
andamento é sempre `.agebackup-<nome>.log`. Apenas os **7 mais recentes** ficam
guardados (configurável).

```
~/agebackup/logs/
├── .agebackup-falhas.log                        # execução atual (texto)
├── .agebackup-falhas.2026-10-21-1842.log.gz     # execução anterior
├── .agebackup-falhas.2026-10-20-0300.log.gz
├── .agebackup-removidos.log
├── .agebackup-removidos.2026-10-21-1842.log.gz
├── .agebackup-envios.log                        # status dos envios ao FTP
└── .agebackup-envios.2026-10-21-1842.log.gz
```

Ler um log compactado:

```sh
zcat ~/agebackup/logs/.agebackup-falhas.2026-10-21-1842.log.gz | less
```

Listar os logs, a política ativa e os arquivos comprimidos:

```sh
uv run agebackup-backup --logs
```

### Configurar a retenção

A retenção define quantos logs fechados são mantidos antes de serem apagados.

```sh
uv run agebackup-setup --logs
```

```
  Politica de rotacao dos logs

  Retencao atual: 7 execucoes
  Alterar a retencao? [n/S]: s
  0 = guardar todos os logs, sem apagar nada
  1 a 365 = quantos logs fechar e manter
  Logs a manter [7]: 30
  Comprimir os logs antigos com gzip? [S/n]:
```

Para mudar de volta, edite a seção `logs` do `agebackup.json` (junto ao
aplicativo):

```json
"logs": {
  "enabled": true,
  "keep_logs": 7,
  "compress": true,
  "directory": "logs"
}
```

| Campo | Valores | Efeito |
| --- | --- | --- |
| `keep_logs` | `0` a `365` | `0` = guardar tudo; N = manter N logs fechados |
| `compress` | `true` / `false` | `false` deixa os logs antigos em texto |
| `enabled` | `true` / `false` | Desativa a rotação |

Valores fora do intervalo são ajustados ao máximo (365). O padrão é
**7 logs**.

### Exemplo com 3 logs de retenção

Com `keep_logs: 3`, o AgeBackup guarda apenas os 3 logs fechados mais recentes.
Os anteriores são apagados (a contagem é por data/hora no nome, então a ordem é
cronológica).

> A retenção só apaga arquivos **comprimidos** (`.gz`) de execuções anteriores.
> O log da execução corrente nunca é apagado, nem arquivos com nome inesperado.

### Como a virada é detectada

A rotação roda **no início da execução, antes de qualquer escrita**. Se um log
existir nesse momento, ele é da execução anterior e é fechado com a data/hora do
próprio arquivo (mtime). Cada log tem seu ciclo: `.agebackup-falhas.log`,
`.agebackup-removidos.log` e `.agebackup-envios.log` são rotacionados de forma
independente.

> Versões anteriores usavam um arquivo de marca, `.agebackup-mes`, para decidir
> a virada. Ele **não é mais criado**; se existir numa instalação antiga, é
> removido na próxima execução do backup e ignorado pela conferência.

A rotação é idempotente: rodar várias vezes sem um log corrente não faz nada
além do necessário. Se um log de execução anterior ficar pendente (execução
interrompida), ele é comprimido na próxima execução.

### Economia de espaço

O gzip costuma reduzir logs de texto em 80% ou mais, porque o formato TSV é
muito repetitivo. Mesmo com muitos logs guardados, o histórico raramente passa
de poucos MB.

---

## Passo 9 — Compactar o backup em um arquivo

Depois do backup, você pode juntar a pasta do backup inteira em um único arquivo
`.tar.gz` — útil para guardar um retrato datado em outro disco ou enviar para a
nuvem.

```sh
uv run agebackup-compactar
```

```
==============================================================
  Compactar backup
==============================================================
  Origem   : /home/isaac/bkps
  Destino  : /mnt/c/backups
  Tipo     : full
  Retencao : guardar todos
  Modo     : real

  Arquivo  : /mnt/c/backups/bkps_20261019-1635.tar.gz
  Tipo     : full
  Tamanho  : 727.7 MB
  Conteudo : 1732 arquivo(s)
```

O nome gerado é `<pasta>_AAAAMMDD-HHMM.tar.gz`. Um prefixo opcional entra antes da
data — `<pasta>_<prefixo>_AAAAMMDD-HHMM.tar.gz` —, útil para marcar a origem da cópia
(ex.: `bkps_nuvem_20261019-1437.tar.gz`). A gravação é atômica: o
AgeBackup escreve um `.tmp` e só então renomeia, então uma falha no meio não
deixa um arquivo pela metade. Os `.tmp` de execuções interrompidas ficam de fora
do arquivo. Com o horário no nome, duas execuções no mesmo dia geram arquivos
distintos (não se sobrescrevem).

### Full e incremental

A política segue a configuração `compactacao.full_a_cada`, que é **quantos dias
entre um full e o próximo** (padrão: **7**):

- **full** — guarda a pasta de backup inteira;
- **incremental** — guarda só os arquivos novos e alterados desde o full.

Ou seja, com o padrão de 7 dias: um full por semana e, nos dias intermediários,
apenas os incrementais — muito mais rápido e leve no dia a dia.

```
/mnt/c/backups/
├── bkps_RSKO_20261019-2200.tar.gz        # full
├── bkps_RSKO_inc_20261020-2200.tar.gz    # incremental (dia seguinte)
├── bkps_RSKO_inc_20261021-2200.tar.gz    # incremental
└── .agebackup-compactacao.json           # estado: último full e quando foi feito
```

O incremental tem a marca `inc` antes da data:
`<pasta>[_<prefixo>]_inc_AAAAMMDD-HHMM.tar.gz`. Para **restaurar**, extraia o
full e depois cada incremental por cima, em ordem:

```sh
tar xzf bkps_RSKO_20261019-2200.tar.gz
tar xzf bkps_RSKO_inc_20261020-2200.tar.gz
tar xzf bkps_RSKO_inc_20261021-2200.tar.gz
```

A contagem de dias vem do arquivo de estado `.agebackup-compactacao.json`,
gravado na pasta de destino. Um full novo é feito automaticamente quando: é a
primeira compactação, já passaram os dias configurados desde o último full, ou
o full de referência foi apagado pela retenção.

Para mudar a periodicidade (aba **Configuração → Compactação**, ou na linha de
comando):

| `full_a_cada` | Efeito |
| --- | --- |
| `7` (padrão) | full a cada 7 dias; incrementais nos demais |
| `1` | full todos os dias (equivale a "sempre full") |
| `0` | compacta tudo a cada execução |
| `30` | um full por mês; incrementais nos demais dias |

Para forçar um dos modos:

```sh
uv run agebackup-compactar --full         # força a pasta inteira
uv run agebackup-compactar --incremental  # só o que mudou (erro se não houver full)
```

### Onde o arquivo é gravado

- `--destino P` — grava em `P`;
- sem a opção, usa o `compactacao.destino` da configuração;
- sem nada configurado, grava na pasta **acima** do backup.

Para fixar o destino, use a seção `compactacao` do `agebackup.json` (ou a aba
**Configuração → Compactação**):

```json
"compactacao": {
  "destino": "/mnt/c/backups",
  "manter": 0,
  "prefixo": "",
  "full_a_cada": 7
}
```

| Campo | Valores | Efeito |
| --- | --- | --- |
| `destino` | caminho | Onde gravar (vazio = pasta acima do backup) |
| `manter` | `0` a `60` | `0` = guardar tudo; N = manter os N mais recentes |
| `prefixo` | texto | Texto entre a pasta e a data, ex.: `bkps_nuvem_20261019-1437.tar.gz` (vazio = sem prefixo) |
| `full_a_cada` | `0` a `365` | Dias entre um full e o próximo (`7` = semanal; `0` = sempre full) |

> A pasta de destino **não** pode ficar dentro do backup: senão o próprio
> arquivo entraria no backup e cresceria a cada execução.

### Simular, listar e limitar

```sh
uv run agebackup-compactar --dry-run       # mostra o que seria feito, sem gravar
uv run agebackup-compactar --listar        # lista os arquivos já gerados
uv run agebackup-compactar --manter 5      # guarda só os 5 mais recentes
uv run agebackup-compactar --prefixo nuvem # bkps_nuvem_AAAAMMDD-HHMM.tar.gz
uv run agebackup-compactar --full          # força a compactação full
uv run agebackup-compactar --incremental   # força a incremental
uv run agebackup-compactar --destino /mnt/outro-disco
```

> A compactação é um passo **separado** do backup. Rode quando quiser — por
> exemplo no fim da linha do cron (veja a seguir).

---

## Passo 10 — Enviar o arquivo compactado para o FTP

Para tirar a cópia do computador, o `agebackup-enviar` sobe o `.tar.gz` mais
recente do destino da compactação para um servidor FTP/FTPS.

```sh
uv run agebackup-enviar
```

```
==============================================================
  Enviar backup para FTP
==============================================================
  Servidor : u208146-sub16.your-storagebox.de:21 (FTPS)
  Usuario  : u208146-sub16
  Arquivo  : /mnt/c/backups/bkps_RSKO_20261021-2244.tar.gz
  Pasta    : /2026/10
  Retencao : 7 arquivo(s)
  Confere  : tamanho
  Modo     : real

  enviando... 100.0%  (13.2 GB de 13.2 GB)
  conferindo no servidor...
  Status   : /home/isaac/agebackup/logs/.agebackup-envios.log

  Arquivo  : bkps_RSKO_20261021-2244.tar.gz
  Local    : 12.9 GB
  Remoto   : /2026/10/bkps_RSKO_20261021-2244.tar.gz
  Tamanho  : 12.9 GB (no servidor)
  Conferido: tamanho (igual ao local)

  OK: envio concluido e conferido.
```

O arquivo vai para uma pasta de **ano e mês** (`/2026/10/`), criada sozinha se
não existir, e fica junto dos meses anteriores. Esse padrão pode ser
personalizado — veja [Pasta remota personalizada](#pasta-remota-personalizada).

### Conferência remota dos logs

Depois do `.tar.gz`, o AgeBackup envia também os **logs** para uma subpasta
`logs` do mesmo mês (`/2026/10/logs/`), para você poder auditar de longe o que
aconteceu sem depender da máquina local:

```
/2026/10/
├── bkps_RSKO_20261021-2244.tar.gz
└── logs/
    ├── .agebackup-falhas.log                     # execução corrente
    ├── .agebackup-falhas.2026-10-20-0300.log.gz  # execuções fechadas
    ├── .agebackup-removidos.log
    └── .agebackup-envios.log                     # status dos envios
```

Os logs fechados **já vão comprimidos** (`.log.gz`), pela rotação do Passo 8; o
log da execução corrente vai em texto. Cada um é conferido pelo tamanho no
servidor, igual ao `.tar.gz`. Para pular esse passo:

```sh
uv run agebackup-enviar --sem-logs
```

### Log de status dos envios

Toda tentativa de envio — pelo comando `agebackup-enviar` ou pela aba **Upload
Manual** — acrescenta uma linha em **`.agebackup-envios.log`**, na pasta de logs
do backup. O envio que falha também é registrado, para você saber o que faltou.

O formato é TSV, uma linha por arquivo:

```
data<TAB>status<TAB>arquivo<TAB>caminho<TAB>tamanho_local<TAB>tamanho_remoto<TAB>pasta_remota<TAB>conferencia<TAB>detalhe
```

| Coluna | Conteúdo |
| --- | --- |
| `data` | data/hora da tentativa (ISO 8601) |
| `status` | `ok` ou `falha` |
| `arquivo` | nome do arquivo enviado |
| `caminho` | caminho local **completo** |
| `tamanho_local` / `tamanho_remoto` | bytes; remoto `0` quando não conferido |
| `pasta_remota` | pasta calculada no servidor |
| `conferencia` | `tamanho`, `sha256` ou vazio |
| `detalhe` | mensagem de erro, quando houver |

Exemplo:

```
2026-10-22T22:10:03+00:00	falha	bkps_RSKO_20261021-2244.tar.gz	/mnt/c/backups/bkps_RSKO_20261021-2244.tar.gz	13841203200	0	/2026/10	tamanho	tamanho diferente no servidor: local 13841203200B, remoto 0B
```

Pela interface, abra a aba **Log** e clique em **Carregar
.agebackup-envios.log**; o filtro `falha` mostra só o que não subiu. O arquivo
é rotacionado junto com os demais logs (quando a rotação está ativa) e mantém os
`keep_logs` mais recentes.

### Credenciais

Os dados do servidor ficam **dentro do próprio `agebackup.json`**, na seção
`ftp`, com a **senha criptografada**:

```json
"ftp": {
  "host": "u208146-sub16.your-storagebox.de",
  "porta": 21,
  "usuario": "u208146-sub16",
  "senha_criptografada": "gAAAAAB...",
  "pasta_remota": "",
  "tls": true
}
```

Na aba **Configuração → Envio (FTP/FTPS)** dá para editar **host, porta,
usuário, senha, pasta remota e TLS**. Ao salvar, todos esses dados vão para o
`agebackup.json`; a senha é cifrada com a chave de `.agebackup-ftp.key`, que
fica ao lado do arquivo de configuração, com permissão restrita.

> **Importante:** a senha salva nunca é exibida de volta. O campo fica em
> branco ao abrir a configuração: deixe-o vazio para manter a senha atual ou
> digite uma nova para substituí-la. O botão **Mostrar** só revela o que você
> acabou de digitar.

Para migrar uma instalação antiga, use **Importar credenciais do .ini...** (ou
**Importar ftp.ini padrão**) e clique em **Salvar**. A partir daí o arquivo
externo não é mais necessário. **Limpar credenciais salvas** remove host,
usuário, senha e pasta remota do JSON ao salvar.

Ainda é possível usar um arquivo externo de credenciais, mas ele só é
consultado quando **host e usuário estão vazios** na configuração. São aceitos
dois formatos.

Formato de três linhas (o usado no Storage Box da Hetzner):

```
ftp://u208146-sub16.your-storagebox.de
user: u208146-sub16
password: sua-senha
```

Formato `.ini`:

```ini
[ftp]
host = u208146-sub16.your-storagebox.de
user = u208146-sub16
password = sua-senha
porta = 21
pasta =
tls = true
```

Para usar um arquivo externo, aponte em `envio.credenciais`:

```json
"envio": {
  "credenciais": "/home/isaac/.config/agebackup/ftphetzner.ini",
  "manter": 7,
  "pasta_remota": ""
}
```

| Campo | Valores | Efeito |
| --- | --- | --- |
| `credenciais` | caminho | Arquivo externo com host/usuário/senha (vazio = `ftp.ini`; os dados de `ftp` têm prioridade) |
| `manter` | `0` a `365` | `0` = guardar tudo; N = manter os N mais recentes no servidor |
| `pasta_remota` | texto | Padrão personalizado do caminho remoto (vazio = `/AAAA/MM/`) |

> **FTPS x FTP:** por padrão a conexão usa **FTPS explícito** na porta 21 (o
> esperado por servidores como o Storage Box). Para FTP puro, use
> `"tls": false` na seção `ftp`.

### Pasta remota personalizada

Por padrão o arquivo vai para `/AAAA/MM/` (ex.: `/2026/10/`). Você pode definir
qualquer caminho, usando as variáveis abaixo — o resto é livre (qualquer
caractere válido em nome de pasta):

| Variável | Vira | Exemplo (22/10/2026) |
| --- | --- | --- |
| `YYYY` | ano com 4 dígitos | `2026` |
| `YY` | ano com 2 dígitos | `26` |
| `MM` | mês com 2 dígitos | `10` |
| `M` | mês sem zero à esquerda | `10` |
| `dd` | dia com 2 dígitos | `22` |
| `d` | dia sem zero à esquerda | `22` |

Exemplos:

| `pasta_remota` | Resultado |
| --- | --- |
| *(vazio)* | `/2026/10/` |
| `/backups/YYYY/MM` | `/backups/2026/10/` |
| `/RSKO/YYYY-MM` | `/RSKO/2026-10/` |
| `/clientes/RSKO/YYYY/MM/dd` | `/clientes/RSKO/2026/10/22/` |
| `/rotina-YY` | `/rotina-26/` |

A pasta é criada automaticamente no servidor, nível por nível, se não existir.
Os logs vão para uma subpasta `logs` **dentro** dessa pasta.

### Conferência do que subiu

O envio sempre confere o **tamanho** do arquivo no servidor contra o local — é a
conferência barata, e pega um envio truncado. Para a prova byte a byte (útil
depois de enviar dezenas de GB), use o SHA-256:

```sh
uv run agebackup-enviar --verificar-sha256    # baixa de volta e compara o hash
```

Conferir sem enviar nada (o arquivo já está no servidor):

```sh
uv run agebackup-enviar --conferir /mnt/c/backups/bkps_RSKO_20261021-2244.tar.gz
```

Outras opções:

```sh
uv run agebackup-enviar --dry-run             # simula, sem enviar
uv run agebackup-enviar --arquivo P           # envia um arquivo específico
uv run agebackup-enviar --manter 3            # guarda só os 3 mais recentes
uv run agebackup-enviar --sem-verificacao     # não confere o tamanho
uv run agebackup-enviar --sem-logs            # não envia os logs
uv run agebackup-enviar --credenciais P       # outro arquivo de credenciais
```

> O SHA-256 gasta a banda **de novo** (baixa o arquivo inteiro). Em um link de
> 5 MB/s, isso significa ~45 min para um arquivo de 13 GB.

---

## Passo 11 — Restaurar arquivos

Restaurar é o caminho de volta: tirar um arquivo (ou tudo) de dentro do
`.tar.gz` gerado no Passo 9.

### Pela janela (aba Restaurar)

A aba **Restaurar** cobre os dois casos:

1. **Arquivo individual** — clique em **Selecionar .tar.gz** (a janela já abre
   na pasta de compactação), use o campo **Filtrar** para achar o arquivo,
   selecione um ou mais itens e escolha:
   - **Restaurar selecionado(s) aqui...** — extrai na pasta de compactação
     (padrão);
   - **Restaurar em outra pasta...** — pergunta o destino.

2. **Arquivo completo** — **Restaurar arquivo COMPLETO** extrai todo o
   conteúdo, também com a pasta de compactação como destino padrão.

> O destino padrão da restauração é a **pasta de compactação**
> (`compactacao.destino`). Você pode trocar na hora, na caixa de diálogo.

**Arquivos grandes:** a primeira abertura de um `.tar.gz` precisa descomprimir
o arquivo só para listar o conteúdo, o que pode levar alguns minutos. A janela
continua respondendo e mostra a contagem de itens; o botão **Cancelar leitura**
interrompe. Depois da primeira leitura o índice fica em cache (pasta
`indices/`, junto ao `agebackup.json`), então abrir o mesmo arquivo de novo é
imediato — desde que ele não tenha sido alterado. A lista mostra no máximo
2.000 itens por vez: use o **Filtro** para encontrar o que precisa.

### Pela linha de comando

Listar o conteúdo de um arquivo:

```sh
tar tzf /mnt/c/backups/bkps_RSKO_20261019-2200.tar.gz | less
```

Extrair só um arquivo (ou uma pasta):

```sh
# extrai apenas "Documentos/contrato.pdf" para /tmp/restaurado
tar xzf /mnt/c/backups/bkps_RSKO_20261019-2200.tar.gz \
    -C /tmp/restaurado "Documentos/contrato.pdf"
```

Extrair tudo:

```sh
mkdir -p /tmp/restaurado
tar xzf /mnt/c/backups/bkps_RSKO_20261019-2200.tar.gz -C /tmp/restaurado
```

### Sequência com incrementais

Um incremental **não** é autossuficiente: ele contém só o que mudou. Para
recompor um estado, extraia o **full** e depois os incrementais **na ordem do
nome** (que é cronológica), todos para a mesma pasta:

```sh
mkdir -p /tmp/restaurado
tar xzf /mnt/c/backups/bkps_RSKO_20261019-2200.tar.gz     -C /tmp/restaurado
tar xzf /mnt/c/backups/bkps_RSKO_inc_20261020-2200.tar.gz -C /tmp/restaurado
tar xzf /mnt/c/backups/bkps_RSKO_inc_20261021-2200.tar.gz -C /tmp/restaurado
```

Os incrementais sobrescrevem com a versão mais nova apenas os arquivos que
mudaram — o resto continua vindo do full.

---

## Agendar execução automática

O script `atualizar.sh` faz os três passos em sequência: baixa o backup,
compacta e envia para o FTP. Falhas parciais de download (arquivos com download
bloqueado pelo dono) **não** impedem a compactação nem o envio.

Edite o crontab:

```sh
crontab -e
```

Backup, compactação e envio todo dia às 22h:

```cron
PATH=/home/isaac/.local/bin:/usr/local/bin:/usr/bin:/bin
0 22 * * * /home/isaac/projetos/agebackup/atualizar.sh >> /home/isaac/agebackup-atualizar.log 2>&1
```

> A linha `PATH=` é necessária: o cron não herda o `~/.local/bin`, onde o `uv`
> costuma ficar. Sem ela, o script falha com `uv: command not found`.

O script usa uma trava (`flock`): se a execução anterior ainda estiver rodando,
a nova sai sem fazer nada — evita duas execuções competindo pelo mesmo arquivo.
O resultado de cada passo fica nos logs do projeto (`logs/backup.log`,
`logs/compactacao.log`, `logs/envio.log`).

Verifique que funcionou:

```sh
tail -20 ~/agebackup-atualizar.log
tail -20 /home/isaac/projetos/agebackup/logs/envio.log
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
- **Move a cópia local quando o Drive renomeia ou move um arquivo** (sem
  rebaixar, desde que o conteúdo não tenha mudado); o manifesto é atualizado
  para o caminho novo
- **Comprime os logs antigos automaticamente** quando a execução vira

**Não faz (ainda):**

- **Não sincroniza de volta** — é somente leitura
- **Não apaga** arquivos locais: apenas registra a remoção no log (mesmo
  quando o Drive renomeia e o conteúdo mudou junto, a cópia antiga fica —
  o `--check` a lista como fora do manifesto)
- **Não baixa versões anteriores** de arquivos
- **Não agenda sozinho** — use cron

---

## Problemas comuns

### "No module named 'tkinter'" ao abrir a janela

O Python não tem o Tkinter instalado. Instale e confira:

```sh
sudo apt update && sudo apt install -y python3-tk
python3 -c "import tkinter; print('tkinter OK')"
```

Se você usa `uv`, pode ser preciso recriar o ambiente depois da instalação:
`uv sync --reinstall`.

### A janela não abre no WSL

O WSL2 atualizado já traz o WSLg. Se ainda assim nada aparecer, confirme que
está no WSL2 (`wsl -l -v` no Windows) e atualize o WSL. Em WSL1, é preciso um
servidor X (ex.: VcXsrv) e configurar `export DISPLAY=:0`.

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

uv run agebackup-gui              # abrir a janela única (configuração, backup, log...)

uv run agebackup-setup            # configurar
uv run agebackup-setup --status   # ver estado
uv run agebackup-setup --test     # testar conexão
uv run agebackup-setup --logs     # editar retenção dos logs
uv run agebackup-setup --compactacao  # editar política de compactação
uv run agebackup-setup --reset    # apagar configuração

uv run agebackup-backup --dry-run # simular
uv run agebackup-backup           # executar
uv run agebackup-backup --falhas  # ver falhas registradas
uv run agebackup-backup --listar-grandes  # originais grandes guardados em PDF
uv run agebackup-backup --reconstruir-grandes  # baixa o original dos pendentes
uv run agebackup-backup --logs    # ver logs e arquivos comprimidos
uv run agebackup-backup --check   # conferir integridade (offline)

uv run agebackup-compactar           # arquivar o backup em .tar.gz
uv run agebackup-compactar --listar  # listar os arquivos gerados
uv run agebackup-compactar --dry-run # simular, sem gravar
```

> Para rodar **sem Python** (`uv`), gere os executáveis autônomos com
> `./packaging/build.sh` — a saída vai para `dist/`. Detalhes em
> [packaging/README.md](packaging/README.md).

## Arquivos do projeto

```
~/projetos/agebackup/
├── agebackup.json     # configuração (junto ao app; credenciais criptografadas)
├── src/agebackup/
│   ├── backup.py      # motor do backup
│   ├── cli.py         # comando agebackup-backup
│   ├── compactacao.py # comando agebackup-compactar (.tar.gz do backup)
│   ├── config.py      # configuração, credenciais e política de logs
│   ├── config_paths.py# onde fica o agebackup.json (junto ao app) e migração
│   ├── crypto_ftp.py  # criptografia das credenciais (FTP, Service Account, ADC)
│   ├── drive.py       # cliente da Drive API e download
│   ├── envios.py      # log de status dos envios ao FTP
│   ├── falhas.py      # log de falhas
│   ├── ftp.py         # comando agebackup-enviar (envio e conferência)
│   ├── ftp_import.py  # importa credenciais .ini para o config.json
│   ├── gui/           # aplicativo gráfico (Tkinter)
│   ├── manifest.py    # manifesto e log de remoções
│   ├── reconstruir.py # reconstrói .pptx/.docx/.xlsx de nativos grandes
│   ├── rotacao.py     # rotação por execução e retenção dos logs
│   ├── setup.py       # tela de configuração
│   └── verificacao.py # verificação offline de integridade (--check)
├── packaging/         # executáveis autônomos (PyInstaller)
├── tests/             # suíte de testes
└── .opencode/skills/  # documentação de referência
```

## Referência da API

- [Visão geral da Drive API](https://developers.google.com/workspace/drive/api/guides/about-sdk)
- [Download e export](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Escolha de escopos](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Erros comuns](https://developers.google.com/workspace/drive/api/guides/handle-errors)