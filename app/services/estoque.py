"""Regras do estoque do terreiro.

Inventário periódico: o saldo vale da última contagem, e muda quando alguém
reconta ou lança um ajuste. Não há baixa automática por gira — exigiria que
todo uso fosse registrado, e um controle assim pela metade é pior que um
honestamente aproximado, porque entrega número preciso e errado.

Todo movimento passa por aqui. É o que mantém ``ItemEstoque.quantidade`` e o
histórico de ``MovimentoEstoque`` contando a mesma história.
"""

from sqlalchemy.orm import Session

from app.models import ItemEstoque, MovimentoEstoque, OrigemMovimentoEnum


def registrar_movimento(
    db: Session,
    item: ItemEstoque,
    delta: int,
    origem: OrigemMovimentoEnum = OrigemMovimentoEnum.MANUAL,
    motivo: str | None = None,
) -> MovimentoEstoque:
    """Soma ``delta`` ao saldo e deixa o rastro do que aconteceu.

    O saldo nunca fica negativo: o terreiro não tem como ter menos que nada na
    prateleira, e um número negativo só esconderia um erro de contagem.
    """
    quantidade_nova = max((item.quantidade or 0) + delta, 0)
    delta_efetivo = quantidade_nova - (item.quantidade or 0)

    item.quantidade = quantidade_nova
    movimento = MovimentoEstoque(
        item=item,
        delta=delta_efetivo,
        quantidade_apos=quantidade_nova,
        origem=origem,
        motivo=motivo,
    )
    db.add(movimento)
    return movimento


def definir_quantidade(
    db: Session,
    item: ItemEstoque,
    quantidade: int,
    origem: OrigemMovimentoEnum = OrigemMovimentoEnum.MANUAL,
    motivo: str | None = None,
) -> MovimentoEstoque | None:
    """Recontagem: grava o número que a pessoa viu na prateleira.

    Devolve ``None`` quando o número não mudou — recontar e achar o mesmo saldo
    não é um movimento, e poluiria o histórico sem dizer nada.
    """
    alvo = max(quantidade, 0)
    if alvo == (item.quantidade or 0):
        return None
    return registrar_movimento(db, item, alvo - (item.quantidade or 0), origem, motivo)


def itens_em_alerta(db: Session) -> list[ItemEstoque]:
    """Itens que chegaram ao mínimo definido, dos mais críticos para os menos."""
    itens = [
        item
        for item in db.query(ItemEstoque).order_by(ItemEstoque.nome).all()
        if item.em_alerta
    ]
    # Quem está mais longe do próprio mínimo aparece primeiro; o nome desempata
    # para a lista não dançar entre um carregamento e outro.
    return sorted(itens, key=lambda i: (i.quantidade - i.minimo_alerta, i.nome or ""))


def resumo(db: Session) -> dict:
    em_alerta = itens_em_alerta(db)
    return {
        "total_itens": db.query(ItemEstoque).count(),
        "qtd_em_alerta": len(em_alerta),
        "itens_em_alerta": em_alerta,
    }
