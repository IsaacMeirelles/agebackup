"""Utilitários compartilhados pela GUI."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox

# Intervalo (ms) com que a thread principal verifica a fila de resultados.
INTERVALO_POLL = 150


class ThreadedRunner:
    """Executa uma função em segundo plano sem travar a interface.

    Tkinter **não é thread-safe**: chamar `after`, widgets ou `messagebox` de
    dentro de uma thread de trabalho pode travar o interpretador Tcl. Por isso a
    thread apenas deposita o resultado numa fila, e a thread principal a
    consulta periodicamente com `after`.
    """

    def __init__(self, root: tk.Misc):
        self.root = root
        self._fila: queue.Queue = queue.Queue()

    def run(self, func, *args, on_done=None, on_error=None, **kwargs):
        """Inicia `func(*args, **kwargs)` em segundo plano.

        `on_done`/`on_error` são chamados na thread principal (podem mexer na
        interface sem risco).
        """

        def _trabalho():
            try:
                resultado = func(*args, **kwargs)
            # Fronteira da interface: qualquer falha da tarefa vira mensagem
            # para o usuário, então capturar Exception de propósito.
            except Exception as exc:  # noqa: BLE001
                self._fila.put(("erro", exc))
            else:
                self._fila.put(("ok", resultado))

        threading.Thread(target=_trabalho, daemon=True).start()
        self._aguardar(on_done, on_error)

    def _aguardar(self, on_done, on_error):
        try:
            tipo, valor = self._fila.get_nowait()
        except queue.Empty:
            self.root.after(INTERVALO_POLL, lambda: self._aguardar(on_done, on_error))
            return

        if tipo == "ok":
            if on_done is not None:
                on_done(valor)
        elif on_error is not None:
            on_error(valor)
        else:
            messagebox.showerror("Erro", str(valor))


class Progresso:
    """Compartilha progresso entre a thread de trabalho e a interface.

    A thread só chama `atualizar(valor)` (operação simples, sem tocar no
    Tkinter). A thread principal lê o valor com `after` e chama o callback.
    """

    def __init__(self, root: tk.Misc, callback, intervalo: int = 250):
        self.root = root
        self.callback = callback
        self.intervalo = intervalo
        self._valor = None
        self._parado = False
        self._agendar()

    def atualizar(self, valor):
        """Chamado da thread de trabalho: apenas guarda o valor."""
        self._valor = valor

    def parar(self):
        """Chamado da thread principal: encerra o polling."""
        self._parado = True

    def _agendar(self):
        self.root.after(self.intervalo, self._tick)

    def _tick(self):
        if self._parado:
            return
        if self._valor is not None:
            try:
                self.callback(self._valor)
            except tk.TclError:
                return
            self._valor = None
        self._agendar()


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
