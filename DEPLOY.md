# Implantação em outro servidor

Este manual descreve como levar o **AgeBackup já compilado** para outro
servidor Linux e executá-lo. Ele cobre os pré-requisitos de sistema, a
transferência dos binários e da configuração, a primeira execução, o
agendamento e os problemas mais comuns.

> **Escopo:** servidor Linux **x86_64** (64 bits), com `systemd` e acesso por
> SSH. Os exemplos usam o usuário de serviço `agebackup`, a pasta
> `/opt/agebackup` e os dados em `/srv/agebackup`. Troque os caminhos e o nome
> do usuário se o seu ambiente for diferente.
>
> Se o destino for **Windows**, o binário Linux não funciona: compile no
> Windows ou execute o AgeBackup em uma máquina virtual/WSL Linux. Se for
> **ARM** (Raspberry Pi, servidor ARM), também é preciso recompilar no destino.

---

## 1. O que será transferido

Os binários ficam em `dist/`, na máquina onde o projeto foi compilado:

| Binário | Para que serve | Precisa levar? |
| --- | --- | --- |
| `agebackup-setup` | configuração e autenticação | Sim, na primeira instalação |
| `agebackup-backup` | baixa o Google Drive | Sim |
| `agebackup-compactar` | gera o `.tar.gz` | Se usa compactação |
| `agebackup-enviar` | envia para FTP/FTPS | Se usa envio |
| `agebackup-gui` | janela única | Só se o servidor tiver interface gráfica ou acesso X11 |

Além dos binários, leve estes arquivos **quando estiver migrando uma instalação
que já funciona**:

| Arquivo | Obrigatório? | Observação |
| --- | --- | --- |
| `agebackup.json` | Sim, para aproveitar a configuração | Fica **ao lado do executável** |
| `.agebackup-ftp.key` | Sim, se a senha FTP já estiver salva | Sem ele a senha não é descriptografada |
| chave JSON da Service Account | Se esse for o método de autenticação | O caminho fica dentro do `agebackup.json` |
| `ftp.ini` | Só se você usa credenciais externas | Também fica ao lado do executável |
| `~/.config/gcloud/application_default_credentials.json` | Só no modo ADC | Credencial do **usuário que executará o backup** |
| pasta de backup + `.agebackup-manifest.json` | Opcional | Só se quiser evitar baixar tudo de novo |

> **Não copie** o `dist/agebackup.json` de um teste local sem revisar. Ele pode
> apontar para caminhos que não existem no servidor.

O binário é **onefile**: um único arquivo que se extrai para um diretório
temporário ao executar. Ele **não** é estático: depende da `glibc` do Linux.
Versão usada para gerar os binários deste repositório: **Ubuntu 26.04.1 LTS,
glibc 2.43, Python 3.14.4**. O binário também é específico de arquitetura.

---

## 2. Pré-requisitos

### 2.1 Sistema operacional e arquitetura

No servidor, confira:

```sh
uname -m
# x86_64  (se aparecer aarch64/arm64, o binário x86_64 não serve)

ldd --version | head -1
# Exemplo: ldd (Ubuntu GLIBC 2.43-...) 2.43

cat /etc/os-release
```

Regras práticas:

- **x86_64 + glibc igual ou mais nova** que a da máquina que compilou: o
  binário tende a rodar.
- **glibc mais antiga** (por exemplo, Ubuntu 24.04 tem glibc 2.39): o binário
  pode falhar com `version 'GLIBC_2.43' not found`. Nesse caso **recompile no
  servidor** (ou em um contêiner com a mesma versão do destino). Não há como
  contornar isso apenas instalando Python.
- **Alpine/musl**: o binário glibc não roda. Recompile em um ambiente
  compatível ou use uma distribuição com glibc.
- **ARM**: recompile no próprio servidor.

Para recompilar no servidor, veja a seção 11.

### 2.2 Espaço em disco

O backup local ocupa aproximadamente o tamanho dos arquivos do Drive. A
compactação gera uma **segunda cópia** (comprimida) em outro diretório. O
binário onefile ainda precisa extrair seus arquivos temporários.

Reserve, no mínimo:

- espaço para o backup local;
- espaço para pelo menos um `.tar.gz` full;
- algumas centenas de MB livres para o diretório temporário.

Confira:

```sh
df -h /srv /opt /var/lib
```

