"""Diálogo de ajuda contextual."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .utils import centralizar_janela


AJUDA_GERAL = """AGEBACKUP - PAINEL ÚNICO

Abas:
- Início/Status: visão geral e ações rápidas
- Configuração: conta, backup, compactação, logs, envio FTP/FTPS
- Backup: executar backup com log em tempo real (caminho completo)
- Compactação: listar, forçar FULL/INCREMENTAL, aplicar retenção
- Upload Manual: enviar .tar.gz ou logs sob demanda
- Restaurar: restaurar arquivo individual ou backup completo
- Log: visualizar logs com caminho completo e filtro
- Ajuda: esta tela

Atalhos:
- F1: Ajuda desta tela
- Ctrl+S: Salvar (na aba Configuração)
- Ctrl+Q: Sair

Restaurar:
- Arquivo individual: abra o .tar.gz, filtre, selecione e extraia
- Total/encadeado: extraia o FULL primeiro, depois os INCREMENTAIS na ordem cronológica

Configuração fica junto à aplicação (agebackup.json)."""


class HelpDialog:
    def __init__(self, parent):
        self.janela = tk.Toplevel(parent)
        self.janela.title("Ajuda - AgeBackup")
        self.janela.transient(parent)
        self.janela.grab_set()
        centralizar_janela(self.janela, 650, 520)
        self._criar()

    def _criar(self):
        frame = ttk.Frame(self.janela, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        texto = tk.Text(frame, wrap=tk.WORD, font=("TkDefaultFont", 9))
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=texto.yview)
        texto.configure(yscrollcommand=scroll.set)
        texto.insert(tk.END, AJUDA_GERAL)
        texto.configure(state=tk.DISABLED)
        texto.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        botoes = ttk.Frame(self.janela, padding=(10, 5))
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="Fechar", command=self.janela.destroy).pack(side=tk.RIGHT)
        self.janela.bind("<Escape>", lambda e: self.janela.destroy())
        self.janela.bind("<F1>", lambda e: self.janela.destroy())
