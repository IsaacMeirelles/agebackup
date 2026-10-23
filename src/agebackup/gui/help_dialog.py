"""Diálogo de ajuda: guia detalhado da aba aberta.

O texto de cada guia explica a finalidade da aba, campo por campo e o que cada
botão faz ao ser clicado. O usuário pode abrir a ajuda já na aba em que está
(F1) e trocar de guia pela lista no topo da janela.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .utils import centralizar_janela

# Ordem em que os guias aparecem na lista do diálogo.
GUIAS: list[tuple[str, str]] = [
    ("inicio", "Início/Status"),
    ("config", "Configuração"),
    ("backup", "Backup"),
    ("compact", "Compactação"),
    ("upload", "Upload Manual"),
    ("restore", "Restaurar"),
    ("log", "Log"),
]

NOMES = dict(GUIAS)


AJUDA_INICIO = """== INÍCIO/STATUS ==
Painel de resumo do AgeBackup. Não executa backup nem altera nada: serve para
conferir rapidamente se a configuração carregada é a que você espera.

# O que aparece no quadro "Status Geral"
Cada linha é lida do arquivo de configuração no momento em que a aba é aberta
ou em que você clica em **Atualizar status**:
- **Configuração**: caminho completo do `agebackup.json` em uso. Ele fica junto
  ao aplicativo (ou na raiz do projeto, quando roda com `uv run`).
- **Conta**: e-mail configurado, ou o método de autenticação quando não há
  e-mail.
- **Destino backup**: pasta local que recebe os arquivos do Google Drive.
- **Pasta Drive**: ID da pasta de origem. "(todo Drive)" significa que o backup
  pega o Drive inteiro.
- **Compactação**: texto da política atual (por exemplo, "full a cada 7 dias")
  e o prefixo usado nos nomes dos `.tar.gz`.
- **Logs**: quantos logs fechados são mantidos e se eles são comprimidos.
- **Envio FTP**: caminho do arquivo de credenciais ou "(padrão)".

# Botões
- **Ir para Backup**: abre a aba Backup. Use quando o resumo estiver correto e
  você quiser iniciar a cópia.
- **Ir para Compactação**: abre a aba Compactação, para gerar o `.tar.gz`.
- **Ir para Upload Manual**: abre a aba Upload Manual, para enviar um arquivo
  ou os logs ao servidor FTP.
- **Ir para Restaurar**: abre a aba Restaurar, para recuperar itens de um
  `.tar.gz`.
- **Ir para Log**: abre a aba Log, para ler os registros de execução.
- **Atualizar status**: relê o `agebackup.json` e redesenha o resumo. Clique
  aqui depois de salvar uma configuração em outra aba.
- **Abrir Ajuda (F1)**: abre esta janela, já no guia da aba atual.

# Quando a configuração não existe
O quadro mostra "Configuração não encontrada" e o caminho esperado do arquivo.
Nesse caso, abra a aba **Configuração**, preencha os campos e clique em
**Salvar (Ctrl+S)**. O resumo só passa a aparecer depois disso.

# Dica
F1 abre a ajuda de qualquer aba. Ctrl+S salva a configuração a partir de
qualquer aba. Ctrl+Q fecha o programa.
"""

AJUDA_CONFIG = """== CONFIGURAÇÃO ==
Reúne todos os parâmetros do AgeBackup. Nada é gravado enquanto você digita:
as alterações só valem depois de clicar em **Salvar (Ctrl+S)**.

# Barra superior
- **Arquivo de configuração**: mostra o caminho completo do `agebackup.json`
  que será lido e gravado. É só informativo.
- **Salvar (Ctrl+S)**: valida os campos, ajusta números fora da faixa e grava
  tudo no `agebackup.json`, com permissão restrita (somente o seu usuário). Ao
  terminar, mostra uma mensagem com o caminho gravado.
- As cinco sub-abas abaixo são partes do mesmo arquivo: salvar grava todas de
  uma vez, não apenas a que está visível.

