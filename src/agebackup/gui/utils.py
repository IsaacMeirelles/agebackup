"""Utilitários compartilhados pela GUI."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk


class ThreadedRunner:
    """Executa função em thread sem travar a interface."""

    def __init__(self, root: tk.Tk):
        self.root = root

    def run(self, func, *args, on_done=None, on_error=None, **kwargs):
        def _wrap():
            try:
                resultado = func(*args, **kwargs)
                if on_done:
                    self.root.after(0, lambda r=resultado: on_done(r))
            except Exception as exc:
                if on_error:
                    self.root.after(0, lambda e=exc: on_error(e))
                else:
                    self.root.after(0, lambda e=exc: messagebox.showerror("Erro", str(e)))

        thread = threading.Thread(target=_wrap, daemon=True)
        thread.start()
        return thread


def escolher_arquivo(parent, title="Selecionar arquivo", **kwargs):
    from tkinter import filedialog

    return filedialog.askopenfilename(parent=parent, title=title, **kwargs)


def escolher_pasta(parent, title="Selecionar pasta"):
    from tkinter import filedialog

    return filedialog.askdirectory(parent=parent, title=title)


def escolher_salvar(parent, title="Salvar como", **kwargs):
    from tkinter import filedialog

    return filedialog.asksaveasfilename(parent=parent, title=title, **kwargs)


def formatar_tamanho(tamanho_bytes: int) -> str:
    if tamanho_bytes <= 0:
        return "0 B"
    unidades = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    valor = float(tamanho_bytes)
    while valor >= 1024 and i < len(unidades) - 1:
        valor /= 1024.0
        i += 1
    if i == 0:
        return f"{int(valor)} {unidades[i]}"
    return f"{valor:.1f} {unidades[i]}"


def centralizar_janela(janela: tk.Toplevel, largura: int = 700, altura: int = 500):
    janela.update_idletasks()
    x = (janela.winfo_screenwidth() // 2) - (largura // 2)
    y = (janela.winfo_screenheight() // 2) - (altura // 2)
    janela.geometry(f"{largura}x{altura}+{x}+{y}")
