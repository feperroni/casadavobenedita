"""Visão operacional: presença, atendimento e falta mês a mês."""

from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    AptidaoFuncao,
    AreaEnum,
    CargoEnum,
    FuncaoOperacionalEnum,
    Gira,
    Pessoa,
    TipoGiraEnum,
)

LIMPEZA_1 = FuncaoOperacionalEnum.LIMPEZA_1
LIMPEZA_1_PESSOA_2 = FuncaoOperacionalEnum.LIMPEZA_1_PESSOA_2
LIMPEZA_2 = FuncaoOperacionalEnum.LIMPEZA_2
PORTEIRA_ATENDIMENTO = FuncaoOperacionalEnum.PORTEIRA_ATENDIMENTO
PORTEIRA_SENHA = FuncaoOperacionalEnum.PORTEIRA_SENHA


def data_em(ano: int, mes: int, dia: int) -> datetime:
    """Giras usam data ingênua: a coluna ``Gira.data`` é DateTime sem timezone."""
    return datetime(ano, mes, dia)  # noqa: DTZ001


def criar_pessoa(db, nome, cargo=CargoEnum.RODIZIO, ativo=1, aptidoes=None):
    """``aptidoes`` nula não marca nenhuma — os testes de presença não usam
    função operacional nenhuma. Quem testa Limpeza 1/2 passa a lista."""
    pessoa = Pessoa(
        nome=nome,
        cargo=cargo,
        area=AreaEnum.MEDIUNIDADE,
        mensalidade=0.0,
        ativo=ativo,
    )
    if aptidoes:
        pessoa.aptidoes = [AptidaoFuncao(funcao=funcao) for funcao in aptidoes]
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)
    return pessoa


def criar_gira(db, data):
    gira = Gira(tipo=TipoGiraEnum.CABOCLO, data=data)
    db.add(gira)
    db.commit()
    db.refresh(gira)
    return gira


def salvar_escala(client, gira_id, trabalhadores):
    resposta = client.put(
        f"/giras/{gira_id}/escala",
        json={"trabalhadores": trabalhadores, "funcoes": []},
    )
    assert resposta.status_code == 200, resposta.text


def test_mes_sem_gira_vem_vazio_e_nao_quebra(db):
    criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    assert resumo["total_giras"] == 0
    assert resumo["giras"] == []
    assert resumo["integrantes"] == []


def test_conta_presenca_atendimento_e_falta_de_cada_um(db):
    ana = criar_pessoa(db, "Ana")
    criar_pessoa(db, "Bruno")
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        # Ana esteve e atendeu; o Bruno nem foi (entra como falta).
        salvar_escala(
            client,
            gira.id,
            [{"pessoa_id": ana.id, "presente": True, "atendeu": True}],
        )
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    por_nome = {i["nome"]: i for i in resumo["integrantes"]}
    assert por_nome["Ana"] == {
        "pessoa_id": ana.id,
        "nome": "Ana",
        "cargo": CargoEnum.RODIZIO.value,
        "presencas": 1,
        "atendimentos": 1,
        "faltas": 0,
        "porteira_atendimento": 0,
        "porteira_senha": 0,
        "limpeza_1": 0,
        "limpeza_2": 0,
    }
    assert por_nome["Bruno"]["faltas"] == 1
    assert por_nome["Bruno"]["presencas"] == 0

    assert resumo["giras"][0]["presentes"] == 1
    assert resumo["giras"][0]["atenderam"] == 1
    assert resumo["giras"][0]["faltaram"] == 1


def test_presente_que_nao_atendeu_conta_so_como_presenca(db):
    """Estar na gira e atender são coisas diferentes — cambono de apoio, por ex."""
    ana = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        salvar_escala(
            client,
            gira.id,
            [{"pessoa_id": ana.id, "presente": True, "atendeu": False}],
        )
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    integrante = resumo["integrantes"][0]
    assert integrante["presencas"] == 1
    assert integrante["atendimentos"] == 0
    assert integrante["faltas"] == 0