O destino da compactação **não pode ficar dentro** da pasta do backup.

O binário `onefile` se extrai para `$TMPDIR` (normalmente `/tmp`). Se o seu
`/tmp` estiver montado com `noexec`, a execução falha mesmo com espaço livre.
Nesse caso use um diretório temporário executável:

```sh
sudo install -d -o agebackup -g agebackup -m 700 /var/lib/agebackup/tmp
sudo -u agebackup -H env TMPDIR=/var/lib/agebackup/tmp \
  /opt/agebackup/agebackup-backup --help
```

### 2.3 Rede e relógio

O servidor precisa de saída para a internet:

- HTTPS (443) para as APIs do Google (`*.googleapis.com`, inclusive
  `oauth2.googleapis.com` e `www.googleapis.com`);
- FTP/FTPS: porta de controle (normalmente 21) e a faixa de portas passivas
  configurada no servidor FTP;
- DNS funcionando;
- relógio sincronizado. Relógio muito errado quebra TLS e a autenticação
  Google.

```sh
timedatectl
sudo timedatectl set-ntp true
# Opcional: acertar o fuso usado nos logs
sudo timedatectl set-timezone America/Sao_Paulo
```

Se a rede usa proxy, exporte as variáveis antes de executar (e também no
`systemd`, se for agendar):

```sh
export HTTPS_PROXY=http://proxy.exemplo:3128
export HTTP_PROXY=http://proxy.exemplo:3128
export NO_PROXY=localhost,127.0.0.1
```

A janela gráfica, quando aberta fora do terminal, pode não herdar essas
variáveis. Nesse caso abra-a pelo terminal depois de exportá-las.

### 2.4 Pacotes do sistema

Para os comandos de linha de comando (backup, compactação e envio), **não é
necessário Python, pip, uv, Tkinter ou PyInstaller**. O binário já embute o
interpretador e as bibliotecas Python.

Instale apenas o básico (Debian/Ubuntu):

```sh
sudo apt update
sudo apt install -y ca-certificates tzdata util-linux
```

- `tzdata`: fusos horários dos logs;
- `util-linux`: fornece o `flock`, usado no script de automação;
- `ca-certificates`: útil para diagnósticos e para o sistema em geral (o
  binário leva o `certifi` embutido).

Se for usar a **interface gráfica** no servidor, ela precisa de uma sessão
gráfica (X11/Wayland) e das bibliotecas de X/Tk. Em Debian/Ubuntu:

```sh
sudo apt install -y \
  libx11-6 libxext6 libxrender1 libxft2 libxss1 \
  libfontconfig1 libfreetype6 fonts-dejavu-core xauth
```

O `xauth` só é necessário se você pretende abrir a GUI por SSH com
`ssh -X`. Em RHEL/Fedora, os equivalentes são `libX11`, `libXext`,
`libXrender`, `libXft`, `libXScrnSaver`, `fontconfig`, `freetype` e
`dejavu-sans-fonts`.

### 2.5 Conta Google e credenciais

O servidor precisa de uma credencial com permissão de **leitura** no Drive.
Há dois caminhos:

#### Service Account — recomendado para servidor

Não depende de navegador nem de `gcloud`. Passos:

1. No Google Cloud Console, habilite a **Google Drive API** no projeto.
2. Crie uma **Service Account**.
3. Gere uma chave **JSON** para ela (Keys → Add key → JSON).
4. Compartilhe a pasta do Drive que será copiada com o e-mail
   `client_email` da Service Account, com permissão de **Leitor**.
5. Anote o **ID da pasta** (o trecho depois de `/folders/` na URL).

Limitações importantes:

- Uma Service Account **não enxerga o “Meu Drive” pessoal** como raiz. É
  necessário compartilhar uma pasta específica com ela, ou usá-la em um
  **Drive compartilhado** (Shared Drive) do qual ela seja membro.
- Para copiar o Drive pessoal inteiro, o caminho mais simples é usar **ADC**
  (conta pessoal) em vez de Service Account.

#### ADC (Application Default Credentials)

Usa a sua conta Google e requer o `gcloud` na máquina (ou a cópia do arquivo
ADC). Como o servidor normalmente não tem navegador, o login pode ser feito
com `--no-launch-browser`: o `gcloud` mostra uma URL, você autoriza em outra
máquina e cola o código no terminal.

