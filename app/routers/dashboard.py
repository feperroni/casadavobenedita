from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AreaEnum, Entidade, EscalaGira, Gira, Pessoa
from app.schemas import (
    IntegranteEspiritualResponse,
    OperacionalMensalResponse,
    VisaoGeralResponse,
)
from app.services.operacional import resumo_mensal

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/visao-geral", response_model=VisaoGeralResponse)
def visao_geral(db: Session = Depends(get_db)):
    """Números do terreiro: composição da corrente e atividade nas giras."""
    integrantes = db.query(Pessoa).filter(Pessoa.ativo == 1).all()
    por_area = {area: 0 for area in AreaEnum}
    for pessoa in integrantes:
        por_area[pessoa.area] = por_area.get(pessoa.area, 0) + 1

    giras = db.query(Gira).order_by(Gira.data.desc()).all()
    escalas = db.query(EscalaGira).all()

    ultimas_giras = []
    for gira in giras[:5]:
        da_gira = [e for e in escalas if e.gira_id == gira.id]
        ultimas_giras.append(
            {
                "gira_id": gira.id,
                "nome": gira.nome,
                "tipo": gira.tipo,
                "data": gira.data,
                "atenderam": len([e for e in da_gira if e.atendeu]),
                "presentes": len([e for e in da_gira if e.presente]),
            }
        )

    return {
        "total_integrantes": len(integrantes),
        "total_mediunidade": por_area.get(AreaEnum.MEDIUNIDADE, 0),
        "total_lideranca": por_area.get(AreaEnum.LIDERANCA, 0),
        "total_curimba": por_area.get(AreaEnum.CURIMBA, 0),
        "total_giras": len(giras),
        "total_entidades": db.query(Entidade).count(),
        "mediuns_que_atenderam": len({e.pessoa_id for e in escalas if e.atendeu}),
        "ultimas_giras": ultimas_giras,
    }


@router.get("/espiritual", response_model=list[IntegranteEspiritualResponse])
def visao_espiritual(db: Session = Depends(get_db)):
    """Cada integrante com os guias/entidades vinculados."""
    pessoas = db.query(Pessoa).order_by(Pessoa.nome).all()
    return [{"pessoa": pessoa, "entidades": pessoa.guias} for pessoa in pessoas]


@router.get("/operacional", response_model=OperacionalMensalResponse)
def visao_operacional(ano: int, mes: int, db: Session = Depends(get_db)):
    """Presença, atendimento e falta de cada integrante no mês informado."""
    return resumo_mensal(db, ano, mes)
