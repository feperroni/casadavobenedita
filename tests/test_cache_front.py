"""index.html e /static/* têm de revalidar sempre — nunca ficar em cache.

Sem isto, um deploy podia atualizar a página (novas colunas, novo filtro) e o
navegador continuar servindo o app.js de antes por tempo indefinido: o HTML
mudava, o script que desenha os dados não, e a tela ficava com campo sem
preencher sem nenhum erro visível. Aconteceu de verdade depois do deploy que
acrescentou porteira/filtro na Frequência por integrante.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_pagina_principal_exige_revalidacao():
    with TestClient(app) as client:
        resposta = client.get("/")

    assert resposta.headers["cache-control"] == "no-cache"


def test_estaticos_exigem_revalidacao():
    with TestClient(app) as client:
        resposta = client.get("/static/app.js")

    assert resposta.status_code == 200
    assert resposta.headers["cache-control"] == "no-cache"


def test_arquivo_igual_volta_rapido_sem_baixar_de_novo():
    """``no-cache`` não é ``no-store``: o ETag ainda evita reenviar o arquivo
    inteiro quando o navegador já tem a versão certa."""
    with TestClient(app) as client:
        primeira = client.get("/static/app.js")
        etag = primeira.headers["etag"]

        revalidada = client.get("/static/app.js", headers={"If-None-Match": etag})

    assert revalidada.status_code == 304


def test_arquivo_diferente_baixa_de_novo():
    with TestClient(app) as client:
        resposta = client.get(
            "/static/app.js", headers={"If-None-Match": '"etag-que-nao-existe"'}
        )

    assert resposta.status_code == 200


def test_rota_de_api_nao_ganha_o_cabecalho():
    """O middleware é só para o front — não deve mexer em resposta de API."""
    with TestClient(app) as client:
        resposta = client.get("/health")

    assert "cache-control" not in {k.lower() for k in resposta.headers}
