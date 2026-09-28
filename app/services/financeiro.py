"""Cálculos do módulo financeiro: resumo mensal, inadimplência e evolução.

A isenção atravessa os meses; o pagamento, não. Quem foi marcado isento em
setembro segue isento em outubro sem ninguém remarcar, porque isenção é uma
condição que vale até alguém desfazer — tirar a isenção em outubro faz
novembro voltar a cobrar. Já "Pago" é fato de um mês só: propagá-lo daria a
todo mundo um mês seguinte quitado sem que ninguém tivesse pago.
"""

from sqlalchemy.orm import Session

from app.models import Pagamento, Pessoa, StatusPagamentoEnum


def _integrantes_ativos(db: Session) -> list[Pessoa]:
    return db.query(Pessoa).filter(Pessoa.ativo == 1).all()


def status_por_pessoa(db: Session, ano: int, mes: int) -> dict[int, dict]:
    """O que vale para cada pessoa no mês, com a isenção herdada já aplicada.

    Devolve, por pessoa: o lançamento do próprio mês (se houver), o status que
    vale e se ele veio por herança de um mês anterior — a UI precisa saber a
    diferença para não dar a entender que já existe lançamento gravado.
    """
    alvo = (ano, mes)
    do_mes: dict[int, Pagamento] = {}
    ultimo_anterior: dict[int, Pagamento] = {}

    # A carga é pequena (dezenas de pessoas por alguns anos) e assim a regra
    # fica em um lugar só, sem SQL que precise valer no SQLite e no Postgres.
    for pagamento in db.query(Pagamento).all():
        competencia = (pagamento.ano, pagamento.mes)
        if competencia == alvo:
            do_mes[pagamento.pessoa_id] = pagamento
        elif competencia < alvo:
            anterior = ultimo_anterior.get(pagamento.pessoa_id)
            if anterior is None or (anterior.ano, anterior.mes) < competencia:
                ultimo_anterior[pagamento.pessoa_id] = pagamento

    efetivo: dict[int, dict] = {}
    for pessoa in _integrantes_ativos(db):
        pagamento = do_mes.get(pessoa.id)
        if pagamento is not None:
            status, herdado = pagamento.status, False
        else:
            anterior = ultimo_anterior.get(pessoa.id)
            isento_antes = (
                anterior is not None and anterior.status == StatusPagamentoEnum.ISENTO
            )
            status = (
                StatusPagamentoEnum.ISENTO
                if isento_antes
                else StatusPagamentoEnum.PENDENTE
            )
            herdado = isento_antes
        efetivo[pessoa.id] = {
            "pessoa_id": pessoa.id,
            "status": status,
            "herdado": herdado,
            "valor": pagamento.valor if pagamento else None,
        }
    return efetivo


def resumo_mensal(db: Session, ano: int, mes: int) -> dict:
    """Resumo do mês: previsto, recebido, pendente e lista de inadimplentes."""
    integrantes = _integrantes_ativos(db)
    efetivo = status_por_pessoa(db, ano, mes)

    total_previsto = 0.0
    total_recebido = 0.0
    total_pendente = 0.0
    qtd_pagos = 0
    qtd_pendentes = 0
    inadimplentes = []

    for pessoa in integrantes:
        situacao = efetivo[pessoa.id]
        # Isento não entra nem no previsto: não é dívida esquecida, é quem o
        # terreiro decidiu não cobrar — inclusive quando a isenção foi herdada
        # de um mês anterior e ninguém relançou nada neste.
        if situacao["status"] == StatusPagamentoEnum.ISENTO:
            continue

        previsto = pessoa.mensalidade or 0.0
        total_previsto += previsto

        if situacao["status"] == StatusPagamentoEnum.PAGO:
            total_recebido += situacao["valor"] or 0.0
            qtd_pagos += 1
            continue

        # Só abate o que foi efetivamente pago; valor lançado como pendente não abate.
        devido = previsto
        total_pendente += max(devido, 0.0)
        qtd_pendentes += 1
        inadimplentes.append(
            {
                "pessoa_id": pessoa.id,
                "nome": pessoa.nome,
                "telefone": pessoa.telefone,
                "valor_devido": max(devido, 0.0),
                "status": situacao["status"],
            }
        )

    return {
        "ano": ano,
        "mes": mes,
        "total_previsto": total_previsto,
        "total_recebido": total_recebido,
        "total_pendente": total_pendente,
        "qtd_pagos": qtd_pagos,
        "qtd_pendentes": qtd_pendentes,
        "inadimplentes": inadimplentes,
    }


def evolucao_anual(db: Session, ano: int) -> list[dict]:
    """Total recebido por mês no ano informado (12 posições, sempre preenchidas)."""
    recebidos = {mes: 0.0 for mes in range(1, 13)}
    pagamentos = (
        db.query(Pagamento)
        .filter(Pagamento.ano == ano, Pagamento.status == StatusPagamentoEnum.PAGO)
        .all()
    )
    for pagamento in pagamentos:
        if 1 <= pagamento.mes <= 12:
            recebidos[pagamento.mes] += pagamento.valor or 0.0

    return [
        {"ano": ano, "mes": mes, "total_recebido": total}
        for mes, total in recebidos.items()
    ]
