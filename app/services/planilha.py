"""Planilha imprimível da gira.

Não é o relatório de uma gira já realizada: é o formulário que vai para o
terreiro. As funções operacionais já saem preenchidas com a sugestão do
rodízio; o resto é a lista de integrantes com a coluna "Função" em branco,
para anotar à mão quem trabalhou e onde. Depois esses dados voltam para o
sistema pelo cadastro da gira.
"""

import re
import unicodedata
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.models import Pessoa, TipoGiraEnum

COLUNAS = ("Nome do Médium", "Função")

_TITULO = Font(bold=True, size=14)
_SECAO = Font(bold=True, size=11)
_CABECALHO = Font(bold=True, color="FFFFFF")
_FUNDO_CABECALHO = PatternFill("solid", fgColor="4A5568")
_BORDA = Border(*[Side(style="thin", color="BBBBBB")] * 4)


def _linha_cabecalho(planilha, indice: int) -> None:
    for coluna, texto in enumerate(COLUNAS, start=1):
        celula = planilha.cell(row=indice, column=coluna, value=texto)
        celula.font = _CABECALHO
        celula.fill = _FUNDO_CABECALHO
        celula.alignment = Alignment(horizontal="center")
        celula.border = _BORDA


def _linha_dados(planilha, indice: int, nome: str, funcao: str) -> None:
    for coluna, texto in enumerate((nome, funcao), start=1):
        celula = planilha.cell(row=indice, column=coluna, value=texto)
        celula.border = _BORDA


def nome_arquivo(tipo: TipoGiraEnum, data: date) -> str:
    """Nome ASCII-safe: o cabeçalho Content-Disposition não aceita acento."""
    sem_acento = unicodedata.normalize("NFKD", tipo.value)
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    return f"gira-{slug}-{data.isoformat()}.xlsx"


def gerar_planilha_gira(
    tipo: TipoGiraEnum,
    data: date,
    sugestoes: list[dict],
    integrantes: list[Pessoa],
) -> BytesIO:
    livro = Workbook()
    planilha = livro.active
    planilha.title = "Gira"

    planilha["A1"] = f"Gira de {tipo.value}"
    planilha["A1"].font = _TITULO
    planilha["A2"] = f"Data: {data.strftime('%d/%m/%Y')}"
    planilha["A2"].font = Font(size=11)

    linha = 4
    planilha.cell(
        row=linha, column=1, value="FUNÇÕES OPERACIONAIS (sugestão do rodízio)"
    )
    planilha.cell(row=linha, column=1).font = _SECAO
    linha += 1
    _linha_cabecalho(planilha, linha)
    linha += 1
    for sugestao in sugestoes:
        _linha_dados(
            planilha,
            linha,
            sugestao["nome"] or "(sem elegível disponível)",
            sugestao["funcao"].value,
        )
        linha += 1

    linha += 1
    planilha.cell(row=linha, column=1, value="QUEM TRABALHOU NA GIRA (preencher à mão)")
    planilha.cell(row=linha, column=1).font = _SECAO
    linha += 1
    _linha_cabecalho(planilha, linha)
    linha += 1
    for pessoa in integrantes:
        _linha_dados(planilha, linha, pessoa.nome, "")
        linha += 1

    planilha.column_dimensions["A"].width = 38
    planilha.column_dimensions["B"].width = 32
    # Impressão: retrato, tudo na largura de uma página.
    planilha.page_setup.orientation = "portrait"
    planilha.page_setup.fitToWidth = 1
    planilha.sheet_properties.pageSetUpPr.fitToPage = True

    arquivo = BytesIO()
    livro.save(arquivo)
    arquivo.seek(0)
    return arquivo
