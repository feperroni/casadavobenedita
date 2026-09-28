from sqlalchemy.orm import Session

from app.models import EscalaGira, Gira


def gerar_relatorio_gira(db: Session, gira_id: int) -> dict:
    """
    Monta o relatório completo de uma gira: dados da gira + escalas de quem
    esteve presente (quem faltou não entra no relatório de quem trabalhou).
    """
    gira = db.query(Gira).filter(Gira.id == gira_id).first()
    if not gira:
        return None

    escalas = (
        db.query(EscalaGira)
        .filter(EscalaGira.gira_id == gira_id, EscalaGira.presente.is_(True))
        .all()
    )

    return {
        "gira": gira,
        "escalas": escalas,
    }


def gerar_relatorio_texto(db: Session, gira_id: int) -> str:
    """
    Gera uma versão em texto simples do relatório, útil para impressão
    ou envio via WhatsApp/e-mail.
    """
    dados = gerar_relatorio_gira(db, gira_id)
    if not dados:
        return "Gira não encontrada."

    gira = dados["gira"]
    escalas = dados["escalas"]

    linhas = [
        f"Relatório da Gira - {gira.nome or gira.tipo.value}",
        f"Linha: {gira.tipo.value}",
        f"Data: {gira.data.strftime('%d/%m/%Y %H:%M')}",
        "",
        "Escala:",
    ]

    for escala in escalas:
        if escala.entidade:
            atuacao = (
                f"incorporando {escala.entidade.nome} ({escala.entidade.tipo.value})"
            )
        elif escala.atendeu:
            atuacao = "atendeu"
        else:
            atuacao = "sem atendimento"
        linhas.append(f"- {escala.pessoa.nome} ({escala.cargo.value}) {atuacao}")

    if gira.observacoes:
        linhas.append("")
        linhas.append(f"Observações: {gira.observacoes}")

    return "\n".join(linhas)
