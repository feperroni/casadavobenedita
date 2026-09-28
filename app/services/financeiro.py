"""Cálculos do módulo financeiro: resumo mensal, inadimplência e evolução."""

from sqlalchemy.orm import Session

from app.models import Pagamento, Pessoa, StatusPagamentoEnum


def _integrantes_ativos(db: Session) -> list[Pessoa]:
    return db.query(Pessoa).filter(Pessoa.ativo == 1).all()


def resumo_mensal(db: Session, ano: int, mes: int) -> dict:
    """Resumo do mês: previsto, recebido, pendente e lista de inadimplentes."""
    integrantes = _integrantes_ativos(db)
    pagamentos = {
        p.pessoa_id: p
        for p in db.query(Pagamento)
        .filter(Pagamento.ano == ano, Pagamento.mes == mes)
        .all()
    }

    total_previsto = 0.0
    total_recebido = 0.0
    total_pendente = 0.0
    qtd_pagos = 0
    qtd_pendentes = 0
    inadimplentes = []

    for pessoa in integrantes:
        pagamento = pagamentos.get(pessoa.id)
        if pagamento and pagamento.status == StatusPagamentoEnum.ISENTO:
            continue

        previsto = pessoa.mensalidade or 0.0
        total_previsto += previsto

        if pagamento and pagamento.status == StatusPagamentoEnum.PAGO:
            total_recebido += pagamento.valor or 0.0
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
                "status": (
                    pagamento.status if pagamento else StatusPagamentoEnum.PENDENTE
                ),
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
