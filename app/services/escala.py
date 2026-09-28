import random

from sqlalchemy.orm import Session

from app.models import CargoEnum, Entidade, EscalaGira, Gira, Pessoa


def gerar_escala_automatica(db: Session, gira: Gira) -> list[EscalaGira]:
    """
    Gera a escala de médiuns/entidades para uma gira, respeitando:
    - Médiuns fixos são sempre alocados.
    - Médiuns de rodízio são sorteados/alternados.
    - Cada médium só pode incorporar entidades do tipo da gira.
    """
    escalas_criadas = []

    # Busca médiuns fixos e de rodízio ativos
    fixos = (
        db.query(Pessoa).filter(Pessoa.cargo == CargoEnum.FIXO, Pessoa.ativo == 1).all()
    )
    rodizio = (
        db.query(Pessoa)
        .filter(Pessoa.cargo == CargoEnum.RODIZIO, Pessoa.ativo == 1)
        .all()
    )
    cambonos = (
        db.query(Pessoa)
        .filter(Pessoa.cargo == CargoEnum.CAMBONO, Pessoa.ativo == 1)
        .all()
    )

    # Sorteia parte dos médiuns de rodízio (ex: metade da lista)
    qtd_rodizio = max(1, len(rodizio) // 2)
    rodizio_selecionados = random.sample(rodizio, k=min(qtd_rodizio, len(rodizio)))

    medium_alocados = fixos + rodizio_selecionados

    for pessoa in medium_alocados:
        entidade = (
            db.query(Entidade)
            .filter(Entidade.medium_id == pessoa.id, Entidade.tipo == gira.tipo)
            .first()
        )
        if not entidade:
            continue  # médium não tem entidade compatível com esta gira

        escalas_criadas.append(
            EscalaGira(
                gira_id=gira.id,
                pessoa_id=pessoa.id,
                entidade_id=entidade.id,
                cargo=pessoa.cargo,
            )
        )

    # Aloca cambonos: entram sem entidade, pois atuam como suporte
    for cambono in cambonos:
        escalas_criadas.append(
            EscalaGira(
                gira_id=gira.id,
                pessoa_id=cambono.id,
                entidade_id=None,
                cargo=CargoEnum.CAMBONO,
            )
        )

    return escalas_criadas
