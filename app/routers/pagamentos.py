from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Pagamento, Pessoa, StatusPagamentoEnum
from app.schemas import (
    EvolucaoMensalResponse,
    PagamentoCreate,
    PagamentoResponse,
    ResumoFinanceiroResponse,
    StatusCompetenciaResponse,
)
from app.services.financeiro import evolucao_anual, resumo_mensal, status_por_pessoa

router = APIRouter(prefix="/pagamentos", tags=["Pagamentos"])


@router.post("/", response_model=PagamentoResponse)
def registrar_pagamento(dados: PagamentoCreate, db: Session = Depends(get_db)):
    """Cria ou atualiza o pagamento de um integrante em um mês/ano."""
    if not 1 <= dados.mes <= 12:
        raise HTTPException(status_code=400, detail="Mês deve estar entre 1 e 12.")

    pessoa = db.query(Pessoa).filter(Pessoa.id == dados.pessoa_id).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Integrante não encontrado.")

    pagamento = (
        db.query(Pagamento)
        .filter(
            Pagamento.pessoa_id == dados.pessoa_id,
            Pagamento.ano == dados.ano,
            Pagamento.mes == dados.mes,
        )
        .first()
    )
    if not pagamento:
        pagamento = Pagamento(**dados.dict())
        db.add(pagamento)
    else:
        for campo, valor in dados.dict().items():
            setattr(pagamento, campo, valor)

    if pagamento.status == StatusPagamentoEnum.PAGO and not pagamento.pago_em:
        pagamento.pago_em = date.today()

    db.commit()
    db.refresh(pagamento)
    return pagamento


@router.get("/", response_model=list[PagamentoResponse])
def listar_pagamentos(
    ano: int | None = None,
    mes: int | None = None,
    pessoa_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Pagamento)
    if ano is not None:
        query = query.filter(Pagamento.ano == ano)
    if mes is not None:
        query = query.filter(Pagamento.mes == mes)
    if pessoa_id is not None:
        query = query.filter(Pagamento.pessoa_id == pessoa_id)
    return query.all()


@router.get("/resumo", response_model=ResumoFinanceiroResponse)
def resumo_financeiro(
    ano: int = Query(...),
    mes: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    return resumo_mensal(db, ano, mes)


@router.get("/competencia", response_model=list[StatusCompetenciaResponse])
def status_da_competencia(
    ano: int = Query(...),
    mes: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Situação de cada integrante ativo no mês, com a isenção herdada."""
    return list(status_por_pessoa(db, ano, mes).values())


@router.get("/evolucao", response_model=list[EvolucaoMensalResponse])
def evolucao_financeira(ano: int = Query(...), db: Session = Depends(get_db)):
    return evolucao_anual(db, ano)


@router.delete("/{pagamento_id}")
def deletar_pagamento(pagamento_id: int, db: Session = Depends(get_db)):
    pagamento = db.query(Pagamento).filter(Pagamento.id == pagamento_id).first()
    if not pagamento:
        raise HTTPException(status_code=404, detail="Pagamento não encontrado.")

    db.delete(pagamento)
    db.commit()
    return {"detail": "Pagamento removido com sucesso."}
