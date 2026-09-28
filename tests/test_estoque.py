"""Estoque: cadastro manual, recontagem, ajuste avulso e alerta de mínimo."""

from fastapi.testclient import TestClient

from app.main import app
from app.models import ItemEstoque


def criar(client, nome, **campos):
    corpo = {"nome": nome, **campos}
    resposta = client.post("/estoque/itens", json=corpo)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_item_nasce_com_o_saldo_informado_e_o_historico_correspondente():
    with TestClient(app) as client:
        item = criar(client, "Vela branca 7 dias", quantidade=12, unidade="unidade")
        assert item["quantidade"] == 12

        # O saldo inicial vira movimento: o histórico nasce completo, sem um
        # número aparecendo do nada.
        movimentos = client.get(f"/estoque/itens/{item['id']}/movimentos").json()
        assert len(movimentos) == 1
        assert movimentos[0]["delta"] == 12
        assert movimentos[0]["quantidade_apos"] == 12
        assert movimentos[0]["origem"] == "Manual"


def test_item_sem_saldo_inicial_nao_gera_movimento():
    with TestClient(app) as client:
        item = criar(client, "Alguidar médio")
        assert item["quantidade"] == 0
        assert client.get(f"/estoque/itens/{item['id']}/movimentos").json() == []


def test_recontagem_grava_a_diferenca():
    with TestClient(app) as client:
        item = criar(client, "Guaraná", quantidade=10)

        recontado = client.post(
            f"/estoque/itens/{item['id']}/movimentos", json={"quantidade": 6}
        )
        assert recontado.status_code == 200, recontado.text
        assert recontado.json()["quantidade"] == 6

        movimentos = client.get(f"/estoque/itens/{item['id']}/movimentos").json()
        assert movimentos[0]["delta"] == -4
        assert movimentos[0]["quantidade_apos"] == 6


def test_recontar_o_mesmo_numero_nao_polui_o_historico():
    with TestClient(app) as client:
        item = criar(client, "Charuto", quantidade=5)

        client.post(f"/estoque/itens/{item['id']}/movimentos", json={"quantidade": 5})

        # Um movimento só: o do cadastro. Conferir e achar o mesmo saldo não é
        # um movimento e não deve entrar no histórico.
        assert len(client.get(f"/estoque/itens/{item['id']}/movimentos").json()) == 1


def test_ajuste_avulso_soma_e_subtrai():
    with TestClient(app) as client:
        item = criar(client, "Vela palito", quantidade=20)

        client.post(
            f"/estoque/itens/{item['id']}/movimentos",
            json={"delta": -4, "motivo": "Usadas na gira"},
        )
        atual = client.get(f"/estoque/itens/{item['id']}").json()
        assert atual["quantidade"] == 16

        movimentos = client.get(f"/estoque/itens/{item['id']}/movimentos").json()
        assert movimentos[0]["motivo"] == "Usadas na gira"


def test_saldo_nao_fica_negativo():
    with TestClient(app) as client:
        item = criar(client, "Defumador", quantidade=2)

        client.post(f"/estoque/itens/{item['id']}/movimentos", json={"delta": -10})

        atual = client.get(f"/estoque/itens/{item['id']}").json()
        assert atual["quantidade"] == 0
        # O movimento registra o que de fato saiu, não o que foi pedido.
        movimentos = client.get(f"/estoque/itens/{item['id']}/movimentos").json()
        assert movimentos[0]["delta"] == -2


def test_movimento_exige_recontagem_ou_ajuste_mas_nao_os_dois():
    with TestClient(app) as client:
        item = criar(client, "Mel", quantidade=3)

        nenhum = client.post(f"/estoque/itens/{item['id']}/movimentos", json={})
        assert nenhum.status_code == 400

        ambos = client.post(
            f"/estoque/itens/{item['id']}/movimentos",
            json={"quantidade": 5, "delta": 2},
        )
        assert ambos.status_code == 400


def test_alerta_dispara_ao_chegar_no_minimo():
    with TestClient(app) as client:
        item = criar(client, "Cachaça", quantidade=5, minimo_alerta=2)
        assert item["em_alerta"] is False

        client.post(f"/estoque/itens/{item['id']}/movimentos", json={"quantidade": 2})

        # Chegar ao mínimo já conta: é a hora de repor, não depois de furar.
        assert client.get(f"/estoque/itens/{item['id']}").json()["em_alerta"] is True

        resumo = client.get("/estoque/resumo").json()
        assert resumo["qtd_em_alerta"] == 1
        assert resumo["itens_em_alerta"][0]["nome"] == "Cachaça"


def test_item_sem_minimo_nunca_alerta():
    with TestClient(app) as client:
        item = criar(client, "Fósforo", quantidade=0)

        assert item["em_alerta"] is False
        assert client.get("/estoque/resumo").json()["qtd_em_alerta"] == 0


def test_nome_repetido_e_recusado():
    with TestClient(app) as client:
        criar(client, "Vinho branco", quantidade=1)

        repetido = client.post("/estoque/itens", json={"nome": "Vinho branco"})
        assert repetido.status_code == 400
        assert "Já existe" in repetido.json()["detail"]


def test_editar_cadastro_nao_mexe_no_saldo():
    with TestClient(app) as client:
        item = criar(client, "Farofa", quantidade=7, minimo_alerta=1)

        atualizado = client.put(
            f"/estoque/itens/{item['id']}",
            json={
                "nome": "Farofa de dendê",
                "categoria": "Oferenda",
                "unidade": "pacote",
                "minimo_alerta": 3,
                "contar_por_foto": False,
            },
        )
        assert atualizado.status_code == 200, atualizado.text
        corpo = atualizado.json()
        assert corpo["nome"] == "Farofa de dendê"
        assert corpo["contar_por_foto"] is False
        # A quantidade só muda por movimento — editar o cadastro não a toca.
        assert corpo["quantidade"] == 7
        assert len(client.get(f"/estoque/itens/{item['id']}/movimentos").json()) == 1


def test_remover_item_leva_o_historico_junto(db):
    with TestClient(app) as client:
        item = criar(client, "Pemba", quantidade=4)
        client.post(f"/estoque/itens/{item['id']}/movimentos", json={"delta": -1})

        assert client.delete(f"/estoque/itens/{item['id']}").status_code == 200
        assert client.get(f"/estoque/itens/{item['id']}").status_code == 404

    assert db.query(ItemEstoque).count() == 0


def test_itens_marcados_para_a_foto_ficam_distinguiveis():
    """Erva e folha entram só na mão; a leitura por foto tem de saber disso."""
    with TestClient(app) as client:
        criar(client, "Vela branca", quantidade=10)
        criar(client, "Arruda", quantidade=1, contar_por_foto=False)

        itens = client.get("/estoque/itens").json()
        por_nome = {i["nome"]: i["contar_por_foto"] for i in itens}

        assert por_nome["Vela branca"] is True
        assert por_nome["Arruda"] is False