# Sub-aba Conta
Define como o programa se autentica no Google Drive.
- **Método de autenticação**: escolha entre **ADC** (Application Default
  Credentials, o login feito pelo `gcloud`) e **Service Account** (chave JSON
  de uma conta de serviço, indicada para servidores e execução automática). A
  escolha muda qual credencial o backup usa.
- **E-mail**: endereço associado à conta. Serve para identificação e para o
  resumo do status; não é usado como senha.
- **Chave Service Account (JSON)**: caminho completo do arquivo `.json` da
  conta de serviço. Só é necessário quando o método é Service Account. O botão
  **Procurar...** abre o seletor de arquivos e preenche o campo.
- **Escopos**: fixo em `drive.readonly`, ou seja, o AgeBackup só lê o Drive e
  nunca apaga nem altera nada lá.

# Sub-aba Backup (Google Drive)
- **Pasta de destino do backup**: pasta local que recebe os arquivos. É
  obrigatória para o backup rodar. O botão **Procurar...** escolhe a pasta e
  preenche o campo. Se a pasta não existir na hora do backup, ele falha com
  mensagem de erro.
- **ID da pasta no Google Drive**: cole o ID de uma pasta específica para
  copiar só o conteúdo dela. Deixe **vazio** para copiar o Drive inteiro. O ID
  é o trecho final da URL da pasta no Drive.
- **Incluir unidades compartilhadas**: quando marcado, também copia o conteúdo
  de unidades compartilhadas (Shared Drives) às quais a conta tem acesso.
  Desmarcado, só o "Meu Drive" é copiado.

# Sub-aba Compactação
Controla os arquivos `.tar.gz` gerados a partir do backup.
- **Pasta dos arquivos compactados (.tar.gz)**: onde os pacotes são gravados.
  Vazio significa "na pasta acima da pasta de destino do backup" (o padrão).
  **Procurar...** escolhe a pasta.
- **Prefixo do nome**: texto inserido no nome do arquivo, útil para separar
  conjuntos de backups. Vazio significa sem prefixo. Caracteres inválidos são
  removidos automaticamente ao salvar.
- **Manter (0 = guardar todos)**: quantos arquivos compactados devem ser
  mantidos. Ao aplicar a retenção, os mais antigos acima desse número são
  apagados. **0 desliga a exclusão** e guarda tudo.
- **Full a cada N dias (0 = sempre full)**: define a política automática.
  Exemplo: 7 gera um FULL por semana e INCREMENTAL nos outros dias. **0** faz
  FULL em toda execução. Ao salvar, valores fora da faixa permitida são
  ajustados.

# Sub-aba Logs
- **Ativar logs de falhas**: marcado, o programa grava o registro de arquivos
  que falharam na cópia. Desmarcado, esse registro não é gerado.
- **Pasta dos logs (dentro do destino, vazio = raiz)**: subpasta, relativa à
  pasta de destino do backup, onde ficam os logs. O padrão é `logs`. Caminhos
  absolutos ou com `..` são recusados e voltam ao padrão ao salvar.
- **Manter logs fechados (0 = indeterminado)**: quantos logs antigos são
  preservados na rotação. **0** guarda indefinidamente.
- **Comprimir logs antigos (.gz)**: marcado, os logs já fechados são
  comprimidos para ocupar menos espaço.
- Os logs sempre registram o **caminho completo** dos arquivos, o que facilita
  localizar o que falhou.

# Sub-aba Envio (FTP/FTPS)
- **Arquivo de credenciais FTP/FTPS (.ini)**: caminho do arquivo `.ini` com
  host, usuário e senha. **Procurar...** seleciona o arquivo.
- **Usar padrão junto à app**: preenche o campo com o `ftp.ini` que fica na
  mesma pasta do aplicativo.
- **Manter no servidor FTP (0 = guardar todos)**: quantos backups ficam no
  servidor. Ao enviar, os mais antigos acima desse número são removidos.
  **0 desliga a exclusão**.
