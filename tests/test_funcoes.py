"""Rodízio das funções operacionais e planilha imprimível."""

from datetime import datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import migracoes
from app.database import engine
from app.main import app
from app.models import (
    FUNCOES_COM_APTIDAO,
    AptidaoFuncao,
    AreaEnum,
    CargoEnum,
    FuncaoGira,
    FuncaoOperacionalEnum,
    Gira,
    Pessoa,
    TipoGiraEnum,
)
from app.services.funcoes import sugerir

LIMPEZA_1 = FuncaoOperacionalEnum.LIMPEZA_1
LIMPEZA_2 = FuncaoOperacionalEnum.LIMPEZA_2
LIMPEZA_2_PESSOA_2 = FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_2
PORTEIRA_ATENDIMENTO = FuncaoOperacionalEnum.PORTEIRA_ATENDIMENTO
PORTEIRA_SENHA = FuncaoOperacionalEnum.PORTEIRA_SENHA


def data_em(ano: int, mes: int, dia: int) -> datetime:
    """Giras usam data ingênua: a coluna ``Gira.data`` é DateTime sem timezone."""
    return datetime(ano, mes, dia)  # noqa: DTZ001


def criar_pessoa(db, nome, cargo=CargoEnum.RODIZIO, ativo=1, funcoes=None):
    """Apta a todas as funções por padrão; ``funcoes`` restringe o cadastro."""
    pessoa = Pessoa(
        nome=nome,
        cargo=cargo,
        area=AreaEnum.MEDIUNIDADE,
        mensalidade=0.0,
        ativo=ativo,
    )
    pessoa.aptidoes = [
        AptidaoFuncao(funcao=funcao)
        for funcao in (FUNCOES_COM_APTIDAO if funcoes is None else funcoes)
    ]
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)
    return pessoa


def criar_gira(db, data, funcoes=()):
    gira = Gira(tipo=TipoGiraEnum.CABOCLO, data=data)
    db.add(gira)
    db.commit()
    db.refresh(gira)
    for funcao, pessoa in funcoes:
        db.add(FuncaoGira(gira_id=gira.id, pessoa_id=pessoa.id, funcao=funcao))
    db.commit()
    return gira


def por_funcao(db, ignorar_gira_id=None):
    return {s["funcao"]: s for s in sugerir(db, ignorar_gira_id=ignorar_gira_id)}


def por_funcao_id(sugestoes):
    return {s["funcao"]: s["pessoa_id"] for s in sugestoes}


def test_apenas_rodizio_e_cambono_entram_no_sorteio(db):
    criar_pessoa(db, "Ana Fixa", cargo=CargoEnum.FIXO)
    criar_pessoa(db, "Bruno Inativo", cargo=CargoEnum.RODIZIO, ativo=0)
    cambono = criar_pessoa(db, "Carla Cambono", cargo=CargoEnum.CAMBONO)

    sugestoes = por_funcao(db)

    # Só sobrou a cambona: ela pega a primeira função e as demais ficam vazias.
    assert sugestoes[PORTEIRA_ATENDIMENTO]["pessoa_id"] == cambono.id
    assert sugestoes[LIMPEZA_1]["pessoa_id"] is None


def test_ninguem_repete_enquanto_houver_quem_nao_trabalhou(db):
    # Quatro elegíveis para cinco posições: com menos gente que posições, a
    # regra de "uma função por pessoa" estreita o rodízio e a última fica vazia.
    pessoas = [criar_pessoa(db, nome) for nome in ("Ana", "Bruno", "Carla", "Diego")]
    escalados = []

    # Quatro giras seguidas aceitando sempre a sugestão de cada função.
    for semana in range(4):
        sugestoes = sugerir(db)
        escalados.append(por_funcao_id(sugestoes)[LIMPEZA_1])
        criar_gira(
            db,
            data_em(2026, 1, 5) + timedelta(days=7 * semana),
            [
                (s["funcao"], next(p for p in pessoas if p.id == s["pessoa_id"]))
                for s in sugestoes
                if s["pessoa_id"]
            ],
        )

    assert sorted(escalados) == sorted(
        p.id for p in pessoas
    ), "cada elegível deveria passar pela Limpeza 1 antes de alguém repetir"

    # Fechado o ciclo, a fila reinicia por quem trabalhou há mais tempo.
    assert por_funcao(db)[LIMPEZA_1]["pessoa_id"] == escalados[0]


def test_quem_acabou_de_trabalhar_sai_da_frente_de_todas_as_funcoes(db):
    ana = criar_pessoa(db, "Ana")
    for nome in ("Bruno", "Carla", "Diego", "Elena", "Fabio"):
        criar_pessoa(db, nome)

    criar_gira(db, data_em(2026, 1, 5), [(LIMPEZA_1, ana)])

    sugestoes = por_funcao(db)

    # A carga é contada junto: ter feito a Limpeza 1 tira a Ana da frente de
    # todas as posições, e não só da fila da Limpeza 1. Fosse por função, ela
    # voltaria já na próxima gira numa das outras — que é o que se quer evitar.
    escolhidos = {s["nome"] for s in sugestoes.values()}
    assert "Ana" not in escolhidos
    # Com cinco colegas zerados para cinco posições, ela nem é chamada.
    assert escolhidos == {"Bruno", "Carla", "Diego", "Elena", "Fabio"}


