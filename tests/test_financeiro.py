"""Financeiro: isenção que atravessa os meses e resumo da competência.

A isenção é condição, não fato do mês: quem foi isentado em setembro segue
isento em outubro sem ninguém remarcar, até que alguém desfaça. "Pago" é o
oposto — vale só no mês em que aconteceu.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.models import AreaEnum, CargoEnum, Pessoa


def criar_pessoa(db, nome, mensalidade=100.0, ativo=1):
    pessoa = Pessoa(
        nome=nome,
        cargo=CargoEnum.RODIZIO,
        area=AreaEnum.MEDIUNIDADE,
        mensalidade=mensalidade,
        ativo=ativo,
    )
    db.add(pessoa)
    db.commit()
    db.refresh(pessoa)
    return pessoa


def lancar(client, pessoa_id, ano, mes, status, valor=0.0):
    resposta = client.post(
        "/pagamentos/",
        json={
            "pessoa_id": pessoa_id,
            "ano": ano,
            "mes": mes,
            "valor": valor,
            "status": status,
        },
    )
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def competencia(client, ano, mes):
    resposta = client.get(f"/pagamentos/competencia?ano={ano}&mes={mes}")
    assert resposta.status_code == 200, resposta.text
    return {c["pessoa_id"]: c for c in resposta.json()}


def test_sem_lancamento_nenhum_a_pessoa_fica_pendente(db):
    ana = criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        situacao = competencia(client, 2026, 9)[ana.id]

    assert situacao["status"] == "Pendente"
    assert situacao["herdado"] is False


def test_isencao_de_um_mes_segue_valendo_no_mes_seguinte(db):
    ana = criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        lancar(client, ana.id, 2026, 9, "Isento")

        outubro = competencia(client, 2026, 10)[ana.id]
        novembro = competencia(client, 2026, 11)[ana.id]

    assert outubro["status"] == "Isento"
    # Herdado: não existe lançamento de outubro, a isenção é a de setembro.
    assert outubro["herdado"] is True
    assert novembro["status"] == "Isento"


def test_tirar_a_isencao_faz_o_mes_seguinte_voltar_a_cobrar(db):
    ana = criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        lancar(client, ana.id, 2026, 9, "Isento")
        # Em outubro o terreiro desfaz a isenção.
        lancar(client, ana.id, 2026, 10, "Pendente")

        novembro = competencia(client, 2026, 11)[ana.id]

    assert novembro["status"] == "Pendente"
    assert novembro["herdado"] is False


def test_pagamento_nao_se_propaga_para_o_mes_seguinte(db):
    """Pagar setembro não pode deixar outubro quitado sem ninguém pagar."""
    ana = criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        lancar(client, ana.id, 2026, 9, "Pago", valor=100.0)

        outubro = competencia(client, 2026, 10)[ana.id]

    assert outubro["status"] == "Pendente"


def test_isencao_herdada_sai_do_previsto_e_da_inadimplencia(db):
    """O resumo tem de enxergar a isenção herdada, não só a lançada no mês."""
    isenta = criar_pessoa(db, "Ana", mensalidade=100.0)
    criar_pessoa(db, "Bruno", mensalidade=100.0)

    with TestClient(app) as client:
        lancar(client, isenta.id, 2026, 9, "Isento")

        resumo = client.get("/pagamentos/resumo?ano=2026&mes=10").json()

    # Só o Bruno entra na conta de outubro; a Ana segue isenta por herança.
    assert resumo["total_previsto"] == 100.0
    assert resumo["qtd_pendentes"] == 1
    assert [i["nome"] for i in resumo["inadimplentes"]] == ["Bruno"]


def test_a_isencao_nao_volta_do_passado_por_cima_de_lancamento_do_mes(db):
    """Lançamento do próprio mês manda sobre qualquer herança."""
    ana = criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        lancar(client, ana.id, 2026, 9, "Isento")
        lancar(client, ana.id, 2026, 10, "Pago", valor=100.0)

        outubro = competencia(client, 2026, 10)[ana.id]

    assert outubro["status"] == "Pago"
    assert outubro["herdado"] is False


def test_isencao_do_ano_anterior_atravessa_a_virada(db):
    ana = criar_pessoa(db, "Ana")

    with TestClient(app) as client:
        lancar(client, ana.id, 2026, 12, "Isento")

        janeiro = competencia(client, 2027, 1)[ana.id]

    assert janeiro["status"] == "Isento"
    assert janeiro["herdado"] is True