```sh
# execute como o usuário que fará o backup
gcloud auth application-default login \
  --no-launch-browser \
  --scopes=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

O arquivo gerado fica em
`~/.config/gcloud/application_default_credentials.json` do usuário que rodou
o comando. Se o backup for executado por outro usuário, faça o login com esse
usuário ou copie o arquivo para o `HOME` dele com permissão `600`.

> O assistente acrescenta `--no-launch-browser` automaticamente quando detecta
> WSL. Em um servidor Linux comum (sem navegador), rode o comando `gcloud`
> acima manualmente **antes** de abrir o `agebackup-setup`; o assistente então
> reaproveita o ADC já existente.

### 2.6 Servidor FTP/FTPS

Tenha em mãos:

- host e porta (normalmente 21);
- usuário e senha;
- FTPS explícito (padrão) ou FTP puro (`tls = false`);
- pasta remota (opcional; o padrão é `/AAAA/MM/`);
- espaço disponível e permissão de escrita no servidor FTP.

O envio usa **modo passivo**. Se o firewall do servidor FTP estiver fechado
para a faixa passiva, o login funciona mas o upload travará.

### 2.7 Usuário de serviço e permissões

Não execute o AgeBackup como `root`: a configuração e os arquivos do backup
ficariam com dono `root` e o serviço poderia não conseguir gravar. Use `sudo`
apenas para instalar pacotes e binários; para executar, use
`sudo -u agebackup -H ...` ou o serviço `systemd`. Crie um usuário dedicado:

```sh
sudo useradd --system \
  --create-home \
  --home-dir /var/lib/agebackup \
  --shell /usr/sbin/nologin \
  agebackup
```

Crie as pastas:

```sh
sudo install -d -o agebackup -g agebackup -m 700 \
  /opt/agebackup /var/lib/agebackup /var/lib/agebackup/tmp

sudo install -d -o agebackup -g agebackup -m 750 \
  /srv/agebackup /srv/agebackup/backup /srv/agebackup/compactados
```

Por que `/opt/agebackup` pertence ao usuário `agebackup`: o
`agebackup.json` e a chave `.agebackup-ftp.key` ficam **ao lado do
executável**, e o assistente precisa gravar nesse diretório. Se a pasta for
somente leitura, a configuração falhará com erro de permissão.

> **Importante:** o caminho da configuração é derivado do **executável**, não
> do diretório atual. Por isso, não coloque o binário em `/usr/local/bin` nem
> crie um symlink para ele. Mantenha sempre uma pasta própria da aplicação
> (`/opt/agebackup` ou `~/AgeBackup`) com os binários e a configuração juntos.

---

## 3. Transferir os binários

Na máquina de origem, gere (ou confira) os executáveis:

```sh
cd ~/projetos/agebackup
./packaging/build.sh
ls -lh dist/agebackup-gui dist/agebackup-backup dist/agebackup-setup \
       dist/agebackup-compactar dist/agebackup-enviar
```

Confira o tipo e os hashes:

```sh
file dist/agebackup-backup
sha256sum dist/agebackup-setup dist/agebackup-backup \
          dist/agebackup-compactar dist/agebackup-enviar
```

Copie para o servidor (ajuste `usuario@servidor`):

```sh
scp dist/agebackup-setup \
    dist/agebackup-backup \
    dist/agebackup-compactar \
    dist/agebackup-enviar \
    usuario@servidor:/tmp/

# somente se for usar a interface gráfica no servidor
scp dist/agebackup-gui usuario@servidor:/tmp/
```

No servidor, instale os binários na pasta da aplicação:

```sh
sudo install -o agebackup -g agebackup -m 755 \
  /tmp/agebackup-setup \
  /tmp/agebackup-backup \
  /tmp/agebackup-compactar \
  /tmp/agebackup-enviar \
  /opt/agebackup/

# opcional
sudo install -o agebackup -g agebackup -m 755 \
  /tmp/agebackup-gui /opt/agebackup/

rm -f /tmp/agebackup-setup /tmp/agebackup-backup \
      /tmp/agebackup-compactar /tmp/agebackup-enviar /tmp/agebackup-gui
```

Confira os hashes no destino contra os da origem:

```sh
sha256sum /opt/agebackup/agebackup-*
```

Teste se o binário inicia:

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-setup --help
sudo -u agebackup -H /opt/agebackup/agebackup-backup --help
```

