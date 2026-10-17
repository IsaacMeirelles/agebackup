"""Reconstrói arquivos nativos do Google grandes demais para o ``files.export``.

O ``files.export`` tem limite de 10 MB por requisição. Quando um arquivo nativo
(Docs, Sheets, Slides) não cabe, o backup ainda garante a aparência salvando um
PDF, mas o PDF perde a edição. Este módulo tenta recuperar o formato editável
pela API nativa correspondente, que **não** tem esse limite:

- Apresentação -> ``.pptx`` (Slides API)
- Documento    -> ``.docx`` (Docs API)
- Planilha     -> ``.xlsx`` (Sheets API)

A reconstrução é estrutural, não byte a byte: preserva o conteúdo (texto,
formas, imagens, células e fórmulas), mas não o tema/matriz, as transições, as
animações e a mídia embutida (vídeo). O arquivo sai com o sufixo
``.reconstruido`` para nunca ser confundido com um export fiel.

Arquivos **enviados** ao Drive (uploads como ``.md``, ``.txt``, ``.pdf``,
``.xlsx``) são blobs e baixam inteiros pelo ``files.download``, sem passar por
aqui: o limite de 10 MB só atinge os tipos nativos ``application/vnd.google-apps.*``.
"""

from __future__ import annotations

import io
import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from googleapiclient.discovery import Resource, build

from agebackup.config import (
    DOCUMENTS_READONLY_SCOPE,
    PRESENTATIONS_READONLY_SCOPE,
    READONLY_SCOPE,
    SPREADSHEETS_READONLY_SCOPE,
    build_credentials,
)

# Sufixo do arquivo reconstruído. Fica ao lado do PDF (nome original + sufixo),
# então nunca sobrescreve nem se passa por um export fiel.
SUFIXO_RECONSTRUIDO = ".reconstruido"

# Tempo limite, em segundos, para baixar a mídia embutida (imagens).
TIMEOUT_MIDIA = 30


class ReconstrucaoIndisponivel(Exception):
    """O tipo do arquivo não tem reconstrutor, ou o conteúdo é insuficiente."""


@dataclass(frozen=True)
class Especie:
    """Como reconstruir um tipo nativo do Google."""

    api: str
    versao: str
    escopo: str
    extensao: str
    construtor: Callable[[Resource, str, Path], Path]