- **Pasta remota personalizada (variáveis)**: pasta de destino no servidor.
  Aceita texto livre e as variáveis abaixo, substituídas pela data do envio:
  - **YYYY** = ano com 4 dígitos (2026)
  - **YY** = ano com 2 dígitos (26)
  - **MM** = mês com 2 dígitos (01 a 12)
  - **M** = mês sem zero à esquerda
  - **dd** = dia com 2 dígitos
  - **d** = dia sem zero à esquerda
  Exemplos: `/backups/YYYY/MM`, `/RSKO/YYYY-MM`, `/clientes/acme/dd-MM-YYYY`.
  Vazio usa o padrão `/AAAA/MM/`. A senha do FTP fica **criptografada** dentro
  do `agebackup.json`; a chave fica em `.agebackup-ftp.key`, na mesma pasta.

# Erros comuns
- "Não foi possível salvar": verifique se você tem permissão de escrita na
  pasta do aplicativo.
- Campo vazio obrigatório: o backup não roda sem a pasta de destino.
- Depois de salvar, volte ao **Início/Status** e clique em **Atualizar status**
  para conferir se os valores ficaram como você queria.
"""

AJUDA_BACKUP = """== BACKUP ==
Copia os arquivos do Google Drive para a pasta de destino configurada. A
execução usa todos os parâmetros da aba **Configuração**; não há campos para
preencher aqui.

# Antes de clicar em Iniciar
1. A configuração precisa estar salva (aba Configuração → **Salvar**).
2. A pasta de destino do backup precisa estar definida e acessível.
3. A autenticação precisa estar válida (ADC ou chave de Service Account).

Se algo estiver faltando, o programa mostra uma mensagem de erro e não inicia.

# Botões
- **Iniciar Backup**: carrega a configuração, limpa o log da tela e começa a
  cópia em segundo plano. Durante a execução o botão fica desabilitado para
  evitar duas cópias ao mesmo tempo. Ao concluir, o botão volta e o status
  inferior mostra "Backup concluído". Se ocorrer um erro, aparece uma janela
  com a causa e o andamento fica registrado no log.
- **Limpar log**: apaga somente o texto da tela e zera os contadores. Não apaga
  arquivos de log gravados em disco nem interfere em uma execução em curso.

# O que aparece durante a execução
- **Execução em tempo real**: cada linha mostra o que está sendo feito, com o
  **caminho completo** do arquivo (origem e destino). Role a tela para
  acompanhar.
- **Contadores**: ao final, mostram quantos arquivos foram **Baixados**,
  **Inalterados**, **Movidos** e quantos tiveram **Falhas**. "Inalterados" são
  arquivos que já estavam iguais no destino; "Movidos" são arquivos que
  mudaram de pasta no Drive.

# O que o programa faz internamente
- Compara o conteúdo do Drive com o que já existe no destino, baixando apenas
  o que é novo ou mudou.
- Mantém um manifesto para saber o que já foi copiado e detectar alterações.
- Grava o registro de falhas conforme a aba Logs.
- Arquivos removidos do Drive não são apagados do destino automaticamente.

# Dicas
- Você pode trocar de aba enquanto o backup roda; ele continua em segundo
  plano. Evite fechar a janela antes de terminar.
- Em caso de falha, abra a aba **Log** e carregue o
  `.agebackup-falhas.log` para ver os caminhos completos dos arquivos com
  problema.
- Rodar o backup de novo é seguro: o que já está igual não é baixado outra vez.
"""

AJUDA_COMPACT = """== COMPACTAÇÃO ==
Transforma a pasta de backup em arquivos `.tar.gz`, para guardar ou enviar ao
servidor. Usa a política definida na aba Configuração (sub-aba Compactação).

# A lista
Mostra os arquivos `.tar.gz` encontrados na pasta de compactação, do mais novo
para o mais antigo, com quatro colunas:
- **Arquivo**: nome do pacote.
- **Tipo**: **FULL** (cópia completa) ou **INCREMENTAL** (só o que mudou desde
  o último full).
- **Tamanho**: tamanho legível (KB, MB, GB).
- **Caminho completo**: onde o arquivo está no disco.

