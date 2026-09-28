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
    atendeu: bool = False


class EscalaGiraCreate(EscalaGiraBase):
    pass


class EscalaGiraResponse(EscalaGiraBase):
    id: int

    class Config:
        from_attributes = True


class TrabalhadorGira(BaseModel):
    """Uma pessoa da escala; entidade só faz sentido quando ``atendeu``."""

    pessoa_id: int
    entidade_id: int | None = None
    cargo: CargoEnum | None = None
    presente: bool = True
    atendeu: bool = False


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
class EscalaAtualizacaoRequest(BaseModel):
    """Correção pontual pós-gira. Campo ausente (``None``) não é tocado."""

    presente: bool | None = None
    atendeu: bool | None = None


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


class StatusCompetenciaResponse(BaseModel):
    """O que vale para a pessoa no mês, com a isenção herdada já resolvida.

    ``herdado`` distingue "isento porque alguém marcou neste mês" de "isento
    porque a isenção de um mês anterior continua valendo" — sem lançamento
    gravado nesta competência.
    """

    pessoa_id: int
    status: StatusPagamentoEnum
    herdado: bool
    valor: float | None = None


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
    atenderam: int
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


# ---------- Visão operacional ----------
class GiraOperacionalResponse(BaseModel):
    gira_id: int
    nome: str | None = None
    tipo: TipoGiraEnum
    data: datetime
    presentes: int
    atenderam: int
    faltaram: int
    porteira_atendimento: list[str] = []
    porteira_senha: list[str] = []
    limpeza_1: list[str] = []
    limpeza_2: list[str] = []


class IntegranteOperacionalResponse(BaseModel):
    """Quantas vezes a pessoa esteve, atendeu, faltou e ocupou cada função no mês."""

    pessoa_id: int
    nome: str
    cargo: CargoEnum
    presencas: int
    atendimentos: int
    faltas: int
    porteira_atendimento: int = 0
    porteira_senha: int = 0
    limpeza_1: int = 0
    limpeza_2: int = 0


class OperacionalMensalResponse(BaseModel):
    ano: int
    mes: int
    total_giras: int
    giras: list[GiraOperacionalResponse]
    integrantes: list[IntegranteOperacionalResponse]


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
    atualizado_em: datetime

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


# ---------- Leitura do estoque por foto ----------
class ItemLidoResponse(BaseModel):
    """Item do catálogo que apareceu nas fotos, com o saldo atual ao lado."""

    item_id: int
    nome: str
    unidade: str
    quantidade_atual: int
    quantidade_lida: int
    confianca: str
    observacao: str | None = None


class ItemNovoResponse(BaseModel):
    """Coisa vista nas fotos que ainda não está cadastrada."""

    nome: str
    quantidade: int
    unidade: str
    categoria: str | None = None
    confianca: str


class ItemAusenteResponse(BaseModel):
    """Item do catálogo que não apareceu — fica como está, não zera."""

    item_id: int
    nome: str
    unidade: str
    quantidade_atual: int


class LeituraFotoResponse(BaseModel):
    encontrados: list[ItemLidoResponse]
    novos: list[ItemNovoResponse]
    nao_apareceram: list[ItemAusenteResponse]


class AjusteLeitura(BaseModel):
    """Uma linha da proposta que o usuário aceitou.

    ``item_id`` para recontagem de item existente, ``nome`` para cadastrar um
    item novo — um ou outro, nunca os dois.
    """

    item_id: int | None = None
    nome: str | None = None
    quantidade: int
    unidade: str = "unidade"
    categoria: str | None = None


class AplicarLeituraRequest(BaseModel):
    ajustes: list[AjusteLeitura]


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
