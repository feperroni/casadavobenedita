"""Módulo de mensagens reutilizável (financeiro, avisos de gira, etc.).

O envio é feito por link `wa.me`: a API devolve, para cada destinatário, uma URL
que abre o WhatsApp com a mensagem já preenchida. Não requer credenciais.
"""

import re
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models import Pessoa

DDI_PADRAO = "55"


def normalizar_telefone(telefone: str) -> str:
    """Converte o telefone para o formato aceito pelo wa.me (só dígitos, com DDI)."""
    digitos = re.sub(r"\D", "", telefone or "")
    if not digitos:
        return ""
    digitos = digitos.removeprefix("00")
    if len(digitos) <= 11 and not digitos.startswith(DDI_PADRAO):
        digitos = DDI_PADRAO + digitos
    return digitos


def montar_link_whatsapp(telefone: str, mensagem: str) -> str:
    return f"https://wa.me/{normalizar_telefone(telefone)}?text={quote(mensagem)}"


def personalizar(mensagem: str, pessoa: Pessoa) -> str:
    """Substitui os marcadores disponíveis na mensagem."""
    substituicoes = {
        "{nome}": pessoa.nome or "",
        "{primeiro_nome}": (pessoa.nome or "").split(" ")[0],
        "{valor}": f"{pessoa.mensalidade:.2f}".replace(".", ","),
    }
    for marcador, valor in substituicoes.items():
        mensagem = mensagem.replace(marcador, valor)
    return mensagem


def preparar_mensagens(db: Session, pessoa_ids: list[int], mensagem: str) -> list[dict]:
    """Monta a lista de destinatários com os links de WhatsApp prontos."""
    destinatarios = []
    for pessoa_id in pessoa_ids:
        pessoa = db.query(Pessoa).filter(Pessoa.id == pessoa_id).first()
        if not pessoa:
            destinatarios.append(
                {
                    "pessoa_id": pessoa_id,
                    "nome": "(não encontrado)",
                    "mensagem": mensagem,
                    "erro": "Integrante não encontrado.",
                }
            )
            continue

        texto = personalizar(mensagem, pessoa)
        if not normalizar_telefone(pessoa.telefone):
            destinatarios.append(
                {
                    "pessoa_id": pessoa.id,
                    "nome": pessoa.nome,
                    "telefone": pessoa.telefone,
                    "mensagem": texto,
                    "erro": "Integrante sem telefone cadastrado.",
                }
            )
            continue

        destinatarios.append(
            {
                "pessoa_id": pessoa.id,
                "nome": pessoa.nome,
                "telefone": pessoa.telefone,
                "mensagem": texto,
                "whatsapp_url": montar_link_whatsapp(pessoa.telefone, texto),
            }
        )
    return destinatarios
