from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Entidade,
    EscalaGira,
    FuncaoGira,
    Gira,
    Pessoa,
    aptidao_exigida,
    rotulo_aptidao,
)
from app.schemas import (
    EscalaGiraResponse,
    EscalaManualRequest,
    FuncaoGiraResponse,
    GiraCreate,
    GiraResponse,
    RelatorioGiraResponse,
    SugestaoFuncaoResponse,
)
from app.services.escala import gerar_escala_automatica
from app.services.funcoes import sugerir
from app.services.relatorio import gerar_relatorio_gira, gerar_relatorio_texto

router = APIRouter(prefix="/giras", tags=["Giras"])


@router.post("/", response_model=GiraResponse)
def criar_gira(gira: GiraCreate, db: Session = Depends(get_db)):
    nova_gira = Gira(**gira.dict())
    db.add(nova_gira)
    db.commit()
    db.refresh(nova_gira)
    return nova_gira


@router.get("/", response_model=list[GiraResponse])
def listar_giras(db: Session = Depends(get_db)):
    return db.query(Gira).all()


@router.get("/{gira_id}", response_model=GiraResponse)
def obter_gira(gira_id: int, db: Session = Depends(get_db)):
    gira = db.query(Gira).filter(Gira.id == gira_id).first()
    if not gira:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")
    return gira


@router.put("/{gira_id}", response_model=GiraResponse)
def atualizar_gira(gira_id: int, dados: GiraCreate, db: Session = Depends(get_db)):
    gira = db.query(Gira).filter(Gira.id == gira_id).first()
    if not gira:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")

    for campo, valor in dados.dict().items():
        setattr(gira, campo, valor)
    db.commit()
    db.refresh(gira)
    return gira


@router.delete("/{gira_id}")
def deletar_gira(gira_id: int, db: Session = Depends(get_db)):
    gira = db.query(Gira).filter(Gira.id == gira_id).first()
    if not gira:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")

    db.delete(gira)
    db.commit()
    return {"detail": "Gira removida com sucesso."}


@router.post("/{gira_id}/gerar-escala", response_model=list[EscalaGiraResponse])
def gerar_escala(gira_id: int, db: Session = Depends(get_db)):
    gira = db.query(Gira).filter(Gira.id == gira_id).first()
    if not gira:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")

    # Gera a nova escala antes de tocar na anterior: se a geração falhar,
    # a escala existente permanece intacta em vez de ser perdida.
    novas = gerar_escala_automatica(db, gira)
    if not novas:
        raise HTTPException(
            status_code=400,
            detail="Não foi possível gerar escala: verifique médiuns e entidades cadastradas.",
        )

    # Remove escalas anteriores para essa gira (evita duplicidade)
    db.query(EscalaGira).filter(EscalaGira.gira_id == gira_id).delete()
    db.add_all(novas)
    db.commit()
    for escala in novas:
        db.refresh(escala)

    return novas


@router.put("/{gira_id}/escala", response_model=list[EscalaGiraResponse])
def definir_escala(
    gira_id: int, dados: EscalaManualRequest, db: Session = Depends(get_db)
):
    """Substitui a escala da gira pelos trabalhadores informados pelo usuário.

    O cargo, quando omitido, vem do cadastro da pessoa. A entidade é opcional
    mesmo para quem atendeu — só entra quando o usuário sabe e informa qual
    guia incorporou. Quem não está na lista não some do registro: entra como
    falta, presente e atendeu ambos falsos, para a visão operacional mostrar
    quem faltou, não só quem esteve.
    """
    gira = db.query(Gira).filter(Gira.id == gira_id).first()
    if not gira:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")

    novas = []
    presentes_ids = set()
    for trabalhador in dados.trabalhadores:
        pessoa = db.query(Pessoa).filter(Pessoa.id == trabalhador.pessoa_id).first()
        if not pessoa:
            raise HTTPException(
                status_code=404,
                detail=f"Pessoa {trabalhador.pessoa_id} não encontrada.",
            )

        entidade_id = trabalhador.entidade_id if trabalhador.atendeu else None
        if entidade_id is not None:
            entidade = db.query(Entidade).filter(Entidade.id == entidade_id).first()
            if not entidade:
                raise HTTPException(status_code=404, detail="Entidade não encontrada.")
            if entidade.medium_id != pessoa.id:
                raise HTTPException(
                    status_code=400,
                    detail=f"{entidade.nome} não é guia de {pessoa.nome}.",
                )

        presentes_ids.add(pessoa.id)
        novas.append(
            EscalaGira(
                gira_id=gira.id,
                pessoa_id=pessoa.id,
                entidade_id=entidade_id,
                cargo=trabalhador.cargo or pessoa.cargo,
                presente=trabalhador.presente,
                atendeu=trabalhador.atendeu,
            )
        )

    faltantes = (
        db.query(Pessoa)
        .filter(Pessoa.ativo == 1, Pessoa.id.notin_(presentes_ids))
        .all()
    )
    for pessoa in faltantes:
        novas.append(
            EscalaGira(
                gira_id=gira.id,
                pessoa_id=pessoa.id,
                entidade_id=None,
                cargo=pessoa.cargo,
                presente=False,
                atendeu=False,
            )
        )

    novas_funcoes = _validar_funcoes(db, gira.id, dados.funcoes)

    db.query(EscalaGira).filter(EscalaGira.gira_id == gira_id).delete()
    db.query(FuncaoGira).filter(FuncaoGira.gira_id == gira_id).delete()
    db.add_all(novas)
    db.add_all(novas_funcoes)
    db.commit()
    for escala in novas:
        db.refresh(escala)
    return novas