def test_as_duas_posicoes_da_limpeza_2_caem_em_pessoas_diferentes(db):
    for nome in ("Ana", "Bruno", "Carla", "Diego", "Elena"):
        criar_pessoa(db, nome)

    sugestoes = por_funcao(db)

    primeira = sugestoes[LIMPEZA_2]["pessoa_id"]
    segunda = sugestoes[LIMPEZA_2_PESSOA_2]["pessoa_id"]
    assert primeira and segunda
    assert primeira != segunda


def test_menos_carregado_vem_antes_de_quem_ficou_mais_tempo_parado(db):
    ana = criar_pessoa(db, "Ana")
    bruno = criar_pessoa(db, "Bruno")

    # A Ana trabalhou há muito tempo, mas duas vezes; o Bruno, uma só e recente.
    criar_gira(db, data_em(2026, 1, 5), [(LIMPEZA_1, ana), (LIMPEZA_2, bruno)])
    criar_gira(db, data_em(2026, 1, 12), [(PORTEIRA_SENHA, ana)])

    # Quem tem menos giras nas costas vem primeiro, mesmo tendo trabalhado
    # mais recentemente: o critério principal é a carga, não a data.
    assert por_funcao(db)[PORTEIRA_ATENDIMENTO]["nome"] == "Bruno"


def test_rodizio_pula_quem_nao_esta_apto_a_funcao(db):
    # A Ana só faz limpeza. Mesmo vindo antes no alfabeto e nunca tendo
    # trabalhado, a porteira tem de passar direto por ela e cair no Bruno.
    criar_pessoa(db, "Ana", funcoes=[LIMPEZA_1, LIMPEZA_2])
    criar_pessoa(db, "Bruno")

    sugestoes = por_funcao(db)

    assert sugestoes[PORTEIRA_ATENDIMENTO]["nome"] == "Bruno"
    assert sugestoes[LIMPEZA_1]["nome"] == "Ana"


def test_funcao_sem_ninguem_apto_sai_vazia(db):
    criar_pessoa(db, "Ana", funcoes=[PORTEIRA_ATENDIMENTO])

    sugestoes = por_funcao(db)

    assert sugestoes[PORTEIRA_ATENDIMENTO]["nome"] == "Ana"
    assert sugestoes[LIMPEZA_1]["pessoa_id"] is None
    assert sugestoes[LIMPEZA_2]["pessoa_id"] is None


def test_migracao_marca_quem_ja_existia_como_apto_a_tudo(db):
    # Banco de versão anterior: a pessoa existe sem nenhuma linha de aptidão.
    # Sem o backfill ela sumiria do rodízio no primeiro deploy.
    sem_aptidao = criar_pessoa(db, "Ana", funcoes=[])
    restrita = criar_pessoa(db, "Bruno", funcoes=[LIMPEZA_1])
    assert sem_aptidao.funcoes_aptas == []

    migracoes.aplicar(engine)
    db.expire_all()

    assert sem_aptidao.funcoes_aptas == list(FUNCOES_COM_APTIDAO)
    # Quem o usuário já restringiu não é mexido pela migração.
    assert restrita.funcoes_aptas == [LIMPEZA_1]


def test_uma_aptidao_de_limpeza_cobre_as_duas_posicoes(db):
    # Marcar "Limpeza 2" no cadastro habilita as duas posições — não existe
    # aptidão separada por posição, justamente para não pedir duas decisões
    # que sempre significam a mesma coisa.
    criar_pessoa(db, "Ana", funcoes=[LIMPEZA_2])
    criar_pessoa(db, "Bruno", funcoes=[LIMPEZA_2])
    criar_pessoa(db, "Carla", funcoes=[PORTEIRA_ATENDIMENTO])

    sugestoes = por_funcao(db)

    assert sugestoes[LIMPEZA_2]["nome"] in {"Ana", "Bruno"}
    assert sugestoes[LIMPEZA_2_PESSOA_2]["nome"] in {"Ana", "Bruno"}
    assert sugestoes[LIMPEZA_2]["nome"] != sugestoes[LIMPEZA_2_PESSOA_2]["nome"]
    # A Carla não faz limpeza e fica de fora das duas.
    assert "Carla" not in {
        sugestoes[LIMPEZA_2]["nome"],
        sugestoes[LIMPEZA_2_PESSOA_2]["nome"],
    }


