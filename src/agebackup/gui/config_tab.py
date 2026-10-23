"""Aba de configuração unificada."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from agebackup import config as config_mod
from agebackup import config_paths, crypto_ftp, ftp, ftp_import
from agebackup.config import (
    AUTH_ADC,
    AUTH_SERVICE_ACCOUNT,
    Config,
    ConfigError,
    FtpConfig,
)


class ConfigTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Configuração")
        self.status_callback = status_callback
        self.config = None
        self.vars = {}
        self._adc_json = ""
        self._criar()
        self.carregar()

    def _criar(self):
        topo = ttk.Frame(self.frame)
        topo.pack(fill=tk.X)
        ttk.Label(topo, text="Arquivo de configuração:").pack(side=tk.LEFT)
        self.lbl_path = ttk.Label(topo, text=str(config_mod.CONFIG_FILE))
        self.lbl_path.pack(side=tk.LEFT, padx=5)
        ttk.Button(topo, text="Salvar (Ctrl+S)", command=self.salvar).pack(
            side=tk.RIGHT
        )

        self.sub = ttk.Notebook(self.frame)
        self.sub.pack(fill=tk.BOTH, expand=True, pady=5)

        self.tab_conta = ttk.Frame(self.sub, padding=10)
        self.tab_backup = ttk.Frame(self.sub, padding=10)
        self.tab_compact = ttk.Frame(self.sub, padding=10)
        self.tab_logs = ttk.Frame(self.sub, padding=10)
        self.tab_envio = ttk.Frame(self.sub, padding=10)

        self.sub.add(self.tab_conta, text="Conta")
        self.sub.add(self.tab_backup, text="Backup (Google Drive)")
        self.sub.add(self.tab_compact, text="Compactação")
        self.sub.add(self.tab_logs, text="Logs")
        self.sub.add(self.tab_envio, text="Envio (FTP/FTPS)")

        self._criar_conta()
        self._criar_backup()
        self._criar_compact()
        self._criar_logs()
        self._criar_envio()

    def _criar_conta(self):
        f = self.tab_conta
        self.vars["auth_method"] = tk.StringVar(value=AUTH_ADC)
        ttk.Label(f, text="Método de autenticação:").grid(row=0, column=0, sticky=tk.W)
        cb = ttk.Combobox(
            f,
            textvariable=self.vars["auth_method"],
            values=[AUTH_ADC, AUTH_SERVICE_ACCOUNT],
            state="readonly",
        )
        cb.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(f, text="E-mail:").grid(row=1, column=0, sticky=tk.W)
        self.vars["account_email"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["account_email"], width=40).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Chave Service Account (JSON):").grid(
            row=2, column=0, sticky=tk.W
        )
        self.vars["sa_key"] = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.vars["sa_key"], width=40)
        e.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Button(
            f,
            text="Importar JSON...",
            command=self._procurar_sa,
        ).grid(row=2, column=2, padx=2)
        self.lbl_sa_status = ttk.Label(f, text="", foreground="#555")
        self.lbl_sa_status.grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(0, 4))
        self.lbl_adc_status = ttk.Label(f, text="", foreground="#555")
        self.lbl_adc_status.grid(row=4, column=0, columnspan=2, sticky=tk.W)
        ttk.Button(
            f,
            text="Importar ADC do gcloud",
            command=self._importar_adc,
        ).grid(row=4, column=2, padx=2)
        ttk.Label(
            f,
            text=(
                "As credenciais importadas são gravadas cifradas no "
                "agebackup.json; os arquivos externos deixam de ser necessários."
            ),
        ).grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(4, 2))
        ttk.Label(
            f,
            text="Escopos (apenas leitura): https://www.googleapis.com/auth/drive.readonly",
        ).grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=4)

    def _atualizar_status_credenciais(self):
        """Mostra o que está embutido no JSON e o que ainda é externo."""
        cfg = self.config
        conta = cfg.account if cfg is not None else None
        if conta is None:
            self.lbl_sa_status.config(text="")
            self.lbl_adc_status.config(text="")
            return

        if conta.service_account_json_criptografado:
            texto_sa = "Service Account: JSON salvo e cifrado no agebackup.json."
        elif self.vars["sa_key"].get().strip():
            texto_sa = (
                "Service Account: o arquivo indicado será importado e cifrado "
                "ao clicar em Salvar."
            )
        else:
            texto_sa = "Service Account: nenhuma credencial salva."
        self.lbl_sa_status.config(text=texto_sa)

        if self._adc_json:
            texto_adc = (
                "ADC: credencial importada; será gravada cifrada ao clicar em "
                "Salvar."
            )
        elif conta.adc_json_criptografado:
            texto_adc = "ADC: credencial salva e cifrada no agebackup.json."
        elif config_mod.ADC_FILE.exists():
            texto_adc = (
                "ADC: credencial externa encontrada; ao salvar, será copiada "
                "cifrada para o agebackup.json."
            )
        else:
            texto_adc = "ADC: nenhuma credencial interna ou externa encontrada."
        self.lbl_adc_status.config(text=texto_adc)

    def _procurar_sa(self):
        arq = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")]
        )
        if not arq:
            return
        try:
            dados = json.loads(Path(arq).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("Credencial inválida", str(e))
            return
        if not isinstance(dados, dict) or dados.get("type") != "service_account":
            messagebox.showerror(
                "Credencial inválida",
                "O arquivo selecionado não é uma chave de Service Account.",
            )
            return
        self.vars["sa_key"].set(arq)
        if not self.vars["account_email"].get().strip():
            self.vars["account_email"].set(dados.get("client_email", ""))
        self._atualizar_status_credenciais()

    def _importar_adc(self):
        if not config_mod.ADC_FILE.exists():
            messagebox.showerror(
                "ADC não encontrado",
                "Não há credencial ADC do gcloud. Faça o login com:\n\n"
                "gcloud auth application-default login",
            )
            return
        try:
            texto = config_mod.ADC_FILE.read_text(encoding="utf-8")
            dados = json.loads(texto)
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("Credencial ADC inválida", str(e))
            return
        if not isinstance(dados, dict) or not (
            dados.get("type") == "authorized_user" or dados.get("refresh_token")
        ):
            messagebox.showerror(
                "Credencial ADC inválida",
                "O arquivo ADC não contém um token de usuário (authorized_user).",
            )
            return
        self._adc_json = texto
        self.vars["auth_method"].set(AUTH_ADC)
        if not self.vars["account_email"].get().strip():
            self.vars["account_email"].set(
                dados.get("account") or dados.get("email") or ""
            )
        self._atualizar_status_credenciais()

    def _criar_backup(self):
        f = self.tab_backup
        ttk.Label(f, text="Pasta de destino do backup:").grid(
            row=0, column=0, sticky=tk.W
        )
        self.vars["backup_dest"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["backup_dest"], width=50).grid(
            row=0, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Button(f, text="Procurar...", command=self._procurar_dest).grid(
            row=0, column=2, padx=2
        )
        ttk.Label(f, text="ID da pasta no Google Drive (vazio = todo Drive):").grid(
            row=1, column=0, sticky=tk.W
        )
        self.vars["folder_id"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["folder_id"], width=50).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        self.vars["include_shared"] = tk.BooleanVar()
        ttk.Checkbutton(
            f,
            text="Incluir unidades compartilhadas",
            variable=self.vars["include_shared"],
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)

    def _procurar_dest(self):
        pasta = filedialog.askdirectory()
        if pasta:
            self.vars["backup_dest"].set(pasta)

    def _criar_compact(self):
        f = self.tab_compact
        ttk.Label(f, text="Pasta dos arquivos compactados (.tar.gz):").grid(
            row=0, column=0, sticky=tk.W
        )
        self.vars["compact_dest"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["compact_dest"], width=50).grid(
            row=0, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Button(f, text="Procurar...", command=self._procurar_compact).grid(
            row=0, column=2, padx=2
        )
        ttk.Label(f, text="Prefixo do nome (vazio = sem prefixo):").grid(
            row=1, column=0, sticky=tk.W
        )
        self.vars["compact_prefix"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["compact_prefix"], width=30).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Manter (0 = guardar todos):").grid(
            row=2, column=0, sticky=tk.W
        )
        self.vars["compact_manter"] = tk.StringVar(value="0")
        ttk.Spinbox(
            f, from_=0, to=60, textvariable=self.vars["compact_manter"], width=10
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(f, text="Full a cada N dias (0 = sempre full):").grid(
            row=3, column=0, sticky=tk.W
        )
        self.vars["full_a_cada"] = tk.StringVar(value="7")
        ttk.Spinbox(
            f, from_=0, to=365, textvariable=self.vars["full_a_cada"], width=10
        ).grid(row=3, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Label(
            f, text="Ajuda: full a cada 7 dias = full semanal, incremental nos demais."
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=4)

    def _procurar_compact(self):
        pasta = filedialog.askdirectory()
        if pasta:
            self.vars["compact_dest"].set(pasta)

    def _criar_logs(self):
        f = self.tab_logs
        self.vars["logs_enabled"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f, text="Ativar logs de falhas", variable=self.vars["logs_enabled"]
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(f, text="Pasta dos logs (dentro do destino, vazio = raiz):").grid(
            row=1, column=0, sticky=tk.W
        )
        self.vars["logs_dir"] = tk.StringVar(value="logs")
        ttk.Entry(f, textvariable=self.vars["logs_dir"], width=30).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Manter logs fechados (0 = indeterminado):").grid(
            row=2, column=0, sticky=tk.W
        )
        self.vars["logs_manter"] = tk.StringVar(value="7")
        ttk.Spinbox(
            f, from_=0, to=365, textvariable=self.vars["logs_manter"], width=10
        ).grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        self.vars["logs_compress"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f, text="Comprimir logs antigos (.gz)", variable=self.vars["logs_compress"]
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=2)
        ttk.Label(f, text="Logs incluirão caminho completo dos arquivos.").grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=4
        )

    def _criar_envio(self):
        f = self.tab_envio

        cred = ttk.LabelFrame(
            f,
            text="Credenciais FTP/FTPS (salvas no agebackup.json)",
            padding=8,
        )
        cred.pack(fill=tk.X)

        ttk.Label(cred, text="Host:").grid(row=0, column=0, sticky=tk.W)
        self.vars["ftp_host"] = tk.StringVar()
        ttk.Entry(cred, textvariable=self.vars["ftp_host"], width=34).grid(
            row=0, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(cred, text="Porta:").grid(row=0, column=2, sticky=tk.W)
        self.vars["ftp_porta"] = tk.StringVar(value="21")
        ttk.Entry(cred, textvariable=self.vars["ftp_porta"], width=7).grid(
            row=0, column=3, sticky=tk.W, padx=5, pady=2
        )
        self.vars["ftp_tls"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(cred, text="TLS/FTPS", variable=self.vars["ftp_tls"]).grid(
            row=0, column=4, sticky=tk.W, padx=5, pady=2
        )

        ttk.Label(cred, text="Usuário:").grid(row=1, column=0, sticky=tk.W)
        self.vars["ftp_usuario"] = tk.StringVar()
        ttk.Entry(cred, textvariable=self.vars["ftp_usuario"], width=34).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(cred, text="Senha:").grid(row=1, column=2, sticky=tk.W)
        self.vars["ftp_senha"] = tk.StringVar()
        self.ent_senha = ttk.Entry(
            cred, textvariable=self.vars["ftp_senha"], width=20, show="*"
        )
        self.ent_senha.grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
        self.vars["ftp_mostrar_senha"] = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cred,
            text="Mostrar",
            variable=self.vars["ftp_mostrar_senha"],
            command=self._alternar_senha,
        ).grid(row=1, column=4, sticky=tk.W, padx=5, pady=2)

        self.lbl_senha_status = ttk.Label(cred, text="", foreground="#555")
        self.lbl_senha_status.grid(
            row=2, column=0, columnspan=5, sticky=tk.W, pady=(0, 4)
        )

        ttk.Label(cred, text="Pasta remota personalizada:").grid(
            row=3, column=0, sticky=tk.W
        )
        self.vars["ftp_pasta"] = tk.StringVar()
        ttk.Entry(cred, textvariable=self.vars["ftp_pasta"], width=50).grid(
            row=3, column=1, columnspan=4, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(
            cred,
            text=(
                "Suporta YYYY, YY, MM, M, dd, d. Ex.: /backups/YYYY/MM ou "
                "/RSKO/YYYY-MM. Vazio usa /AAAA/MM/."
            ),
        ).grid(row=4, column=0, columnspan=5, sticky=tk.W, pady=(0, 4))

        botoes = ttk.Frame(cred)
        botoes.grid(row=5, column=0, columnspan=5, sticky=tk.W, pady=(4, 0))
        ttk.Button(
            botoes,
            text="Importar credenciais do .ini...",
            command=self._importar_ftp,
        ).pack(side=tk.LEFT)
        ttk.Button(
            botoes,
            text="Importar ftp.ini padrão",
            command=self._importar_ftp_padrao,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            botoes,
            text="Limpar credenciais salvas",
            command=self._limpar_credenciais_ftp,
        ).pack(side=tk.LEFT, padx=2)

        opcoes = ttk.LabelFrame(f, text="Opções de envio", padding=8)
        opcoes.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(opcoes, text="Manter no servidor FTP (0 = guardar todos):").grid(
            row=0, column=0, sticky=tk.W
        )
        self.vars["ftp_manter"] = tk.StringVar(value="7")
        ttk.Spinbox(
            opcoes, from_=0, to=365, textvariable=self.vars["ftp_manter"], width=10
        ).grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)

        ttk.Label(opcoes, text="Arquivo .ini legado (opcional):").grid(
            row=1, column=0, sticky=tk.W
        )
        self.vars["ftp_ini"] = tk.StringVar()
        ttk.Entry(opcoes, textvariable=self.vars["ftp_ini"], width=50).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Button(opcoes, text="Procurar...", command=self._procurar_ftp).grid(
            row=1, column=2, padx=2
        )
        ttk.Button(
            opcoes, text="Usar padrão junto à app", command=self._ftp_padrao
        ).grid(row=1, column=3, padx=2)
        ttk.Label(
            opcoes,
            text=(
                "O arquivo .ini só é usado quando host/usuário estão vazios. "
                "Com as credenciais preenchidas acima, tudo fica no agebackup.json."
            ),
        ).grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(4, 0))

    def _alternar_senha(self):
        self.ent_senha.config(show="" if self.vars["ftp_mostrar_senha"].get() else "*")

    def _atualizar_status_senha(self):
        """Mostra se já existe senha cifrada, sem exibi-la de volta."""
        cfg = self.config
        valor = getattr(getattr(cfg, "ftp", None), "senha_criptografada", "")
        if valor:
            texto = (
                "Senha já salva e criptografada. Deixe o campo em branco para "
                "manter; digite outra para substituir."
            )
        else:
            texto = "Nenhuma senha salva. Preencha o campo acima para cadastrar."
        self.lbl_senha_status.config(text=texto)

    def _preencher_credenciais_ftp(self, cred, origem: str) -> None:
        self.vars["ftp_host"].set(cred.host)
        self.vars["ftp_porta"].set(str(cred.porta or 21))
        self.vars["ftp_usuario"].set(cred.usuario)
        self.vars["ftp_senha"].set(cred.senha)
        self.vars["ftp_pasta"].set(cred.pasta)
        self.vars["ftp_tls"].set(bool(cred.tls))
        self.lbl_senha_status.config(
            text=(
                f"Credenciais carregadas de {origem}. Clique em Salvar para "
                "gravar tudo cifrado no agebackup.json."
            )
        )

    def _importar_ftp(self):
        arq = filedialog.askopenfilename(filetypes=[("INI", "*.ini"), ("Todos", "*.*")])
        if not arq:
            return
        try:
            cred = ftp.ler_credenciais(Path(arq))
        except (OSError, ValueError) as e:
            messagebox.showerror("Erro ao importar credenciais", str(e))
            return
        self._preencher_credenciais_ftp(cred, arq)

    def _importar_ftp_padrao(self):
        caminho = config_paths.get_ftp_ini_path_default()
        try:
            cred = ftp.ler_credenciais(caminho)
        except (OSError, ValueError) as e:
            messagebox.showerror(
                "Erro ao importar credenciais",
                f"{e}\n\nCaminho procurado: {caminho}",
            )
            return
        self._preencher_credenciais_ftp(cred, str(caminho))

    def _limpar_credenciais_ftp(self):
        if not messagebox.askyesno(
            "Limpar credenciais",
            "Apagar host, usuário, senha e pasta remota salvos no agebackup.json?\n"
            "O arquivo .ini (se configurado) voltará a ser usado.",
        ):
            return
        self.vars["ftp_host"].set("")
        self.vars["ftp_porta"].set("21")
        self.vars["ftp_usuario"].set("")
        self.vars["ftp_senha"].set("")
        self.vars["ftp_pasta"].set("")
        self.vars["ftp_tls"].set(True)
        if self.config is not None:
            self.config.ftp = FtpConfig()
        self.lbl_senha_status.config(
            text="Credenciais serão removidas ao clicar em Salvar."
        )

    def _procurar_ftp(self):
        arq = filedialog.askopenfilename(filetypes=[("INI", "*.ini"), ("Todos", "*.*")])
        if arq:
            self.vars["ftp_ini"].set(arq)

    def _ftp_padrao(self):
        self.vars["ftp_ini"].set(str(config_paths.get_ftp_ini_path_default()))

    def carregar(self):
        try:
            config_paths.migrar_se_necessario()
            cfg = config_mod.load()
        except ConfigError as e:
            messagebox.showerror("Erro ao carregar configuração", str(e))
            cfg = Config()
        if cfg is None:
            cfg = Config()
        self.config = cfg
        self._adc_json = ""
        self.lbl_path.config(text=str(config_mod.CONFIG_FILE))
        self.vars["auth_method"].set(cfg.account.auth_method)
        self.vars["account_email"].set(cfg.account.email)
        self.vars["sa_key"].set(cfg.account.service_account_key_path)
        self.vars["backup_dest"].set(cfg.backup.destination)
        self.vars["folder_id"].set(cfg.backup.folder_id)
        self.vars["include_shared"].set(cfg.backup.include_shared_drives)
        self.vars["compact_dest"].set(cfg.compactacao.destino)
        self.vars["compact_prefix"].set(cfg.compactacao.prefixo)
        self.vars["compact_manter"].set(str(cfg.compactacao.manter))
        self.vars["full_a_cada"].set(str(cfg.compactacao.full_a_cada))
        self.vars["logs_enabled"].set(cfg.logs.enabled)
        self.vars["logs_dir"].set(cfg.logs.directory)
        self.vars["logs_manter"].set(str(cfg.logs.keep_logs))
        self.vars["logs_compress"].set(cfg.logs.compress)
        self.vars["ftp_ini"].set(cfg.envio.credenciais)
        self.vars["ftp_manter"].set(str(cfg.envio.manter))
        ftp_cfg = cfg.ftp or FtpConfig()
        self.vars["ftp_host"].set(ftp_cfg.host)
        self.vars["ftp_porta"].set(str(ftp_cfg.porta or 21))
        self.vars["ftp_usuario"].set(ftp_cfg.usuario)
        self.vars["ftp_senha"].set("")
        self.vars["ftp_tls"].set(bool(ftp_cfg.tls))
        self.vars["ftp_pasta"].set(cfg.envio.pasta_remota or ftp_cfg.pasta_remota or "")
        self._atualizar_status_senha()
        self._atualizar_status_credenciais()
        if self.status_callback:
            self.status_callback(f"Configuração carregada de {config_mod.CONFIG_FILE}")

    def _preparar_credenciais_google(self, cfg):
        """Cifra no JSON as credenciais Google indicadas/importadas."""
        metodo = self.vars["auth_method"].get()
        caminho_sa = self.vars["sa_key"].get().strip()
        cfg.account.auth_method = metodo
        cfg.account.email = self.vars["account_email"].get().strip()

        if metodo == AUTH_SERVICE_ACCOUNT and caminho_sa:
            arquivo = Path(caminho_sa).expanduser()
            if not arquivo.exists():
                raise ConfigError(f"Chave de Service Account não encontrada: {arquivo}")
            try:
                texto = arquivo.read_text(encoding="utf-8")
                dados = json.loads(texto)
            except (OSError, json.JSONDecodeError) as e:
                raise ConfigError(
                    f"Não foi possível ler a chave de Service Account: {e}"
                ) from e
            if not isinstance(dados, dict) or dados.get("type") != "service_account":
                raise ConfigError(
                    "O arquivo indicado não é uma chave de Service Account válida."
                )
            cfg.account.service_account_json_criptografado = crypto_ftp.criptografar(
                texto
            )
            cfg.account.service_account_key_path = ""
            if not cfg.account.email:
                cfg.account.email = dados.get("client_email", "")
        elif caminho_sa:
            # Mantém compatibilidade com quem prefere apontar um arquivo externo
            # enquanto usa outro método de autenticação.
            cfg.account.service_account_key_path = caminho_sa
        else:
            cfg.account.service_account_key_path = ""

        if self._adc_json:
            cfg.account.adc_json_criptografado = crypto_ftp.criptografar(self._adc_json)
        elif metodo == AUTH_ADC and not cfg.account.adc_json_criptografado:
            # Ao salvar no modo ADC, leva também a credencial externa do gcloud
            # para o JSON, evitando depender do HOME no próximo servidor.
            try:
                texto_adc = config_mod.ADC_FILE.read_text(encoding="utf-8")
                dados_adc = json.loads(texto_adc)
            except OSError, json.JSONDecodeError:
                dados_adc = {}
            if isinstance(dados_adc, dict) and (
                dados_adc.get("type") == "authorized_user"
                or dados_adc.get("refresh_token")
            ):
                cfg.account.adc_json_criptografado = crypto_ftp.criptografar(texto_adc)

    def salvar(self):
        try:
            cfg = self.config or Config()
            self._preparar_credenciais_google(cfg)
            cfg.backup.destination = self.vars["backup_dest"].get().strip()
            cfg.backup.folder_id = self.vars["folder_id"].get().strip()
            cfg.backup.include_shared_drives = bool(self.vars["include_shared"].get())
            cfg.compactacao.destino = self.vars["compact_dest"].get().strip()
            cfg.compactacao.prefixo = self.vars["compact_prefix"].get().strip()
            try:
                cfg.compactacao.manter = int(self.vars["compact_manter"].get())
            except ValueError:
                cfg.compactacao.manter = 0
            try:
                cfg.compactacao.full_a_cada = int(self.vars["full_a_cada"].get())
            except ValueError:
                cfg.compactacao.full_a_cada = 7
            cfg.logs.enabled = bool(self.vars["logs_enabled"].get())
            cfg.logs.directory = self.vars["logs_dir"].get().strip()
            try:
                cfg.logs.keep_logs = int(self.vars["logs_manter"].get())
            except ValueError:
                cfg.logs.keep_logs = 7
            cfg.logs.compress = bool(self.vars["logs_compress"].get())
            cfg.envio.credenciais = self.vars["ftp_ini"].get().strip()
            try:
                manter = int(self.vars["ftp_manter"].get())
            except ValueError:
                manter = 7
            ftp_import.aplicar_credenciais(
                cfg,
                host=self.vars["ftp_host"].get(),
                porta=self.vars["ftp_porta"].get(),
                usuario=self.vars["ftp_usuario"].get(),
                senha=self.vars["ftp_senha"].get(),
                pasta=self.vars["ftp_pasta"].get(),
                tls=bool(self.vars["ftp_tls"].get()),
                manter=manter,
            )
            caminho = config_mod.save(cfg)
            self.config = cfg
            self.vars["sa_key"].set(cfg.account.service_account_key_path)
            self._adc_json = ""
            self._atualizar_status_credenciais()
            self.vars["ftp_ini"].set(cfg.envio.credenciais)
            self.vars["ftp_senha"].set("")
            self.vars["ftp_mostrar_senha"].set(False)
            self.ent_senha.config(show="*")
            self._atualizar_status_senha()
            messagebox.showinfo("Salvo", f"Configuração salva em:\n{caminho}")
            if self.status_callback:
                self.status_callback(f"Salvo: {caminho}")
        except (ConfigError, ValueError) as e:
            messagebox.showerror("Erro ao salvar", str(e))
