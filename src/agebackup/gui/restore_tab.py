"""Aba de restauração (arquivo individual e total)."""

from __future__ import annotations

import os
import tarfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from agebackup.logging_paths import caminho_completo

from .utils import ThreadedRunner, centralizar_janela


class RestoreTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Restaurar")
        self.status_callback = status_callback
        self.arquivo_tar = None
        self.membros = []
        self._criar()

    def _criar(self):
        topo = ttk.LabelFrame(self.frame, text="Arquivo compactado (.tar.gz)", padding=5)
        topo.pack(fill=tk.X)
        self.lbl_arquivo = ttk.Label(topo, text="Nenhum arquivo selecionado")
        self.lbl_arquivo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(topo, text="Selecionar .tar.gz", command=self.selecionar).pack(side=tk.LEFT, padx=2)

        filtro_frame = ttk.Frame(self.frame)
        filtro_frame.pack(fill=tk.X, pady=2)
        ttk.Label(filtro_frame, text="Filtrar:").pack(side=tk.LEFT)
        self.var_filtro = tk.StringVar()
        self.var_filtro.trace("w", lambda *a: self._filtrar())
        ttk.Entry(filtro_frame, textvariable=self.var_filtro, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Label(filtro_frame, text="(arquivo individual ou total)").pack(side=tk.LEFT)

        cols = ("nome",)
        self.tree = ttk.Treeview(self.frame, columns=cols, show="headings", height=14)
        self.tree.heading("nome", text="Conteúdo do arquivo compactado")
        self.tree.column("nome", width=700)
        scroll = ttk.Scrollbar(self.frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=5)
        scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=5)

        botoes = ttk.Frame(self.frame)
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="Restaurar selecionado(s) aqui...", command=self.restaurar_aqui).pack(side=tk.LEFT)
        ttk.Button(botoes, text="Restaurar em outra pasta...", command=self.restaurar_outro).pack(side=tk.LEFT, padx=2)
        ttk.Button(botoes, text="Restaurar arquivo COMPLETO", command=self.restaurar_completo).pack(side=tk.LEFT, padx=2)

        self.lbl_info = ttk.Label(
            self.frame,
            text="Dica: se for incremental, extraia o FULL primeiro e depois os incrementais na ordem cronológica.",
        )
        self.lbl_info.pack(anchor=tk.W)

    def selecionar(self):
        arq = filedialog.askopenfilename(filetypes=[("Tar.gz", "*.tar.gz"), ("Todos", "*.*")])
        if not arq:
            return
        self.arquivo_tar = Path(arq)
        self.lbl_arquivo.config(text=f"{self.arquivo_tar.name}  |  {caminho_completo(self.arquivo_tar)}")
        self._carregar_membros()

    def _carregar_membros(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.membros = []
        if not self.arquivo_tar or not self.arquivo_tar.exists():
            return
        try:
            with tarfile.open(self.arquivo_tar, "r:gz") as tar:
                for m in tar.getmembers():
                    self.membros.append(m.name)
            self._filtrar()
        except Exception as e:
            messagebox.showerror("Erro ao ler tar.gz", str(e))

    def _filtrar(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        filtro = self.var_filtro.get().lower()
        for nome in self.membros:
            if filtro and filtro not in nome.lower():
                continue
            self.tree.insert("", tk.END, values=(nome,))

    def _selecionados(self):
        sel = self.tree.selection()
        if not sel:
            return []
        res = []
        for s in sel:
            vals = self.tree.item(s, "values")
            if vals:
                res.append(vals[0])
        return res

    def restaurar_aqui(self):
        self._restaurar(destino=".")

    def restaurar_outro(self):
        pasta = filedialog.askdirectory(title="Selecionar pasta de destino")
        if not pasta:
            return
        self._restaurar(destino=pasta)

    def restaurar_completo(self):
        pasta = filedialog.askdirectory(title="Restaurar arquivo COMPLETO neste destino")
        if not pasta:
            return
        if not self.arquivo_tar:
            messagebox.showerror("Erro", "Selecione um arquivo .tar.gz")
            return
        try:
            with tarfile.open(self.arquivo_tar, "r:gz") as tar:
                tar.extractall(path=pasta)
            messagebox.showinfo("Restaurado", f"Arquivo completo extraído para:\n{caminho_completo(pasta)}")
            if self.status_callback:
                self.status_callback("Restauração completa concluída")
        except Exception as e:
            messagebox.showerror("Erro ao restaurar", str(e))

    def _restaurar(self, destino):
        if not self.arquivo_tar:
            messagebox.showerror("Erro", "Selecione um arquivo .tar.gz")
            return
        sel = self._selecionados()
        if not sel:
            messagebox.showerror("Erro", "Selecione pelo menos um arquivo/pasta para restaurar")
            return
        dest = Path(destino)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(self.arquivo_tar, "r:gz") as tar:
                for nome in sel:
                    membro = tar.getmember(nome)
                    tar.extract(membro, path=dest)
            messagebox.showinfo(
                "Restaurado",
                f"{len(sel)} item(ns) extraído(s) para:\n{caminho_completo(dest)}",
            )
            if self.status_callback:
                self.status_callback("Restauração individual concluída")
        except Exception as e:
            messagebox.showerror("Erro ao restaurar", str(e))