def test_soma_as_giras_do_mes_e_ignora_as_de_fora(db):
    ana = criar_pessoa(db, "Ana")
    de_marco = [
        criar_gira(db, data_em(2026, 3, 7)),
        criar_gira(db, data_em(2026, 3, 21)),
    ]
    fevereiro = criar_gira(db, data_em(2026, 2, 28))
    abril = criar_gira(db, data_em(2026, 4, 1))

    with TestClient(app) as client:
        for gira in (*de_marco, fevereiro, abril):
            salvar_escala(
                client,
                gira.id,
                [{"pessoa_id": ana.id, "presente": True, "atendeu": True}],
            )
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    # A virada de mês é o ponto sensível: 28/02 e 01/04 ficam de fora.
    assert resumo["total_giras"] == 2
    assert resumo["integrantes"][0]["presencas"] == 2


def test_dezembro_nao_vaza_para_o_ano_seguinte(db):
    """Dezembro é o único mês em que o fim do intervalo troca de ano."""
    ana = criar_pessoa(db, "Ana")
    dezembro = criar_gira(db, data_em(2026, 12, 20))
    janeiro = criar_gira(db, data_em(2027, 1, 3))

    with TestClient(app) as client:
        for gira in (dezembro, janeiro):
            salvar_escala(
                client,
                gira.id,
                [{"pessoa_id": ana.id, "presente": True, "atendeu": False}],
            )
        resumo = client.get("/dashboard/operacional?ano=2026&mes=12").json()

    assert resumo["total_giras"] == 1
    assert resumo["integrantes"][0]["presencas"] == 1


def test_quem_entrou_depois_nao_aparece_com_falta_retroativa(db):
    """Sem linha na gira não há falta: a pessoa nem estava no terreiro ainda."""
    ana = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        salvar_escala(
            client,
            gira.id,
            [{"pessoa_id": ana.id, "presente": True, "atendeu": False}],
        )
        # Só agora entra no terreiro, depois da gira já registrada.
        criar_pessoa(db, "Zara")
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    assert [i["nome"] for i in resumo["integrantes"]] == ["Ana"]


def test_integrantes_saem_em_ordem_alfabetica(db):
    for nome in ("Zara", "Ana", "Mira"):
        criar_pessoa(db, nome)
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        salvar_escala(client, gira.id, [])
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    assert [i["nome"] for i in resumo["integrantes"]] == ["Ana", "Mira", "Zara"]


def test_giras_do_mes_mostra_quem_fez_a_limpeza(db):
    """Limpeza 1 e Limpeza 2 saem por nome, na ordem das posições da gira."""
    ana = criar_pessoa(db, "Ana", aptidoes=[LIMPEZA_1])
    bruno = criar_pessoa(db, "Bruno", aptidoes=[LIMPEZA_1])
    carla = criar_pessoa(db, "Carla", aptidoes=[LIMPEZA_2])
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": LIMPEZA_1.value, "pessoa_id": ana.id},
                    {"funcao": LIMPEZA_1_PESSOA_2.value, "pessoa_id": bruno.id},
                    {"funcao": LIMPEZA_2.value, "pessoa_id": carla.id},
                ],
            },
        )
        assert resposta.status_code == 200, resposta.text

        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    gira_do_mes = resumo["giras"][0]
    # A Pessoa 1 vem antes da Pessoa 2, mesmo tendo sido salva depois na API.
    assert gira_do_mes["limpeza_1"] == ["Ana", "Bruno"]
    assert gira_do_mes["limpeza_2"] == ["Carla"]


def test_gira_sem_limpeza_preenchida_vem_com_lista_vazia(db):
    criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        salvar_escala(client, gira.id, [])
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    assert resumo["giras"][0]["limpeza_1"] == []
    assert resumo["giras"][0]["limpeza_2"] == []
    assert resumo["giras"][0]["porteira_atendimento"] == []
    assert resumo["giras"][0]["porteira_senha"] == []


def test_giras_do_mes_mostra_quem_fez_a_porteira(db):
    """A mesma listagem por nome já feita pra limpeza vale pras porteiras."""
    ana = criar_pessoa(db, "Ana", aptidoes=[PORTEIRA_ATENDIMENTO])
    bruno = criar_pessoa(db, "Bruno", aptidoes=[PORTEIRA_SENHA])
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": ana.id},
                    {"funcao": PORTEIRA_SENHA.value, "pessoa_id": bruno.id},
                ],
            },
        )
        assert resposta.status_code == 200, resposta.text

        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    gira_do_mes = resumo["giras"][0]
    assert gira_do_mes["porteira_atendimento"] == ["Ana"]
    assert gira_do_mes["porteira_senha"] == ["Bruno"]
    # Porteira não é limpeza: cada coluna só traz quem é dela.
    assert gira_do_mes["limpeza_1"] == []
    assert gira_do_mes["limpeza_2"] == []


