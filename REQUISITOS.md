# Requisitos e Manual do Usuário — AgeBackup

Backup do Google Drive para o seu computador.

Este manual é o caminho completo, do zero até o backup rodando em produção.
Siga na ordem.

---

## Sumário

1. [O que o AgeBackup faz](#1-o-que-o-agebackup-faz)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Autenticar sua conta](#3-autenticar-sua-conta)
4. [Configurar (passo a passo)](#4-configurar-passo-a-passo)
5. [Referência dos campos](#5-referência-dos-campos)
6. [Executar o backup](#6-executar-o-backup)
7. [Os logs](#7-os-logs)
8. [Agendar execução automática](#8-agendar-execução-automática)
9. [Referência de comandos](#9-referência-de-comandos)
10. [Problemas comuns](#10-problemas-comuns)
11. [Limitações conhecidas](#11-limitações-conhecidas)

---

## 1. O que o AgeBackup faz

Você aponta o AgeBackup para uma pasta local. Ele lê o seu Google Drive e copia os
arquivos para lá. Na segunda execução, só baixa o que mudou.

Ponto importante: **o AgeBackup nunca apaga nada do seu computador.** Ele apenas
*registra* em log quando um arquivo some do Drive, para você decidir.

---

## 2. Pré-requisitos

### Python — já instalado

O projeto já está pronto em `~/projetos/agebackup`, com Python 3.14 e as
dependências. Nada a fazer aqui.

### gcloud CLI — opcional

O agebackup usa a **gcloud CLI** para obter credenciais quando o método é ADC. Ela
**não é obrigatória**: o método Service Account funciona sem gcloud.

```sh
sudo apt-get update && sudo apt-get install -y google-cloud-cli
```

Se preferir o instalador oficial: <https://cloud.google.com/sdk/docs/install>

Confirme que funcionou:

```sh
gcloud --version
```

> Sem a gcloud CLI você ainda consegue configurar e usar o backup — basta
> escolher o método **Service Account** no assistente.

---

## 3. Autenticar sua conta

O agebackup precisa de uma credencial que representa **você**, para ter acesso aos
seus arquivos. Há **dois métodos**, e o assistente pergunta qual usar:

| Método | Navegador? | Quando usar |
| --- | --- | --- |
| **ADC via gcloud** | Sim (ou copiar URL) | Uso pessoal, conta Google comum |
| **Service Account** | **Não** | Servidores, WSL sem navegador, automação |

### Método 1 — ADC via gcloud (recomendado no dia a dia)

Você não precisa rodar o comando na mão: o próprio `agebackup-setup` dispara

```sh
gcloud auth application-default login \
  --scopes https://www.googleapis.com/auth/drive.readonly,\
https://www.googleapis.com/auth/cloud-platform
```

O escopo `cloud-platform` é acrescentado automaticamente porque versões
recentes do gcloud **recusam** emitir credenciais só com o escopo do Drive.

O navegador abre e você autoriza. Escolha sua conta e permita o acesso.

> **Em WSL / servidor sem navegador:** o gcloud não abre o navegador sozinho. O
> agebackup detecta isso e usa `--no-launch-browser`: ele imprime uma URL. Copie,
> abra no navegador do Windows (ou de outra máquina), autorize, copie o
> **código** exibido e cole de volta no terminal.

### Método 2 — Service Account (sem navegador)

Não depende de navegador nem de gcloud. Como usar:

1. No [Google Cloud Console](https://console.cloud.google.com/iam-admin/serviceaccounts),
   crie uma **conta de serviço**.
2. Gere uma **chave JSON** para ela (Keys → Add key → JSON).
3. **Compartilhe** a pasta (ou o Drive) que quer copiar com o e-mail da conta
   de serviço (`client_email`), com permissão de **Leitor**.
4. No `agebackup-setup`, escolha a opção `2` e informe o caminho do arquivo JSON.

O agebackup valida o arquivo na hora: se não for uma chave de Service Account
(campo `type` diferente de `service_account`), ele avisa e pede outro.

### Aviso de "app não verificado"

No fluxo ADC, o Google mostra um aviso, porque o AgeBackup é um projeto próprio,
fora da lista de aplicativos verificados. **Isso é esperado.** Clique em:

**Avançado** → **Acessar o AgeBackup (não seguro)**

Só faça isso porque você sabe que o app é o seu. Nunca dispense esse aviso em um
site que você não reconhece.

### Se a gcloud CLI não estiver instalada

Sem a gcloud você ainda pode usar o **Service Account** (método 2), que não
depende dela. Escolha a opção `2` no assistente.

---

## 4. Configurar (passo a passo)

```sh
cd ~/projetos/agebackup
uv run agebackup-setup
```

O assistente faz **4 passos**. Ele mostra o estado atual antes de perguntar
qualquer coisa, e mostra a opção sugerida entre colchetes — basta apertar
Enter para aceitá-la.

### Se você já configurou antes

Ao rodar o assistente novamente, a **primeira pergunta** é se deve reaproveitar
a configuração existente:

```
  Configuracao existente: ADC (gcloud) - usuario@exemplo.com

  Usar a configuracao existente? [S/n]:
```

| Resposta | O que acontece |
| --- | --- |
| **Enter** (`s`) | Reaproveita tudo; cada passo mostra o valor atual |
| `n` | **Ignora** a configuração antiga e começa do zero |

Se você responder `s`, cada passo passa a mostrar o valor atual:

```
==============================================================
  Configuracao do AgeBackup
==============================================================

  Pressione Enter para manter, ou digite outro valor para alterar.
  Para nao alterar nada, pressione Ctrl+C a qualquer momento.
```

A regra é simples:

| O que você faz | O que acontece |
| --- | --- |
| Aperta **Enter** | Mantém o valor atual |
| Digita outro valor | Substitui apenas esse campo |
| Digita **`-`** | **Limpa** o campo (volta ao padrão) |
| Aperta **Ctrl+C** | Cancela tudo; nada é salvo |

**Nada é alterado por acidente.** Se você simplesmente for até o fim
apertando Enter, a configuração termina exatamente igual.

Depois de uma autenticação **validada com sucesso**, o assistente pergunta uma
última coisa:

```
  Na proxima vez, perguntar de novo se deve usar a configuracao existente? [S/n]:
```

Responda `n` para **desligar** essa pergunta nas próximas execuções (guardado no
campo `ask_reuse` da configuração). Assim o setup reaproveita direto, sem nag.

Exemplo real — uma configuração com pasta definida e 6 meses de retenção:

```
  Passo 2 de 4 - Destino e escopo do backup
==============================================================
  Pasta local onde os arquivos serao gravados.
  Configuracao atual: /dados/backup
  Destino local [/dados/backup]: /home/isaac/novo

  Para fazer backup de apenas uma pasta do Drive, informe o ID.
  Configuracao atual: PASTA_123
  Pressione Enter para manter, ou digite - para voltar ao Drive inteiro.
  ID da pasta no Drive [PASTA_123]:

  Shared drives (Drive compartilhado de equipe) exigem escopo extra
  e podem nao estar acessiveis com sua conta.
  Configuracao atual: sim
  Incluir shared drives? [S/n]:
```

> **Importante:** quando existe uma pasta configurada, apertar Enter **mantém**
> a pasta. Para voltar a copiar o Drive inteiro, digite `-`.

### Passo 1 — Conta e credenciais

Se já existir configuração e você aceitou reaproveitá-la, o AgeBackup **testa a
autenticação atual** antes de oferecer mantê-la:

```
  Verificando a autenticacao atual...
  Conectado como usuario@exemplo.com
```

Depois, o menu de método de autenticação:

```
  Metodo de autenticacao:
    1) ADC via gcloud     - usa sua conta Google (abre ou copia uma URL)
    2) Service Account    - chave em JSON, sem navegador
    3) Manter a autenticacao atual (validada agora)
  Opcao [3]:
```

A opção `3` (**Manter**) só aparece quando as credenciais atuais foram
**validadas agora**. Se a autenticação estiver quebrada, o assistente avisa:

```
  ATENCAO: a autenticacao atual NAO esta funcionando.
  Escolha um metodo abaixo para reautenticar.
```

Nesse caso o padrão muda para `1`, e "manter" deixa de ser sugerido — para você
não gravar de novo uma configuração que já falhou.

Escolhendo **1 (ADC)**, se já houver credenciais:

```
  Credenciais ADC ja existem para: usuario@exemplo.com
    Fazer login novamente? [n/S]:
```

Responda `n` para reaproveitar. Responda `s` para refazer a autorização — útil
se você trocou de conta ou se algum arquivo der erro de permissão.

**Se a gcloud CLI não estiver instalada**, o AgeBackup avisa e sugere o método 2
(Service Account), que não precisa dela.

### Passo 2 — Destino e escopo

Você define **para onde** e **o quê** copiar.

**Destino local** — pasta onde os arquivos serão gravados.

```
  Destino local [/home/isaac/agebackup]:
```

Sugestão padrão: `~/agebackup`. Pressione Enter para aceitar. Digite outro caminho
se preferir (ex.: `/mnt/disco-externo/backup`). A pasta é criada sozinha se não
existir.

**ID da pasta no Drive** — o mais importante para o desempenho.

```
  ID da pasta no Drive:
```

Aqui você tem duas opções:

| O que digitar | O que acontece | Quando usar |
| --- | --- | --- |
| *(vazio, só Enter)* | Baixa **o Drive inteiro** | Quer um backup completo |
| Um ID de pasta | Baixa **essa pasta e tudo dentro dela** | Quer algo menor ou mais rápido |

Como descobrir o ID: abra a pasta no navegador do Drive. O final da URL é o
ID, algo como `1a2B3cD4eF5gH6iJ7kL8mN9oP0qR`.

> A pasta **é recursiva**: subpastas dentro dela também são copiadas. O agebackup
> espelha a estrutura do Drive no disco (veja "Como os arquivos são
> organizados" abaixo).

**Shared drives** — unidades compartilhadas de equipe.

```
  Incluir shared drives? [n/S]:
```

| Opção | O que acontece |
| --- | --- |
| `n` (recomendado) | Baixa só o seu Drive pessoal |
| `s` | Inclui também os drives compartilhados |

Shared drives pertencem à sua organização e podem exigir escopos adicionais.
Comece com `n` — é mais simples e normalmente é o que você quer.

### Passo 3 — Teste de conexão

```
  Consultando a Drive API...
  Conectado como usuario@exemplo.com
```

O agebackup faz uma chamada real à API. Se mostrar erro aqui, não adianta seguir:
volte ao [passo 3](#3-autenticar-sua-conta).

### Passo 4 — Pasta, rotação e retenção dos logs

Define em que subpasta do destino os logs ficam e quanto tempo guardar os
antigos. Explicado em detalhe na [seção 7](#7-os-logs).

```
  Pasta dos logs atual: logs
  Digite '-' para gravar na raiz do destino.
  Pasta dos logs (dentro do destino) [logs]:
  Retencao atual: 12 meses
  Alterar a retencao? [n/S]:
```

Pressione Enter para manter a pasta `logs`. Digite outro nome para trocar, ou
`-` para gravar os logs na raiz do destino (como nas versões antigas).
Responda `n` para manter os 12 meses de retenção, ou `s` para escolher outro
prazo.

### Conferindo a configuração

```sh
uv run agebackup-setup --status
```

```
==============================================================
  Estado atual
==============================================================
  gcloud CLI     : instalado
    caminho      : /usr/bin/gcloud
  Credenciais    : encontradas (ADC)
    conta        : usuario@exemplo.com
    projeto      : meu-projeto
  Arquivo        : /home/isaac/.config/agebackup/config.json
    conta        : usuario@exemplo.com
    metodo       : adc
    autenticada  : sim
    escopos      : https://www.googleapis.com/auth/drive.readonly
    destino      : /home/isaac/agebackup
    pasta Drive  : (Drive inteiro)
    retencao     : 12 meses
    compactacao  : gzip
    pasta logs   : logs
```

### Onde fica salvo

`~/.config/agebackup/config.json`, com permissão `600` (só você pode ler).

---

## 5. Referência dos campos

Referência completa de todos os campos. O arquivo tem três seções: `account`,
`backup` e `logs`.

```json
{
  "account": {
    "email": "usuario@exemplo.com",
    "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
    "auth_method": "adc",
    "service_account_key_path": "",
    "verified": true,
    "ask_reuse": true
  },
  "backup": {
    "destination": "/home/isaac/agebackup",
    "folder_id": "",
    "include_shared_drives": false
  },
  "logs": {
    "enabled": true,
    "keep_months": 12,
    "compress": true,
    "directory": "logs"
  }
}
```

### Seção `account`

#### `email`

A conta Google usada no backup. É preenchida automaticamente após o login —
você não precisa editar.

#### `scopes` — **tem mais de uma opção**

Lista de permissões pedidas à sua conta. Define **o que o AgeBackup pode ver e
fazer**.

| Valor | O que permite | Consequência |
| --- | --- | --- |
| `drive.readonly` **(padrão)** | Ler e baixar arquivos | Seguro, sem burocracia |
| `drive.file` | Ler arquivos que o próprio app criou | Não ajuda em backup |
| `drive` | Ver e gerenciar **todo** o seu Drive | Escopo restrito: o Google exige verificação do app |

**Qual usar?** `drive.readonly`.

`drive` é o único que realmente faria sentido para um backup completo, mas é
um *escopo restrito*: para uso fora do seu próprio projeto, o Google exige
verificação do app, o que leva dias e exige passar por análise. Para um
backup pessoal, `drive.readonly` funciona e evita esse trâmite.

> ⚠️ **Atenção:** com `drive.readonly`, o AgeBackup pode ler o conteúdo dos
> arquivos, mas não pode gravá-los no Drive. É exatamente o que um backup
> unidirecional precisa.

**Trocar o escopo:** edite o JSON e rode `uv run agebackup-setup` de novo para
reautenticar com a nova permissão. Alterar a lista sem reautenticar mantém a
credencial antiga.

#### `auth_method` — **tem mais de uma opção**

Como a credencial é obtida:

| Valor | O que é | Precisa de navegador? |
| --- | --- | --- |
| `adc` **(padrão)** | Application Default Credentials, via `gcloud` | Sim (ou copiar URL no WSL) |
| `service_account` | Chave JSON de conta de serviço | **Não** |

#### `service_account_key_path`

Caminho do arquivo JSON da chave de Service Account. Só é usado quando
`auth_method` é `service_account`. O arquivo precisa ter `"type":
"service_account"`.

Quando você informa uma chave no assistente, o AgeBackup **copia** o JSON para
`~/.config/agebackup/` com permissão `0o600` e grava esse caminho. Assim a
chave não fica dentro do repositório git. O arquivo original não é removido.

> **Nunca remova um arquivo de credencial sem ter uma cópia.** A chave de
> Service Account (e qualquer `credentials.json`/`token.json`) não é
> recuperável pelo git, porque `*.json` é ignorado. Antes de qualquer `rm`,
> `mv` ou limpeza de repositório, confirme que existe uma cópia de segurança.

#### `verified`

`true` depois que o AgeBackup conseguiu conectar à API com essas credenciais na
última configuração. `false` significa que a autenticação ainda não foi
validada (ou falhou). Serve para diagnóstico rápido.

#### `ask_reuse` — **tem mais de uma opção**

Controla se o `agebackup-setup` pergunta, ao abrir, se deve **reaproveitar a
configuração existente**.

| Valor | O que acontece |
| --- | --- |
| `true` **(padrão)** | Pergunta "Usar a configuracao existente?" a cada abertura |
| `false` | Reaproveita direto, sem perguntar |

Depois de uma autenticação **bem-sucedida**, o assistente oferece desligar essa
pergunta. Você também pode editar o campo à mão.

### Seção `backup`

#### `destination`

Pasta local onde os arquivos caem. Não precisa existir: o AgeBackup cria.

Cuidados:

- **Use um disco com espaço.** O backup ocupa aproximadamente o tamanho do
  Drive.
- **Evite a própria pasta do Drive.** Se o destino estiver dentro de uma pasta
  sincronizada pelo Google, cada download pode disparar uma nova sincronização
  e o backup pode nunca terminar.

#### Como os arquivos são organizados

O agebackup **espelha a árvore de pastas do Drive** no destino. Um arquivo em
`Didaticos/Administracao/lei.pdf` no Drive vira
`<destino>/Didaticos/Administracao/lei.pdf` no disco.

- **Sem `folder_id`** (Drive inteiro): o caminho local reproduz o caminho no
  Drive a partir da raiz.
- **Com `folder_id`**: o nome da pasta informada vira o primeiro nível local.
  Ex.: apontando para `Didaticos`, o arquivo acima fica em
  `<destino>/Didaticos/Administracao/lei.pdf`.

Arquivos que estão na raiz do Drive caem direto no destino, sem subpasta.
Nomes repetidos na mesma pasta ganham sufixo `(1)`, `(2)`, ... — o AgeBackup nunca
sobrescreve um arquivo existente.

#### `folder_id` — **tem mais de uma opção**

Qual pasta do Drive copiar. Vazio significa o Drive inteiro.

| Valor | O que acontece | Trade-off |
| --- | --- | --- |
| `""` (vazio) | Drive inteiro | Completo, porém lento na primeira vez |
| ID de uma pasta | Essa pasta e todas as subpastas | Rápido, parcial |

Exemplo:

```json
"folder_id": "1a2B3c4D5eF6gH7iJ8kL9mN0oP1qR"
```

Como obter o ID: abra a pasta no Drive; o ID é o último trecho da URL.

> O `folder_id` **é recursivo**: o AgeBackup desce nas subpastas e reproduz a
> estrutura de pastas no disco. O nome da pasta informada vira o primeiro
> nível local (ex.: `bkps/Didaticos/Administracao/arquivo.pdf`).

#### `include_shared_drives` — **tem mais de uma opção**

Se os drives compartilhados da sua organização entram no backup.

| Valor | Inclui | Quando usar |
| --- | --- | --- |
| `false` (padrão) | Só o seu Drive pessoal | Caso comum |
| `true` | Também os drives de equipe | Você depende de arquivos da equipe |

Ao marcar `true`, o AgeBackup usa `corpora=allDrives`. Pode encontrar:

- drives em que você não tem acesso — o log vai marcar como `bloqueado`;
- erros de permissão na listagem.

Comece com `false`. Só ligue se realmente precisar.

### Seção `logs`

Controla os arquivos de registro. Detalhes na [seção 7](#7-os-logs).

#### `enabled`

| Valor | Efeito |
| --- | --- |
| `true` (padrão) | Logs são rotacionados, comprimidos e expurgados |
| `false` | Nada é comprimido nem apagado. Os logs crescem para sempre |

Use `false` apenas para depurar. Em uso normal, deixe ligado — os logs
crescem rápido se algo der errado todo dia.

#### `keep_months` — **tem mais de uma opção**

Quantos meses de logs comprimidos manter.

| Valor | Efeito | Quando usar |
| --- | --- | --- |
| `0` | Guarda **tudo**, nunca apaga | Quer histórico completo |
| `1` a `120` | Mantém N meses, apaga o mais antigo | Padrão |

- **Padrão:** `12` (um ano).
- **Valores fora do intervalo** são ajustados: acima de 120 vira 120, negativo
  vira 0.
- **Valor não numérico** volta ao padrão (12).

Como o cálculo funciona: em outubro com `keep_months: 6`, o AgeBackup mantém
arquivos de **abril a outubro** e apaga março e anteriores. O log do mês
corrente nunca é apagado.

Para alterar sem refazer o assistente:

```sh
uv run agebackup-setup --logs
```

#### `compress`

| Valor | Efeito | Quando usar |
| --- | --- | --- |
| `true` (padrão) | Logs antigos viram `.gz` (gzip) | Normal |
| `false` | Logs antigos ficam em texto puro | Quer ler sem `zcat` |

O gzip reduz logs de texto em 80% ou mais. Não há motivo forte para desligar.

#### `directory`

Subpasta do destino onde os logs são gravados.

| Valor | Efeito |
| --- | --- |
| `"logs"` (padrão) | Logs em `<destino>/logs/` |
| `""` (vazio) | Logs na raiz do destino (comportamento antigo) |
| outro nome | Logs em `<destino>/<nome>/` |

O manifesto `.agebackup-manifest.json` **não** muda: continua na raiz do destino.

- **Caminhos absolutos** (`/etc`) e com `..` voltam ao padrão (`logs`): os logs
  precisam ficar dentro do backup.

Para alterar:

```sh
uv run agebackup-setup --logs
```

Evite escolher um nome de pasta que exista no Drive que você faz backup (por
exemplo, uma pasta `logs` na origem), para não misturar os logs do AgeBackup com os
arquivos copiados. Se acontecer, eles não colidem pelos nomes (os logs começam
com `.agebackup-`), mas ficam juntos.

### Resumo das opções múltiplas

| Campo | Opções | Padrão |
| --- | --- | --- |
| `scopes` | `drive.readonly`, `drive`, `drive.file` | `drive.readonly` |
| `folder_id` | vazio (Drive todo) ou ID de uma pasta | vazio |
| `include_shared_drives` | `true`, `false` | `false` |
| `logs.enabled` | `true`, `false` | `true` |
| `logs.keep_months` | `0` a `120` | `12` |
| `logs.compress` | `true`, `false` | `true` |
| `logs.directory` | nome de subpasta ou vazio | `logs` |

---

## 6. Executar o backup

### Sempre comece simulando

```sh
uv run agebackup-backup --dry-run
```

Isso lista o que **seria** baixado, sem gravar nada:

```
  baixaria     relatorio.pdf (2.0KB)
  baixaria     planilha (0B)

==============================================================
  Resumo
==============================================================
  128 arquivos, 128 a baixar, 0 inalterados

  Simulacao: nenhum arquivo foi gravado.
```

Confira a lista. Se estiver correta, siga.

### Executando de verdade

```sh
uv run agebackup-backup
```

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

  baixando     relatorio.pdf...
  ok           relatorio.pdf

==============================================================
  Resumo
==============================================================
  128 arquivos, 96 baixados, 30 inalterados, 87.3MB novos
```

### Segunda execução

```sh
uv run agebackup-backup
```

```
  128 arquivos, 0 baixados, 128 inalterados
```

O agebackup compara a data de modificação do Drive com a do arquivo local. Só
rebaixa o que mudou.

### Opções

| Opção | Efeito |
| --- | --- |
| `--dry-run` | Só lista; não grava nada |
| `--verbose`, `-v` | Mostra também os inalterados |
| `--falhas` | Lista as últimas falhas registradas |
| `--logs` | Mostra os logs, a política e os comprimidos |

**Código de saída:** `0` se tudo deu certo, `1` se houve falha **ou** algum
arquivo exigiu operação de longa duração (ver [seção 11](#11-limitações-conhecidas)).

---

## 7. Os logs

O agebackup mantém dois logs e um manifesto. Por padrão, os **logs** ficam numa
subpasta `logs/` dentro do backup — o nome da pasta é configurável no Passo 4
do assistente (ou pela chave `logs.directory`). O **manifesto** fica na raiz do
backup.

```
~/agebackup/
├── logs/
│   ├── .agebackup-falhas.log
│   └── .agebackup-removidos.log
└── .agebackup-manifest.json
```

### O que cada um registra

| Arquivo | Registra | Nunca apaga conteúdo? |
| --- | --- | --- |
| `logs/.agebackup-falhas.log` | O que **não conseguiu baixar** | Só expurga por retenção |
| `logs/.agebackup-removidos.log` | O que **sumiu do Drive** | Só expurga por retenção |
| `.agebackup-manifest.json` | Ligação arquivo local ↔ ID no Drive | Atualizado sempre |

### Arquivos removidos na origem

Quando um arquivo que o AgeBackup já baixou deixa de aparecer na listagem do
Drive, ele consulta o arquivo por ID para saber **por que** saiu:

```
  removido    notas-antigas.txt
  excluido    contrato-2025.pdf
  sem acesso  relatorio.pdf
  registrado em /home/isaac/agebackup/logs/.agebackup-removidos.log
```

| Rótulo | Significado | Situação típica |
| --- | --- | --- |
| `removido` | Ainda existe e não está na lixeira, mas saiu da listagem | Caso raro |
| `excluido` | Está na lixeira do Drive | Você apagou |
| `sem acesso` | A API respondeu 403/404 | Foi movido para uma pasta **não compartilhada** com a conta |

No resumo, `removido` e `excluido` entram como **"N removidos na origem"**;
`sem acesso` aparece separado como **"N sem acesso (fora do escopo)"**.

**O arquivo continua no seu computador.** O agebackup não apaga nada. A decisão é
sua.

Formato do log:

```
2026-10-12T12:39:38+00:00	removido	notas-antigas.txt
2026-10-12T12:41:02+00:00	excluido	contrato-2025.pdf
2026-10-12T12:45:10+00:00	sem_acesso	relatorio.pdf
```

Data e hora da detecção + motivo + caminho. Uma linha por arquivo.

**Como ele sabe o que foi removido?** O manifesto (`.agebackup-manifest.json`)
guarda a correspondência entre o caminho local e o ID no Drive. Isso evita
falsos positivos:

| Situação | Reporta como removido? |
| --- | --- |
| Baixou `a.pdf`, foi deletado do Drive | **sim** (`excluido`) |
| Arquivo movido para pasta não compartilhada | não (`sem acesso`) |
| Você mesmo colocou `nota.txt` na pasta | não |
| Arquivo que o AgeBackup nunca baixou | não |
| A listagem do Drive falhou no meio | não |
| Arquivo já limpo do disco antes | não |

### Arquivos que falharam

```
  Falhas (2):
    - contrato-restrito.pdf: bloqueado
        download bloqueado pelo dono do arquivo
    - video-grande.mp4: operacao_longa
        o tipo application/vnd.google-apps.video não aceita files.export
```

Categorias:

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
| `listagem` | A listagem parou no meio | Repita o backup |

Consultar:

```sh
uv run agebackup-backup --falhas

# só as de hoje
grep "^2026-10-12" ~/agebackup/logs/.agebackup-falhas.log

# quantas de cada tipo
awk -F'\t' '{print $3}' ~/agebackup/logs/.agebackup-falhas.log | sort | uniq -c

# só as que exigem operação longa
awk -F'\t' '$3=="operacao_longa" {print $2}' ~/agebackup/logs/.agebackup-falhas.log
```

### Rotação e retenção

Os logs são comprimidos por mês, dentro da pasta de logs:

```
~/agebackup/logs/
├── .agebackup-falhas.log              # outubro (texto)
├── .agebackup-falhas.2026-09.log.gz   # setembro (comprimido)
├── .agebackup-removidos.log
├── .agebackup-removidos.2026-09.log.gz
└── .agebackup-mes                     # marca do mês corrente
```

Ler um compactado:

```sh
zcat ~/agebackup/logs/.agebackup-falhas.2026-09.log.gz | less
```

Listar tudo:

```sh
uv run agebackup-backup --logs
```

**Como a virada de mês é detectada:** por um arquivo de marca, `.agebackup-mes`.
Deliberadamente **não** se usa a data de modificação do log, porque gravar no
mês corrente atualizaria essa data e poderia esconder um log antigo — juntando
meses diferentes no mesmo arquivo.

A rotação roda uma vez por execução e é idempotente: rodar várias vezes no
mesmo mês não faz nada além do necessário.

**Configurando a retenção e a pasta dos logs:**

```sh
uv run agebackup-setup --logs
```

### Apagar logs manualmente

Nenhum log é apagado automaticamente além da retenção. Para liberar espaço:

```sh
rm ~/agebackup/logs/.agebackup-falhas.2026-08.log.gz
```

Não apague `.agebackup-manifest.json` — sem ele o AgeBackup perde a capacidade de
detectar remoções.

---

## 8. Agendar execução automática

Edite o crontab:

```sh
crontab -e
```

Backup todo dia às 3h:

```cron
0 3 * * * cd /home/isaac/projetos/agebackup && /home/isaac/projetos/agebackup/.venv/bin/python -m agebackup.cli >> /home/isaac/agebackup-backup.log 2>&1
```

Detalhes que importam:

- **Use o caminho absoluto** do interpretador. O `PATH` do cron é mínimo e não
  inclui o venv.
- **`>>` e não `>`**: acrescentar, para preservar o histórico.
- **Verifique** rodando: `tail -20 ~/agebackup-backup.log`

---

## 9. Referência de comandos

### Configuração

| Comando | O quê |
| --- | --- |
| `uv run agebackup-setup` | Assistente completo (4 passos) |
| `uv run agebackup-setup --status` | Mostra o estado atual |
| `uv run agebackup-setup --test` | Testa a conexão com a API |
| `uv run agebackup-setup --logs` | Edita pasta, rotação e retenção dos logs |
| `uv run agebackup-setup --reset` | Apaga a configuração |

### Backup

| Comando | O quê |
| --- | --- |
| `uv run agebackup-backup --dry-run` | Simula, não grava |
| `uv run agebackup-backup` | Executa |
| `uv run agebackup-backup -v` | Detalhado |
| `uv run agebackup-backup --falhas` | Últimas falhas |
| `uv run agebackup-backup --logs` | Logs e política de rotação |

---

## 10. Problemas comuns

### "gcloud CLI não encontrado"

A gcloud CLI não está instalada. Você pode instalá-la (veja a
[seção 2](#2-pré-requisitos)) **ou** usar o método Service Account, que não
depende dela: rode `uv run agebackup-setup` e escolha a opção `2`.

### "cloud-platform scope is required but not requested"

Versões recentes do gcloud recusam emitir credenciais só com escopos restritos
como o do Drive. O agebackup já pede os **dois** escopos automaticamente
(`drive.readonly` + `cloud-platform`). Se você estiver rodando o gcloud na mão,
inclua o `cloud-platform`:

```sh
gcloud auth application-default login \
  --scopes https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

### O navegador não abre (WSL, servidor, SSH)

O agebackup detecta o WSL e usa `--no-launch-browser`: ele imprime uma URL. Copie,
abra no navegador do Windows (ou de outra máquina), autorize, copie o código e
cole de volta no terminal. Se nem isso funcionar, use o método **Service
Account** (opção `2`), que não precisa de navegador.

### "Credenciais ausentes"

```sh
gcloud auth application-default login
uv run agebackup-setup
```

Ou, sem gcloud, escolha o método Service Account no assistente.

### A autenticação anterior parou de funcionar

Rode `uv run agebackup-setup`. No Passo 1 o AgeBackup **testa** as credenciais e, se
estiverem quebradas, avisa e já sugere reautenticar (a opção "manter" deixa de
aparecer). Se preferir começar limpo, responda `n` à pergunta "Usar a
configuracao existente?".

### App "não verificado" no navegador

Escolha **Avançado** → **Acessar o AgeBackup (não seguro)**. É esperado: o AgeBackup é
um projeto próprio, fora da lista de apps verificados do Google.

### Arquivos aparecem como "arquivo (1).ext"

Já existe um arquivo com esse nome na pasta. O agebackup nunca sobrescreve: cria um
novo com sufixo.

### Download marcado como `bloqueado`

O dono do arquivo restringiu o download
([`canDownload`](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)
é `false`). Não há como contornar.

### Erro de cota (`cota_excedida`)

Você atingiu o limite de requisições da API. Espere algumas horas ou peça
[aumento de cota](https://developers.google.com/workspace/drive/api/guides/limits).

### `erro_local: disco cheio`

O destino não tem espaço. O backup precisa de espaço aproximadamente igual ao
tamanho do Drive.

### `build-essential` ausente

Só é necessário se alguma dependência compilar código nativo. Não afeta o uso
normal:

```sh
sudo apt-get update && sudo apt-get install -y build-essential
```

---

## 11. Limitações conhecidas

Seja claro sobre o que **não** funciona:

| Limitação | Detalhe |
| --- | --- |
| **Não executa operações de longa duração** | Google Vids e documentos do Workspace acima de 10 MB ficam registrados como `operacao_longa`, sem serem baixados |
| **Não sincroniza de volta** | É somente leitura, por opção de segurança |
| **Não apaga arquivos locais** | Só registra a remoção no log |
| **Não baixa versões anteriores** | Só a versão atual de cada arquivo |
| **Não agenda sozinho** | Use cron |
| **Não renomeia/move locais** | Se um arquivo muda de nome ou de pasta no Drive, o AgeBackup grava uma cópia nova; não remove a antiga |
| **Testes usam servidor emulado** | A suíte automatizada roda contra um servidor HTTP local; o caminho real já foi verificado manualmente com uma conta somente-leitura |

### Sobre a última limitação

Isto é importante: o código está coberto por **248 testes** que rodam contra um
servidor HTTP local emulado, reproduzindo o comportamento da API. O caminho
real já foi exercitado manualmente (leitura somente, com uma Service Account),
mas não é coberto pela suíte automatizada.

Sugestão: rode primeiro o `--dry-run`, e depois faça o backup de uma pasta
pequena (usando `folder_id`) antes de soltar o Drive inteiro.

---

## Estrutura do projeto

```
~/projetos/agebackup/
├── src/agebackup/
│   ├── backup.py      # motor do backup
│   ├── cli.py         # comando agebackup-backup
│   ├── config.py      # configuração, credenciais, política de logs
│   ├── drive.py       # cliente da Drive API e download
│   ├── falhas.py      # log de falhas
│   ├── manifest.py    # manifesto e log de remoções
│   ├── rotacao.py     # rotação mensal e retenção
│   └── setup.py       # tela de configuração
├── tests/             # 248 testes
├── USERGUIDE.md        # guia do usuário
└── .opencode/skills/  # documentação de referência da API
```

## Referência da API

- [Visão geral da Drive API](https://developers.google.com/workspace/drive/api/guides/about-sdk)
- [Download e export](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Escolha de escopos](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Erros comuns](https://developers.google.com/workspace/drive/api/guides/handle-errors)
- [Limites de uso](https://developers.google.com/workspace/drive/api/guides/limits)