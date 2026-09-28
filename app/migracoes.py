"""Ajustes de esquema idempotentes para bancos criados por versões anteriores.

O projeto não usa Alembic: as tabelas nascem de ``Base.metadata.create_all``,
que não altera tabelas já existentes. Estas funções rodam na subida da app e
aplicam apenas as mudanças incrementais necessárias, tanto em SQLite quanto em
PostgreSQL.
"""

import enum

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app import models
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


def adicionar_atendeu_na_escala(engine: Engine) -> None:
    """``atendeu`` separa "foi para a gira" de "fez atendimento" na escala.

    Sem esta coluna, todo registro antigo de escala ficaria sem valor e o
    INSERT de uma escala nova quebraria num NOT NULL sem default explícito.
    """
    inspetor = inspect(engine)
    if "escalas_gira" not in inspetor.get_table_names():
        return
    if "atendeu" in _colunas(inspetor, "escalas_gira"):
        return

    falso = "0" if engine.dialect.name == "sqlite" else "FALSE"
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "ALTER TABLE escalas_gira "
                f"ADD COLUMN atendeu BOOLEAN NOT NULL DEFAULT {falso}"
            )
        )


def adicionar_atualizado_em_no_estoque(engine: Engine) -> None:
    """``atualizado_em`` mostra quando o item foi adicionado ou mexido por último.

    Sem ``DEFAULT`` no ALTER TABLE de propósito: o SQLite recusa um default
    não constante (``CURRENT_TIMESTAMP``) num ``ADD COLUMN``, e ``ItemEstoque``
    já cobre a lacuna sozinho com o ``default=func.now()`` do lado Python.
    Aqui só falta preencher quem já existia — herda o instante de ``criado_em``,
    para quem nunca foi tocado depois do cadastro não ficar em branco.
    """
    inspetor = inspect(engine)
    if "itens_estoque" not in inspetor.get_table_names():
        return
    if "atualizado_em" in _colunas(inspetor, "itens_estoque"):
        return

    with engine.begin() as conexao:
        conexao.execute(
            text("ALTER TABLE itens_estoque ADD COLUMN atualizado_em TIMESTAMP")
        )
        conexao.execute(
            text(
                "UPDATE itens_estoque SET atualizado_em = criado_em "
                "WHERE atualizado_em IS NULL"
            )
        )


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


def sincronizar_enums(engine: Engine) -> None:
    """Sincroniza QUALQUER enum do projeto contra o que já está gravado.

    ``create_all()`` cria tabela e tipo que não existem, mas nunca atualiza o
    que já existe — nem coluna nova, nem (o que interessa aqui) valor novo
    num enum. No PostgreSQL, ``Enum(...)`` vira um tipo nativo; quando a
    Limpeza 2 virou duas posições, o tipo continuou só com os 4 valores
    antigos e todo INSERT do quinto quebrava com 500, porque o banco recusava
    um valor que o tipo nativo não conhecia. No SQLite, o mesmo tipo vira um
    CHECK gravado na criação da tabela, com o mesmo efeito.

    Em vez de corrigir só o caso da Limpeza 2, isto roda para todo enum do
    projeto a cada subida — a próxima vez que qualquer um deles ganhar um
    membro novo (como os desta mesma leva de mudanças), o valor já entra
    sozinho, sem precisar de outra migração como esta.
    """
    if engine.dialect.name == "postgresql":
        _sincronizar_enums_nativos_postgresql(engine)
    elif engine.dialect.name == "sqlite":
        _liberar_checks_de_enum_sqlite(engine)


def _enums_do_projeto() -> list[type[enum.Enum]]:
    return [
        classe
        for classe in vars(models).values()
        if isinstance(classe, type) and issubclass(classe, enum.Enum)
    ]


def _sincronizar_enums_nativos_postgresql(engine: Engine) -> None:
    tipos_no_banco = {t["name"]: set(t["labels"]) for t in inspect(engine).get_enums()}
    if not tipos_no_banco:
        return

    for classe in _enums_do_projeto():
        labels_no_banco = tipos_no_banco.get(classe.__name__.lower())
        # Tipo que ainda não existe é problema do create_all(), não deste
        # sincronismo — ele só adiciona valor a tipo que já está lá.
        if labels_no_banco is None:
            continue
        faltando = [m.name for m in classe if m.name not in labels_no_banco]
        if not faltando:
            continue
        # ALTER TYPE ... ADD VALUE não roda dentro de uma transação em toda
        # versão do Postgres; autocommit funciona em todas.
        with engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as conexao:
            for nome_membro in faltando:
                escapado = nome_membro.replace("'", "''")
                conexao.execute(
                    text(
                        f"ALTER TYPE {classe.__name__.lower()} "
                        f"ADD VALUE IF NOT EXISTS '{escapado}'"
                    )
                )


def _sql_de_criacao_sqlite(engine, tabela: str) -> str | None:
    with engine.connect() as conexao:
        return conexao.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:tabela"),
            {"tabela": tabela},
        ).scalar()


def _liberar_checks_de_enum_sqlite(engine: Engine) -> None:
    """Recria, sem CHECK, cada tabela cuja criação ainda carrega um.

    SQLite não tem ALTER TABLE para trocar um CHECK — dropar e recriar
    preservando os dados é o único caminho, como em outras migrações deste
    arquivo. Sem CHECK nenhum a tabela nunca mais precisa deste tratamento:
    a validação de verdade já é feita em Python, no schema Pydantic e em
    ``_validar_funcoes``, antes de qualquer INSERT chegar aqui.
    """
    tabelas = {
        "funcoes_gira": """
            CREATE TABLE {nova} (
                id INTEGER NOT NULL PRIMARY KEY,
                gira_id INTEGER NOT NULL REFERENCES giras(id) ON DELETE CASCADE,
                pessoa_id INTEGER NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
                funcao VARCHAR NOT NULL,
                CONSTRAINT uq_funcao_gira UNIQUE (gira_id, funcao)
            )
        """,
        "aptidoes_funcao": """
            CREATE TABLE {nova} (
                id INTEGER NOT NULL PRIMARY KEY,
                pessoa_id INTEGER NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
                funcao VARCHAR NOT NULL,
                CONSTRAINT uq_aptidao_pessoa_funcao UNIQUE (pessoa_id, funcao)
            )
        """,
    }
    inspetor = inspect(engine)
    tabelas_existentes = inspetor.get_table_names()

    for tabela, criar_nova in tabelas.items():
        if tabela not in tabelas_existentes:
            continue
        sql_atual = _sql_de_criacao_sqlite(engine, tabela)
        if sql_atual is None or "CHECK" not in sql_atual.upper():
            continue  # já foi recriada antes, ou nunca teve CHECK

        colunas = ", ".join(c["name"] for c in inspetor.get_columns(tabela))
        nova = f"{tabela}_nova"
        with engine.begin() as conexao:
            conexao.execute(text(criar_nova.format(nova=nova)))
            conexao.execute(
                text(f"INSERT INTO {nova} ({colunas}) SELECT {colunas} FROM {tabela}")
            )
            conexao.execute(text(f"DROP TABLE {tabela}"))
            conexao.execute(text(f"ALTER TABLE {nova} RENAME TO {tabela}"))


def aplicar(engine: Engine) -> None:
    adicionar_nome_da_gira(engine)
    permitir_escala_sem_entidade(engine)
    adicionar_admin_e_notas(engine)
    adicionar_atendeu_na_escala(engine)
    adicionar_atualizado_em_no_estoque(engine)
    marcar_aptidao_para_todas_as_funcoes(engine)
    sincronizar_enums(engine)
