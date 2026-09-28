import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class CargoEnum(str, enum.Enum):
    FIXO = "Médium Fixo"
    RODIZIO = "Médium de Rodízio"
    CAMBONO = "Cambono"


class AreaEnum(str, enum.Enum):
    MEDIUNIDADE = "Mediunidade"
    LIDERANCA = "Liderança"
    CURIMBA = "Curimba"


class StatusPagamentoEnum(str, enum.Enum):
    PAGO = "Pago"
    PENDENTE = "Pendente"
    ISENTO = "Isento"


class FuncaoOperacionalEnum(str, enum.Enum):
    """Posições de apoio da gira, preenchidas por rodízio.

    A Limpeza 2 é feita por duas pessoas, então ocupa duas posições. O nome
    ``LIMPEZA_2`` fica como está de propósito: é ele que está gravado nas
    colunas Enum do banco, e renomeá-lo obrigaria a migrar todas as giras e
    aptidões já registradas. Só o rótulo mudou.
    """

    PORTEIRA_ATENDIMENTO = "Porteira de Atendimento"
    PORTEIRA_SENHA = "Porteira de Senha"
    LIMPEZA_1 = "Limpeza 1"
    LIMPEZA_2 = "Limpeza 2 - Pessoa 1"
    LIMPEZA_2_PESSOA_2 = "Limpeza 2 - Pessoa 2"


# As duas posições da Limpeza 2 são o mesmo trabalho e valem uma aptidão só:
# quem pode fazer a limpeza pode ocupar qualquer uma das duas. Guardar aptidão
# por posição faria o usuário marcar duas caixas que sempre dizem a mesma
# coisa, e obrigaria a migrar o cadastro de todo mundo para criar a segunda.
APTIDAO_DA_POSICAO = {
    FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_2: FuncaoOperacionalEnum.LIMPEZA_2,
}

# O que vira caixa de marcação no cadastro do integrante.
FUNCOES_COM_APTIDAO = tuple(
    funcao for funcao in FuncaoOperacionalEnum if funcao not in APTIDAO_DA_POSICAO
)


def aptidao_exigida(funcao: FuncaoOperacionalEnum) -> FuncaoOperacionalEnum:
    """Qual aptidão o cadastro precisa ter marcada para ocupar esta posição."""
    return APTIDAO_DA_POSICAO.get(funcao, funcao)


# A aptidão da limpeza vale para as duas posições, então o rótulo dela não pode
# citar só a primeira — a mensagem sairia falando da Pessoa 1 para quem tentou
# preencher a Pessoa 2.
ROTULO_DA_APTIDAO = {FuncaoOperacionalEnum.LIMPEZA_2: "Limpeza 2"}


def rotulo_aptidao(funcao: FuncaoOperacionalEnum) -> str:
    """Como chamar a aptidão exigida por esta posição ao falar com o usuário."""
    exigida = aptidao_exigida(funcao)
    return ROTULO_DA_APTIDAO.get(exigida, exigida.value)


class TipoGiraEnum(str, enum.Enum):
    PRETO_VELHO = "Preto Velho"
    CABOCLO = "Caboclo"
    EXU = "Exu"
    POMBA_GIRA = "Pomba Gira"
    CRIANCA = "Erê"
    MIRIM = "Mirim"
    BAIANO = "Baiano"
    MALANDRO = "Malandro"
    MARINHEIRO = "Marinheiro"
    CIGANO = "Cigano"
    BOIADEIRO = "Boiadeiro"
    ORIXA = "Orixá"
    OUTRO = "Outro"


