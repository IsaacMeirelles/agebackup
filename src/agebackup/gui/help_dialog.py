"""Diálogo de ajuda tutorial por aba."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .utils import centralizar_janela

AJUDA_TUTORIAL = """AGEBACKUP - TUTORIAL POR ABA

INÍCIO/STATUS
- Para que serve: visão geral da configuração carregada (config junto à aplicação)
- Ações: "Ir para..." navega entre abas, "Atualizar status" recarrega informações
- Dica: arquivo de configuração = agebackup.json na pasta do app/binário

CONFIGURAÇÃO
Sub-abas:
- Conta: método de autenticação (ADC ou Service Account), e-mail, chave JSON
- Backup (Google Drive): pasta de destino local, ID da pasta (vazio = todo Drive), incluir unidades compartilhadas
- Compactação: pasta dos .tar.gz, prefixo, manter (0 = todos), full a cada N dias (0 = sempre full). Variável full_a_cada controla política
- Logs: ativar logs, pasta dos logs, manter logs fechados, comprimir .gz. Logs gravam caminho completo
- Envio (FTP/FTPS): arquivo de credenciais ou dados salvos no config.json com senha criptografada. Pasta remota personalizável com variáveis YYYY, YY, MM, M, dd, d

Ações: Salvar (Ctrl+S) grava tudo no agebackup.json

BACKUP
- Para que serve: executar backup do Google Drive para pasta local
- Campos/infos: usa configuração da aba Configuração
- Ações: "Iniciar Backup" roda em thread com log em tempo real (caminho completo). "Limpar log" limpa tela
- Resultado: contadores de baixados/inalterados/movidos/falhas

COMPACTAÇÃO
- Para que serve: gerar .tar.gz (full/incremental) seguindo política
- Ações: "Seguir política (auto)" usa full_a_cada, "Forçar FULL", "Forçar INCREMENTAL", "Aplicar retenção", "Atualizar lista"
- Lista mostra arquivo, tipo, tamanho, caminho completo

UPLOAD MANUAL
- Para que serve: enviar .tar.gz ou logs sob demanda
- Ações: "Procurar .tar.gz", "Listar compactados", "Enviar arquivo selecionado" (com conferência por tamanho/SHA256 conforme módulo), "Enviar logs" para /AAAA/MM/logs
- Usa credenciais salvas no config.json (criptografadas) ou arquivo .ini

RESTAURAR
- Para que serve: restaurar arquivo individual OU restaurar arquivo completo
- Fluxo arquivo individual: selecionar .tar.gz (padrão = pasta de compactação), filtrar conteúdo, selecionar item(ns), escolher destino (padrão = pasta de compactação) ou restaurar aqui
- Fluxo total: "Restaurar arquivo COMPLETO" extrai todo o tar.gz para pasta escolhida (padrão = pasta de compactação)
- IMPORTANTE: para incremental encadeado, extraia o FULL primeiro, depois INCREMENTAIS na ordem cronológica

LOG
- Para que serve: visualizar logs com caminho completo
- Ações: carregar agebackup-atualizar.log, carregar .agebackup-falhas.log, abrir arquivo, copiar seleção, filtrar por texto
- Todos os caminhos relevantes são exibidos completos

AJUDA
- Para que serve: tutorial detalhado desta tela
- Atalho: F1

CONFIGURAÇÃO JUNTO À APLICAÇÃO
- agebackup.json fica junto ao app/binário
- Migração automática de ~/.config/agebackup/config.json na primeira execução
- Senha FTP criptografada salva em ftp.senha_criptografada no JSON

PASTA REMOTA FTP PERSONALIZÁVEL
- Pode usar qualquer caractere válido para pastas
- Variáveis: YYYY (2026), YY (26), MM (10), M (10), dd (22), d (22)
- Exemplo: /backups/YYYY/MM ou /RSKO/YYYY-MM"""


class HelpDialog:
    def __init__(self, parent):
        self.janela = tk.Toplevel(parent)
        self.janela.title("Ajuda - AgeBackup (Tutorial por aba)")
        self.janela.transient(parent)
        self.janela.grab_set()
        centralizar_janela(self.janela, 720, 620)
        self._criar()

    def _criar(self):
        frame = ttk.Frame(self.janela, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        texto = tk.Text(frame, wrap=tk.WORD, font=("TkDefaultFont", 9))
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=texto.yview)
        texto.configure(yscrollcommand=scroll.set)
        texto.insert(tk.END, AJUDA_TUTORIAL)
        texto.configure(state=tk.DISABLED)
        texto.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        botoes = ttk.Frame(self.janela, padding=(10, 5))
        botoes.pack(fill=tk.X)
        ttk.Button(botoes, text="Fechar", command=self.janela.destroy).pack(
            side=tk.RIGHT
        )
        self.janela.bind("<Escape>", lambda e: self.janela.destroy())
        self.janela.bind("<F1>", lambda e: self.janela.destroy())