A lista é apenas informativa; ela não é atualizada sozinha. Clique em
**Atualizar lista** depois de gerar ou apagar arquivos.

# Botões
- **Seguir política (auto)**: é o modo recomendado. Verifica quando foi o
  último FULL e a configuração "Full a cada N dias":
  - se **N = 0**, gera sempre FULL;
  - se o último FULL está dentro do prazo, gera **INCREMENTAL**;
  - se o prazo venceu (ou não existe FULL), gera **FULL**.
  Ao terminar, atualiza a lista e mostra "Compactação finalizada".
- **Forçar FULL**: gera um FULL agora, ignorando a política. Use quando quiser
  uma base completa nova (por exemplo, antes de uma limpeza).
- **Forçar INCREMENTAL**: gera um INCREMENTAL agora, mesmo fora da política.
  Só faz sentido se já existir um FULL anterior, pois o incremental contém
  apenas as diferenças.
- **Aplicar retenção**: aplica o campo "Manter" da configuração. Se "Manter"
  for maior que zero, apaga os pacotes mais antigos que ultrapassam o limite.
  Se for 0, nada é apagado. **Esta ação apaga arquivos de verdade** e não pede
  confirmação, por isso confira o valor de "Manter" antes de clicar.
- **Atualizar lista**: relê a pasta de compactação e redesenha a tabela.

# Como o pacote é montado
- O nome segue o padrão `nome_base_prefixo_data.tar.gz`; o prefixo é o da
  configuração.
- O FULL inclui a pasta de backup inteira (menos arquivos temporários).
- O INCREMENTAL inclui apenas arquivos novos ou alterados desde o FULL
  anterior. Por isso, ao restaurar uma sequência, o FULL deve ser extraído
  primeiro.

# Dicas
- Faça o backup (aba Backup) antes de compactar, para o pacote refletir os
  dados mais recentes.
- Se a lista estiver vazia, confira a pasta de compactação e se já houve alguma
  compactação. A mensagem abaixo da lista mostra o caminho e a quantidade de
  arquivos encontrados.
"""

AJUDA_UPLOAD = """== UPLOAD MANUAL ==
Envia ao servidor FTP/FTPS um arquivo `.tar.gz` ou os logs, sob demanda, sem
depender da rotina automática. Tudo o que acontece aparece no quadro **Log do
envio**, com caminhos completos.

# Campo de arquivo
- A caixa de texto no topo mostra o caminho do arquivo que será enviado. Você
  pode digitar o caminho diretamente ou usar os botões ao lado.

# Botões
- **Procurar .tar.gz**: abre o seletor de arquivos, filtra por `.tar.gz` e
  coloca o caminho escolhido na caixa. O caminho completo é registrado no log.
- **Listar compactados**: lê a pasta de compactação configurada e lista no log
  até 20 arquivos, do mais novo para o mais antigo, cada um com nome e caminho
  completo. Serve para conferir o que existe antes de enviar. Se a pasta não
  existir, mostra um aviso.
- **Enviar arquivo selecionado**: usa as credenciais salvas no
  `agebackup.json` (senha criptografada) ou, se não houver, o arquivo `.ini`
  indicado na configuração. Mostra o usuário/host/porta, a pasta remota
  calculada e transfere o arquivo. A transferência é conferida pelo tamanho e
  por verificação de integridade; se algo não bater, o envio é reportado como
  erro. Ao terminar, o log mostra o caminho remoto e quantos bytes foram
  enviados, e aplica a retenção configurada ("Manter no servidor FTP"): com
  valor maior que zero, os arquivos mais antigos acima do limite são removidos
  do servidor (e listados no log); com 0, nada é removido.
- **Enviar logs**: envia a pasta de logs configurada para
  `<pasta remota>/logs`, também aplicando a retenção. O log informa quantos
  arquivos foram enviados e quais falharam; se algum falhar, aparece um aviso.

# Log de status dos envios
Cada tentativa, inclusive as que falham, é registrada em
**`.agebackup-envios.log`**, na pasta de logs configurada (Configuração →
Logs). O arquivo é TSV, uma linha por arquivo enviado, com:

