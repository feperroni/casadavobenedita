from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Entidade, Pessoa
from app.schemas import EntidadeCreate, EntidadeResponse

router = APIRouter(prefix="/entidades", tags=["Entidades"])


@router.post("/", response_model=EntidadeResponse)
def criar_entidade(entidade: EntidadeCreate, db: Session = Depends(get_db)):
    medium = db.query(Pessoa).filter(Pessoa.id == entidade.medium_id).first()
    if not medium:
        raise HTTPException(status_code=404, detail="Médium não encontrado.")

    nova_entidade = Entidade(**entidade.dict())
    db.add(nova_entidade)
    db.commit()
    db.refresh(nova_entidade)
    return nova_entidade


@router.get("/", response_model=list[EntidadeResponse])
def listar_entidades(db: Session = Depends(get_db)):
    return db.query(Entidade).all()


@router.get("/{entidade_id}", response_model=EntidadeResponse)
def obter_entidade(entidade_id: int, db: Session = Depends(get_db)):
    entidade = db.query(Entidade).filter(Entidade.id == entidade_id).first()
    if not entidade:
        raise HTTPException(status_code=404, detail="Entidade não encontrada.")
    return entidade


@router.get("/medium/{medium_id}", response_model=list[EntidadeResponse])
def listar_entidades_por_medium(medium_id: int, db: Session = Depends(get_db)):
    return db.query(Entidade).filter(Entidade.medium_id == medium_id).all()


@router.put("/{entidade_id}", response_model=EntidadeResponse)
def atualizar_entidade(
    entidade_id: int, dados: EntidadeCreate, db: Session = Depends(get_db)
):
    entidade = db.query(Entidade).filter(Entidade.id == entidade_id).first()
    if not entidade:
        raise HTTPException(status_code=404, detail="Entidade não encontrada.")

    for campo, valor in dados.dict().items():
        setattr(entidade, campo, valor)

    db.commit()
    db.refresh(entidade)
    return entidade


@router.delete("/{entidade_id}")
def deletar_entidade(entidade_id: int, db: Session = Depends(get_db)):
    entidade = db.query(Entidade).filter(Entidade.id == entidade_id).first()
    if not entidade:
        raise HTTPException(status_code=404, detail="Entidade não encontrada.")

    db.delete(entidade)
    db.commit()
    return {"detail": "Entidade removida com sucesso."}
