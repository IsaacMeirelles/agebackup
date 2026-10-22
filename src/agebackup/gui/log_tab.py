"""Aba de visualização de logs com caminho completo."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from agebackup import config as config_mod
from agebackup.logging_paths import caminho_completo


class LogTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Log")
        self.status_callback = status_callback
        self._criar()

    def _criar(self):
        topo = ttk.Frame(self.frame)
        topo.pack(fill=tk.X)
        ttk.Button(topo, text="Carregar agebackup-atualizar.log", command=self.carregar_atualizar).pack(
            side=tk.LEFT
        )
        ttk.Button(topo, text="Carregar .agebackup-falhas.log", command=self.carregar_falhas).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(topo, text="Abrir arquivo...", command=self.abrir_arquivo).pack(side=tk.LEFT, padx=2)
        ttk.Button(topo, text="Copiar seleção", command=self.copiar).pack(side=tk.LEFT, padx=2)
        ttk.Button(topo, text="Limpar", command=self.limpar).pack(side=tk.LEFT, padx=2)
        ttk.Label(topo, text="Filtro:").pack(side=tk.LEFT, padx=(10, 2))
        self.var_filtro = tk.StringVar()
        self.var_filtro.trace("w", lambda *a: self._aplicar_filtro())
        ttk.Entry(topo, textvariable=self.var_filtro, width=30).pack(side=tk.LEFT)
        ttk.Label(topo, text="(caminho completo exibido)").pack(side=tk.RIGHT)

        self.texto = scrolledtext.ScrolledText(self.frame, wrap=tk.WORD, font=("Consolas", 9))
        self.texto.pack(fill=tk.BOTH, expand=True, pady=5)
        self.conteudo_completo = ""
        self.lbl = ttk.Label(self.frame, text="")
        self.lbl.pack(anchor=tk.W)

    def limpar(self):
        self.texto.delete("1.0", tk.END)
        self.conteudo_completo = ""
        self.lbl.config(text="")

    def _carregar(self, caminho: Path):
        if not caminho.exists():
            messagebox.showwarning("Arquivo não encontrado", f"Não encontrado:\n{caminho_completo(caminho)}")
            return
        try:
            dados = caminho.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            messagebox.showerror("Erro ao ler", str(e))
            return
        self.conteudo_completo = dados
        self.var_filtro.set("")
        self.texto.delete("1.0", tk.END)
        self.texto.insert(tk.END, dados)
        self.lbl.config(text=f"Arquivo: {caminho_completo(caminho)} | Linhas: {dados.count(chr(10))+1}")
        if self.status_callback:
            self.status_callback(f"Log carregado: {caminho.name}")

    def carregar_atualizar(self):
        self._carregar(Path.home() / "agebackup-atualizar.log")

    def carregar_falhas(self):
        cfg = config_mod.load()
        if cfg:
            destino_backup = Path(cfg.backup.destination).expanduser()
            pasta_logs = cfg.logs.pasta(destino_backup)
            self._carregar(pasta_logs / ".agebackup-falhas.log")
        else:
            self._carregar(Path.home() / ".agebackup-falhas.log")

    def abrir_arquivo(self):
        arq = filedialog.askopenfilename(filetypes=[("Log", "*.log"), ("GZ", "*.gz"), ("Todos", "*.*")])
        if arq:
            self._carregar(Path(arq))

    def copiar(self):
        try:
            sel = self.texto.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.texto.clipboard_clear()
            self.texto.clipboard_append(sel)
            if self.status_callback:
                self.status_callback("Seleção copiada")
        except tk.TclError:
            pass

    def _aplicar_filtro(self):
        if not self.conteudo_completo:
            return
        filtro = self.var_filtro.get().lower()
        linhas = self.conteudo_completo.splitlines(True)
        if not filtro:
            self.texto.delete("1.0", tk.END)
            self.texto.insert(tk.END, self.conteudo_completo)
            return
        filtradas = [l for l in linhas if filtro in l.lower()]
        self.texto.delete("1.0", tk.END)
        self.texto.insert(tk.END, "".join(filtradas))
        self.lbl.config(text=f"Filtrado: {len(filtradas)}/{len(linhas)} linha(s) | contém '{filtro}'")
