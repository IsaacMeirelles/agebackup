"""Aplicação GUI única do AgeBackup."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from agebackup import config as config_mod
from agebackup import config_paths

from .backup_tab import BackupTab
from .compact_tab import CompactTab
from .config_tab import ConfigTab
from .help_dialog import HelpDialog
from .log_tab import LogTab
from .restore_tab import RestoreTab
from .upload_tab import UploadTab


class AgeBackupApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AgeBackup")
        self.root.geometry("980x680")
        self.root.minsize(880, 620)

        # Migração automática para config junto à app
        try:
            config_paths.migrar_se_necessario()
        except OSError:
            pass

        topo = ttk.Frame(root)
        topo.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(topo, text="AgeBackup - Painel Único").pack(side=tk.LEFT)
        ttk.Label(topo, text="F1: Ajuda").pack(side=tk.RIGHT)
        ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X)

        self.status_var = tk.StringVar(value="Pronto")
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self.status_bar = ttk.Label(
            root, textvariable=self.status_var, anchor=tk.W, relief=tk.SUNKEN
        )
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # Abas
        self.tab_inicio = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_inicio, text="Início/Status")
        self._criar_inicio()

        self.config_tab = ConfigTab(self.notebook, self.set_status)
        self.backup_tab = BackupTab(self.notebook, self.set_status)
        self.compact_tab = CompactTab(self.notebook, self.set_status)
        self.upload_tab = UploadTab(self.notebook, self.set_status)
        self.restore_tab = RestoreTab(self.notebook, self.set_status)
        self.log_tab = LogTab(self.notebook, self.set_status)

        # Ajuda
        ttk.Button(
            self.tab_inicio,
            text="Abrir Ajuda (F1)",
            command=self.abrir_ajuda,
        ).pack(anchor=tk.W, pady=2)

        self.root.bind("<F1>", lambda e: self.abrir_ajuda())
        self.root.bind("<Control-s>", lambda e: self._salvar_config())
        self.root.bind("<Control-q>", lambda e: self.root.quit())

        self.atualizar_status()

    def set_status(self, msg):
        self.status_var.set(msg)
        self.root.update_idletasks()

    def _criar_inicio(self):
        frame = ttk.LabelFrame(self.tab_inicio, text="Status Geral", padding=10)
        frame.pack(fill=tk.X)
        self.lbl_status = ttk.Label(frame, text="Carregando...")
        self.lbl_status.pack(anchor=tk.W)
        botoes = ttk.Frame(self.tab_inicio)
        botoes.pack(fill=tk.X, pady=10)
        ttk.Button(
            botoes, text="Ir para Backup", command=lambda: self.notebook.select(2)
        ).pack(side=tk.LEFT)
        ttk.Button(
            botoes, text="Ir para Compactação", command=lambda: self.notebook.select(3)
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            botoes,
            text="Ir para Upload Manual",
            command=lambda: self.notebook.select(4),
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            botoes, text="Ir para Restaurar", command=lambda: self.notebook.select(5)
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            botoes, text="Ir para Log", command=lambda: self.notebook.select(6)
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(botoes, text="Atualizar status", command=self.atualizar_status).pack(
            side=tk.RIGHT
        )

    def atualizar_status(self):
        try:
            cfg = config_mod.load()
        except config_mod.ConfigError, OSError:
            cfg = None
        if not cfg:
            self.lbl_status.config(
                text="Configuração não encontrada. Vá em Configuração e salve primeiro.\n"
                f"Arquivo: {config_mod.CONFIG_FILE}"
            )
            self.set_status("Sem configuração")
            return
        texto = []
        texto.append(f"Configuração: {config_mod.CONFIG_FILE}")
        texto.append(f"Conta: {cfg.account.email or cfg.account.auth_method}")
        texto.append(f"Destino backup: {cfg.backup.destination or '(não definido)'}")
        texto.append(f"Pasta Drive: {cfg.backup.folder_id or '(todo Drive)'}")
        texto.append(
            f"Compactação: full {cfg.compactacao.texto_full_a_cada()}, prefixo='{cfg.compactacao.prefixo or ''}'"
        )
        texto.append(
            f"Logs: manter={cfg.logs.keep_logs}, comprimir={cfg.logs.compress}"
        )
        texto.append(f"Envio FTP: credenciais={cfg.envio.credenciais or '(padrão)'}")
        self.lbl_status.config(text="\n".join(texto))
        self.set_status("Status atualizado")

    def _salvar_config(self):
        try:
            self.config_tab.salvar()
        except config_mod.ConfigError, OSError:
            pass

    def abrir_ajuda(self):
        HelpDialog(self.root)


def main():
    root = tk.Tk()
    AgeBackupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
