"""Aba de compactação."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from agebackup import compactacao
from agebackup import config as config_mod
from agebackup.logging_paths import caminho_completo

from .utils import ThreadedRunner, formatar_tamanho


class CompactTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Compactação")
        self.status_callback = status_callback
        self._criar()
        self.atualizar_lista()

    def _criar(self):
        topo = ttk.Frame(self.frame)
        topo.pack(fill=tk.X)
        ttk.Button(
            topo, text="Seguir política (auto)", command=self.compactar_auto
        ).pack(side=tk.LEFT)
        ttk.Button(topo, text="Forçar FULL", command=self.forcar_full).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(topo, text="Forçar INCREMENTAL", command=self.forcar_inc).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(topo, text="Aplicar retenção", command=self.aplicar_retencao).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(topo, text="Atualizar lista", command=self.atualizar_lista).pack(
            side=tk.LEFT, padx=2
        )

        cols = ("arquivo", "tipo", "tamanho", "caminho_completo")
        self.tree = ttk.Treeview(self.frame, columns=cols, show="headings", height=12)
        self.tree.heading("arquivo", text="Arquivo")
        self.tree.heading("tipo", text="Tipo")
        self.tree.heading("tamanho", text="Tamanho")
        self.tree.heading("caminho_completo", text="Caminho completo")
        self.tree.column("arquivo", width=220)
        self.tree.column("tipo", width=80)
        self.tree.column("tamanho", width=100)
        self.tree.column("caminho_completo", width=420)
        scroll = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=5)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        self.lbl_info = ttk.Label(self.frame, text="")
        self.lbl_info.pack(anchor=tk.W)

    def atualizar_lista(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        cfg = config_mod.load()
        if not cfg:
            self.lbl_info.config(text="Sem configuração")
            return
        destino_backup = Path(cfg.backup.destination).expanduser()
        pasta = cfg.compactacao.pasta(destino_backup)
        if not pasta.exists():
            self.lbl_info.config(text=f"Pasta não existe: {caminho_completo(pasta)}")
            return
        arquivos = sorted(
            pasta.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for arq in arquivos:
            tipo = "INCREMENTAL" if "_inc_" in arq.name else "FULL"
            try:
                tam = formatar_tamanho(arq.stat().st_size)
            except OSError:
                tam = "-"
            self.tree.insert(
                "", tk.END, values=(arq.name, tipo, tam, caminho_completo(arq))
            )
        self.lbl_info.config(
            text=f"{len(arquivos)} arquivo(s) compactado(s) em {caminho_completo(pasta)}"
        )

    def _rodar(self, args):
        runner = ThreadedRunner(self.frame.winfo_toplevel())

        def _exec():
            return compactacao.main(args)

        def _ok(r):
            self.atualizar_lista()
            if self.status_callback:
                self.status_callback("Compactação concluída")
            messagebox.showinfo("Compactação", "Compactação finalizada.")

        def _err(e):
            messagebox.showerror("Erro na compactação", str(e))

        runner.run(_exec, on_done=_ok, on_error=_err)

    def compactar_auto(self):
        self._rodar([])

    def forcar_full(self):
        self._rodar(["--full"])

    def forcar_inc(self):
        self._rodar(["--incremental"])

    def aplicar_retencao(self):
        cfg = config_mod.load()
        if not cfg:
            return
        destino_backup = Path(cfg.backup.destination).expanduser()
        pasta = cfg.compactacao.pasta(destino_backup)
        nome_base = destino_backup.name
        prefixo = cfg.compactacao.prefixo
        if prefixo:
            base = f"{nome_base}_{prefixo}"
        else:
            base = nome_base
        removidos = compactacao._aplicar_retencao(pasta, base, cfg.compactacao.manter)
        if removidos:
            messagebox.showinfo(
                "Retenção aplicada", f"{len(removidos)} arquivo(s) removido(s)."
            )
        else:
            messagebox.showinfo(
                "Retenção", "Nenhum arquivo removido (manter=0 ou dentro do limite)."
            )
        self.atualizar_lista()
