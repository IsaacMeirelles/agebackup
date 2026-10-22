"""Aba de execução do backup."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from agebackup import backup
from agebackup import config as config_mod
from agebackup.logging_paths import caminho_completo

from .utils import ThreadedRunner


class BackupTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Backup")
        self.status_callback = status_callback
        self.runner = None
        self._criar()

    def _criar(self):
        topo = ttk.Frame(self.frame)
        topo.pack(fill=tk.X)
        self.btn_iniciar = ttk.Button(topo, text="Iniciar Backup", command=self.iniciar)
        self.btn_iniciar.pack(side=tk.LEFT)
        self.btn_limpar = ttk.Button(topo, text="Limpar log", command=self.limpar)
        self.btn_limpar.pack(side=tk.LEFT, padx=5)
        ttk.Label(
            topo,
            text="Log exibe caminho completo dos arquivos",
        ).pack(side=tk.RIGHT)

        frame_log = ttk.LabelFrame(self.frame, text="Execução em tempo real", padding=5)
        frame_log.pack(fill=tk.BOTH, expand=True, pady=5)

        self.log = scrolledtext.ScrolledText(
            frame_log, wrap=tk.WORD, font=("Consolas", 9)
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.configure(state=tk.DISABLED)

        self.contadores = ttk.Label(
            self.frame, text="Baixados: 0 | Inalterados: 0 | Movidos: 0 | Falhas: 0"
        )
        self.contadores.pack(anchor=tk.W)

    def limpar(self):
        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)
        self.contadores.config(
            text="Baixados: 0 | Inalterados: 0 | Movidos: 0 | Falhas: 0"
        )

    def _log(self, msg):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"{msg}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def iniciar(self):
        cfg = config_mod.load()
        if cfg is None:
            messagebox.showerror(
                "Configuração não encontrada",
                "Configure o backup primeiro na aba Configuração.",
            )
            return
        if not cfg.backup.destination:
            messagebox.showerror(
                "Destino não definido",
                "Informe a pasta de destino na aba Configuração.",
            )
            return
        self.btn_iniciar.configure(state=tk.DISABLED)
        self.limpar()
        self._log("Iniciando backup...")
        self._log(f"Destino: {caminho_completo(cfg.backup.destination)}")
        runner = ThreadedRunner(self.frame.winfo_toplevel())
        self.runner = runner

        def _exec():
            return backup.main([])

        def _ok(r):
            self.btn_iniciar.configure(state=tk.NORMAL)
            self._log("Backup finalizado.")
            if self.status_callback:
                self.status_callback("Backup concluído")

        def _err(e):
            self.btn_iniciar.configure(state=tk.NORMAL)
            self._log(f"ERRO: {e}")
            messagebox.showerror("Erro no backup", str(e))

        runner.run(_exec, on_done=_ok, on_error=_err)
