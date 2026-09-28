from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FUNCOES_COM_APTIDAO, AptidaoFuncao, Pessoa, aptidao_exigida
from app.schemas import PessoaCreate, PessoaResponse

router = APIRouter(prefix="/pessoas", tags=["Pessoas"])


def _aplicar_aptidoes(pessoa: Pessoa, funcoes) -> None:
    """Substitui as funções que a pessoa pode assumir.

    ``None`` (campo ausente no corpo) mantém o comportamento antigo de apta a
    tudo; a lista, mesmo vazia, é gravada como veio.

    Mexe só na diferença de propósito. Recriar a coleção inteira faz o
    SQLAlchemy inserir a linha nova antes de apagar a antiga, e a unicidade
    (pessoa, função) derruba toda edição que mantenha alguma aptidão — que é
    justamente o caso comum de desmarcar uma ou duas.
    """
    # A posição extra da Limpeza 2 não tem aptidão própria: se vier na lista,
    # colapsa na aptidão da limpeza em vez de virar uma linha órfã.
    desejadas = (
        set(FUNCOES_COM_APTIDAO)
        if funcoes is None
        else {aptidao_exigida(funcao) for funcao in funcoes}
    )

    pessoa.aptidoes = [a for a in pessoa.aptidoes if a.funcao in desejadas]
    ja_marcadas = {a.funcao for a in pessoa.aptidoes}
    pessoa.aptidoes.extend(
        AptidaoFuncao(funcao=funcao)
        for funcao in FUNCOES_COM_APTIDAO
        if funcao in desejadas and funcao not in ja_marcadas
    )


@router.post("/", response_model=PessoaResponse)
def criar_pessoa(pessoa: PessoaCreate, db: Session = Depends(get_db)):
    existente = None
    if pessoa.email:
        existente = db.query(Pessoa).filter(Pessoa.email == pessoa.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="E-mail já cadastrado.")

    campos = pessoa.dict()
    funcoes_aptas = campos.pop("funcoes_aptas")
    nova_pessoa = Pessoa(**campos)
    _aplicar_aptidoes(nova_pessoa, funcoes_aptas)
    db.add(nova_pessoa)
    db.commit()
    db.refresh(nova_pessoa)
    return nova_pessoa


@router.get("/", response_model=list[PessoaResponse])
def listar_pessoas(db: Session = Depends(get_db)):
    return db.query(Pessoa).all()


@router.get("/{pessoa_id}", response_model=PessoaResponse)
def obter_pessoa(pessoa_id: int, db: Session = Depends(get_db)):
    pessoa = db.query(Pessoa).filter(Pessoa.id == pessoa_id).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")
    return pessoa


@router.put("/{pessoa_id}", response_model=PessoaResponse)
def atualizar_pessoa(
    pessoa_id: int, dados: PessoaCreate, db: Session = Depends(get_db)
):
    pessoa = db.query(Pessoa).filter(Pessoa.id == pessoa_id).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")

    campos = dados.dict()
    funcoes_aptas = campos.pop("funcoes_aptas")
    for campo, valor in campos.items():
        setattr(pessoa, campo, valor)
    _aplicar_aptidoes(pessoa, funcoes_aptas)

    db.commit()
    db.refresh(pessoa)
    return pessoa


@router.delete("/{pessoa_id}")
def deletar_pessoa(pessoa_id: int, db: Session = Depends(get_db)):
    pessoa = db.query(Pessoa).filter(Pessoa.id == pessoa_id).first()
    if not pessoa:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada.")

    db.delete(pessoa)
    db.commit()
    return {"detail": "Pessoa removida com sucesso."}
