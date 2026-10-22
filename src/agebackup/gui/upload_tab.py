"""Aba de upload manual."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from agebackup import config as config_mod
from agebackup import ftp
from agebackup.logging_paths import caminho_completo

from .utils import ThreadedRunner


class UploadTab:
    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Upload Manual")
        self.status_callback = status_callback
        self.arquivo_selecionado = tk.StringVar()
        self._criar()

    def _criar(self):
        topo = ttk.LabelFrame(self.frame, text="Selecionar arquivo", padding=5)
        topo.pack(fill=tk.X)
        ttk.Entry(topo, textvariable=self.arquivo_selecionado, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(topo, text="Procurar .tar.gz", command=self.procurar).pack(side=tk.LEFT, padx=2)
        ttk.Button(topo, text="Listar compactados", command=self.listar_compactados).pack(side=tk.LEFT, padx=2)

        botoes = ttk.Frame(self.frame)
        botoes.pack(fill=tk.X, pady=5)
        ttk.Button(botoes, text="Enviar arquivo selecionado", command=self.enviar).pack(side=tk.LEFT)
        ttk.Button(botoes, text="Enviar logs", command=self.enviar_logs).pack(side=tk.LEFT, padx=2)

        frame_log = ttk.LabelFrame(self.frame, text="Log do envio", padding=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        self.log = scrolledtext.ScrolledText(frame_log, wrap=tk.WORD, font=("Consolas", 9))
        self.log.pack(fill=tk.BOTH, expand=True)

    def _log(self, msg):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def procurar(self):
        arq = filedialog.askopenfilename(filetypes=[("Tar.gz", "*.tar.gz"), ("Todos", "*.*")])
        if arq:
            self.arquivo_selecionado.set(arq)
            self._log(f"Selecionado: {caminho_completo(arq)}")

    def listar_compactados(self):
        cfg = config_mod.load()
        if not cfg:
            return
        destino_backup = Path(cfg.backup.destination).expanduser()
        pasta = cfg.compactacao.pasta(destino_backup)
        if not pasta.exists():
            messagebox.showwarning("Aviso", f"Pasta não existe: {caminho_completo(pasta)}")
            return
        self._log(f"Compactados em {caminho_completo(pasta)}:")
        for arq in sorted(pasta.glob("*.tar.gz"), reverse=True)[:20]:
            self._log(f"  {arq.name} -> {caminho_completo(arq)}")

    def enviar(self):
        cfg = config_mod.load()
        if not cfg:
            messagebox.showerror("Erro", "Sem configuração")
            return
        arquivo = self.arquivo_selecionado.get().strip()
        if not arquivo:
            messagebox.showerror("Erro", "Selecione um arquivo para enviar")
            return
        try:
            if hasattr(cfg, "ftp") and cfg.ftp.tem_dados():
                cred_obj = ftp.obter_credenciais(cfg)
                cred_para_envio = cred_obj
                self._log(f"Usando credenciais salvas no config.json (criptografadas)")
            else:
                cred = cfg.envio.caminho_credenciais()
                if not cred.exists():
                    messagebox.showerror("Erro", f"Arquivo de credenciais não encontrado: {cred}")
                    return
                cred_obj = ftp.ler_credenciais(cred)
                cred_para_envio = cred_obj
            self._log(f"Credenciais: {cred_obj.usuario}@{cred_obj.host}:{cred_obj.porta}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))
            return
        runner = ThreadedRunner(self.frame.winfo_toplevel())
        self._log(f"Enviando {caminho_completo(arquivo)}...")
        padrao_ftp = getattr(cfg.envio, "pasta_remota", "") or (getattr(cfg.ftp, "pasta_remota", "") if hasattr(cfg, "ftp") else "")
        self._log(f"Pasta remota: {ftp.pasta_remota(padrao=padrao_ftp)}")

        def _exec():
            from datetime import datetime
            pasta_custom = getattr(cfg.envio, "pasta_remota", "") or (getattr(cfg.ftp, "pasta_remota", "") if hasattr(cfg, "ftp") else "")
            pasta = ftp.pasta_remota(datetime.now(), cred_obj.pasta, padrao=pasta_custom) if pasta_custom else ftp.pasta_remota(datetime.now(), cred_obj.pasta)
            return ftp.enviar_com_conferencia(
                Path(arquivo), cred_obj, manter=cfg.envio.manter, verificacao=True, sha256_completo=False
            )

        def _ok(r):
            self._log(f"OK: {r}")
            if self.status_callback:
                self.status_callback("Upload concluído")

        def _err(e):
            self._log(f"ERRO: {e}")
            messagebox.showerror("Erro no envio", str(e))

        runner.run(_exec, on_done=_ok, on_error=_err)

    def enviar_logs(self):
        cfg = config_mod.load()
        if not cfg:
            return
        destino_backup = Path(cfg.backup.destination).expanduser()
        pasta_logs = cfg.logs.pasta(destino_backup)
        cred = cfg.envio.caminho_credenciais()
        runner = ThreadedRunner(self.frame.winfo_toplevel())
        self._log(f"Enviando logs de {caminho_completo(pasta_logs)}...")

        def _exec():
            return ftp.enviar_logs(pasta_logs, cred, manter=cfg.envio.manter)

        def _ok(r):
            self._log(f"Logs enviados: {r}")
            if self.status_callback:
                self.status_callback("Logs enviados")

        def _err(e):
            self._log(f"ERRO: {e}")
            messagebox.showerror("Erro ao enviar logs", str(e))

        runner.run(_exec, on_done=_ok, on_error=_err)
