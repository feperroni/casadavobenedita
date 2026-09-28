"""Leitura do estoque por foto: proposta, conferência e aplicação.

A chamada ao provedor é mockada — o que se testa aqui é o que fazemos com a
resposta dela, que é onde mora a lógica que pode estragar o estoque.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import types

from app.main import app
from app.models import ItemEstoque
from app.services import visao_estoque

# 1x1 PNG, só para haver bytes de imagem válidos no upload.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def foto(nome="prateleira.png"):
    return ("fotos", (nome, PNG, "image/png"))


def responder(monkeypatch, payload, capturar=None):
    """Finge a resposta do modelo, já no formato do schema."""

    def falso_generate_content(**kwargs):
        if capturar is not None:
            capturar.update(kwargs)
        return SimpleNamespace(text=json.dumps(payload))

    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=falso_generate_content)
    )
    monkeypatch.setattr(visao_estoque.genai, "Client", lambda: cliente)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")


def criar_item(client, nome, **campos):
    resposta = client.post("/estoque/itens", json={"nome": nome, **campos})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_modelo_usa_o_padrao_sem_a_variavel(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)

    assert visao_estoque.modelo() == visao_estoque.MODELO_PADRAO


def test_variavel_de_ambiente_troca_o_modelo_sem_precisar_editar_codigo(monkeypatch):
    # O Google já aposentou modelo do nível gratuito com poucos dias de aviso
    # (foi o que aconteceu com o gemini-2.5-flash); a troca precisa ser uma
    # variável no Railway, não um deploy.
    monkeypatch.setenv("GEMINI_MODEL", "gemini-9000-flash")

    assert visao_estoque.modelo() == "gemini-9000-flash"


def test_a_chamada_usa_o_modelo_configurado(monkeypatch):
    capturado = {}
    responder(monkeypatch, {"encontrados": [], "novos": []}, capturar=capturado)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-modelo-de-teste")

    with TestClient(app) as client:
        client.post("/estoque/leitura-foto", files=[foto()])

    assert capturado["model"] == "gemini-modelo-de-teste"


def test_modelo_aposentado_vira_mensagem_clara_em_vez_de_500(monkeypatch):
    """Reproduz o 404 real: 'model ... is no longer available to new users'."""

    def falso_generate_content(**kwargs):
        raise visao_estoque.genai.errors.ClientError(
            404,
            {
                "error": {
                    "code": 404,
                    "message": (
                        "This model models/gemini-2.5-flash is no longer "
                        "available to new users. Please update your code to "
                        "use models/gemini-3.6-flash for the latest features "
                        "and improvements."
                    ),
                    "status": "NOT_FOUND",
                }
            },
        )

    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=falso_generate_content)
    )
    monkeypatch.setattr(visao_estoque.genai, "Client", lambda: cliente)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    # 503 com a mensagem do Google, não 500: o catch de APIError segurou o
    # que aconteceu de verdade em produção.
    assert resposta.status_code == 503
    assert "no longer available" in resposta.json()["detail"]


def sobrecarga():
    """O 503 real que o Google devolve quando o modelo está congestionado."""
    return visao_estoque.genai.errors.ServerError(
        503,
        {
            "error": {
                "code": 503,
                "message": (
                    "This model is currently experiencing high demand. Spikes "
                    "in demand are usually temporary. Please try again later."
                ),
                "status": "UNAVAILABLE",
            }
        },
    )


def responder_apos_falhas(monkeypatch, falhas, payload):
    """Falha ``falhas`` vezes com sobrecarga e só então responde."""
    chamadas = {"n": 0}

    def falso_generate_content(**kwargs):
        chamadas["n"] += 1
        if chamadas["n"] <= falhas:
            raise sobrecarga()
        return SimpleNamespace(text=json.dumps(payload))

    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=falso_generate_content)
    )
    monkeypatch.setattr(visao_estoque.genai, "Client", lambda: cliente)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    # A espera de verdade só faria a suíte demorar; o que importa é o laço.
    monkeypatch.setattr(visao_estoque.time, "sleep", lambda _: None)
    return chamadas


def test_sobrecarga_passageira_e_repetida_sem_incomodar_o_usuario(monkeypatch):
    """503 de pico costuma passar em segundos — não vale perder a foto enviada."""
    chamadas = responder_apos_falhas(
        monkeypatch, falhas=2, payload={"encontrados": [], "novos": []}
    )

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 200, resposta.text
    assert chamadas["n"] == 3, "deveria ter tentado de novo depois dos dois 503"


def test_sobrecarga_que_nao_passa_vira_recado_em_portugues(monkeypatch):
    """Sem isto o usuário lê o JSON cru do Google no celular, como aconteceu."""
    chamadas = responder_apos_falhas(monkeypatch, falhas=99, payload={})

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 503
    detalhe = resposta.json()["detail"]
    assert "sobrecarregado" in detalhe
    assert "faça a conferência na mão" in detalhe
    # Nada de despejo do erro do provedor na tela.
    assert "UNAVAILABLE" not in detalhe
    assert "{" not in detalhe
    assert chamadas["n"] == visao_estoque.TENTATIVAS


def test_erro_permanente_nao_fica_repetindo(monkeypatch):
    """Modelo aposentado repetiria o mesmo 404 três vezes, só demorando mais."""
    chamadas = {"n": 0}

    def falso_generate_content(**kwargs):
        chamadas["n"] += 1
        raise visao_estoque.genai.errors.ClientError(
            404, {"error": {"code": 404, "message": "no longer available"}}
        )

    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=falso_generate_content)
    )
    monkeypatch.setattr(visao_estoque.genai, "Client", lambda: cliente)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    monkeypatch.setattr(visao_estoque.time, "sleep", lambda _: None)

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 503
    assert chamadas["n"] == 1


def test_resposta_cortada_vira_recado_em_vez_de_500(monkeypatch):
    """Estante com muitos itens distintos pode estourar o teto de tokens.

    O JSON chega pela metade: tem texto, mas não fecha. Sem tratamento isso
    subia como JSONDecodeError e o usuário via um 500 com stack trace.
    """

    def falso_generate_content(**kwargs):
        return SimpleNamespace(
            text='{"encontrados": [{"item_id": 1, "quantidade": 12, "confi'
        )

    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=falso_generate_content)
    )
    monkeypatch.setattr(visao_estoque.genai, "Client", lambda: cliente)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 503
    assert "incompleta" in resposta.json()["detail"]


def test_prompt_ensina_a_contar_item_agrupado_em_nicho(monkeypatch):
    """A caixa de nichos é como o terreiro guarda vela: sem isto, a IA se cala.

    As instruções mandam não estimar o que está encoberto — numa caixa dessas
    toda vela encosta na vizinha, e o modelo devolvia a estante quase vazia.
    """
    capturado = {}
    responder(monkeypatch, {"encontrados": [], "novos": []}, capturar=capturado)

    with TestClient(app) as client:
        client.post("/estoque/leitura-foto", files=[foto()])

    instrucoes = capturado["config"].system_instruction
    assert "cada ponta visível é uma unidade" in instrucoes
    assert "Cor faz parte da identidade" in instrucoes


def test_sem_chave_a_leitura_avisa_em_vez_de_estourar(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 503
    assert "GEMINI_API_KEY" in resposta.json()["detail"]


def test_primeira_leitura_propoe_tudo_como_novo(monkeypatch):
    responder(
        monkeypatch,
        {
            "encontrados": [],
            "novos": [
                {
                    "nome": "Vela branca 7 dias",
                    "quantidade": 12,
                    "unidade": "unidade",
                    "categoria": "Velas",
                    "confianca": "alta",
                }
            ],
        },
    )

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["novos"][0]["nome"] == "Vela branca 7 dias"
    assert corpo["encontrados"] == []
    assert corpo["nao_apareceram"] == []


def test_o_catalogo_vai_no_prompt_a_partir_da_segunda_leitura(monkeypatch):
    capturado = {}
    responder(monkeypatch, {"encontrados": [], "novos": []}, capturar=capturado)

    with TestClient(app) as client:
        criar_item(client, "Cachaça", quantidade=3, unidade="garrafa")
        client.post("/estoque/leitura-foto", files=[foto()])

    # Conferir uma lista fechada erra bem menos que descobrir do zero: o
    # catálogo precisa chegar ao modelo, com o id que ele deve devolver.
    texto = capturado["contents"][-1]
    assert "Cachaça" in texto
    assert "id " in texto


def test_itens_que_a_foto_nao_conta_ficam_fora_do_prompt(monkeypatch):
    capturado = {}
    responder(monkeypatch, {"encontrados": [], "novos": []}, capturar=capturado)

    with TestClient(app) as client:
        criar_item(client, "Arruda", quantidade=2, contar_por_foto=False)
        criar_item(client, "Vela branca", quantidade=5)
        client.post("/estoque/leitura-foto", files=[foto()])

    texto = capturado["contents"][-1]
    assert "Vela branca" in texto
    assert "Arruda" not in texto


def test_todas_as_fotos_vao_na_mesma_chamada(monkeypatch):
    capturado = {}
    responder(monkeypatch, {"encontrados": [], "novos": []}, capturar=capturado)

    with TestClient(app) as client:
        client.post(
            "/estoque/leitura-foto",
            files=[foto("sala1.png"), foto("sala2.png"), foto("sala3.png")],
        )

    # Uma foto por chamada faria o mesmo item, visível em duas, virar dois.
    imagens = [b for b in capturado["contents"] if isinstance(b, types.Part)]
    assert len(imagens) == 3


def test_item_do_catalogo_que_nao_apareceu_e_listado_mas_nao_zera(monkeypatch):
    responder(monkeypatch, {"encontrados": [], "novos": []})

    with TestClient(app) as client:
        item = criar_item(client, "Guaraná", quantidade=8)
        resposta = client.post("/estoque/leitura-foto", files=[foto()]).json()

        # A foto mostra uma prateleira, não o estoque inteiro: zerar o que não
        # apareceu seria o pior erro possível.
        assert resposta["nao_apareceram"][0]["nome"] == "Guaraná"
        assert client.get(f"/estoque/itens/{item['id']}").json()["quantidade"] == 8


def test_encontrado_mostra_o_saldo_atual_ao_lado_do_lido(monkeypatch):
    with TestClient(app) as client:
        item = criar_item(client, "Vela palito", quantidade=20)
        responder(
            monkeypatch,
            {
                "encontrados": [
                    {
                        "item_id": item["id"],
                        "quantidade": 14,
                        "confianca": "baixa",
                        "observacao": "Caixa parcialmente encoberta",
                    }
                ],
                "novos": [],
            },
        )

        lido = client.post("/estoque/leitura-foto", files=[foto()]).json()

    encontrado = lido["encontrados"][0]
    assert encontrado["quantidade_atual"] == 20
    assert encontrado["quantidade_lida"] == 14
    assert encontrado["confianca"] == "baixa"
    assert encontrado["observacao"] == "Caixa parcialmente encoberta"


def test_id_inventado_pelo_modelo_e_descartado(monkeypatch):
    responder(
        monkeypatch,
        {
            "encontrados": [
                {
                    "item_id": 9999,
                    "quantidade": 5,
                    "confianca": "alta",
                    "observacao": "",
                }
            ],
            "novos": [],
        },
    )

    with TestClient(app) as client:
        criar_item(client, "Mel", quantidade=1)
        lido = client.post("/estoque/leitura-foto", files=[foto()]).json()

    assert lido["encontrados"] == []


def test_a_leitura_sozinha_nao_mexe_no_estoque(monkeypatch):
    with TestClient(app) as client:
        item = criar_item(client, "Charuto", quantidade=10)
        responder(
            monkeypatch,
            {
                "encontrados": [
                    {
                        "item_id": item["id"],
                        "quantidade": 2,
                        "confianca": "alta",
                        "observacao": "",
                    }
                ],
                "novos": [],
            },
        )

        client.post("/estoque/leitura-foto", files=[foto()])

        # Proposta é proposta: só o aplicar muda saldo.
        assert client.get(f"/estoque/itens/{item['id']}").json()["quantidade"] == 10
        assert len(client.get(f"/estoque/itens/{item['id']}/movimentos").json()) == 1


def test_aplicar_reconta_existente_e_cadastra_novo():
    with TestClient(app) as client:
        item = criar_item(client, "Vela branca", quantidade=12)

        resposta = client.post(
            "/estoque/leitura-foto/aplicar",
            json={
                "ajustes": [
                    {"item_id": item["id"], "quantidade": 7},
                    {
                        "nome": "Champanhe",
                        "quantidade": 2,
                        "unidade": "garrafa",
                        "categoria": "Bebidas",
                    },
                ]
            },
        )
        assert resposta.status_code == 200, resposta.text

        por_nome = {i["nome"]: i for i in resposta.json()}
        assert por_nome["Vela branca"]["quantidade"] == 7
        # O que a foto viu fora do catálogo entra cadastrado, não vira aviso.
        assert por_nome["Champanhe"]["quantidade"] == 2
        assert por_nome["Champanhe"]["unidade"] == "garrafa"

        movimentos = client.get(f"/estoque/itens/{item['id']}/movimentos").json()
        assert movimentos[0]["delta"] == -5
        # A origem separa o que veio da foto do que foi digitado na mão.
        assert movimentos[0]["origem"] == "Foto"


def test_item_novo_nasce_com_o_historico_da_foto():
    """O saldo do item recém-criado tem de vir de um movimento rastreável."""
    with TestClient(app) as client:
        resposta = client.post(
            "/estoque/leitura-foto/aplicar",
            json={"ajustes": [{"nome": "Guaraná", "quantidade": 4}]},
        )
        assert resposta.status_code == 200, resposta.text

        novo = next(i for i in resposta.json() if i["nome"] == "Guaraná")
        movimentos = client.get(f"/estoque/itens/{novo['id']}/movimentos").json()
        assert len(movimentos) == 1
        assert movimentos[0]["delta"] == 4
        assert movimentos[0]["origem"] == "Foto"


def test_aplicar_exige_item_existente_ou_novo_mas_nao_os_dois():
    with TestClient(app) as client:
        item = criar_item(client, "Farofa", quantidade=1)

        for ajuste in (
            {"quantidade": 3},
            {"item_id": item["id"], "nome": "Outro", "quantidade": 3},
        ):
            resposta = client.post(
                "/estoque/leitura-foto/aplicar", json={"ajustes": [ajuste]}
            )
            assert resposta.status_code == 400, ajuste


def test_recusa_por_seguranca_vira_mensagem_e_nao_indexerror(monkeypatch):
    def falso_generate_content(**kwargs):
        # Bloqueio volta sem candidato de texto; ler `.text` não estoura,
        # devolve None — mas ler content[0] direto, como fazíamos antes,
        # estouraria.
        return SimpleNamespace(
            text=None,
            candidates=[],
            prompt_feedback=SimpleNamespace(
                block_reason=SimpleNamespace(value="SAFETY")
            ),
        )

    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=falso_generate_content)
    )
    monkeypatch.setattr(visao_estoque.genai, "Client", lambda: cliente)
    monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")

    with TestClient(app) as client:
        resposta = client.post("/estoque/leitura-foto", files=[foto()])

    assert resposta.status_code == 503
    assert "recusada" in resposta.json()["detail"]
    assert "SAFETY" in resposta.json()["detail"]


def test_mais_de_quatro_fotos_e_recusado(monkeypatch):
    responder(monkeypatch, {"encontrados": [], "novos": []})

    with TestClient(app) as client:
        resposta = client.post(
            "/estoque/leitura-foto", files=[foto(f"f{i}.png") for i in range(5)]
        )

    assert resposta.status_code == 503
    assert "no máximo" in resposta.json()["detail"]


def test_formato_de_imagem_nao_suportado_e_recusado(monkeypatch):
    responder(monkeypatch, {"encontrados": [], "novos": []})

    with TestClient(app) as client:
        resposta = client.post(
            "/estoque/leitura-foto",
            files=[("fotos", ("doc.pdf", b"%PDF-1.4", "application/pdf"))],
        )

    assert resposta.status_code == 503
    assert "Formato" in resposta.json()["detail"]


@pytest.mark.parametrize("configurada", [True, False])
def test_endpoint_diz_se_a_leitura_esta_disponivel(monkeypatch, configurada):
    if configurada:
        monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste")
    else:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with TestClient(app) as client:
        assert (
            client.get("/estoque/leitura-foto/disponivel").json()["disponivel"]
            is configurada
        )


def test_nao_guarda_a_imagem_em_disco(monkeypatch, tmp_path, db):
    """A foto entra na chamada e é descartada — nada vai para o banco."""
    responder(monkeypatch, {"encontrados": [], "novos": []})

    with TestClient(app) as client:
        client.post("/estoque/leitura-foto", files=[foto()])

    # Nenhum item nasce da leitura sozinha, e não existe tabela de imagem.
    assert db.query(ItemEstoque).count() == 0
    assert "imagem" not in {t.lower() for t in ItemEstoque.metadata.tables}