Se aparecer `GLIBC_2.xx not found`, veja a seção 11.

---

## 4. Levar a configuração existente (migração)

Se o servidor é uma instalação nova, pule para a seção 5 e rode o assistente
no próprio servidor.

Se você já tem uma instalação funcionando e quer preservar a configuração,
copie os arquivos **ao lado dos binários**:

```sh
# na origem: envie os arquivos para /tmp do servidor
scp agebackup.json .agebackup-ftp.key usuario@servidor:/tmp/

# se usar Service Account, envie também a chave JSON
scp /caminho/da/service-account.json usuario@servidor:/tmp/

# se usar credenciais FTP externas
scp ftp.ini usuario@servidor:/tmp/
```

No servidor:

```sh
sudo install -o agebackup -g agebackup -m 600 \
  /tmp/agebackup.json /tmp/.agebackup-ftp.key /opt/agebackup/
```

Faça o mesmo com a chave JSON da Service Account e com o `ftp.ini`, se
existirem. A chave JSON e o `ftp.ini` também devem ser `600`.

### 4.1 A chave da senha FTP

A senha FTP fica cifrada no `agebackup.json` com uma chave em
`.agebackup-ftp.key`, no mesmo diretório. **Copie os dois juntos.** Se levar só
o `agebackup.json`, a senha não será descriptografada; nesse caso, digite a
senha novamente na aba **Configuração → Envio** (em uma máquina com GUI) ou
use o `ftp.ini`.

### 4.2 ADC: cuidado com o `HOME`

A credencial ADC **não** fica junto ao executável. Ela fica em:

```text
~/.config/gcloud/application_default_credentials.json
```

do usuário que executa o backup. Se o serviço rodará como `agebackup`, o
arquivo precisa estar em:

```text
/var/lib/agebackup/.config/gcloud/application_default_credentials.json
```

O caminho mais seguro é refazer o login como `agebackup` no servidor, ou
copiar o arquivo com dono e permissão corretos:

```sh
sudo install -d -o agebackup -g agebackup -m 700 \
  /var/lib/agebackup/.config/gcloud
sudo install -o agebackup -g agebackup -m 600 \
  ~/.config/gcloud/application_default_credentials.json \
  /var/lib/agebackup/.config/gcloud/
```

### 4.3 Ajustar os caminhos

O `agebackup.json` copiado pode apontar para caminhos da máquina antiga
(`/home/...`, `/mnt/c/...`). Depois de copiar, rode o assistente como o usuário
do serviço e ajuste:

- destino do backup (`backup.destination`);
- destino da compactação (`compactacao.destino`).

Os dados de FTP não são alterados pelo assistente; para configurá-los no
servidor, veja a seção 5.1.

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-setup
```

O assistente reaproveita a configuração existente, testa a autenticação e
reapresenta os valores. A seção `ftp` e a chave `.agebackup-ftp.key` são
preservadas se você não alterar a senha.

---

## 5. Configurar no servidor (primeira instalação)

Execute o assistente **como o usuário que fará o backup**:

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-setup
```

O assistente tem quatro passos:

1. **Conta e credenciais** — Service Account (recomendado no servidor) ou ADC.
2. **Backup** — pasta local de destino, `folder_id` e Drives compartilhados.
3. **Logs** — retenção e compactação dos logs.
4. **Compactação** — destino, retenção, prefixo e intervalo do full.

Sugestão para o servidor deste manual:

| Campo | Valor sugerido |
| --- | --- |
| Destino do backup | `/srv/agebackup/backup` |
| Destino da compactação | `/srv/agebackup/compactados` |
| Retenção da compactação | `7` (ajuste ao seu espaço) |
| Full a cada | `7` dias |
| Logs | ativos, 7 arquivos |