class Pessoa(Base):
    __tablename__ = "pessoas"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    telefone = Column(String, nullable=True)
    cargo = Column(Enum(CargoEnum), nullable=False)
    area = Column(Enum(AreaEnum), nullable=False, default=AreaEnum.MEDIUNIDADE)
    mensalidade = Column(Float, nullable=False, default=0.0)
    admin = Column(Boolean, nullable=False, default=False)
    notas = Column(String, nullable=True)
    ativo = Column(Integer, default=1)
    criado_em = Column(DateTime, server_default=func.now())

    guias = relationship(
        "Entidade", back_populates="medium", cascade="all, delete-orphan"
    )
    escalas = relationship(
        "EscalaGira", back_populates="pessoa", cascade="all, delete-orphan"
    )
    pagamentos = relationship(
        "Pagamento", back_populates="pessoa", cascade="all, delete-orphan"
    )
    funcoes = relationship(
        "FuncaoGira", back_populates="pessoa", cascade="all, delete-orphan"
    )
    aptidoes = relationship(
        "AptidaoFuncao", back_populates="pessoa", cascade="all, delete-orphan"
    )

    @property
    def funcoes_aptas(self) -> list[FuncaoOperacionalEnum]:
        """Funções que a pessoa pode assumir, na ordem canônica do rodízio."""
        marcadas = {a.funcao for a in self.aptidoes}
        return [f for f in FuncaoOperacionalEnum if f in marcadas]


class AptidaoFuncao(Base):
    """Quais funções operacionais a pessoa pode assumir.

    Nem todo mundo pode fazer limpeza ou porteira — por questão de saúde, de
    horário ou do próprio trabalho na gira. Sem linha aqui para uma função, a
    pessoa não é sugerida nem aceita nela.
    """

    __tablename__ = "aptidoes_funcao"
    __table_args__ = (
        UniqueConstraint("pessoa_id", "funcao", name="uq_aptidao_pessoa_funcao"),
    )

    id = Column(Integer, primary_key=True, index=True)
    pessoa_id = Column(
        Integer, ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False
    )
    funcao = Column(Enum(FuncaoOperacionalEnum), nullable=False)

    pessoa = relationship("Pessoa", back_populates="aptidoes")


class Entidade(Base):
    """Guia/Entidade vinculada a um médium específico."""

    __tablename__ = "entidades"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    tipo = Column(Enum(TipoGiraEnum), nullable=False)
    medium_id = Column(
        Integer, ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False
    )

    medium = relationship("Pessoa", back_populates="guias")
    escalas = relationship(
        "EscalaGira", back_populates="entidade", cascade="all, delete-orphan"
    )


class Gira(Base):
    __tablename__ = "giras"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=True)
    tipo = Column(Enum(TipoGiraEnum), nullable=False)
    data = Column(DateTime, nullable=False)
    observacoes = Column(String, nullable=True)
    criado_em = Column(DateTime, server_default=func.now())

    escalas = relationship(
        "EscalaGira", back_populates="gira", cascade="all, delete-orphan"
    )
    funcoes = relationship(
        "FuncaoGira", back_populates="gira", cascade="all, delete-orphan"
    )


class FuncaoGira(Base):
    """Quem ocupou cada posição de apoio numa gira (uma pessoa por função)."""

    __tablename__ = "funcoes_gira"
    __table_args__ = (UniqueConstraint("gira_id", "funcao", name="uq_funcao_gira"),)

    id = Column(Integer, primary_key=True, index=True)
    gira_id = Column(
        Integer, ForeignKey("giras.id", ondelete="CASCADE"), nullable=False
    )
    pessoa_id = Column(
        Integer, ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False
    )
    funcao = Column(Enum(FuncaoOperacionalEnum), nullable=False)

    gira = relationship("Gira", back_populates="funcoes")
    pessoa = relationship("Pessoa", back_populates="funcoes")