def test_salvar_a_segunda_posicao_exige_a_aptidao_de_limpeza(db):
    so_porteira = criar_pessoa(db, "Ana", funcoes=[PORTEIRA_ATENDIMENTO])
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": LIMPEZA_2_PESSOA_2.value, "pessoa_id": so_porteira.id}
                ],
            },
        )

    assert resposta.status_code == 400
    # A mensagem nomeia a aptidão que falta, sem citar a outra posição: quem
    # tentou preencher a Pessoa 2 não deve ler um erro sobre a Pessoa 1.
    detalhe = resposta.json()["detail"]
    assert "apto para Limpeza 2." in detalhe
    assert "Pessoa 1" not in detalhe


def test_salvar_funcao_para_quem_nao_e_apto_e_recusado(db):
    ana = criar_pessoa(db, "Ana", funcoes=[PORTEIRA_ATENDIMENTO])
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [{"funcao": LIMPEZA_1.value, "pessoa_id": ana.id}],
            },
        )

    assert resposta.status_code == 400
    assert "não está marcado como apto" in resposta.json()["detail"]


def test_mesma_pessoa_nao_ocupa_duas_funcoes_na_mesma_gira(db):
    for nome in ("Ana", "Bruno", "Carla", "Diego", "Elena"):
        criar_pessoa(db, nome)

    escolhidos = [s["pessoa_id"] for s in sugerir(db)]

    assert (
        len(set(escolhidos)) == 5
    ), "as cinco posições devem cair em pessoas distintas"


def test_gira_em_edicao_nao_penaliza_quem_ja_esta_nela(db):
    ana = criar_pessoa(db, "Ana")
    bruno = criar_pessoa(db, "Bruno")
    carla = criar_pessoa(db, "Carla")
    zara = criar_pessoa(db, "Zara")

    # Todo mundo já passou pela Limpeza 1; a Zara foi a última, na gira aberta.
    criar_gira(db, data_em(2026, 1, 1), [(LIMPEZA_1, ana)])
    criar_gira(db, data_em(2026, 1, 8), [(LIMPEZA_1, bruno)])
    criar_gira(db, data_em(2026, 1, 15), [(LIMPEZA_1, carla)])
    em_edicao = criar_gira(db, data_em(2026, 1, 22), [(LIMPEZA_1, zara)])

    # Todos com uma gira nas costas: a ordem sai pela data, e a Zara, por ser a
    # mais recente, cai na última função da vez.
    assert por_funcao(db)[LIMPEZA_2]["nome"] == "Zara"
    # Ignorando a gira em edição, a Zara volta a contar como quem não trabalhou
    # e reassume a frente — senão reabrir a gira empurraria a própria escalada
    # para o fim da fila.
    sem_a_gira_aberta = por_funcao(db, ignorar_gira_id=em_edicao.id)
    assert sem_a_gira_aberta[PORTEIRA_ATENDIMENTO]["nome"] == "Zara"


def test_salvar_funcoes_pela_api_e_recusar_cargo_inelegivel(db):
    rodizio = criar_pessoa(db, "Ana", cargo=CargoEnum.RODIZIO)
    fixo = criar_pessoa(db, "Bruno", cargo=CargoEnum.FIXO)
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        ok = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [{"funcao": LIMPEZA_1.value, "pessoa_id": rodizio.id}],
            },
        )
        assert ok.status_code == 200, ok.text

        salvas = client.get(f"/giras/{gira.id}/funcoes").json()
        assert len(salvas) == 1
        assert salvas[0]["pessoa_id"] == rodizio.id

        recusado = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [{"funcao": LIMPEZA_1.value, "pessoa_id": fixo.id}],
            },
        )
        assert recusado.status_code == 400
        assert "rodízio e cambonos" in recusado.json()["detail"]


def test_mesma_pessoa_em_duas_funcoes_e_recusada(db):
    pessoa = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": LIMPEZA_1.value, "pessoa_id": pessoa.id},
                    {"funcao": LIMPEZA_2.value, "pessoa_id": pessoa.id},
                ],
            },
        )

    assert resposta.status_code == 400
    assert "duas funções" in resposta.json()["detail"]


def test_planilha_sai_com_cabecalho_e_funcoes_sugeridas(db):
    criar_pessoa(db, "Ana")
    criar_pessoa(db, "Bruno", cargo=CargoEnum.FIXO)

    with TestClient(app) as client:
        resposta = client.get("/planilhas/gira?tipo=Caboclo&data=2026-08-12")

    assert resposta.status_code == 200, resposta.text
    assert "spreadsheetml" in resposta.headers["content-type"]
    assert "gira-caboclo-2026-08-12.xlsx" in resposta.headers["content-disposition"]

    planilha = load_workbook(BytesIO(resposta.content)).active
    texto = "\n".join(
        str(celula.value)
        for linha in planilha.iter_rows()
        for celula in linha
        if celula.value
    )
    assert "Gira de Caboclo" in texto
    assert "12/08/2026" in texto
    assert "Porteira de Atendimento" in texto
    # Ana é elegível e deve sair sugerida; Bruno é fixo, mas entra na lista de
    # integrantes para preencher à mão.
    assert "Ana" in texto
    assert "Bruno" in texto