Depois de configurar, teste a conexão com a API:

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-setup --test
sudo -u agebackup -H /opt/agebackup/agebackup-setup --status
```

O `--test` verifica a **API do Google e o acesso à pasta**. Ele **não** testa o
FTP.

### 5.1 Configurar o FTP sem interface gráfica

Há duas formas.

**Forma A — configurar em uma máquina com GUI e copiar.** Abra o AgeBackup em
uma máquina com tela, preencha **Configuração → Envio (FTP/FTPS)**, salve,
feche o programa e copie `agebackup.json` + `.agebackup-ftp.key` para o
servidor. É o caminho mais simples e mantém a senha cifrada.

**Forma B — usar `ftp.ini` no servidor.** Crie o arquivo ao lado dos binários:

```sh
sudo -u agebackup -H tee /opt/agebackup/ftp.ini >/dev/null <<'EOF'
[ftp]
host = ftp.exemplo.com
user = usuario
password = sua-senha
porta = 21
pasta =
tls = true
EOF

sudo chown agebackup:agebackup /opt/agebackup/ftp.ini
sudo chmod 600 /opt/agebackup/ftp.ini
```

O `ftp.ini` só é usado quando a seção `ftp` do `agebackup.json` está vazia. Se
você configurou o FTP pela GUI, os dados estão no JSON e têm prioridade; nesse
caso a `.agebackup-ftp.key` é obrigatória.

Se preferir um caminho diferente para o arquivo de credenciais, defina
`envio.credenciais` no JSON (ou passe `--credenciais P` no comando).

> Testar FTP com `--dry-run` **não** abre conexão: ele apenas mostra o que
> seria enviado. A primeira validação real acontece no primeiro envio; confira
> o log `.agebackup-envios.log` na pasta de logs do backup.

---

## 6. Primeira execução e validação

### 6.1 Simulação

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-backup --dry-run
```

Confira a conta, a pasta de destino e a quantidade de arquivos. O `--dry-run`
não grava nada.

### 6.2 Backup real

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-backup
```

Verifique:

```sh
ls -la /srv/agebackup/backup
ls -la /srv/agebackup/backup/logs
sudo -u agebackup -H /opt/agebackup/agebackup-backup --check
sudo -u agebackup -H /opt/agebackup/agebackup-backup --logs
```

- `.agebackup-manifest.json` guarda o mapa Drive → arquivo local;
- `logs/.agebackup-falhas.log` lista o que não foi baixado;
- `--check` confere a integridade **sem acessar a API**.

O backup pode terminar com código diferente de zero quando algum arquivo foi
bloqueado pelo proprietário ou falhou. Isso **não** impede a compactação e o
envio; o resumo e o log de falhas mostram o que aconteceu.

### 6.3 Compactação

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-compactar
ls -lh /srv/agebackup/compactados
```

O primeiro arquivo é um **full**. Nos dias seguintes, a política padrão gera
**incrementais** (`..._inc_AAAAMMDD-HHMM.tar.gz`) e um novo full a cada 7
dias. Para forçar:

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-compactar --full
sudo -u agebackup -H /opt/agebackup/agebackup-compactar --incremental
```

### 6.4 Envio FTP

Primeiro simule:

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-enviar --dry-run
```

Depois envie de verdade:

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-enviar
```

Confira o resultado e o log:

```sh
tail -5 /srv/agebackup/backup/logs/.agebackup-envios.log
```

O envio confere o tamanho no servidor. Para conferir byte a byte (mais lento):

```sh
sudo -u agebackup -H /opt/agebackup/agebackup-enviar --verificar-sha256
```

### 6.5 Restaurar um arquivo de teste

Antes de confiar no processo, teste uma restauração:

```sh
mkdir -p /tmp/restaurado
tar tzf /srv/agebackup/compactados/SEU_ARQUIVO.tar.gz | head
tar xzf /srv/agebackup/compactados/SEU_ARQUIVO.tar.gz \
    -C /tmp/restaurado
ls -R /tmp/restaurado | head
```

Se houver incrementais, extraia o full e depois cada incremental **na ordem
cronológica** para a mesma pasta. Veja a seção 8.

---

## 7. Agendar a execução

### 7.1 Script de rotina

O `atualizar.sh` do repositório usa `uv`; no servidor com binários autônomos,
use um script próprio. Crie `/opt/agebackup/rotina.sh`:

```sh
#!/usr/bin/env bash
set -uo pipefail

APP=/opt/agebackup
LOG=/var/lib/agebackup/rotina.log
export HOME=/var/lib/agebackup
export TMPDIR=/var/lib/agebackup/tmp

cd "$APP" || exit 1
mkdir -p "$(dirname "$LOG")"

