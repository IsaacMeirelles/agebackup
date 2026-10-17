"""Testes dos reconstrutores de arquivos nativos grandes.

Não chamam a API de verdade: usam serviços falsos que devolvem estruturas
parecidas com as das APIs do Slides, Docs e Sheets. O resultado é lido de volta
com python-pptx, python-docx e openpyxl, provando que o arquivo abre.
"""

import base64
import re

import pytest

from agebackup import reconstruir as mod
from agebackup.reconstruir import (
    ReconstrucaoIndisponivel,
    docs_para_docx,
    extensao_de,
    limpar_servicos,
    planilha_para_xlsx,
    reconstruir,
    slides_para_pptx,
    tem_reconstrutor,
)

# PNG 1x1 vermelho, válido, para exercitar a inclusão de imagem.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg=="
)


class _Req:
    def __init__(self, dados):
        self._dados = dados

    def execute(self):
        return self._dados


class _ServicoSlides:
    def __init__(self, apresentacao):
        self._apresentacao = apresentacao

    def presentations(self):
        return self

    def get(self, presentationId):
        return _Req(self._apresentacao)


class _ServicoDocs:
    def __init__(self, documento):
        self._documento = documento

    def documents(self):
        return self

    def get(self, documentId):
        return _Req(self._documento)


class _ServicoSheets:
    def __init__(self, meta, valores):
        self._meta = meta
        self._valores = valores
        self.intervalos = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if "range" not in kwargs:
            return _Req(self._meta)

        bruto = kwargs["range"]
        self.intervalos.append(bruto)
        titulo, _, celulas = bruto.partition("!")
        linhas = self._valores.get(titulo.strip("'"), [])
        if celulas:
            faixa = re.match(r"[A-Z]+(\d+):[A-Z]+(\d+)$", celulas)
            if faixa:
                inicio, fim = int(faixa.group(1)), int(faixa.group(2))
                linhas = linhas[inicio - 1 : fim]
        return _Req({"values": linhas})


def _texto_slides(*conteudos: str) -> dict:
    elementos = []
    for conteudo in conteudos:
        elementos.append({"textRun": {"content": conteudo}})
        elementos.append({"paragraphMarker": {}})
    return {"textElements": elementos}


def _elemento(propriedades: dict, **extra) -> dict:
    return {"elementProperties": propriedades, **extra}


def _dim(valor: int) -> dict:
    """Uma ``Dimension`` do Slides, como a API devolve."""
    return {"magnitude": valor, "unit": "EMU"}


# --------------------------------------------------------------------------
# Slides -> pptx
# --------------------------------------------------------------------------


def _apresentacao(elementos, largura=9_144_000, altura=5_143_500):
    return {
        "pageSize": {"width": _dim(largura), "height": _dim(altura)},
        "slides": [{"pageElements": elementos}],
    }


def test_slides_reconstroi_texto(tmp_path):
    servico = _ServicoSlides(
        _apresentacao(
            [
                _elemento(
                    {"size": {"width": _dim(3_000_000), "height": _dim(1_000_000)}},
                    shape={"text": _texto_slides("Titulo", "corpo")},
                )
            ]
        )
    )
    destino = tmp_path / "saida.pptx"

    slides_para_pptx(servico, "APRES", destino)

    from pptx import Presentation

    prs = Presentation(str(destino))
    textos = [
        forma.text_frame.text
        for slide in prs.slides
        for forma in slide.shapes
        if forma.has_text_frame
    ]
    juntos = "\n".join(textos)
    assert "Titulo" in juntos
    assert "corpo" in juntos


def test_slides_aplica_tamanho_da_pagina(tmp_path):
    servico = _ServicoSlides(_apresentacao([], largura=7_200_000, altura=5_400_000))
    destino = tmp_path / "saida.pptx"

    slides_para_pptx(servico, "APRES", destino)

    from pptx import Presentation

    prs = Presentation(str(destino))
    assert prs.slide_width == 7_200_000
    assert prs.slide_height == 5_400_000