def test_frequencia_por_integrante_soma_limpeza_1_e_2_no_mes(db):
    """A Ana faz Limpeza 1 nas duas giras do mês; o Bruno, Limpeza 2 numa só."""
    ana = criar_pessoa(db, "Ana", aptidoes=[LIMPEZA_1])
    bruno = criar_pessoa(db, "Bruno", aptidoes=[LIMPEZA_2])
    gira1 = criar_gira(db, data_em(2026, 3, 7))
    gira2 = criar_gira(db, data_em(2026, 3, 14))

    with TestClient(app) as client:
        r1 = client.put(
            f"/giras/{gira1.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": LIMPEZA_1.value, "pessoa_id": ana.id},
                    {"funcao": LIMPEZA_2.value, "pessoa_id": bruno.id},
                ],
            },
        )
        assert r1.status_code == 200, r1.text
        r2 = client.put(
            f"/giras/{gira2.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [{"funcao": LIMPEZA_1.value, "pessoa_id": ana.id}],
            },
        )
        assert r2.status_code == 200, r2.text

        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    por_nome = {i["nome"]: i for i in resumo["integrantes"]}
    assert por_nome["Ana"]["limpeza_1"] == 2
    assert por_nome["Ana"]["limpeza_2"] == 0
    assert por_nome["Bruno"]["limpeza_1"] == 0
    assert por_nome["Bruno"]["limpeza_2"] == 1


def test_frequencia_por_integrante_zerada_sem_limpeza(db):
    criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        salvar_escala(client, gira.id, [])
        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    integrante = resumo["integrantes"][0]
    assert integrante["limpeza_1"] == 0
    assert integrante["limpeza_2"] == 0
    assert integrante["porteira_atendimento"] == 0
    assert integrante["porteira_senha"] == 0


def test_frequencia_por_integrante_soma_as_duas_porteiras_no_mes(db):
    """A Ana é porteira de atendimento em duas giras; o Bruno, de senha numa."""
    ana = criar_pessoa(db, "Ana", aptidoes=[PORTEIRA_ATENDIMENTO])
    bruno = criar_pessoa(db, "Bruno", aptidoes=[PORTEIRA_SENHA])
    gira1 = criar_gira(db, data_em(2026, 3, 7))
    gira2 = criar_gira(db, data_em(2026, 3, 14))

    with TestClient(app) as client:
        r1 = client.put(
            f"/giras/{gira1.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": ana.id},
                    {"funcao": PORTEIRA_SENHA.value, "pessoa_id": bruno.id},
                ],
            },
        )
        assert r1.status_code == 200, r1.text
        r2 = client.put(
            f"/giras/{gira2.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": ana.id}
                ],
            },
        )
        assert r2.status_code == 200, r2.text

        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    por_nome = {i["nome"]: i for i in resumo["integrantes"]}
    assert por_nome["Ana"]["porteira_atendimento"] == 2
    assert por_nome["Ana"]["porteira_senha"] == 0
    assert por_nome["Bruno"]["porteira_atendimento"] == 0
    assert por_nome["Bruno"]["porteira_senha"] == 1
    # Porteira não pode vazar para a coluna de limpeza, nem o contrário.
    assert por_nome["Ana"]["limpeza_1"] == 0
    assert por_nome["Ana"]["limpeza_2"] == 0


def test_quem_ocupa_porteira_e_limpeza_na_mesma_gira_conta_nas_duas(db):
    """Uma pessoa pode ter mais de uma função na gira; cada coluna conta a sua."""
    ana = criar_pessoa(db, "Ana", aptidoes=[PORTEIRA_SENHA, LIMPEZA_1])
    gira = criar_gira(db, data_em(2026, 3, 7))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_SENHA.value, "pessoa_id": ana.id},
                    {"funcao": LIMPEZA_1.value, "pessoa_id": ana.id},
                ],
            },
        )
        assert resposta.status_code == 200, resposta.text

        resumo = client.get("/dashboard/operacional?ano=2026&mes=3").json()

    integrante = resumo["integrantes"][0]
    assert integrante["porteira_senha"] == 1
    assert integrante["limpeza_1"] == 1
    assert integrante["porteira_atendimento"] == 0