- data/hora da tentativa;
- status: **ok** ou **falha**;
- nome e **caminho local completo** do arquivo;
- tamanho local e tamanho remoto em bytes;
- pasta remota usada;
- conferência aplicada (tamanho, sha256 ou vazia);
- detalhe do erro, quando houver.

O caminho do log aparece no quadro após cada envio. A rotação (quando ativa na
configuração de logs) fecha esse arquivo no início da próxima execução do
backup, como os demais, mantendo os N mais recentes. Para consultar: aba **Log**
→ **Carregar .agebackup-envios.log** (e filtre por `falha` para ver só o que deu
errado).

# Pasta remota
A pasta de destino no servidor é montada na hora com a data do envio e o
padrão configurado em **Configuração → Envio**. As variáveis aceitas são
`YYYY`, `YY`, `MM`, `M`, `dd` e `d`. Exemplo: `/backups/YYYY/MM` gera
`/backups/2026/10`. Se o campo estiver vazio, o padrão é `/AAAA/MM/`. A linha
"Pasta remota" no log mostra exatamente para onde o arquivo vai.

# Mensagens de erro comuns
- "Arquivo de credenciais não encontrado": o caminho do `.ini` está errado ou
  não existe; corrija na aba Configuração.
- "Selecione um arquivo para enviar": a caixa de caminho está vazia.
- Falha de autenticação ou conexão: confira host, porta, usuário e senha, além
  de o servidor aceitar FTPS.
- Se o arquivo não aparecer no servidor, confira no log a pasta remota exibida
  e se a conta tem permissão de escrita nela.

# Dicas
- O envio roda em segundo plano: a janela continua respondendo.
- Para reenviar, basta selecionar o arquivo de novo; não há limite de tentativas.
- A senha nunca aparece no log.
"""

AJUDA_RESTORE = """== RESTAURAR ==
Recupera itens de dentro de um `.tar.gz`: um arquivo ou pasta específica, ou o
conteúdo completo. Funciona tanto para pacotes FULL quanto INCREMENTAIS.

# Barra do arquivo
- **Nenhum arquivo selecionado / nome do arquivo**: mostra o pacote aberto e o
  caminho completo.
- **Selecionar .tar.gz**: abre o seletor já na pasta de compactação
  configurada. Ao escolher o arquivo, o programa lê o índice do pacote e
  preenche a lista. Em pacotes grandes isso pode levar alguns minutos, porque
  o `.tar.gz` precisa ser descomprimido só para listar o conteúdo. A janela
  continua respondendo e mostra a contagem de itens.
- **Cancelar leitura**: interrompe a leitura do índice. Use quando selecionou o
  arquivo errado ou não quer esperar. A lista fica vazia até você selecionar
  outro arquivo.
- **Índice em cache**: depois da primeira leitura, o índice fica guardado na
  pasta `indices/`, junto ao `agebackup.json`. Abrir o mesmo arquivo novamente
  é imediato, desde que ele não tenha sido alterado (tamanho e data são
  conferidos).

# Filtro e lista
- **Filtrar**: digite parte do nome (sem diferenciar maiúsculas/minúsculas)
  para reduzir a lista em tempo real. Exemplo: `contrato` ou `2026/notas`.
- A tabela mostra até **2.000 itens** por vez para não travar a interface. Se
  houver mais, a mensagem abaixo indica "Mostrando 2.000 de N"; refine o
  filtro para ver os demais.
- **Conteúdo do arquivo compactado**: nomes de arquivos e pastas como estão
  dentro do pacote. Pastas aparecem terminadas em `/`.

# Botões de restauração
- **Restaurar selecionado(s) aqui...**: extrai os itens marcados na pasta de
  compactação configurada (destino padrão). Se você selecionou uma pasta, todos
  os arquivos dentro dela também são extraídos. A extração roda em segundo
  plano e, ao final, mostra o destino e a quantidade de itens.
- **Restaurar em outra pasta...**: igual ao anterior, mas abre uma caixa para
  você escolher o destino. Útil para conferir um arquivo sem mexer na pasta
  original.
