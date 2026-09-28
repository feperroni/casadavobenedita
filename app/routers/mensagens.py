from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import MensagemRequest, MensagemResponse
from app.services.mensagem import preparar_mensagens

router = APIRouter(prefix="/mensagens", tags=["Mensagens"])


@router.post("/whatsapp", response_model=MensagemResponse)
def gerar_mensagens_whatsapp(dados: MensagemRequest, db: Session = Depends(get_db)):
    """Gera os links de WhatsApp para os integrantes selecionados.

    Marcadores aceitos na mensagem: `{nome}`, `{primeiro_nome}`, `{valor}`.
    """
    return {"destinatarios": preparar_mensagens(db, dados.pessoa_ids, dados.mensagem)}
