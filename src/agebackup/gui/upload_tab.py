"""Aba de upload manual."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from agebackup import config as config_mod
from agebackup import ftp
from agebackup.config import ConfigError
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
        ttk.Entry(topo, textvariable=self.arquivo_selecionado, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(topo, text="Procurar .tar.gz", command=self.procurar).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(
            topo, text="Listar compactados", command=self.listar_compactados
        ).pack(side=tk.LEFT, padx=2)

        botoes = ttk.Frame(self.frame)
        botoes.pack(fill=tk.X, pady=5)
        ttk.Button(botoes, text="Enviar arquivo selecionado", command=self.enviar).pack(
            side=tk.LEFT
        )
        ttk.Button(botoes, text="Enviar logs", command=self.enviar_logs).pack(
            side=tk.LEFT, padx=2
        )

        frame_log = ttk.LabelFrame(self.frame, text="Log do envio", padding=5)
        frame_log.pack(fill=tk.BOTH, expand=True)
        self.log = scrolledtext.ScrolledText(
            frame_log, wrap=tk.WORD, font=("Consolas", 9)
        )
        self.log.pack(fill=tk.BOTH, expand=True)

    def _log(self, msg):
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)

    def _obter_credenciais(self, cfg):
        """Usa as credenciais do config.json ou, na falta, o arquivo .ini."""
        if getattr(cfg, "ftp", None) and cfg.ftp.tem_dados():
            self._log("Usando credenciais salvas no config.json (criptografadas)")
            return ftp.obter_credenciais(cfg)
        cred = cfg.envio.caminho_credenciais()
        if not cred.exists():
            raise FileNotFoundError(
                f"Arquivo de credenciais não encontrado: {caminho_completo(cred)}"
            )
        return ftp.ler_credenciais(cred)

    @staticmethod
    def _padrao_ftp(cfg) -> str:
        return getattr(cfg.envio, "pasta_remota", "") or (
            getattr(cfg.ftp, "pasta_remota", "") if getattr(cfg, "ftp", None) else ""
        )

    def procurar(self):
        arq = filedialog.askopenfilename(
            filetypes=[("Tar.gz", "*.tar.gz"), ("Todos", "*.*")]
        )
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
            messagebox.showwarning(
                "Aviso", f"Pasta não existe: {caminho_completo(pasta)}"
            )
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
            cred_obj = self._obter_credenciais(cfg)
            self._log(
                f"Credenciais: {cred_obj.usuario}@{cred_obj.host}:{cred_obj.porta}"
            )
        except (OSError, ValueError, ConfigError) as e:
            messagebox.showerror("Erro", str(e))
            return

        padrao_ftp = self._padrao_ftp(cfg)
        pasta_destino = ftp.pasta_remota(
            datetime.now(), cred_obj.pasta, padrao=padrao_ftp
        )
        self._log(f"Enviando {caminho_completo(arquivo)}...")
        self._log(f"Pasta remota: {pasta_destino}")

        def _exec():
            return ftp.enviar_com_conferencia(
                Path(arquivo),
                cred_obj,
                manter=cfg.envio.manter,
                verificacao=True,
                sha256_completo=False,
                pasta=pasta_destino,
            )

        def _ok(r):
            if r.erro:
                self._log(f"ERRO: {r.erro}")
                messagebox.showerror("Erro no envio", r.erro)
                return
            self._log(f"OK: enviado para {r.remoto} ({r.bytes_enviados} bytes)")
            for nome in r.removidos:
                self._log(f"  removido do servidor: {nome}")
            if self.status_callback:
                self.status_callback("Upload concluído")

        def _err(e):
            self._log(f"ERRO: {e}")
            messagebox.showerror("Erro no envio", str(e))

        ThreadedRunner(self.frame.winfo_toplevel()).run(
            _exec, on_done=_ok, on_error=_err
        )

    def enviar_logs(self):
        cfg = config_mod.load()
        if not cfg:
            return
        destino_backup = Path(cfg.backup.destination).expanduser()
        pasta_logs = cfg.logs.pasta(destino_backup)
        try:
            cred = self._obter_credenciais(cfg)
        except (OSError, ValueError, ConfigError) as e:
            messagebox.showerror("Erro", str(e))
            return
        padrao_ftp = self._padrao_ftp(cfg)
        runner = ThreadedRunner(self.frame.winfo_toplevel())
        self._log(f"Enviando logs de {caminho_completo(pasta_logs)}...")
        self._log(
            "Pasta remota: "
            f"{ftp.pasta_de_logs(datetime.now(), cred.pasta, padrao_ftp)}"
        )

        def _exec():
            return ftp.enviar_logs(
                pasta_logs, cred, manter=cfg.envio.manter, padrao=padrao_ftp
            )

        def _ok(resultados):
            enviados = [r for r in resultados if r.enviado and not r.erro]
            falhas = [r for r in resultados if r.erro]
            self._log(f"Logs enviados: {len(enviados)} arquivo(s)")
            for resultado in falhas:
                self._log(f"  falha em {resultado.arquivo}: {resultado.erro}")
            if self.status_callback:
                self.status_callback(
                    f"Logs enviados: {len(enviados)} | falhas: {len(falhas)}"
                )
            if falhas:
                messagebox.showwarning(
                    "Envio de logs",
                    f"{len(falhas)} arquivo(s) falharam. Veja o log do envio.",
                )
            elif not resultados:
                self._log("Nenhum log encontrado para enviar.")

        def _err(e):
            self._log(f"ERRO: {e}")
            messagebox.showerror("Erro ao enviar logs", str(e))

        runner.run(_exec, on_done=_ok, on_error=_err)