- **Restaurar arquivo COMPLETO**: extrai todo o conteúdo do `.tar.gz` na pasta
  escolhida (a caixa já abre na pasta de compactação). Use quando quiser
  reconstruir tudo de uma vez.

# Restaurando uma sequência (FULL + incrementais)
1. Selecione o `.tar.gz` **FULL** mais antigo que faz parte da sequência e use
   **Restaurar arquivo COMPLETO** (ou restaure os itens desejados).
2. Depois, restaure os **INCREMENTAIS na ordem cronológica** (do mais antigo
   para o mais novo), sempre no mesmo destino.
3. O resultado final é o estado mais recente. Restaurar um incremental sem o
   FULL correspondente deixa arquivos faltando.

# Segurança
- A extração recusa caminhos absolutos e `..` dentro do pacote, para não gravar
  fora da pasta escolhida.
- Se a pasta de destino não existir, ela é criada.
- Arquivos com o mesmo nome no destino são substituídos pelos do pacote.

# Dicas
- Para achar um arquivo rapidamente em pacotes enormes, selecione o `.tar.gz`,
  espere a leitura e use o filtro.
- Para conferir o conteúdo sem abrir a interface:
  `tar tzf arquivo.tar.gz | less`.
- O botão de restaurar arquivo completo não pede confirmação de substituição:
  escolha com cuidado a pasta de destino.
"""

AJUDA_LOG = """== LOG ==
Abre e filtra registros de execução para diagnosticar problemas e conferir o
que foi copiado. Todos os caminhos aparecem completos.

# Botões
- **Carregar agebackup-atualizar.log**: carrega o log de atualização do
  programa, que fica na sua pasta pessoal (`~/agebackup-atualizar.log`). Útil
  para ver o que aconteceu na última atualização do código.
- **Carregar .agebackup-falhas.log**: carrega o registro de falhas do backup,
  que fica na pasta de logs configurada (dentro do destino do backup). Se não
  houver configuração, tenta `~/.agebackup-falhas.log`. Cada linha traz a
  data/hora, o nome, a categoria, o **caminho local completo** e a **data de
  modificação no Drive**, para localizar o arquivo rapidamente. É o primeiro
  lugar a olhar quando o backup termina com falhas.
- **Carregar .agebackup-envios.log**: carrega o status dos envios ao FTP, com
  data/hora, status (ok/falha), caminho local completo, tamanhos, pasta remota
  e detalhe do erro. Use o filtro `falha` para ver só as tentativas que não
  deram certo.
- **Abrir arquivo...**: abre qualquer arquivo de log do disco. Também aceita
  arquivos `.gz` (logs comprimidos), que são descomprimidos na leitura.
- **Copiar seleção**: copia para a área de transferência apenas o trecho que
  você selecionou com o mouse. O status inferior confirma a cópia.
- **Limpar**: apaga o texto da tela e o conteúdo em memória. Não apaga o
  arquivo do disco.
- **Filtro**: à direita dos botões, filtra as linhas em tempo real. Digite, por
  exemplo, `ERRO`, `FALHA` ou o nome de um arquivo. A etiqueta abaixo mostra
  quantas linhas foram encontradas em relação ao total. Apagar o filtro volta a
  mostrar o arquivo inteiro.

# Informações abaixo do texto
Mostra o caminho completo do arquivo carregado e o número de linhas. Quando há
filtro ativo, mostra também quantas linhas correspondem ao texto digitado.

# Dicas
- Para achar um problema de backup, carregue o `.agebackup-falhas.log` e filtre
  por `FALHA` ou pelo caminho da pasta que interessa.
- Para conferir envios, carregue o `.agebackup-envios.log` e filtre por `falha`
  ou pelo nome do arquivo.
- Logs comprimidos (`.gz`) podem ser abertos diretamente com **Abrir
  arquivo...**.
- Se o arquivo não existir, o programa avisa e não altera o que já está na
  tela.