def test_slides_inclui_imagem(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_baixar_url", lambda url: PNG if url else None)
    servico = _ServicoSlides(
        _apresentacao(
            [
                _elemento(
                    {"size": {"width": _dim(100), "height": _dim(100)}},
                    image={"contentUrl": "https://exemplo/img.png"},
                )
            ]
        )
    )
    destino = tmp_path / "saida.pptx"

    slides_para_pptx(servico, "APRES", destino)

    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(destino))
    tipos = {forma.shape_type for forma in prs.slides[0].shapes}
    assert MSO_SHAPE_TYPE.PICTURE in tipos


def test_slides_reconstroi_tabela(tmp_path):
    tabela = {
        "tableRows": [
            {
                "tableCells": [
                    {"text": _texto_slides("A")},
                    {"text": _texto_slides("B")},
                ]
            },
            {
                "tableCells": [
                    {"text": _texto_slides("C")},
                    {"text": _texto_slides("D")},
                ]
            },
        ]
    }
    servico = _ServicoSlides(
        _apresentacao(
            [
                _elemento(
                    {"size": {"width": _dim(2_000_000), "height": _dim(1_000_000)}},
                    table=tabela,
                )
            ]
        )
    )
    destino = tmp_path / "saida.pptx"

    slides_para_pptx(servico, "APRES", destino)

    from pptx import Presentation

    prs = Presentation(str(destino))
    formas = [f for f in prs.slides[0].shapes if f.has_table]
    assert len(formas) == 1
    assert formas[0].table.cell(0, 0).text == "A"
    assert formas[0].table.cell(1, 1).text == "D"


def test_slides_recursa_em_grupo(tmp_path):
    grupo = {
        "group": {
            "children": [
                _elemento(
                    {"size": {"width": _dim(1_000), "height": _dim(1_000)}},
                    shape={"text": _texto_slides("dentro do grupo")},
                )
            ]
        }
    }
    servico = _ServicoSlides(_apresentacao([grupo]))
    destino = tmp_path / "saida.pptx"

    slides_para_pptx(servico, "APRES", destino)

    from pptx import Presentation

    prs = Presentation(str(destino))
    textos = [f.text_frame.text for f in prs.slides[0].shapes if f.has_text_frame]
    assert "dentro do grupo" in textos


# --------------------------------------------------------------------------
# Docs -> docx
# --------------------------------------------------------------------------


def _documento(content):
    return {"body": {"content": content}, "inlineObjects": {}}


def test_docs_reconstroi_titulo_e_corpo(tmp_path):
    documento = _documento(
        [
            {
                "paragraph": {
                    "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    "elements": [{"textRun": {"content": "Capitulo\n"}}],
                }
            },
            {
                "paragraph": {
                    "elements": [
                        {"textRun": {"content": "Primeira frase. "}},
                        {
                            "textRun": {
                                "content": "Negrito",
                                "textStyle": {"bold": True},
                            }
                        },
                        {"textRun": {"content": "\n"}},
                    ]
                }
            },
        ]
    )
    destino = tmp_path / "saida.docx"

    docs_para_docx(_ServicoDocs(documento), "DOC", destino)

    from docx import Document

    doc = Document(str(destino))
    textos = [p.text for p in doc.paragraphs]
    assert "Capitulo" in textos
    assert "Primeira frase. Negrito" in textos
    assert doc.paragraphs[0].style.name == "Heading 1"


def test_docs_reconstroi_tabela(tmp_path):
    celula = lambda texto: {
        "content": [{"paragraph": {"elements": [{"textRun": {"content": texto}}]}}]
    }
    documento = _documento(
        [
            {
                "table": {
                    "tableRows": [
                        {"tableCells": [celula("H1"), celula("H2")]},
                        {"tableCells": [celula("a"), celula("b")]},
                    ]
                }
            }
        ]
    )
    destino = tmp_path / "saida.docx"

    docs_para_docx(_ServicoDocs(documento), "DOC", destino)

    from docx import Document

    doc = Document(str(destino))
    assert len(doc.tables) == 1
    tabela = doc.tables[0]
    assert tabela.cell(0, 0).text == "H1"
    assert tabela.cell(1, 1).text == "b"


# --------------------------------------------------------------------------
# Planilhas -> xlsx
# --------------------------------------------------------------------------