class EscalaGira(Base):
    """Registro de quais médiuns/entidades participam de uma gira."""

    __tablename__ = "escalas_gira"

    id = Column(Integer, primary_key=True, index=True)
    gira_id = Column(
        Integer, ForeignKey("giras.id", ondelete="CASCADE"), nullable=False
    )
    pessoa_id = Column(
        Integer, ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False
    )
    # Nulo quando a pessoa trabalhou sem incorporar (cambono dando suporte).
    entidade_id = Column(
        Integer, ForeignKey("entidades.id", ondelete="CASCADE"), nullable=True
    )
    cargo = Column(Enum(CargoEnum), nullable=False)
    presente = Column(Boolean, nullable=False, default=False)

    gira = relationship("Gira", back_populates="escalas")
    pessoa = relationship("Pessoa", back_populates="escalas")
    entidade = relationship("Entidade", back_populates="escalas")


class Pagamento(Base):
    """Contribuição mensal de um integrante da corrente."""

    __tablename__ = "pagamentos"
    __table_args__ = (
        UniqueConstraint("pessoa_id", "ano", "mes", name="uq_pagamento_pessoa_mes"),
    )

    id = Column(Integer, primary_key=True, index=True)
    pessoa_id = Column(
        Integer, ForeignKey("pessoas.id", ondelete="CASCADE"), nullable=False
    )
    ano = Column(Integer, nullable=False)
    mes = Column(Integer, nullable=False)
    valor = Column(Float, nullable=False, default=0.0)
    status = Column(
        Enum(StatusPagamentoEnum),
        nullable=False,
        default=StatusPagamentoEnum.PENDENTE,
    )
    pago_em = Column(Date, nullable=True)
    observacoes = Column(String, nullable=True)

    pessoa = relationship("Pessoa", back_populates="pagamentos")


class OrigemMovimentoEnum(str, enum.Enum):
    """De onde veio a alteração de saldo — a foto entra na fase seguinte."""

    MANUAL = "Manual"
    FOTO = "Foto"


class ItemEstoque(Base):
    """Um item do almoxarifado do terreiro.

    O saldo mora aqui e é a fonte da verdade; ``MovimentoEstoque`` guarda o
    histórico de como ele chegou nesse número. As duas coisas só mudam juntas,
    pelo serviço de estoque, para não descolarem uma da outra.
    """

    __tablename__ = "itens_estoque"
    __table_args__ = (UniqueConstraint("nome", name="uq_item_estoque_nome"),)

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, nullable=False)
    categoria = Column(String, nullable=True)
    # Rótulo da contagem ("unidade", "pacote", "garrafa"). A quantidade é
    # sempre inteira: meia garrafa conta como uma, e o mínimo absorve a folga.
    unidade = Column(String, nullable=False, default="unidade")
    quantidade = Column(Integer, nullable=False, default=0)
    # Nulo quer dizer "não me avise sobre este item".
    minimo_alerta = Column(Integer, nullable=True)
    # Itens que a foto não consegue contar (ervas, folhas) ficam fora da
    # leitura por imagem e são mantidos só na mão.
    contar_por_foto = Column(Boolean, nullable=False, default=True)
    notas = Column(String, nullable=True)
    criado_em = Column(DateTime, server_default=func.now())

    movimentos = relationship(
        "MovimentoEstoque",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="MovimentoEstoque.id.desc()",
    )

    @property
    def em_alerta(self) -> bool:
        return self.minimo_alerta is not None and self.quantidade <= self.minimo_alerta


class MovimentoEstoque(Base):
    """Cada alteração de saldo de um item, para dar para auditar depois."""

    __tablename__ = "movimentos_estoque"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(
        Integer, ForeignKey("itens_estoque.id", ondelete="CASCADE"), nullable=False
    )
    delta = Column(Integer, nullable=False)
    # Saldo depois do movimento, para ler o histórico sem reprocessar tudo.
    quantidade_apos = Column(Integer, nullable=False)
    origem = Column(
        Enum(OrigemMovimentoEnum), nullable=False, default=OrigemMovimentoEnum.MANUAL
    )
    motivo = Column(String, nullable=True)
    criado_em = Column(DateTime, server_default=func.now())

    item = relationship("ItemEstoque", back_populates="movimentos")
