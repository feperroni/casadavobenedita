import os
from uuid import uuid4

# Use an in-memory SQLite database for tests to avoid altering local development data.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from fastapi.testclient import TestClient

from app.main import app


def test_criar_pessoa_com_admin_e_notas():
    payload = {
        "nome": "Maria da Silva",
        "email": f"maria-{uuid4().hex[:8]}@example.com",
        "telefone": "(11) 99999-9999",
        "cargo": "Médium Fixo",
        "area": "Mediunidade",
        "admin": True,
        "notas": "Responsável pela secretaria e apoio administrativo.",
        "mensalidade": 120.0,
        "ativo": 1,
    }
    with TestClient(app) as client:
        response = client.post("/pessoas/", json=payload)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["nome"] == payload["nome"]
        assert data["admin"] is True
        assert data["notas"] == payload["notas"]

        list_response = client.get("/pessoas/")
        assert list_response.status_code == 200
        pessoas = list_response.json()
        assert any(p["email"] == payload["email"] and p["admin"] for p in pessoas)


def test_pessoa_nasce_apta_a_tudo_quando_o_campo_e_omitido():
    payload = {
        "nome": "João de Ogum",
        "email": f"joao-{uuid4().hex[:8]}@example.com",
        "cargo": "Médium de Rodízio",
        "area": "Mediunidade",
    }
    with TestClient(app) as client:
        criada = client.post("/pessoas/", json=payload)
        assert criada.status_code == 200, criada.text
        # Quatro aptidões, não cinco: a segunda posição da Limpeza 2 é coberta
        # pela mesma marcação da primeira.
        assert criada.json()["funcoes_aptas"] == [
            "Porteira de Atendimento",
            "Porteira de Senha",
            "Limpeza 1",
            "Limpeza 2 - Pessoa 1",
        ]


def test_editar_mantendo_parte_das_funcoes():
    """O caso comum: nasce apta a tudo e o usuário desmarca só algumas.

    As funções mantidas continuam existindo na tabela enquanto as novas são
    gravadas, então recriar a coleção inteira esbarra na unicidade
    (pessoa, função) e derruba a edição com 500.
    """
    payload = {
        "nome": "Carol Perroni",
        "telefone": "11996923238",
        "cargo": "Médium Fixo",
        "area": "Curimba",
        "admin": True,
    }
    with TestClient(app) as client:
        criada = client.post("/pessoas/", json=payload)
        assert criada.status_code == 200, criada.text
        pessoa_id = criada.json()["id"]
        assert len(criada.json()["funcoes_aptas"]) == 4

        # Desmarca as duas porteiras e mantém as limpezas.
        atualizada = client.put(
            f"/pessoas/{pessoa_id}",
            json={**payload, "funcoes_aptas": ["Limpeza 1", "Limpeza 2 - Pessoa 1"]},
        )
        assert atualizada.status_code == 200, atualizada.text
        assert atualizada.json()["funcoes_aptas"] == [
            "Limpeza 1",
            "Limpeza 2 - Pessoa 1",
        ]

        # Salvar de novo sem mudar nada também tem de passar.
        de_novo = client.put(
            f"/pessoas/{pessoa_id}",
            json={**payload, "funcoes_aptas": ["Limpeza 1", "Limpeza 2 - Pessoa 1"]},
        )
        assert de_novo.status_code == 200, de_novo.text
        assert de_novo.json()["funcoes_aptas"] == ["Limpeza 1", "Limpeza 2 - Pessoa 1"]


def test_restringir_e_depois_ampliar_as_funcoes_da_pessoa():
    payload = {
        "nome": "Rita de Iansã",
        "email": f"rita-{uuid4().hex[:8]}@example.com",
        "cargo": "Cambono",
        "area": "Mediunidade",
        "funcoes_aptas": ["Porteira de Senha"],
    }
    with TestClient(app) as client:
        criada = client.post("/pessoas/", json=payload)
        assert criada.status_code == 200, criada.text
        assert criada.json()["funcoes_aptas"] == ["Porteira de Senha"]

        pessoa_id = criada.json()["id"]
        atualizada = client.put(
            f"/pessoas/{pessoa_id}",
            json={**payload, "funcoes_aptas": ["Limpeza 1", "Limpeza 2 - Pessoa 1"]},
        )
        assert atualizada.status_code == 200, atualizada.text
        # A troca substitui, não acumula: a porteira antiga sai da lista.
        assert atualizada.json()["funcoes_aptas"] == [
            "Limpeza 1",
            "Limpeza 2 - Pessoa 1",
        ]

        # Lista vazia é uma escolha válida: não participa de nenhuma função.
        sem_funcao = client.put(
            f"/pessoas/{pessoa_id}", json={**payload, "funcoes_aptas": []}
        )
        assert sem_funcao.status_code == 200, sem_funcao.text
        assert sem_funcao.json()["funcoes_aptas"] == []
