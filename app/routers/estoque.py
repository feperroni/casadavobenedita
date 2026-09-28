from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ItemEstoque, MovimentoEstoque, OrigemMovimentoEnum
from app.schemas import (
    AplicarLeituraRequest,
    ItemEstoqueCreate,
    ItemEstoqueResponse,
    ItemEstoqueUpdate,
    LeituraFotoResponse,
    MovimentoEstoqueRequest,
    MovimentoEstoqueResponse,
    ResumoEstoqueResponse,
)
from app.services import visao_estoque
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


@router.get("/leitura-foto/disponivel")
def leitura_por_foto_disponivel():
    """A UI usa para só mostrar o botão quando a chave está configurada."""
    return {"disponivel": visao_estoque.configurada()}


@router.post("/leitura-foto", response_model=LeituraFotoResponse)
async def ler_estoque_por_foto(
    fotos: list[UploadFile] = File(...), db: Session = Depends(get_db)
):
    """Analisa as fotos e devolve uma proposta — não grava nada.

    Só vira saldo quando o usuário conferir e mandar aplicar.
    """
    # Itens que a foto não consegue contar (erva, folha, ensacado) ficam de
    # fora: pedir para a IA adivinhá-los só geraria número errado para conferir.
    catalogo = (
        db.query(ItemEstoque)
        .filter(ItemEstoque.contar_por_foto.is_(True))
        .order_by(ItemEstoque.nome)
        .all()
    )

    imagens = [(await foto.read(), foto.content_type) for foto in fotos]
    try:
        proposta = visao_estoque.analisar(imagens, catalogo)
    except visao_estoque.VisaoIndisponivelError as erro:
        raise HTTPException(status_code=503, detail=str(erro)) from erro

    por_id = {item.id: item for item in catalogo}
    encontrados = []
    vistos: set[int] = set()
    for lido in proposta.get("encontrados", []):
        item = por_id.get(lido.get("item_id"))
        # Id que não existe no catálogo enviado é descartado em silêncio: não
        # há item real para conferir contra ele.
        if item is None or item.id in vistos:
            continue
        vistos.add(item.id)
        encontrados.append(
            {
                "item_id": item.id,
                "nome": item.nome,
                "unidade": item.unidade,
                "quantidade_atual": item.quantidade,
                "quantidade_lida": max(int(lido.get("quantidade") or 0), 0),
                "confianca": lido.get("confianca") or "media",
                "observacao": (lido.get("observacao") or "").strip() or None,
            }
        )

    return {
        "encontrados": encontrados,
        "novos": [
            {
                "nome": (novo.get("nome") or "").strip(),
                "quantidade": max(int(novo.get("quantidade") or 0), 0),
                "unidade": (novo.get("unidade") or "unidade").strip() or "unidade",
                "categoria": (novo.get("categoria") or "").strip() or None,
                "confianca": novo.get("confianca") or "media",
            }
            for novo in proposta.get("novos", [])
            if (novo.get("nome") or "").strip()
        ],
        # O que não apareceu fica como está. Zerar seria o pior erro possível:
        # a foto mostra uma prateleira, não o estoque inteiro.
        "nao_apareceram": [
            {
                "item_id": item.id,
                "nome": item.nome,
                "unidade": item.unidade,
                "quantidade_atual": item.quantidade,
            }
            for item in catalogo
            if item.id not in vistos
        ],
    }


@router.post("/leitura-foto/aplicar", response_model=list[ItemEstoqueResponse])
def aplicar_leitura(dados: AplicarLeituraRequest, db: Session = Depends(get_db)):
    """Grava as linhas que o usuário aceitou, já com os números que ele revisou.

    Item do catálogo é recontado; o que a foto viu de novo entra cadastrado,
    com o nome que o usuário conferiu na tela. Nada aqui é automático: só
    chega o que ele marcou.
    """
    for ajuste in dados.ajustes:
        if (ajuste.item_id is None) == (ajuste.nome is None):
            raise HTTPException(
                status_code=400,
                detail="Cada ajuste precisa de item_id (existente) ou nome (novo).",
            )

    for ajuste in dados.ajustes:
        quantidade = max(ajuste.quantidade, 0)
        if ajuste.item_id is not None:
            item = _buscar(db, ajuste.item_id)
            definir_quantidade(
                db, item, quantidade, OrigemMovimentoEnum.FOTO, "Leitura por foto"
            )
            continue

        nome = ajuste.nome.strip()
        if not nome:
            raise HTTPException(status_code=400, detail="Item novo sem nome.")
        _recusar_nome_repetido(db, nome, ignorar_id=None)
        item = ItemEstoque(
            nome=nome,
            categoria=ajuste.categoria,
            unidade=ajuste.unidade or "unidade",
            quantidade=0,
        )
        db.add(item)
        if quantidade:
            registrar_movimento(
                db, item, quantidade, OrigemMovimentoEnum.FOTO, "Leitura por foto"
            )

    db.commit()
    return db.query(ItemEstoque).order_by(ItemEstoque.nome).all()
