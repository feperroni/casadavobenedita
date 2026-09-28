"""Acesso restrito: allowlist de e-mail e as travas que impedem falhar aberto."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app, startup_event


@pytest.fixture()
def com_google(monkeypatch):
    """Liga o login como se as credenciais do Google estivessem definidas.

    As constantes são lidas no import do módulo, então não adianta mexer só no
    ambiente depois que ele já carregou.
    """
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "id-de-teste")
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_SECRET", "segredo-de-teste")
    monkeypatch.setenv("EMAILS_PERMITIDOS", "nossocasua@gmail.com")


def test_allowlist_ignora_espaco_e_caixa(monkeypatch):
    monkeypatch.setenv(
        "EMAILS_PERMITIDOS", " Nossocasua@Gmail.com , OUTRO@exemplo.com "
    )

    assert auth.emails_permitidos() == {
        "nossocasua@gmail.com",
        "outro@exemplo.com",
    }


def test_sem_a_variavel_ninguem_entra(monkeypatch):
    """Um e-mail embutido no código autorizaria uma conta que ninguém conferiu."""
    monkeypatch.delenv("EMAILS_PERMITIDOS", raising=False)

    assert auth.emails_permitidos() == set()


def test_producao_recusa_subir_sem_credenciais_do_google(monkeypatch):
    # Este é o buraco que a trava fecha: sem as credenciais o middleware não
    # pede login de ninguém, e a aplicação serviria tudo em silêncio.
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_SECRET", None)
    monkeypatch.setenv("EMAILS_PERMITIDOS", "nossocasua@gmail.com")

    problemas = auth.problemas_de_configuracao()

    assert len(problemas) == 1
    assert "GOOGLE_CLIENT_ID" in problemas[0]


def test_producao_recusa_subir_sem_allowlist(monkeypatch):
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", "id-de-teste")
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_SECRET", "segredo-de-teste")
    monkeypatch.delenv("EMAILS_PERMITIDOS", raising=False)

    problemas = auth.problemas_de_configuracao()

    assert len(problemas) == 1
    assert "EMAILS_PERMITIDOS" in problemas[0]


def test_configuracao_completa_nao_reclama(com_google):
    assert auth.problemas_de_configuracao() == []


def test_startup_em_producao_estoura_com_acesso_aberto(monkeypatch):
    # Roda o startup na mão em vez de marcar o teste como async: sem plugin de
    # async instalado, um teste assíncrono passa sem nunca ter executado.
    monkeypatch.setattr("app.main.APP_ENV", "production")
    monkeypatch.setattr(auth, "SECRET_KEY", "uma-chave-longa-e-aleatoria")
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_SECRET", None)
    monkeypatch.setenv("EMAILS_PERMITIDOS", "nossocasua@gmail.com")

    with pytest.raises(RuntimeError, match="ficaria"):
        asyncio.run(startup_event())


def test_startup_em_producao_passa_com_tudo_configurado(monkeypatch, com_google):
    monkeypatch.setattr("app.main.APP_ENV", "production")
    monkeypatch.setattr(auth, "SECRET_KEY", "uma-chave-longa-e-aleatoria")

    asyncio.run(startup_event())  # não deve levantar


def test_sem_login_nao_da_para_ler_os_integrantes(com_google):
    """A porta principal: com o login ligado, nada de dados sem sessão."""
    with TestClient(app) as client:
        resposta = client.get("/pessoas/", follow_redirects=False)

    assert resposta.status_code in (302, 307)
    assert resposta.headers["location"].endswith("/login")


def test_estoque_e_financeiro_tambem_ficam_atras_do_login(com_google):
    with TestClient(app) as client:
        for caminho in ("/estoque/itens", "/pagamentos/resumo?ano=2026&mes=8"):
            resposta = client.get(caminho, follow_redirects=False)
            assert resposta.status_code in (302, 307), caminho


def test_health_continua_aberto_para_o_railway(com_google):
    """O healthcheck da plataforma não passa por login, e não expõe dado nenhum."""
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_com_login_desligado_a_app_responde(monkeypatch):
    """Desenvolvimento local segue aberto — é o que permite rodar sem o Google."""
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(auth, "GOOGLE_CLIENT_SECRET", None)

    with TestClient(app) as client:
        assert client.get("/pessoas/").status_code == 200
