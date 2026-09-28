"""Configuração comum dos testes.

O banco precisa ser apontado para um arquivo temporário **antes** de qualquer
import de ``app.database`` — por isso isso mora no conftest, que o pytest
carrega antes dos módulos de teste. Sem isso a suíte escrevia no
``gestao_giras.db`` de desenvolvimento, dependendo da ordem de coleta.
"""

import os
import tempfile
from pathlib import Path

BANCO_DE_TESTE = Path(tempfile.gettempdir()) / "gestao_giras_testes.db"
os.environ["DATABASE_URL"] = f"sqlite:///{BANCO_DE_TESTE}"
os.environ.setdefault("APP_ENV", "development")

import pytest

from app.database import Base, SessionLocal, engine


@pytest.fixture(autouse=True)
def banco_limpo():
    """Cada teste começa com o esquema zerado."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db():
    sessao = SessionLocal()
    try:
        yield sessao
    finally:
        sessao.close()