# Uma execução por vez.
exec 9>"$HOME/agebackup.lock"
if ! flock -n 9; then
    echo ">> $(date '+%F %T') já existe uma execução em andamento; saindo." >>"$LOG"
    exit 0
fi

rc_backup=0
rc_compact=0
rc_envio=0

{
    echo ">> $(date '+%F %T')  backup"
    "$APP/agebackup-backup" || rc_backup=$?

    echo ">> $(date '+%F %T')  compactação"
    "$APP/agebackup-compactar" || rc_compact=$?

    echo ">> $(date '+%F %T')  envio FTP"
    "$APP/agebackup-enviar" || rc_envio=$?

    echo ">> $(date '+%F %T')  fim (backup=$rc_backup, compactacao=$rc_compact, envio=$rc_envio)"
} >>"$LOG" 2>&1

exit $((rc_backup || rc_compact || rc_envio))
```

Ajuste dono e permissão:

```sh
sudo chown root:root /opt/agebackup/rotina.sh
sudo chmod 755 /opt/agebackup/rotina.sh
```

> O script continua para a compactação e o envio mesmo quando o backup termina
> com falhas parciais. O código de saída final será diferente de zero se algum
> passo falhou.

### 7.2 Opção A — systemd (recomendado)

Crie `/etc/systemd/system/agebackup.service`:

```ini
[Unit]
Description=AgeBackup (backup + compactacao + envio)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=agebackup
Group=agebackup
WorkingDirectory=/opt/agebackup
Environment=HOME=/var/lib/agebackup
Environment=TMPDIR=/var/lib/agebackup/tmp
Environment=LANG=C.UTF-8
# Se houver proxy, descomente e ajuste:
# Environment=HTTPS_PROXY=http://proxy.exemplo:3128
# Environment=HTTP_PROXY=http://proxy.exemplo:3128
ExecStart=/opt/agebackup/rotina.sh
TimeoutStartSec=0
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
```

Se usar proxy, descomente e preencha `HTTPS_PROXY` (e `HTTP_PROXY`, se
necessário). `TimeoutStartSec=0` evita que o systemd mate um backup longo.

Crie `/etc/systemd/system/agebackup.timer`:

```ini
[Unit]
Description=Executa o AgeBackup diariamente

[Timer]
OnCalendar=*-*-* 22:00:00
Persistent=true
RandomizedDelaySec=5m

[Install]
WantedBy=timers.target
```

Ative:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now agebackup.timer
systemctl list-timers agebackup.timer
```

Teste uma execução imediata:

```sh
sudo systemctl start agebackup.service
tail -n 50 /var/lib/agebackup/rotina.log
```

O serviço é `oneshot`: o `systemctl start` só retorna quando a execução
termina. Se quiser acompanhar em tempo real, use
`sudo systemctl start --no-block agebackup.service` e
`tail -f /var/lib/agebackup/rotina.log`.

### 7.3 Opção B — cron

Se preferir cron:

```sh
sudo crontab -u agebackup -e
```

Adicione:

```cron
15 2 * * * /opt/agebackup/rotina.sh >/dev/null 2>&1
```

O script já registra em `/var/lib/agebackup/rotina.log` e usa `flock`, então
duas execuções não se sobrepõem. Não é necessário configurar `PATH` para `uv`
porque o script chama os binários por caminho absoluto.

---

## 8. Interface gráfica no servidor (opcional)

### 8.1 Servidor com tela

Se o servidor tem ambiente gráfico e você está logado nele:

```sh
/opt/agebackup/agebackup-gui
```

A GUI usa o mesmo `agebackup.json` e a mesma pasta da aplicação do CLI. Rode-a
como o **mesmo usuário** que executa o backup; caso contrário, permissões
`600` no JSON/chave impedem a leitura.

### 8.2 Servidor sem tela (headless)

Não é necessário instalar a GUI. Use os comandos de linha:

```sh
/opt/agebackup/agebackup-backup
/opt/agebackup/agebackup-compactar
/opt/agebackup/agebackup-enviar
```

A restauração interativa é a função mais difícil de substituir no CLI. Em
servidor sem tela, restaure com `tar` (seção 9).

### 8.3 GUI remota por SSH

No cliente, tenha um servidor X (Linux, XQuartz no macOS ou VcXsrv no
Windows) e conecte com:

```sh
ssh -X usuario@servidor
/opt/agebackup/agebackup-gui
```