def _salvar(objeto: object, destino: Path) -> None:
    """Grava o documento de forma atômica (``.tmp`` + troca).

    Vale para ``pptx.Presentation``, ``docx.Document`` e ``openpyxl.Workbook``,
    que expõem um ``save(caminho)``.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        objeto.save(str(temporario))
        os.replace(temporario, destino)
    except OSError:
        temporario.unlink(missing_ok=True)
        raise


def _baixar_url(url: str | None) -> bytes | None:
    """Baixa uma mídia embutida. Devolve None se não der, sem interromper.

    As URLs de mídia das APIs (Slides ``contentUrl``, Docs ``contentUri``) vêm
    "marcadas com a conta de quem pediu": o próprio link dá acesso, sem cabeçalho
    de autorização.
    """
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_MIDIA) as resposta:
            return resposta.read()
    except OSError, ValueError:
        return None


# --------------------------------------------------------------------------
# Apresentações (Slides -> .pptx)
# --------------------------------------------------------------------------

# Índice do layout "em branco" no modelo padrão do python-pptx: as formas são
# posicionadas a partir das coordenadas da API, então não queremos placeholders.
_LAYOUT_EM_BRANCO = 6


def slides_para_pptx(service: Resource, file_id: str, destino: Path) -> Path:
    """Reconstrói uma apresentação do Google em ``.pptx``."""
    from pptx import Presentation

    apresentacao = service.presentations().get(presentationId=file_id).execute()
    documento = Presentation()
    _tamanho_do_slide(documento, apresentacao.get("pageSize") or {})

    for pagina in apresentacao.get("slides", []):
        slide = documento.slides.add_slide(documento.slide_layouts[_LAYOUT_EM_BRANCO])
        for elemento in pagina.get("pageElements", []):
            _elemento_de_slide(slide, elemento)

    _salvar(documento, destino)
    return destino


def _tamanho_do_slide(documento: object, tamanho: dict) -> None:
    """Aplica o tamanho da página (vem da API em EMU)."""
    from pptx.util import Emu

    largura = _magnitude(tamanho.get("width"))
    altura = _magnitude(tamanho.get("height"))
    if largura > 0:
        documento.slide_width = Emu(largura)
    if altura > 0:
        documento.slide_height = Emu(altura)


def _elemento_de_slide(slide: object, elemento: dict) -> None:
    """Recria um elemento (forma, imagem, tabela ou grupo) no slide."""
    caixa = _caixa(elemento.get("elementProperties") or {})
    if "image" in elemento:
        _imagem_de_slide(slide, elemento["image"], caixa)
    elif "table" in elemento:
        _tabela_de_slide(slide, elemento["table"], caixa)
    elif "shape" in elemento:
        _forma_de_slide(slide, elemento["shape"], caixa)
    elif "group" in elemento:
        for filho in elemento["group"].get("children", []):
            _elemento_de_slide(slide, filho)


def _caixa(props: dict) -> tuple[int, int, int, int]:
    """Posição e tamanho (esquerda, topo, largura, altura) em EMU."""
    transformacao = props.get("transform") or {}
    tamanho = props.get("size") or {}
    return (
        int(transformacao.get("translateX", 0) or 0),
        int(transformacao.get("translateY", 0) or 0),
        _magnitude(tamanho.get("width")),
        _magnitude(tamanho.get("height")),
    )


def _magnitude(dimensao: object) -> int:
    """Extrai o valor EMU de uma ``Dimension`` do Slides (``{magnitude, unit}``)."""
    if isinstance(dimensao, dict):
        return int(dimensao.get("magnitude", 0) or 0)
    return int(dimensao or 0)


def _imagem_de_slide(
    slide: object, imagem: dict, caixa: tuple[int, int, int, int]
) -> None:
    from pptx.util import Emu

    dados = _baixar_url(imagem.get("contentUrl"))
    if not dados:
        return
    esquerda, topo, largura, altura = caixa
    try:
        if largura > 0 and altura > 0:
            slide.shapes.add_picture(
                io.BytesIO(dados), Emu(esquerda), Emu(topo), Emu(largura), Emu(altura)
            )
        else:
            slide.shapes.add_picture(io.BytesIO(dados), Emu(esquerda), Emu(topo))
    except Exception:  # noqa: BLE001 - formato de imagem que o python-pptx não lê
        return


def _tabela_de_slide(
    slide: object, tabela: dict, caixa: tuple[int, int, int, int]
) -> None:
    from pptx.util import Emu

    linhas = tabela.get("tableRows") or []
    n_linhas = len(linhas)
    n_colunas = max((len(linha.get("tableCells") or []) for linha in linhas), default=0)
    esquerda, topo, largura, altura = caixa
    if n_linhas == 0 or n_colunas == 0 or largura <= 0 or altura <= 0:
        return

    forma = slide.shapes.add_table(
        n_linhas, n_colunas, Emu(esquerda), Emu(topo), Emu(largura), Emu(altura)
    )
    tabela_pptx = forma.table
    for i, linha in enumerate(linhas):
        for j, celula in enumerate(linha.get("tableCells") or []):
            tabela_pptx.cell(i, j).text = "\n".join(
                _paragrafos(celula.get("text") or {})
            )


def _forma_de_slide(
    slide: object, forma: dict, caixa: tuple[int, int, int, int]
) -> None:
    from pptx.util import Emu

    esquerda, topo, largura, altura = caixa
    paragrafos = _paragrafos(forma.get("text") or {})
    if paragrafos:
        caixa_texto = slide.shapes.add_textbox(
            Emu(esquerda), Emu(topo), Emu(max(largura, 1)), Emu(max(altura, 1))
        )
        _preencher_texto(caixa_texto.text_frame, paragrafos)
        return
    _retangulo_de_slide(slide, forma, caixa)


def _retangulo_de_slide(
    slide: object, forma: dict, caixa: tuple[int, int, int, int]
) -> None:
    """Recria um bloco colorido, para não perder o fundo/formas decorativas."""
    cor = _cor_solida(forma.get("shapeProperties") or {})
    if cor is None:
        return
    esquerda, topo, largura, altura = caixa
    if largura <= 0 or altura <= 0:
        return

    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Emu

    retangulo = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Emu(esquerda), Emu(topo), Emu(largura), Emu(altura)
    )
    retangulo.fill.solid()
    retangulo.fill.fore_color.rgb = RGBColor.from_string(cor)
    retangulo.line.fill.background()


def _cor_solida(props: dict) -> str | None:
    preenchimento = (props.get("shapeBackgroundFill") or {}).get("solidFill") or {}
    cor = (preenchimento.get("color") or {}).get("rgbColor")
    if isinstance(cor, str) and len(cor) == 6:
        return cor
    return None


def _paragrafos(texto: dict) -> list[str]:
    """Extrai os parágrafos de um ``TextContent`` do Slides.

    O Slides fecha cada parágrafo com um ``paragraphMarker``, então a última
    passagem costuma deixar um parágrafo vazio no fim: ele é descartado.
    """
    acumulado: list[str] = [""]
    for elemento in texto.get("textElements", []):
        if "paragraphMarker" in elemento:
            acumulado.append("")
        elif "textRun" in elemento:
            acumulado[-1] += elemento["textRun"].get("content", "")

    linhas = [linha.rstrip("\n") for linha in acumulado]
    while linhas and not linhas[-1].strip():
        linhas.pop()
    return linhas


def _preencher_texto(caixa_texto: object, paragrafos: list[str]) -> None:
    caixa_texto.text = paragrafos[0]
    for paragrafo in paragrafos[1:]:
        caixa_texto.add_paragraph().text = paragrafo


# --------------------------------------------------------------------------
# Documentos (Docs -> .docx)
# --------------------------------------------------------------------------


def docs_para_docx(service: Resource, file_id: str, destino: Path) -> Path:
    """Reconstrói um documento do Google em ``.docx``."""
    from docx import Document

    documento = service.documents().get(documentId=file_id).execute()
    saida = Document()
    objetos = documento.get("inlineObjects") or {}
    for elemento in (documento.get("body") or {}).get("content", []):
        if "paragraph" in elemento:
            _paragrafo_de_docx(saida, elemento["paragraph"], objetos)
        elif "table" in elemento:
            _tabela_de_docx(saida, elemento["table"])

    _salvar(saida, destino)
    return destino


def _paragrafo_de_docx(documento: object, paragrafo: dict, objetos: dict) -> None:
    estilo = (paragrafo.get("paragraphStyle") or {}).get("namedStyleType", "")
    nivel = _nivel_de_titulo(estilo)
    if nivel is not None:
        saida = documento.add_heading(level=nivel)
    else:
        saida = documento.add_paragraph()

    for elemento in paragrafo.get("elements", []):
        run_info = elemento.get("textRun")
        if run_info is not None:
            _run_de_docx(saida, run_info)
            continue
        objeto = elemento.get("inlineObjectElement")
        if objeto is not None:
            _imagem_de_docx(documento, objeto.get("inlineObjectId"), objetos)


def _nivel_de_titulo(estilo: str) -> int | None:
    if estilo == "TITLE":
        return 0
    if estilo.startswith("HEADING_"):
        try:
            return min(int(estilo.split("_", 1)[1]), 9)
        except ValueError:
            return None
    return None


def _run_de_docx(paragrafo: object, run_info: dict) -> None:
    conteudo = run_info.get("content", "").rstrip("\n")
    if not conteudo:
        return
    run = paragrafo.add_run(conteudo)
    estilo = run_info.get("textStyle") or {}
    if estilo.get("bold"):
        run.bold = True
    if estilo.get("italic"):
        run.italic = True
    if estilo.get("underline"):
        run.underline = True
    if estilo.get("strikethrough"):
        run.font.strike = True
    tamanho = _tamanho_em_pontos(estilo.get("fontSize"))
    if tamanho is not None:
        run.font.size = tamanho


def _tamanho_em_pontos(font_size: dict | None) -> object | None:
    magnitude = (font_size or {}).get("magnitude")
    if not magnitude:
        return None
    from docx.shared import Pt

    return Pt(float(magnitude))


def _imagem_de_docx(documento: object, inline_id: str | None, objetos: dict) -> None:
    if not inline_id:
        return
    propriedades = (objetos.get(inline_id) or {}).get("inlineObjectProperties") or {}
    embutido = propriedades.get("embeddedObject") or {}
    uri = (embutido.get("imageProperties") or {}).get("contentUri")
    dados = _baixar_url(uri)
    if not dados:
        return
    try:
        documento.add_picture(io.BytesIO(dados))
    except Exception:  # noqa: BLE001 - formato de imagem que o python-docx não lê
        return


def _tabela_de_docx(documento: object, tabela: dict) -> None:
    linhas = tabela.get("tableRows") or []
    n_linhas = len(linhas)
    n_colunas = max((len(linha.get("tableCells") or []) for linha in linhas), default=0)
    if n_linhas == 0 or n_colunas == 0:
        return

    saida = documento.add_table(rows=n_linhas, cols=n_colunas)
    for i, linha in enumerate(linhas):
        for j, celula in enumerate(linha.get("tableCells") or []):
            if j >= n_colunas:
                continue
            textos = [
                _texto_de_paragrafo(elemento["paragraph"])
                for elemento in celula.get("content", [])
                if "paragraph" in elemento
            ]
            saida.cell(i, j).text = "\n".join(textos)


def _texto_de_paragrafo(paragrafo: dict) -> str:
    partes = [
        elemento["textRun"].get("content", "")
        for elemento in paragrafo.get("elements", [])
        if "textRun" in elemento
    ]
    return "".join(partes).rstrip("\n")


# --------------------------------------------------------------------------
# Planilhas (Sheets -> .xlsx)
# --------------------------------------------------------------------------


def planilha_para_xlsx(service: Resource, file_id: str, destino: Path) -> Path:
    """Reconstrói uma planilha do Google em ``.xlsx`` (valores e fórmulas)."""
    from openpyxl import Workbook

    meta = (
        service.spreadsheets()
        .get(spreadsheetId=file_id, fields="sheets.properties")
        .execute()
    )
    abas = meta.get("sheets") or []
    if not abas:
        raise ReconstrucaoIndisponivel("planilha sem abas legíveis")

    livro = Workbook()
    livro.remove(livro.active)
    for aba in abas:
        props = aba.get("properties") or {}
        titulo = props.get("title", "")
        planilha = livro.create_sheet(title=_titulo_valido(titulo))
        for linha in _valores_da_aba(service, file_id, titulo, props):
            planilha.append(linha)

    _salvar(livro, destino)
    return destino


# Linhas por requisição ao values.get. Abas maiores que isto são lidas em blocos
# para não devolver uma resposta gigante nem estourar a memória.
BLOCO_LINHAS = 5000


def _valores_da_aba(
    service: Resource, file_id: str, titulo: str, props: dict | None = None
) -> list[list]:
    """Valores de uma aba, com as fórmulas preservadas como texto.

    Abas pequenas são lidas de uma só vez. Abas com mais de ``BLOCO_LINHAS``
    linhas são lidas em blocos (``'Aba'!A1:Z5000``, ``'Aba'!A5001:Z10000``, ...),
    usando o ``gridProperties`` informado pela API.
    """
    referencia = _referencia(titulo)
    grade = (props or {}).get("gridProperties") or {}
    total = int(grade.get("rowCount") or 0)
    colunas = int(grade.get("columnCount") or 0)
    if total <= BLOCO_LINHAS or colunas <= 0:
        return _valores(service, file_id, referencia)

    ultima = _coluna_letra(colunas)
    valores: list[list] = []
    for inicio in range(1, total + 1, BLOCO_LINHAS):
        fim = min(inicio + BLOCO_LINHAS - 1, total)
        intervalo = f"{referencia}!A{inicio}:{ultima}{fim}"
        valores.extend(_valores(service, file_id, intervalo))
    return valores


def _referencia(titulo: str) -> str:
    """Nome da aba entre aspas simples, para usar como intervalo."""
    return "'" + titulo.replace("'", "''") + "'"


def _valores(service: Resource, file_id: str, intervalo: str) -> list[list]:
    """Uma chamada a ``spreadsheets.values.get`` com as fórmulas como texto."""
    resposta = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=file_id,
            range=intervalo,
            valueRenderOption="FORMULA",
        )
        .execute()
    )
    return resposta.get("values", [])


def _coluna_letra(numero: int) -> str:
    """Converte o índice de coluna (1 = A) para a letra correspondente."""
    letras = ""
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras or "A"


def _titulo_valido(titulo: str) -> str:
    """Ajusta o nome da aba às regras do Excel (até 31 caracteres, sem símbolos)."""
    limpo = re.sub(r"[\[\]:*?/\\]", "_", titulo or "").strip()
    return (limpo or "Planilha")[:31]


# --------------------------------------------------------------------------
# Despacho
# --------------------------------------------------------------------------

NATIVOS: dict[str, Especie] = {
    "application/vnd.google-apps.presentation": Especie(
        "slides", "v1", PRESENTATIONS_READONLY_SCOPE, ".pptx", slides_para_pptx
    ),
    "application/vnd.google-apps.document": Especie(
        "docs", "v1", DOCUMENTS_READONLY_SCOPE, ".docx", docs_para_docx
    ),
    "application/vnd.google-apps.spreadsheet": Especie(
        "sheets", "v4", SPREADSHEETS_READONLY_SCOPE, ".xlsx", planilha_para_xlsx
    ),
}

# Um cliente por API, criado sob demanda. A autenticação é feita uma única vez.
_servicos: dict[str, Resource] = {}


def _obter_servico(mime_type: str) -> Resource:
    especie = NATIVOS[mime_type]
    if especie.api not in _servicos:
        credenciais = build_credentials(scopes=[READONLY_SCOPE, especie.escopo])
        _servicos[especie.api] = build(
            especie.api,
            especie.versao,
            credentials=credenciais,
            cache_discovery=False,
        )
    return _servicos[especie.api]


def limpar_servicos() -> None:
    """Descarta os clientes em cache (útil em testes e após trocar a conta)."""
    _servicos.clear()


def extensao_de(mime_type: str) -> str:
    """Extensão editável correspondente ao tipo nativo, ou string vazia."""
    especie = NATIVOS.get(mime_type)
    return especie.extensao if especie else ""


def tem_reconstrutor(mime_type: str) -> bool:
    return mime_type in NATIVOS


def reconstruir(mime_type: str, file_id: str, destino: Path) -> Path:
    """Reconstrói o formato editável do arquivo em ``destino``.

    Levanta ``ReconstrucaoIndisponivel`` quando o tipo não tem reconstrutor.
    Qualquer outra exceção (API desabilitada, sem permissão, mídia ilegível)
    sobe para o chamador, que trata como "original só pela web".
    """
    especie = NATIVOS.get(mime_type)
    if especie is None:
        raise ReconstrucaoIndisponivel(f"tipo sem reconstrutor: {mime_type}")
    return especie.construtor(_obter_servico(mime_type), file_id, destino)
