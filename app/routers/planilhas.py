from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Pessoa, TipoGiraEnum
from app.services.funcoes import sugerir
from app.services.planilha import gerar_planilha_gira, nome_arquivo

router = APIRouter(prefix="/planilhas", tags=["Planilhas"])

TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/gira")
def planilha_da_gira(
    tipo: TipoGiraEnum = Query(..., description="Linha da gira"),
    data: date = Query(..., description="Data da gira (AAAA-MM-DD)"),
    db: Session = Depends(get_db),
):
    """Formulário imprimível: funções sugeridas + lista para preencher à mão.

    Não depende de a gira já existir no sistema — serve justamente para levar ao
    terreiro antes dela acontecer.
    """
    integrantes = db.query(Pessoa).filter(Pessoa.ativo == 1).order_by(Pessoa.nome).all()
    arquivo = gerar_planilha_gira(tipo, data, sugerir(db), integrantes)
    return StreamingResponse(
        arquivo,
        media_type=TIPO_XLSX,
        headers={
            "Content-Disposition": f'attachment; filename="{nome_arquivo(tipo, data)}"'
        },
    )
