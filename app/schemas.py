from datetime import date, datetime

from pydantic import BaseModel

from app.models import (
    AreaEnum,
    CargoEnum,
    FuncaoOperacionalEnum,
    OrigemMovimentoEnum,
    StatusPagamentoEnum,
    TipoGiraEnum,
)


# ---------- Pessoa ----------
class PessoaBase(BaseModel):
    nome: str
    email: str | None = None
    telefone: str | None = None
    cargo: CargoEnum
    area: AreaEnum = AreaEnum.MEDIUNIDADE
    mensalidade: float = 0.0
    admin: bool = False
    notas: str | None = None
    ativo: int | None = 1


class PessoaCreate(PessoaBase):
    # Omitir o campo (None) marca a pessoa como apta a todas as funções, que é
    # como o cadastro se comportava antes de a aptidão existir. Lista vazia é
    # diferente: significa "não participa de nenhuma função operacional".
    funcoes_aptas: list[FuncaoOperacionalEnum] | None = None


class PessoaResponse(PessoaBase):
    id: int
    criado_em: datetime
    funcoes_aptas: list[FuncaoOperacionalEnum] = []

    class Config:
        from_attributes = True


# ---------- Entidade ----------
class EntidadeBase(BaseModel):
    nome: str
    tipo: TipoGiraEnum
    medium_id: int


class EntidadeCreate(EntidadeBase):
    pass


class EntidadeResponse(EntidadeBase):
    id: int

    class Config:
        from_attributes = True


# ---------- Gira ----------
class GiraBase(BaseModel):
    nome: str | None = None
    tipo: TipoGiraEnum
    data: datetime
    observacoes: str | None = None


class GiraCreate(GiraBase):
    pass


class GiraResponse(GiraBase):
    id: int
    criado_em: datetime

    class Config:
        from_attributes = True


# ---------- Escala ----------
class EscalaGiraBase(BaseModel):
    gira_id: int
    pessoa_id: int
    entidade_id: int | None = None
    cargo: CargoEnum
    presente: bool = False


class EscalaGiraCreate(EscalaGiraBase):
    pass


class EscalaGiraResponse(EscalaGiraBase):
    id: int

    class Config:
        from_attributes = True


class TrabalhadorGira(BaseModel):
    """Uma pessoa que trabalhou na gira; sem entidade quando só cambonou."""

    pessoa_id: int
    entidade_id: int | None = None
    cargo: CargoEnum | None = None
    presente: bool = True


# ---------- Funções operacionais ----------
class FuncaoGiraBase(BaseModel):
    funcao: FuncaoOperacionalEnum
    pessoa_id: int


class FuncaoGiraResponse(FuncaoGiraBase):
    id: int
    gira_id: int

    class Config:
        from_attributes = True


class SugestaoFuncaoResponse(BaseModel):
    """Quem o rodízio indica para a função; nome vem junto para a UI não cruzar."""

    funcao: FuncaoOperacionalEnum
    pessoa_id: int | None = None
    nome: str | None = None


class EscalaManualRequest(BaseModel):
    trabalhadores: list[TrabalhadorGira]
    funcoes: list[FuncaoGiraBase] = []


# ---------- Relatório ----------
class RelatorioGiraResponse(BaseModel):
    gira: GiraResponse
    escalas: list[EscalaGiraResponse]


# ---------- Presença ----------
class PresencaUpdate(BaseModel):
    presente: bool


# ---------- Pagamento ----------
class PagamentoBase(BaseModel):
    pessoa_id: int
    ano: int
    mes: int
    valor: float = 0.0
    status: StatusPagamentoEnum = StatusPagamentoEnum.PENDENTE
    pago_em: date | None = None
    observacoes: str | None = None


class PagamentoCreate(PagamentoBase):
    pass


class PagamentoResponse(PagamentoBase):
    id: int

    class Config:
        from_attributes = True


class InadimplenteResponse(BaseModel):
    pessoa_id: int
    nome: str
    telefone: str | None = None
    valor_devido: float
    status: StatusPagamentoEnum


class ResumoFinanceiroResponse(BaseModel):
    ano: int
    mes: int
    total_previsto: float
    total_recebido: float
    total_pendente: float
    qtd_pagos: int
    qtd_pendentes: int
    inadimplentes: list[InadimplenteResponse]


class EvolucaoMensalResponse(BaseModel):
    ano: int
    mes: int
    total_recebido: float


# ---------- Visão geral ----------
class GiraResumoResponse(BaseModel):
    gira_id: int
    nome: str | None = None
    tipo: TipoGiraEnum
    data: datetime
    escalados: int
    presentes: int


class VisaoGeralResponse(BaseModel):
    total_integrantes: int
    total_mediunidade: int
    total_lideranca: int
    total_curimba: int
    total_giras: int
    total_entidades: int
    mediuns_que_atenderam: int
    ultimas_giras: list[GiraResumoResponse]


# ---------- Visão espiritual ----------
class IntegranteEspiritualResponse(BaseModel):
    pessoa: PessoaResponse
    entidades: list[EntidadeResponse]


# ---------- Estoque ----------
class ItemEstoqueBase(BaseModel):
    nome: str
    categoria: str | None = None
    unidade: str = "unidade"
    # Nulo desliga o alerta deste item.
    minimo_alerta: int | None = None
    contar_por_foto: bool = True
    notas: str | None = None


class ItemEstoqueCreate(ItemEstoqueBase):
    # Só na criação: depois disso o saldo muda por movimento, nunca por edição
    # do cadastro, senão o histórico perderia o que aconteceu.
    quantidade: int = 0


class ItemEstoqueUpdate(ItemEstoqueBase):
    pass


class ItemEstoqueResponse(ItemEstoqueBase):
    id: int
    quantidade: int
    em_alerta: bool
    criado_em: datetime

    class Config:
        from_attributes = True


class MovimentoEstoqueRequest(BaseModel):
    """Um dos dois: ``quantidade`` reconta, ``delta`` soma ou subtrai."""

    quantidade: int | None = None
    delta: int | None = None
    motivo: str | None = None


class MovimentoEstoqueResponse(BaseModel):
    id: int
    item_id: int
    delta: int
    quantidade_apos: int
    origem: OrigemMovimentoEnum
    motivo: str | None = None
    criado_em: datetime

    class Config:
        from_attributes = True


class ResumoEstoqueResponse(BaseModel):
    total_itens: int
    qtd_em_alerta: int
    itens_em_alerta: list[ItemEstoqueResponse]


# ---------- Mensagens ----------
class MensagemRequest(BaseModel):
    pessoa_ids: list[int]
    mensagem: str


class MensagemDestinatario(BaseModel):
    pessoa_id: int
    nome: str
    telefone: str | None = None
    mensagem: str
    whatsapp_url: str | None = None
    erro: str | None = None


class MensagemResponse(BaseModel):
    destinatarios: list[MensagemDestinatario]
