"""Rodízio das funções operacionais da gira (porteiras e limpeza).

A carga é contada junto, não por função: quem acabou de fazer a Limpeza 1 vai
para o fim da fila de *todas* as posições, senão a pessoa cairia na Limpeza 2
na gira seguinte enquanto alguém ainda não tinha feito nada. Entre quem está
igualmente carregado, a preferência vai para quem já ficou mais tempo sem
trabalhar e para a função que a pessoa fez menos vezes, para variar as posições
em vez de fixar cada um num posto.

Só entram no rodízio médiuns de rodízio e cambonos ativos, e apenas nas funções
para as quais o cadastro os marca como aptos.
"""

from datetime import datetime
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.models import (
    CargoEnum,
    FuncaoGira,
    FuncaoOperacionalEnum,
    Gira,
    Pessoa,
    aptidao_exigida,
)

# Ordem de preenchimento; também evita a mesma pessoa em duas funções na gira.
ORDEM_FUNCOES = (
    FuncaoOperacionalEnum.PORTEIRA_ATENDIMENTO,
    FuncaoOperacionalEnum.PORTEIRA_SENHA,
    FuncaoOperacionalEnum.LIMPEZA_1,
    FuncaoOperacionalEnum.LIMPEZA_2,
    FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_2,
)

CARGOS_ELEGIVEIS = (CargoEnum.RODIZIO, CargoEnum.CAMBONO)

# Quem nunca trabalhou precisa vir antes de quem trabalhou na data mais antiga
# possível; com a contagem à frente no critério, o sentinela nunca desempata
# sozinho, só mantém a ordenação total bem definida.
# Ingênuo de propósito: compara com ``Gira.data``, que é DateTime sem timezone.
NUNCA = datetime.min  # noqa: DTZ901


class Historico(NamedTuple):
    """Quanto e quando cada pessoa trabalhou, no geral e por função."""

    vezes_total: dict[int, int]
    ultima_total: dict[int, datetime]
    vezes_funcao: dict[tuple[int, FuncaoOperacionalEnum], int]
    ultima_funcao: dict[tuple[int, FuncaoOperacionalEnum], datetime]


def elegiveis(db: Session) -> list[Pessoa]:
    return (
        db.query(Pessoa)
        .filter(Pessoa.ativo == 1, Pessoa.cargo.in_(CARGOS_ELEGIVEIS))
        .order_by(Pessoa.nome)
        .all()
    )


def _historico(db: Session, ignorar_gira_id: int | None) -> Historico:
    consulta = db.query(FuncaoGira, Gira.data).join(Gira, FuncaoGira.gira_id == Gira.id)
    # Ao reeditar uma gira, o que já está salvo nela não deve pesar na sugestão.
    if ignorar_gira_id is not None:
        consulta = consulta.filter(FuncaoGira.gira_id != ignorar_gira_id)

    historico = Historico({}, {}, {}, {})
    for registro, data in consulta.all():
        pessoa_id = registro.pessoa_id
        chave = (pessoa_id, registro.funcao)

        historico.vezes_total[pessoa_id] = historico.vezes_total.get(pessoa_id, 0) + 1
        historico.vezes_funcao[chave] = historico.vezes_funcao.get(chave, 0) + 1
        if data > historico.ultima_total.get(pessoa_id, NUNCA):
            historico.ultima_total[pessoa_id] = data
        if data > historico.ultima_funcao.get(chave, NUNCA):
            historico.ultima_funcao[chave] = data
    return historico


def _prioridade(pessoa: Pessoa, funcao: FuncaoOperacionalEnum, h: Historico) -> tuple:
    """Menor é melhor. A carga total manda; a função só desempata.

    Sem a contagem total à frente, cada função teria a própria fila e quem
    acabou de fazer a Limpeza 1 apareceria na Limpeza 2 na gira seguinte.
    """
    return (
        h.vezes_total.get(pessoa.id, 0),
        h.ultima_total.get(pessoa.id, NUNCA),
        h.vezes_funcao.get((pessoa.id, funcao), 0),
        h.ultima_funcao.get((pessoa.id, funcao), NUNCA),
        pessoa.nome or "",
    )


def sugerir(db: Session, ignorar_gira_id: int | None = None) -> list[dict]:
    """Uma sugestão por função, sempre pelo elegível mais "atrasado".

    O desempate final é o nome, de propósito determinístico, para a escala ser
    conferível pelo terreiro. Uma pessoa não ocupa duas funções na mesma gira,
    então com menos gente apta do que funções as últimas posições saem vazias.
    """
    pessoas = elegiveis(db)
    historico = _historico(db, ignorar_gira_id)
    ja_escolhidos: set[int] = set()
    sugestoes = []

    for funcao in ORDEM_FUNCOES:
        exigida = aptidao_exigida(funcao)
        disponiveis = [
            p
            for p in pessoas
            if p.id not in ja_escolhidos and exigida in p.funcoes_aptas
        ]
        escolhido = min(
            disponiveis,
            key=lambda p, f=funcao: _prioridade(p, f, historico),
            default=None,
        )
        if escolhido:
            ja_escolhidos.add(escolhido.id)
        sugestoes.append(
            {
                "funcao": funcao,
                "pessoa_id": escolhido.id if escolhido else None,
                "nome": escolhido.nome if escolhido else None,
            }
        )
    return sugestoes