- O texto é somente leitura; para editar, copie a seleção para outro programa.
"""

AJUDA_POR_ABA = {
    "inicio": AJUDA_INICIO,
    "config": AJUDA_CONFIG,
    "backup": AJUDA_BACKUP,
    "compact": AJUDA_COMPACT,
    "upload": AJUDA_UPLOAD,
    "restore": AJUDA_RESTORE,
    "log": AJUDA_LOG,
}


class HelpDialog:
    """Janela de ajuda com o guia detalhado da aba atual."""

    def __init__(self, parent, chave: str = "inicio"):
        self.janela = tk.Toplevel(parent)
        self.janela.title("Ajuda - AgeBackup")
        self.janela.transient(parent)
        self.janela.grab_set()
        centralizar_janela(self.janela, 860, 700)

        if chave not in AJUDA_POR_ABA:
            chave = "inicio"

        self.var_guia = tk.StringVar(value=NOMES[chave])
        self._criar()
        self._mostrar(chave)

    def _criar(self):
        topo = ttk.Frame(self.janela, padding=(10, 10, 10, 0))
        topo.pack(fill=tk.X)
        ttk.Label(topo, text="Guia da aba:").pack(side=tk.LEFT)
        self.combo = ttk.Combobox(
            topo,
            textvariable=self.var_guia,
            values=[nome for _chave, nome in GUIAS],
            state="readonly",
            width=24,
        )
        self.combo.pack(side=tk.LEFT, padx=5)
        self.combo.bind("<<ComboboxSelected>>", self._trocar_guia)
        ttk.Label(topo, text="F1 abre o guia da aba em que você está").pack(
            side=tk.RIGHT
        )

        frame = ttk.Frame(self.janela, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self.texto = tk.Text(
            frame,
            wrap=tk.WORD,
            font=("TkDefaultFont", 9),
            padx=8,
            pady=8,
            relief=tk.FLAT,
        )
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.texto.yview)
        self.texto.configure(yscrollcommand=scroll.set)
        self.texto.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.texto.tag_configure(
            "titulo", font=("TkDefaultFont", 14, "bold"), spacing3=8
        )
        self.texto.tag_configure(
            "secao",
            font=("TkDefaultFont", 11, "bold"),
            spacing1=12,
            spacing3=4,
        )
        self.texto.tag_configure("negrito", font=("TkDefaultFont", 9, "bold"))
        self.texto.configure(state=tk.DISABLED)

        botoes = ttk.Frame(self.janela, padding=(10, 0, 10, 10))
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="Fechar", command=self.janela.destroy).pack(
            side=tk.RIGHT
        )
        self.janela.bind("<Escape>", lambda e: self.janela.destroy())
        self.janela.bind("<F1>", lambda e: self.janela.destroy())

    def _trocar_guia(self, _evento=None):
        nome = self.var_guia.get()
        for chave, rotulo in GUIAS:
            if rotulo == nome:
                self._mostrar(chave)
                return

    def _mostrar(self, chave: str):
        self._renderizar(AJUDA_POR_ABA.get(chave, AJUDA_INICIO))

    def _renderizar(self, texto_guia: str):
        self.texto.configure(state=tk.NORMAL)
        self.texto.delete("1.0", tk.END)

        for linha in texto_guia.splitlines():
            if linha.startswith("== ") and linha.rstrip().endswith(" =="):
                self.texto.insert(tk.END, linha.strip("= ").strip() + "\n", "titulo")
            elif linha.startswith("# "):
                self.texto.insert(tk.END, linha[2:].strip() + "\n", "secao")
            else:
                self._inserir_formatado(linha + "\n")

        self.texto.configure(state=tk.DISABLED)
        self.texto.yview_moveto(0)

    def _inserir_formatado(self, linha: str):
        """Interpreta **texto** como negrito, sem depender de marcação do Tk."""
        partes = linha.split("**")
        for indice, parte in enumerate(partes):
            if not parte:
                continue
            if indice % 2 == 1:
                self.texto.insert(tk.END, parte, "negrito")
            else:
                self.texto.insert(tk.END, parte)
