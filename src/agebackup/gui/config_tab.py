"""Aba de configuração unificada."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from agebackup import config as config_mod
from agebackup import config_paths
from agebackup.config import (
    AUTH_ADC,
    AUTH_SERVICE_ACCOUNT,
    Config,
    ConfigError,
)


class ConfigTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Configuração")
        self.status_callback = status_callback
        self.config = None
        self.vars = {}
        self._criar()
        self.carregar()

    def _criar(self):
        topo = ttk.Frame(self.frame)
        topo.pack(fill=tk.X)
        ttk.Label(topo, text="Arquivo de configuração:").pack(side=tk.LEFT)
        self.lbl_path = ttk.Label(topo, text=str(config_mod.CONFIG_FILE))
        self.lbl_path.pack(side=tk.LEFT, padx=5)
        ttk.Button(topo, text="Salvar (Ctrl+S)", command=self.salvar).pack(side=tk.RIGHT)

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
        ttk.Label(f, text="Chave Service Account (JSON):").grid(row=2, column=0, sticky=tk.W)
        self.vars["sa_key"] = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.vars["sa_key"], width=40)
        e.grid(row=2, column=1, sticky=tk.W, padx=5, pady=2)
        ttk.Button(f, text="Procurar...", command=self._procurar_sa).grid(
            row=2, column=2, padx=2
        )
        ttk.Label(f, text="Escopos (apenas leitura): https://www.googleapis.com/auth/drive.readonly").grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=4
        )

    def _procurar_sa(self):
        arq = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")]
        )
        if arq:
            self.vars["sa_key"].set(arq)

    def _criar_backup(self):
        f = self.tab_backup
        ttk.Label(f, text="Pasta de destino do backup:").grid(row=0, column=0, sticky=tk.W)
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
        ttk.Checkbutton(f, text="Incluir unidades compartilhadas", variable=self.vars["include_shared"]).grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=2
        )

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
        ttk.Label(f, text="Prefixo do nome (vazio = sem prefixo):").grid(row=1, column=0, sticky=tk.W)
        self.vars["compact_prefix"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["compact_prefix"], width=30).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Manter (0 = guardar todos):").grid(row=2, column=0, sticky=tk.W)
        self.vars["compact_manter"] = tk.StringVar(value="0")
        ttk.Spinbox(f, from_=0, to=60, textvariable=self.vars["compact_manter"], width=10).grid(
            row=2, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Full a cada N dias (0 = sempre full):").grid(row=3, column=0, sticky=tk.W)
        self.vars["full_a_cada"] = tk.StringVar(value="7")
        ttk.Spinbox(f, from_=0, to=365, textvariable=self.vars["full_a_cada"], width=10).grid(
            row=3, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Ajuda: full a cada 7 dias = full semanal, incremental nos demais.").grid(
            row=4, column=0, columnspan=3, sticky=tk.W, pady=4
        )

    def _procurar_compact(self):
        pasta = filedialog.askdirectory()
        if pasta:
            self.vars["compact_dest"].set(pasta)

    def _criar_logs(self):
        f = self.tab_logs
        self.vars["logs_enabled"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Ativar logs de falhas", variable=self.vars["logs_enabled"]).grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Label(f, text="Pasta dos logs (dentro do destino, vazio = raiz):").grid(row=1, column=0, sticky=tk.W)
        self.vars["logs_dir"] = tk.StringVar(value="logs")
        ttk.Entry(f, textvariable=self.vars["logs_dir"], width=30).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Manter logs fechados (0 = indeterminado):").grid(row=2, column=0, sticky=tk.W)
        self.vars["logs_manter"] = tk.StringVar(value="7")
        ttk.Spinbox(f, from_=0, to=365, textvariable=self.vars["logs_manter"], width=10).grid(
            row=2, column=1, sticky=tk.W, padx=5, pady=2
        )
        self.vars["logs_compress"] = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Comprimir logs antigos (.gz)", variable=self.vars["logs_compress"]).grid(
            row=3, column=0, columnspan=2, sticky=tk.W, pady=2
        )
        ttk.Label(f, text="Logs incluirão caminho completo dos arquivos.").grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=4
        )

    def _criar_envio(self):
        f = self.tab_envio
        ttk.Label(f, text="Arquivo de credenciais FTP/FTPS (.ini):").grid(row=0, column=0, sticky=tk.W)
        self.vars["ftp_ini"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["ftp_ini"], width=50).grid(
            row=0, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Button(f, text="Procurar...", command=self._procurar_ftp).grid(row=0, column=2, padx=2)
        ttk.Button(f, text="Usar padrão junto à app", command=self._ftp_padrao).grid(
            row=0, column=3, padx=2
        )
        ttk.Label(f, text="Manter no servidor FTP (0 = guardar todos):").grid(row=1, column=0, sticky=tk.W)
        self.vars["ftp_manter"] = tk.StringVar(value="7")
        ttk.Spinbox(f, from_=0, to=365, textvariable=self.vars["ftp_manter"], width=10).grid(
            row=1, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Pasta remota personalizada (variáveis):").grid(row=2, column=0, sticky=tk.W)
        self.vars["ftp_pasta"] = tk.StringVar()
        ttk.Entry(f, textvariable=self.vars["ftp_pasta"], width=50).grid(
            row=2, column=1, sticky=tk.W, padx=5, pady=2
        )
        ttk.Label(f, text="Suporta: YYYY, YY, MM, M, dd, d. Ex: /backups/YYYY/MM ou /RSKO/YYYY-MM").grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=2
        )
        ttk.Label(f, text="Se vazio, usa padrão /AAAA/MM/").grid(
            row=4, column=0, columnspan=3, sticky=tk.W
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
        self.vars["ftp_pasta"].set(getattr(cfg.envio, "pasta_remota", "") or getattr(cfg, "ftp", None).pasta_remota if getattr(cfg, "ftp", None) else "")
        if self.status_callback:
            self.status_callback(f"Configuração carregada de {config_mod.CONFIG_FILE}")

    def salvar(self):
        try:
            cfg = self.config or Config()
            cfg.account.auth_method = self.vars["auth_method"].get()
            cfg.account.email = self.vars["account_email"].get().strip()
            cfg.account.service_account_key_path = self.vars["sa_key"].get().strip()
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
                cfg.envio.manter = int(self.vars["ftp_manter"].get())
            except ValueError:
                cfg.envio.manter = 7
            pasta_ftp = self.vars.get("ftp_pasta")
            if pasta_ftp:
                cfg.envio.pasta_remota = pasta_ftp.get().strip()
                if hasattr(cfg, "ftp"):
                    cfg.ftp.pasta_remota = pasta_ftp.get().strip()
            caminho = config_mod.save(cfg)
            self.config = cfg
            messagebox.showinfo("Salvo", f"Configuração salva em:\n{caminho}")
            if self.status_callback:
                self.status_callback(f"Salvo: {caminho}")
        except ConfigError as e:
            messagebox.showerror("Erro ao salvar", str(e))
