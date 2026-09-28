"""Presença, atendimento e falta nas giras, mês a mês.

Salvar uma gira grava uma linha por integrante ativo — presente ou faltante —,
então o mês inteiro é só uma soma dessas linhas, sem precisar cruzar nada.

Quem entrou no terreiro depois de uma gira não tem linha nela. Os números
falam, portanto, das giras em que a pessoa já estava cadastrada, e não do
calendário inteiro: alguém que chegou no meio do mês não aparece com faltas
nas giras anteriores à própria entrada.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import EscalaGira, FuncaoGira, FuncaoOperacionalEnum, Gira, Pessoa

# Ordem de exibição dentro de cada categoria — a mesma ordem em que as posições
# são declaradas no enum, para a Pessoa 1 sempre aparecer antes da Pessoa 2/3.
POSICOES_LIMPEZA_1 = (
    FuncaoOperacionalEnum.LIMPEZA_1,
    FuncaoOperacionalEnum.LIMPEZA_1_PESSOA_2,
)
POSICOES_LIMPEZA_2 = (
    FuncaoOperacionalEnum.LIMPEZA_2,
    FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_2,
    FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_3,
)

# Cada coluna de função da tabela por integrante e as posições que a alimentam.
# Fica num lugar só: acrescentar uma coluna nova é mexer aqui, e não em vários
# pontos que precisariam concordar sobre quais chaves existem.
FUNCOES_CONTADAS = {
    "porteira_atendimento": (FuncaoOperacionalEnum.PORTEIRA_ATENDIMENTO,),
    "porteira_senha": (FuncaoOperacionalEnum.PORTEIRA_SENHA,),
    "limpeza_1": POSICOES_LIMPEZA_1,
    "limpeza_2": POSICOES_LIMPEZA_2,
}


def _intervalo_do_mes(ano: int, mes: int) -> tuple[datetime, datetime]:
    """Início do mês e início do seguinte, para um intervalo meio-aberto.

    Meio-aberto (``>= inicio``, ``< fim``) em vez de comparar ano e mês
    separadamente: assim a consulta continua usando o índice de ``Gira.data`` e
    não depende de função de data, que muda de nome entre SQLite e PostgreSQL.

    Ingênuo de propósito: compara com ``Gira.data``, DateTime sem timezone.
    """
    inicio = datetime(ano, mes, 1)  # noqa: DTZ001
    fim = (
        datetime(ano + 1, 1, 1)  # noqa: DTZ001
        if mes == 12
        else datetime(ano, mes + 1, 1)  # noqa: DTZ001
    )
    return inicio, fim


def resumo_mensal(db: Session, ano: int, mes: int) -> dict:
    """Giras do mês e o que cada integrante fez em cada uma delas."""
    inicio, fim = _intervalo_do_mes(ano, mes)
    giras = (
        db.query(Gira)
        .filter(Gira.data >= inicio, Gira.data < fim)
        .order_by(Gira.data)
        .all()
    )

    ids = [gira.id for gira in giras]
    escalas = (
        db.query(EscalaGira).filter(EscalaGira.gira_id.in_(ids)).all() if ids else []
    )
    funcoes = (
        db.query(FuncaoGira).filter(FuncaoGira.gira_id.in_(ids)).all() if ids else []
    )
    # Por gira, quem ocupa cada posição — para montar a lista de nomes de cada
    # coluna (porteiras e limpezas) sem repetir a consulta por gira.
    funcao_por_gira: dict[int, dict[FuncaoOperacionalEnum, str]] = {}
    for funcao_gira in funcoes:
        funcao_por_gira.setdefault(funcao_gira.gira_id, {})[
            funcao_gira.funcao
        ] = funcao_gira.pessoa.nome

    def _nomes_da_funcao(gira_id: int, posicoes: tuple) -> list[str]:
        ocupantes = funcao_por_gira.get(gira_id, {})
        return [ocupantes[posicao] for posicao in posicoes if posicao in ocupantes]

    # Por pessoa, quantas vezes no mês ela ocupou cada função (porteiras e
    # limpezas). Quem ocupou duas funções na mesma gira conta nas duas colunas.
    funcoes_por_pessoa: dict[int, dict[str, int]] = {}
    for funcao_gira in funcoes:
        contadores = funcoes_por_pessoa.setdefault(
            funcao_gira.pessoa_id, dict.fromkeys(FUNCOES_CONTADAS, 0)
        )
        for coluna, posicoes in FUNCOES_CONTADAS.items():
            if funcao_gira.funcao in posicoes:
                contadores[coluna] += 1

    por_gira = []
    for gira in giras:
        da_gira = [e for e in escalas if e.gira_id == gira.id]
        por_gira.append(
            {
                "gira_id": gira.id,
                "nome": gira.nome,
                "tipo": gira.tipo,
                "data": gira.data,
                "presentes": len([e for e in da_gira if e.presente]),
                "atenderam": len([e for e in da_gira if e.atendeu]),
                "faltaram": len([e for e in da_gira if not e.presente]),
                **{
                    coluna: _nomes_da_funcao(gira.id, posicoes)
                    for coluna, posicoes in FUNCOES_CONTADAS.items()
                },
            }
        )

    contagem: dict[int, dict] = {}
    for escala in escalas:
        do_integrante = contagem.setdefault(
            escala.pessoa_id, {"presencas": 0, "atendimentos": 0, "faltas": 0}
        )
        if escala.presente:
            do_integrante["presencas"] += 1
        else:
            do_integrante["faltas"] += 1
        if escala.atendeu:
            do_integrante["atendimentos"] += 1

    # Só quem tem linha no mês. Integrante cadastrado depois da última gira do
    # mês apareceria zerado em tudo, o que não é uma informação — é ruído.
    pessoas = (
        db.query(Pessoa).filter(Pessoa.id.in_(contagem)).order_by(Pessoa.nome).all()
        if contagem
        else []
    )

    return {
        "ano": ano,
        "mes": mes,
        "total_giras": len(giras),
        "giras": por_gira,
        "integrantes": [
            {
                "pessoa_id": pessoa.id,
                "nome": pessoa.nome,
                "cargo": pessoa.cargo,
                **contagem[pessoa.id],
                **funcoes_por_pessoa.get(pessoa.id, dict.fromkeys(FUNCOES_CONTADAS, 0)),
            }
            for pessoa in pessoas
        ],
    }