No servidor, o `X11Forwarding` precisa estar habilitado e o pacote `xauth`
instalado. A interface funciona, mas pode ficar lenta em links de baixa
latência. Para uso diário em servidor, prefira o CLI ou uma sessão VNC/RDP.

Se aparecer `TclError: no display name and no $DISPLAY environment variable`,
não há sessão gráfica disponível. Use o CLI ou configure o encaminhamento X11.

---

## 9. Restaurar em servidor sem interface

Liste o conteúdo do arquivo:

```sh
tar tzf /srv/agebackup/compactados/bkps_20261019-2200.tar.gz | less
```

Extraia um item específico:

```sh
mkdir -p /srv/agebackup/restaurado
tar xzf /srv/agebackup/compactados/bkps_20261019-2200.tar.gz \
    -C /srv/agebackup/restaurado "Documentos/contrato.pdf"
```

Extraia tudo:

```sh
mkdir -p /srv/agebackup/restaurado
tar xzf /srv/agebackup/compactados/bkps_20261019-2200.tar.gz \
    -C /srv/agebackup/restaurado
```

### 9.1 Full + incrementais

Um incremental **não** é autossuficiente. Extraia o full e depois os
incrementais em ordem de nome (a data no nome é cronológica), todos para a
mesma pasta:

```sh
mkdir -p /srv/agebackup/restaurado
tar xzf /srv/agebackup/compactados/bkps_20261019-2200.tar.gz \
    -C /srv/agebackup/restaurado
tar xzf /srv/agebackup/compactados/bkps_RSKO_inc_20261020-2200.tar.gz \
    -C /srv/agebackup/restaurado
tar xzf /srv/agebackup/compactados/bkps_RSKO_inc_20261021-2200.tar.gz \
    -C /srv/agebackup/restaurado
```

Os incrementais sobrescrevem apenas os arquivos que mudaram. O restante
continua vindo do full.

Se o arquivo estiver no FTP, baixe-o antes com seu cliente preferido
(`lftp`, `curl`, FileZilla etc.) e confira o tamanho/SHA-256.

---

## 10. Atualizar o AgeBackup no servidor

1. Pare o agendador para não trocar o binário durante uma execução:

   ```sh
   sudo systemctl stop agebackup.timer
   sudo systemctl stop agebackup.service   # se estiver rodando agora
   ```

2. Guarde a configuração e a chave:

   ```sh
   sudo cp -a /opt/agebackup/agebackup.json \
              /opt/agebackup/.agebackup-ftp.key \
              /var/lib/agebackup/
   ```

3. Copie os novos binários para `/opt/agebackup/` (sem apagar o JSON, a chave,
   a Service Account ou o `ftp.ini`):

   ```sh
   sudo install -o agebackup -g agebackup -m 755 \
     /tmp/agebackup-setup /tmp/agebackup-backup \
     /tmp/agebackup-compactar /tmp/agebackup-enviar \
     /opt/agebackup/
   ```

4. Valide:

   ```sh
   sudo -u agebackup -H /opt/agebackup/agebackup-setup --status
   sudo -u agebackup -H /opt/agebackup/agebackup-setup --test
   sudo -u agebackup -H /opt/agebackup/agebackup-backup --dry-run
   ```

5. Religue o agendador:

   ```sh
   sudo systemctl start agebackup.timer
   ```

Se o novo binário exigir uma `glibc` mais nova do que a do servidor, compile a
versão nova **no servidor** (ou em contêiner compatível) em vez de copiar.

---

## 11. Recompilar no servidor (quando a glibc é incompatível)

O servidor de compilação precisa de `uv` e dos pré-requisitos do projeto.
Depois de gerar os binários, Python e `uv` **não** são necessários para
executá-los.

```sh
# dependências de compilação (Debian/Ubuntu)
sudo apt update
sudo apt install -y git curl build-essential

# instalar o uv para o usuário atual
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"

git clone git@github.com:IsaacMeirelles/agebackup.git
cd agebackup
uv sync
./packaging/build.sh
```

O `uv` baixa o Python 3.14 e as dependências; o PyInstaller está no grupo de
desenvolvimento. Se o servidor for mais antigo, compile nele (ou em um
contêiner com a mesma `glibc`) para que o binário rode nos outros servidores
da mesma geração.

---

