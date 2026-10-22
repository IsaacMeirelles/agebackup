"""Aba de restauração (arquivo individual e total)."""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from agebackup import config_paths
from agebackup.config import ConfigError
from agebackup.logging_paths import caminho_completo

from .utils import Progresso, ThreadedRunner

# Quantas linhas a tabela mostra de uma vez. Um backup grande tem dezenas de
# milhares de itens; inserir todos travaria a interface.
MAX_EXIBIR = 2000

# Aviso de progresso na leitura a cada N itens.
PASSO_PROGRESSO = 500


class _Cancelado(Exception):
    """Leitura interrompida pelo usuário."""


class RestoreTab:
    """Restaura itens de dentro de um `.tar.gz`.

    A leitura do índice roda em segundo plano porque descomprimir um `.tar.gz`
    de vários GB só para listar o conteúdo leva minutos. O índice fica em cache
    (`.agebackup-*` na pasta de configuração) para que a segunda abertura seja
    imediata, desde que o arquivo não tenha mudado.
    """

    def __init__(self, notebook, status_callback):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text="Restaurar")
        self.status_callback = status_callback
        self.arquivo_tar: Path | None = None
        self.membros: list[str] = []
        self._membros_lower: list[str] = []
        self._carregando = False
        self._cancelar = False
        # Identifica a leitura atual. Se o usuário escolher outro arquivo
        # enquanto uma leitura antiga termina, o resultado dela é descartado.
        self._geracao = 0
        self._criar()

    def _criar(self):
        topo = ttk.LabelFrame(
            self.frame, text="Arquivo compactado (.tar.gz)", padding=5
        )
        topo.pack(fill=tk.X)
        self.lbl_arquivo = ttk.Label(topo, text="Nenhum arquivo selecionado")
        self.lbl_arquivo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_selecionar = ttk.Button(
            topo, text="Selecionar .tar.gz", command=self.selecionar
        )
        self.btn_selecionar.pack(side=tk.LEFT, padx=2)
        self.btn_cancelar = ttk.Button(
            topo, text="Cancelar leitura", command=self.cancelar, state=tk.DISABLED
        )
        self.btn_cancelar.pack(side=tk.LEFT, padx=2)

        filtro_frame = ttk.Frame(self.frame)
        filtro_frame.pack(fill=tk.X, pady=2)
        ttk.Label(filtro_frame, text="Filtrar:").pack(side=tk.LEFT)
        self.var_filtro = tk.StringVar()
        self.var_filtro.trace("w", lambda *a: self._filtrar())
        ttk.Entry(filtro_frame, textvariable=self.var_filtro, width=40).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Label(filtro_frame, text="(use o filtro para achar o arquivo)").pack(
            side=tk.LEFT
        )

        area = ttk.Frame(self.frame)
        area.pack(fill=tk.BOTH, expand=True, pady=5)

        cols = ("nome",)
        self.tree = ttk.Treeview(area, columns=cols, show="headings", height=14)
        self.tree.heading("nome", text="Conteúdo do arquivo compactado")
        self.tree.column("nome", width=700)
        scroll = ttk.Scrollbar(area, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        botoes = ttk.Frame(self.frame)
        botoes.pack(fill=tk.X)
        ttk.Button(
            botoes, text="Restaurar selecionado(s) aqui...", command=self.restaurar_aqui
        ).pack(side=tk.LEFT)
        ttk.Button(
            botoes, text="Restaurar em outra pasta...", command=self.restaurar_outro
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(
            botoes, text="Restaurar arquivo COMPLETO", command=self.restaurar_completo
        ).pack(side=tk.LEFT, padx=2)

        self.lbl_info = ttk.Label(
            self.frame,
            text="Dica: se for incremental, extraia o FULL primeiro e depois os "
            "incrementais na ordem cronológica.",
        )
        self.lbl_info.pack(anchor=tk.W)

    # ------------------------------------------------------------------ leitura
    def selecionar(self):
        destino_padrao = _pasta_compactacao_padrao()

        opcoes = {}
        if destino_padrao and os.path.isdir(destino_padrao):
            opcoes["initialdir"] = destino_padrao

        arq = filedialog.askopenfilename(
            title="Selecionar arquivo compactado",
            filetypes=[
                ("Arquivos .tar.gz", "*.tar.gz"),
                ("Todos os arquivos", "*.*"),
            ],
            **opcoes,
        )
        if not arq:
            return

        if self._carregando:
            self._cancelar = True

        self.arquivo_tar = Path(arq)
        self.lbl_arquivo.config(
            text=f"{self.arquivo_tar.name}  |  {caminho_completo(self.arquivo_tar)}"
        )
        self._carregar_membros()

    def cancelar(self):
        """Interrompe a leitura do índice."""
        if self._carregando:
            self._cancelar = True
            self.lbl_info.config(text="Cancelando a leitura...")

    def _limpar_lista(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.membros = []
        self._membros_lower = []
        self.var_filtro.set("")

    def _carregar_membros(self):
        self._limpar_lista()
        self._geracao += 1
        geracao = self._geracao

        if not self.arquivo_tar or not self.arquivo_tar.exists():
            self.lbl_info.config(text="Arquivo não encontrado.")
            return

        # Índice em cache: a segunda abertura é instantânea.
        em_cache = _ler_cache(self.arquivo_tar)
        if em_cache is not None:
            self._carregando = False
            self._aplicar_membros(em_cache)
            self.lbl_info.config(
                text=f"{len(em_cache)} item(ns) no arquivo (índice em cache). "
                "Use o filtro para localizar."
            )
            return

        self._carregando = True
        self._cancelar = False
        self.btn_selecionar.configure(state=tk.DISABLED)
        self.btn_cancelar.configure(state=tk.NORMAL)
        self.lbl_info.config(
            text="Lendo o índice do arquivo... Em arquivos grandes (vários GB) "
            "isso pode levar alguns minutos."
        )
        if self.status_callback:
            self.status_callback("Lendo índice do .tar.gz...")

        arquivo = self.arquivo_tar
        root = self.frame.winfo_toplevel()
        progresso = Progresso(root, lambda n: self._mostrar_progresso(n))

        def _exec():
            nomes: list[str] = []
            try:
                with tarfile.open(arquivo, "r:gz") as tar:
                    for membro in tar:
                        if self._cancelar or self._geracao != geracao:
                            raise _Cancelado()
                        nomes.append(membro.name)
                        if len(nomes) % PASSO_PROGRESSO == 0:
                            progresso.atualizar(len(nomes))
            finally:
                progresso.parar()
            return nomes

        def _ok(nomes):
            if geracao != self._geracao:
                return
            self._carregando = False
            self.btn_selecionar.configure(state=tk.NORMAL)
            self.btn_cancelar.configure(state=tk.DISABLED)
            if self._cancelar:
                self.lbl_info.config(text="Leitura cancelada.")
                return
            _gravar_cache(arquivo, nomes)
            self._aplicar_membros(nomes)
            self.lbl_info.config(
                text=f"{len(nomes)} item(ns) no arquivo. Use o filtro para localizar."
            )
            if self.status_callback:
                self.status_callback(f"{len(nomes)} item(ns) no arquivo")

        def _err(erro):
            if geracao != self._geracao:
                return
            self._carregando = False
            self.btn_selecionar.configure(state=tk.NORMAL)
            self.btn_cancelar.configure(state=tk.DISABLED)
            if isinstance(erro, _Cancelado) or self._cancelar:
                self.lbl_info.config(text="Leitura cancelada.")
                return
            self.lbl_info.config(text=f"Erro ao ler o arquivo: {erro}")
            messagebox.showerror("Erro ao ler o .tar.gz", str(erro))

        ThreadedRunner(root).run(_exec, on_done=_ok, on_error=_err)

    def _aplicar_membros(self, nomes: list[str]):
        self.membros = list(nomes)
        self._membros_lower = [nome.lower() for nome in self.membros]
        self._filtrar()

    def _mostrar_progresso(self, quantidade: int):
        self.lbl_info.config(text=f"Lendo... {quantidade} item(ns)")

    def _filtrar(self):
        if self._carregando:
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

        filtro = self.var_filtro.get().strip().lower()
        if filtro:
            encontrados = [
                nome
                for nome, minusculo in zip(self.membros, self._membros_lower)
                if filtro in minusculo
            ]
        else:
            encontrados = self.membros

        for nome in encontrados[:MAX_EXIBIR]:
            self.tree.insert("", tk.END, values=(nome,))

        total = len(encontrados)
        exibidos = min(total, MAX_EXIBIR)
        if not self.membros:
            self.lbl_info.config(
                text="Nenhum arquivo carregado. Clique em 'Selecionar .tar.gz'."
            )
        elif total == 0:
            self.lbl_info.config(text=f"Nenhum item contém '{filtro}'.")
        elif exibidos < total:
            self.lbl_info.config(
                text=(
                    f"Mostrando {exibidos} de {total} item(ns). "
                    "Refine o filtro para ver os demais."
                )
            )
        elif filtro:
            self.lbl_info.config(text=f"{total} item(ns) encontrado(s).")
        else:
            self.lbl_info.config(
                text=f"{total} item(ns) no arquivo (exibindo até {MAX_EXIBIR})."
            )

    def _selecionados(self) -> list[str]:
        selecao = self.tree.selection()
        nomes = []
        for item in selecao:
            valores = self.tree.item(item, "values")
            if valores:
                nomes.append(valores[0])
        return nomes

    def _pasta_destino_padrao(self) -> str:
        return _pasta_compactacao_padrao()

    # --------------------------------------------------------------- restauração
    def restaurar_aqui(self):
        pasta_padrao = self._pasta_destino_padrao() or os.getcwd()
        self._restaurar(destino=pasta_padrao)

    def restaurar_outro(self):
        padrao = self._pasta_destino_padrao()
        opcoes = {"initialdir": padrao} if padrao and os.path.isdir(padrao) else {}
        pasta = filedialog.askdirectory(title="Selecionar pasta de destino", **opcoes)
        if not pasta:
            return
        self._restaurar(destino=pasta)

    def restaurar_completo(self):
        if not self.arquivo_tar:
            messagebox.showerror("Erro", "Selecione um arquivo .tar.gz")
            return
        padrao = self._pasta_destino_padrao()
        opcoes = {"initialdir": padrao} if padrao and os.path.isdir(padrao) else {}
        pasta = filedialog.askdirectory(
            title="Restaurar arquivo COMPLETO neste destino", **opcoes
        )
        if not pasta:
            return

        arquivo = self.arquivo_tar
        destino = Path(pasta)
        self.lbl_info.config(text="Extraindo o arquivo completo... acompanhe o status.")
        if self.status_callback:
            self.status_callback("Extraindo arquivo completo...")

        def _exec():
            destino.mkdir(parents=True, exist_ok=True)
            with tarfile.open(arquivo, "r:gz") as tar:
                _extrair_tudo(tar, destino)

        def _ok(_resultado):
            self.lbl_info.config(text=f"Extraído para {caminho_completo(destino)}")
            if self.status_callback:
                self.status_callback("Restauração completa concluída")
            messagebox.showinfo(
                "Restaurado",
                f"Arquivo completo extraído para:\n{caminho_completo(destino)}",
            )

        def _err(erro):
            self.lbl_info.config(text=f"Erro: {erro}")
            messagebox.showerror("Erro ao restaurar", str(erro))

        ThreadedRunner(self.frame.winfo_toplevel()).run(
            _exec, on_done=_ok, on_error=_err
        )

    def _restaurar(self, destino):
        if not self.arquivo_tar:
            messagebox.showerror("Erro", "Selecione um arquivo .tar.gz")
            return
        selecionados = self._selecionados()
        if not selecionados:
            messagebox.showerror(
                "Erro",
                "Selecione pelo menos um arquivo/pasta na lista para restaurar",
            )
            return

        arquivo = self.arquivo_tar
        dest = Path(destino)
        alvos = _expandir_pastas(selecionados, self.membros)

        self.lbl_info.config(
            text=f"Extraindo {len(alvos)} item(ns) para {caminho_completo(dest)}..."
        )
        if self.status_callback:
            self.status_callback("Restaurando itens selecionados...")

        def _exec():
            dest.mkdir(parents=True, exist_ok=True)
            with tarfile.open(arquivo, "r:gz") as tar:
                membros = [m for m in tar if m.name in alvos]
                if not membros:
                    raise ValueError(
                        "nenhum dos itens selecionados foi encontrado no arquivo"
                    )
                _extrair_tudo(tar, dest, membros)
            return len(membros)

        def _ok(quantidade):
            self.lbl_info.config(
                text=f"{quantidade} item(ns) extraído(s) para "
                f"{caminho_completo(dest)}"
            )
            if self.status_callback:
                self.status_callback("Restauração individual concluída")
            messagebox.showinfo(
                "Restaurado",
                f"{quantidade} item(ns) extraído(s) para:\n"
                f"{caminho_completo(dest)}",
            )

        def _err(erro):
            self.lbl_info.config(text=f"Erro: {erro}")
            messagebox.showerror("Erro ao restaurar", str(erro))

        ThreadedRunner(self.frame.winfo_toplevel()).run(
            _exec, on_done=_ok, on_error=_err
        )


# --------------------------------------------------------------------- cache
def _pasta_indices() -> Path:
    return config_paths.get_config_dir() / "indices"


def _chave_cache(arquivo: Path) -> str:
    try:
        info = arquivo.stat()
        base = f"{arquivo.resolve()}|{info.st_size}|{info.st_mtime_ns}"
    except OSError:
        base = str(arquivo.absolute())
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def _ler_cache(arquivo: Path) -> list[str] | None:
    caminho = _pasta_indices() / f"{_chave_cache(arquivo)}.json"
    if not caminho.is_file():
        return None
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None
    if not isinstance(dados, dict):
        return None
    nomes = dados.get("membros")
    if not isinstance(nomes, list) or not all(isinstance(n, str) for n in nomes):
        return None
    return nomes


def _gravar_cache(arquivo: Path, membros: list[str]) -> None:
    pasta = _pasta_indices()
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        caminho = pasta / f"{_chave_cache(arquivo)}.json"
        dados = {
            "arquivo": str(arquivo.resolve()),
            "membros": membros,
        }
        caminho.write_text(json.dumps(dados), encoding="utf-8")
    except OSError:
        # Cache é conveniência: se não der para gravar, segue sem ele.
        return


# ------------------------------------------------------------------ auxiliares
def _pasta_compactacao_padrao() -> str:
    """Pasta de compactação configurada, ou vazio se não der para descobrir."""
    from agebackup import config as config_mod

    try:
        cfg = config_mod.load()
    except ConfigError, OSError:
        return ""
    if cfg is None or not cfg.backup.destination:
        return ""
    destino_backup = Path(cfg.backup.destination).expanduser()
    return str(cfg.compactacao.pasta(destino_backup))


def _expandir_pastas(selecionados: list[str], membros: list[str]) -> set[str]:
    """Inclui os filhos das pastas selecionadas.

    Selecionar uma pasta na lista extrai somente o registro da pasta, não o
    conteúdo. Aqui os nomes abaixo dela entram no conjunto, para restaurar a
    árvore inteira.
    """
    alvos = set(selecionados)
    prefixos = [nome.rstrip("/") + "/" for nome in selecionados]
    for nome in membros:
        for prefixo in prefixos:
            if nome.startswith(prefixo):
                alvos.add(nome)
                break
    return alvos


def _extrair_tudo(tar: tarfile.TarFile, destino: Path, membros=None) -> None:
    """Extrai o conteúdo, sanitizando os caminhos (``filter="data"``).

    O filtro ``data`` (Python 3.12+) recusa caminhos absolutos e ``..`` dentro do
    arquivo, evitando que um `.tar.gz` malformado grave fora do destino.
    """
    try:
        tar.extractall(path=destino, members=membros, filter="data")
    except TypeError:  # Python sem o parâmetro `filter`
        tar.extractall(path=destino, members=membros)