def _validar_funcoes(db: Session, gira_id: int, funcoes) -> list[FuncaoGira]:
    """Uma função por vez, sem repetir a mesma função; só quem o cadastro marca apto.

    Uma pessoa pode ocupar várias funções na mesma gira — quem faz a limpeza
    também pode atender com guia, e o terreiro nem sempre tem gente sobrando
    para cada posição. Só a função em si não se repete (isso já é garantido
    pela unicidade (gira, função) no banco).

    A aptidão é cobrada de escalação nova, não do que já está gravado. Quem
    trabalhou numa gira e depois teve a aptidão retirada continua valendo
    naquela gira: a alternativa é o usuário não conseguir mais salvar a gira
    antiga por causa de uma mudança de cadastro feita depois — e nem apagar
    da história alguém que de fato trabalhou.
    """
    ja_salvas = {
        (registro.funcao, registro.pessoa_id)
        for registro in db.query(FuncaoGira).filter(FuncaoGira.gira_id == gira_id)
    }
    vistos_funcao: set = set()
    registros = []

    for item in funcoes:
        if item.funcao in vistos_funcao:
            raise HTTPException(
                status_code=400,
                detail=f"{item.funcao.value} foi informada mais de uma vez.",
            )

        pessoa = db.query(Pessoa).filter(Pessoa.id == item.pessoa_id).first()
        if not pessoa:
            raise HTTPException(
                status_code=404, detail=f"Pessoa {item.pessoa_id} não encontrada."
            )
        inedita = (item.funcao, item.pessoa_id) not in ja_salvas
        if inedita and aptidao_exigida(item.funcao) not in pessoa.funcoes_aptas:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{pessoa.nome} não está marcado como apto para "
                    f"{rotulo_aptidao(item.funcao)}."
                ),
            )

        vistos_funcao.add(item.funcao)
        registros.append(
            FuncaoGira(gira_id=gira_id, pessoa_id=pessoa.id, funcao=item.funcao)
        )

    return registros


@router.get("/funcoes/sugestoes", response_model=list[SugestaoFuncaoResponse])
def sugestoes_de_funcoes(gira_id: int | None = None, db: Session = Depends(get_db)):
    """Quem o rodízio indica para cada função operacional.

    Passe `gira_id` ao editar uma gira: o que já está salvo nela é ignorado,
    senão a própria escalação anterior empurraria a pessoa para o fim da fila.
    """
    return sugerir(db, ignorar_gira_id=gira_id)


@router.get("/{gira_id}/funcoes", response_model=list[FuncaoGiraResponse])
def listar_funcoes_da_gira(gira_id: int, db: Session = Depends(get_db)):
    return db.query(FuncaoGira).filter(FuncaoGira.gira_id == gira_id).all()


@router.get("/{gira_id}/relatorio", response_model=RelatorioGiraResponse)
def relatorio_gira(gira_id: int, db: Session = Depends(get_db)):
    dados = gerar_relatorio_gira(db, gira_id)
    if not dados:
        raise HTTPException(status_code=404, detail="Gira não encontrada.")
    return dados


@router.get("/{gira_id}/relatorio-texto")
def relatorio_gira_texto(gira_id: int, db: Session = Depends(get_db)):
    texto = gerar_relatorio_texto(db, gira_id)
    return {"relatorio": texto}