## 12. Problemas comuns

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| `version 'GLIBC_2.43' not found` | binário compilado em glibc mais nova | recompile no servidor/destino (seção 11) |
| `cannot execute binary file: Exec format error` | arquitetura errada (ARM, 32 bits) | use binário x86_64 ou recompile |
| `No such file or directory` ao executar um binário existente | loader/glibc incompatível | confira `file` e `ldd`; recompile |
| `Permission denied` ao salvar configuração | `/opt/agebackup` não é gravável pelo usuário | `chown agebackup:agebackup /opt/agebackup` e `chmod 700` |
| Configuração “não encontrada” ou criada no lugar errado | binário em `/usr/local/bin` ou symlink | mantenha o binário em `/opt/agebackup` e rode por caminho absoluto |
| `TclError: no display name` | GUI sem sessão gráfica | use CLI; ou `ssh -X` / VNC |
| `libX11.so.6: cannot open shared object file` | bibliotecas X/Tk ausentes | instale os pacotes da seção 2.4 |
| `Failed to extract` / erro em `/tmp` | `/tmp` sem permissão de execução ou cheio | crie `TMPDIR` executável e use `TMPDIR=/var/lib/agebackup/tmp` |
| `No space left on device` | disco cheio (backup + tar + extração) | libere espaço ou mude destinos |
| `gcloud CLI não encontrado` | modo ADC sem gcloud | use Service Account ou instale o gcloud |
| `invalid_grant` / credenciais expiradas | ADC revogado ou copiado para o `HOME` errado | refaça o login como o usuário do serviço |
| `403` / pasta não encontrada | Service Account sem acesso à pasta | compartilhe a pasta com `client_email` como Leitor e confira o `folder_id` |
| FTP não conecta | porta/TLS/firewall | confira host, porta, `tls`, modo passivo e liberação no firewall |
| FTP conecta mas o upload trava | faixa passiva bloqueada | libere a faixa passiva no servidor FTP |
| Senha FTP não descriptografa | `.agebackup-ftp.key` não foi copiada | copie a chave ou digite a senha novamente / use `ftp.ini` |
| `ftp.ini` é ignorado | seção `ftp` do JSON preenchida | esvazie a seção `ftp` ou use os dados/chave do JSON |
| Arquivo remoto menor que o local | upload truncado / conexão caiu | veja `.agebackup-envios.log`; rode `--conferir` ou `--verificar-sha256` |
| Relógio errado / falha TLS | hora dessincronizada | `sudo timedatectl set-ntp true` |
| Backup termina com código 1 | arquivos bloqueados ou falhas parciais | veja `--falhas` e `logs/.agebackup-falhas.log`; compactação/envio continuam |

### Onde olhar os logs

- `logs/.agebackup-falhas.log` — falhas de download;
- `logs/.agebackup-removidos.log` — arquivos que sumiram do Drive;
- `logs/.agebackup-envios.log` — cada tentativa de envio FTP;
- `/var/lib/agebackup/rotina.log` — execução do script agendado;
- `journalctl -u agebackup.service` — saída do systemd.

---

## 13. Checklist final

- [ ] `uname -m` é `x86_64` e a glibc do destino é compatível (ou o binário foi recompilado nele).
- [ ] Usuário `agebackup` e pastas `/opt/agebackup`, `/srv/agebackup/backup`, `/srv/agebackup/compactados` criados com as permissões corretas.
- [ ] Binários copiados, com hash conferido e `--help` funcionando.
- [ ] `agebackup.json` e `.agebackup-ftp.key` (ou `ftp.ini`) no mesmo diretório do executável, com modo `600`.
- [ ] Service Account compartilhada como Leitor ou ADC válido para o usuário do serviço.
- [ ] `agebackup-setup --status` e `--test` OK.
- [ ] `agebackup-backup --dry-run` OK.
- [ ] Primeiro backup real concluído e `--check` sem erros graves.
- [ ] Primeira compactação e primeiro envio FTP concluídos; `.agebackup-envios.log` mostra `ok`.
- [ ] Restauração de um arquivo de teste feita com sucesso.
- [ ] Timer systemd (ou cron) ativo e uma execução de teste disparada.
- [ ] Segredos (`agebackup.json`, `.agebackup-ftp.key`, chave JSON, ADC) com permissão `600` e sem cópia em `/tmp`.
