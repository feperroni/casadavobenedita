"""Ajustes de esquema idempotentes para bancos criados por versões anteriores.

O projeto não usa Alembic: as tabelas nascem de ``Base.metadata.create_all``,
que não altera tabelas já existentes. Estas funções rodam na subida da app e
aplicam apenas as mudanças incrementais necessárias, tanto em SQLite quanto em
PostgreSQL.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models import FUNCOES_COM_APTIDAO


def _colunas(inspetor, tabela: str) -> dict:
    return {c["name"]: c for c in inspetor.get_columns(tabela)}


def adicionar_nome_da_gira(engine: Engine) -> None:
    inspetor = inspect(engine)
    if "giras" not in inspetor.get_table_names():
        return
    if "nome" in _colunas(inspetor, "giras"):
        return
    with engine.begin() as conexao:
        conexao.execute(text("ALTER TABLE giras ADD COLUMN nome VARCHAR"))


def permitir_escala_sem_entidade(engine: Engine) -> None:
    """Torna ``escalas_gira.entidade_id`` opcional (cambono sem incorporação)."""
    inspetor = inspect(engine)
    if "escalas_gira" not in inspetor.get_table_names():
        return
    coluna = _colunas(inspetor, "escalas_gira").get("entidade_id")
    if coluna is None or coluna["nullable"]:
        return

    if engine.dialect.name == "sqlite":
        # SQLite não tem ALTER COLUMN: recria a tabela preservando os dados.
        with engine.begin() as conexao:
            conexao.execute(text("""
                CREATE TABLE escalas_gira_nova (
                    id INTEGER NOT NULL PRIMARY KEY,
                    gira_id INTEGER NOT NULL REFERENCES giras(id) ON DELETE CASCADE,
                    pessoa_id INTEGER NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
                    entidade_id INTEGER REFERENCES entidades(id) ON DELETE CASCADE,
                    cargo VARCHAR NOT NULL,
                    presente BOOLEAN NOT NULL DEFAULT 0
                )
            """))
            conexao.execute(text("""
                INSERT INTO escalas_gira_nova
                    (id, gira_id, pessoa_id, entidade_id, cargo, presente)
                SELECT id, gira_id, pessoa_id, entidade_id, cargo, presente
                FROM escalas_gira
            """))
            conexao.execute(text("DROP TABLE escalas_gira"))
            conexao.execute(
                text("ALTER TABLE escalas_gira_nova RENAME TO escalas_gira")
            )
    else:
        with engine.begin() as conexao:
            conexao.execute(
                text("ALTER TABLE escalas_gira ALTER COLUMN entidade_id DROP NOT NULL")
            )


def adicionar_admin_e_notas(engine: Engine) -> None:
    inspetor = inspect(engine)
    if "pessoas" not in inspetor.get_table_names():
        return

    colunas = _colunas(inspetor, "pessoas")
    # O PostgreSQL recusa 0 como default de BOOLEAN ("column is of type boolean
    # but default expression is of type integer"); o SQLite só entende FALSE a
    # partir da 3.23. Cada dialeto recebe o literal que aceita.
    falso = "0" if engine.dialect.name == "sqlite" else "FALSE"
    with engine.begin() as conexao:
        if "admin" not in colunas:
            conexao.execute(
                text(
                    "ALTER TABLE pessoas "
                    f"ADD COLUMN admin BOOLEAN NOT NULL DEFAULT {falso}"
                )
            )
        if "notas" not in colunas:
            conexao.execute(text("ALTER TABLE pessoas ADD COLUMN notas VARCHAR"))


def marcar_aptidao_para_todas_as_funcoes(engine: Engine) -> None:
    """Quem já estava cadastrado continua apto a tudo, como era antes.

    A aptidão por função nasceu depois; sem este backfill, todo mundo ficaria
    sem nenhuma função marcada e o rodízio pararia de sugerir gente. Só toca em
    quem não tem nenhuma linha — quem o usuário já ajustou fica como está.
    """
    inspetor = inspect(engine)
    tabelas = inspetor.get_table_names()
    if "pessoas" not in tabelas or "aptidoes_funcao" not in tabelas:
        return

    with engine.begin() as conexao:
        sem_aptidao = conexao.execute(text("""
                SELECT p.id FROM pessoas p
                WHERE NOT EXISTS (
                    SELECT 1 FROM aptidoes_funcao a WHERE a.pessoa_id = p.id
                )
            """)).scalars().all()

        for pessoa_id in sem_aptidao:
            for funcao in FUNCOES_COM_APTIDAO:
                conexao.execute(
                    text(
                        "INSERT INTO aptidoes_funcao (pessoa_id, funcao) "
                        "VALUES (:pessoa_id, :funcao)"
                    ),
                    {"pessoa_id": pessoa_id, "funcao": funcao.name},
                )


def aplicar(engine: Engine) -> None:
    adicionar_nome_da_gira(engine)
    permitir_escala_sem_entidade(engine)
    adicionar_admin_e_notas(engine)
    marcar_aptidao_para_todas_as_funcoes(engine)