def test_planilha_reconstroi_valores_e_formulas(tmp_path):
    meta = {"sheets": [{"properties": {"title": "Dados"}}]}
    valores = {"Dados": [["nome", "total"], ["a", "=1+1"]]}
    destino = tmp_path / "saida.xlsx"

    planilha_para_xlsx(_ServicoSheets(meta, valores), "PLAN", destino)

    from openpyxl import load_workbook

    livro = load_workbook(str(destino))
    planilha = livro["Dados"]
    assert planilha["A1"].value == "nome"
    assert planilha["B2"].value == "=1+1"


def test_planilha_grande_le_em_blocos(tmp_path, monkeypatch):
    """Uma aba maior que BLOCO_LINHAS é lida em várias requisições."""
    monkeypatch.setattr(mod, "BLOCO_LINHAS", 2)
    meta = {
        "sheets": [
            {
                "properties": {
                    "title": "Dados",
                    "gridProperties": {"rowCount": 5, "columnCount": 2},
                }
            }
        ]
    }
    valores = {"Dados": [["a", "1"], ["b", "2"], ["c", "3"], ["d", "4"], ["e", "5"]]}
    servico = _ServicoSheets(meta, valores)
    destino = tmp_path / "saida.xlsx"

    planilha_para_xlsx(servico, "PLAN", destino)

    assert servico.intervalos == [
        "'Dados'!A1:B2",
        "'Dados'!A3:B4",
        "'Dados'!A5:B5",
    ]
    from openpyxl import load_workbook

    planilha = load_workbook(str(destino))["Dados"]
    assert planilha["A5"].value == "e"
    assert planilha["B4"].value == "4"


def test_planilha_ajusta_titulo_invalido(tmp_path):
    longo = "relatorio/muito:longo*com?simbolos[proibidos]e mais texto ainda"
    meta = {"sheets": [{"properties": {"title": longo}}]}
    destino = tmp_path / "saida.xlsx"

    planilha_para_xlsx(_ServicoSheets(meta, {}), "PLAN", destino)

    from openpyxl import load_workbook

    livro = load_workbook(str(destino))
    titulo = livro.sheetnames[0]
    assert len(titulo) <= 31
    assert not any(caractere in titulo for caractere in "[]:*?/\\")


def test_planilha_sem_abas_falha(tmp_path):
    with pytest.raises(ReconstrucaoIndisponivel):
        planilha_para_xlsx(
            _ServicoSheets({"sheets": []}, {}), "PLAN", tmp_path / "x.xlsx"
        )


# --------------------------------------------------------------------------
# Despacho e utilidades
# --------------------------------------------------------------------------


def test_extensao_e_disponibilidade():
    assert extensao_de("application/vnd.google-apps.presentation") == ".pptx"
    assert extensao_de("application/vnd.google-apps.document") == ".docx"
    assert extensao_de("application/vnd.google-apps.spreadsheet") == ".xlsx"
    assert extensao_de("text/plain") == ""
    assert tem_reconstrutor("application/vnd.google-apps.document")
    assert not tem_reconstrutor("application/vnd.google-apps.drawing")


def test_reconstruir_tipo_sem_reconstrutor(tmp_path):
    with pytest.raises(ReconstrucaoIndisponivel):
        reconstruir("text/plain", "X", tmp_path / "x.txt")


def test_reconstruir_despacha_para_o_servico(tmp_path, monkeypatch):
    documento = _documento(
        [{"paragraph": {"elements": [{"textRun": {"content": "oi"}}]}}]
    )
    monkeypatch.setattr(mod, "_obter_servico", lambda mime: _ServicoDocs(documento))
    destino = tmp_path / "saida.docx"

    reconstruir("application/vnd.google-apps.document", "DOC", destino)

    assert destino.exists()


def test_limpar_servicos_zera_cache():
    mod._servicos["docs"] = object()
    limpar_servicos()
    assert mod._servicos == {}


def test_salvar_nao_deixa_temporario(tmp_path):
    from openpyxl import Workbook

    destino = tmp_path / "saida.xlsx"
    livro = Workbook()

    mod._salvar(livro, destino)

    assert destino.exists()
    assert not list(tmp_path.glob("*.tmp"))
