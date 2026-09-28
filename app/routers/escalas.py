from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Entidade, EscalaGira, Gira, Pessoa
from app.schemas import EscalaGiraCreate, EscalaGiraResponse, PresencaUpdate

router = APIRouter(prefix="/escalas", tags=["Escalas"])


@router.post("/", response_model=EscalaGiraResponse)
def criar_escala(escala: EscalaGiraCreate, db: Session = Depends(get_db)):
    gira = db.query(Gira).filter(Gira.id == escala.gira_id).first()
    if not gira:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")

    pessoa = db.query(Pessoa).filter(Pessoa.id == escala.pessoa_id).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")

    if escala.entidade_id is not None:
        entidade = db.query(Entidade).filter(Entidade.id == escala.entidade_id).first()
        if not entidade:
            raise HTTPException(status_code=404, detail="Entidade não encontrada.")

    nova_escala = EscalaGira(**escala.dict())
    db.add(nova_escala)
    db.commit()
    db.refresh(nova_escala)
    return nova_escala


@router.get("/", response_model=list[EscalaGiraResponse])
def listar_escalas(db: Session = Depends(get_db)):
    return db.query(EscalaGira).all()


@router.get("/{escala_id}", response_model=EscalaGiraResponse)
def obter_escala(escala_id: int, db: Session = Depends(get_db)):
    escala = db.query(EscalaGira).filter(EscalaGira.id == escala_id).first()
    if not escala:
        raise HTTPException(status_code=404, detail="Escala não encontrada.")
    return escala


@router.get("/gira/{gira_id}", response_model=list[EscalaGiraResponse])
def listar_escalas_por_gira(gira_id: int, db: Session = Depends(get_db)):
    return db.query(EscalaGira).filter(EscalaGira.gira_id == gira_id).all()


@router.patch("/{escala_id}/presenca", response_model=EscalaGiraResponse)
def marcar_presenca(
    escala_id: int, dados: PresencaUpdate, db: Session = Depends(get_db)
):
    escala = db.query(EscalaGira).filter(EscalaGira.id == escala_id).first()
    if not escala:
        raise HTTPException(status_code=404, detail="Escala não encontrada.")

    escala.presente = dados.presente
    db.commit()
    db.refresh(escala)
    return escala


@router.delete("/{escala_id}")
def deletar_escala(escala_id: int, db: Session = Depends(get_db)):
    escala = db.query(EscalaGira).filter(EscalaGira.id == escala_id).first()
    if not escala:
        raise HTTPException(status_code=404, detail="Escala não encontrada.")

    db.delete(escala)
    db.commit()
    return {"detail": "Escala removida com sucesso."}
