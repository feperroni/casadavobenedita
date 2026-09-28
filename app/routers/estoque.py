from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ItemEstoque, MovimentoEstoque, OrigemMovimentoEnum
from app.schemas import (
    ItemEstoqueCreate,
    ItemEstoqueResponse,
    ItemEstoqueUpdate,
    MovimentoEstoqueRequest,
    MovimentoEstoqueResponse,
    ResumoEstoqueResponse,
)
from app.services.estoque import definir_quantidade, registrar_movimento, resumo

router = APIRouter(prefix="/estoque", tags=["Estoque"])


def _buscar(db: Session, item_id: int) -> ItemEstoque:
    item = db.query(ItemEstoque).filter(ItemEstoque.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado.")
    return item


def _recusar_nome_repetido(db: Session, nome: str, ignorar_id: int | None) -> None:
    """Nome duplicado confunde a conferência e atrapalharia a leitura por foto."""
    consulta = db.query(ItemEstoque).filter(ItemEstoque.nome == nome)
    if ignorar_id is not None:
        consulta = consulta.filter(ItemEstoque.id != ignorar_id)
    if consulta.first():
        raise HTTPException(
            status_code=400, detail=f"Já existe um item chamado {nome}."
        )


@router.get("/resumo", response_model=ResumoEstoqueResponse)
def resumo_estoque(db: Session = Depends(get_db)):
    return resumo(db)


@router.get("/itens", response_model=list[ItemEstoqueResponse])
def listar_itens(db: Session = Depends(get_db)):
    return db.query(ItemEstoque).order_by(ItemEstoque.nome).all()


@router.post("/itens", response_model=ItemEstoqueResponse)
def criar_item(dados: ItemEstoqueCreate, db: Session = Depends(get_db)):
    nome = dados.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="O item precisa de um nome.")
    _recusar_nome_repetido(db, nome, ignorar_id=None)

    campos = dados.dict()
    quantidade_inicial = campos.pop("quantidade")
    item = ItemEstoque(**{**campos, "nome": nome, "quantidade": 0})
    db.add(item)
    # O saldo inicial entra como movimento para o histórico começar completo,
    # em vez de o item nascer com um número que ninguém sabe de onde veio.
    if quantidade_inicial:
        registrar_movimento(
            db, item, quantidade_inicial, motivo="Cadastro inicial do item"
        )
    db.commit()
    db.refresh(item)
    return item


@router.get("/itens/{item_id}", response_model=ItemEstoqueResponse)
def obter_item(item_id: int, db: Session = Depends(get_db)):
    return _buscar(db, item_id)


@router.put("/itens/{item_id}", response_model=ItemEstoqueResponse)
def atualizar_item(
    item_id: int, dados: ItemEstoqueUpdate, db: Session = Depends(get_db)
):
    """Edita o cadastro. A quantidade não entra aqui — ela muda por movimento."""
    item = _buscar(db, item_id)
    nome = dados.nome.strip()
    if not nome:
        raise HTTPException(status_code=400, detail="O item precisa de um nome.")
    _recusar_nome_repetido(db, nome, ignorar_id=item_id)

    for campo, valor in dados.dict().items():
        setattr(item, campo, valor)
    item.nome = nome
    db.commit()
    db.refresh(item)
    return item


@router.delete("/itens/{item_id}")
def remover_item(item_id: int, db: Session = Depends(get_db)):
    item = _buscar(db, item_id)
    db.delete(item)
    db.commit()
    return {"detail": "Item removido com sucesso."}


@router.post("/itens/{item_id}/movimentos", response_model=ItemEstoqueResponse)
def movimentar_item(
    item_id: int, dados: MovimentoEstoqueRequest, db: Session = Depends(get_db)
):
    """Recontagem (``quantidade``) ou ajuste avulso (``delta``)."""
    item = _buscar(db, item_id)
    if (dados.quantidade is None) == (dados.delta is None):
        raise HTTPException(
            status_code=400,
            detail="Informe quantidade (recontagem) ou delta (ajuste), não os dois.",
        )

    if dados.quantidade is not None:
        definir_quantidade(
            db, item, dados.quantidade, OrigemMovimentoEnum.MANUAL, dados.motivo
        )
    else:
        registrar_movimento(
            db, item, dados.delta, OrigemMovimentoEnum.MANUAL, dados.motivo
        )
    db.commit()
    db.refresh(item)
    return item


@router.get(
    "/itens/{item_id}/movimentos", response_model=list[MovimentoEstoqueResponse]
)
def listar_movimentos(item_id: int, db: Session = Depends(get_db)):
    _buscar(db, item_id)
    return (
        db.query(MovimentoEstoque)
        .filter(MovimentoEstoque.item_id == item_id)
        .order_by(MovimentoEstoque.id.desc())
        .all()
    )
