"""Rodízio das funções operacionais e planilha imprimível."""

from datetime import datetime, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import migracoes
from app.database import engine
from app.main import app
from app.models import (
    FUNCOES_COM_APTIDAO,
    AptidaoFuncao,
    AreaEnum,
    CargoEnum,
    Entidade,
    FuncaoGira,
    FuncaoOperacionalEnum,
    Gira,
    Pessoa,
    TipoGiraEnum,
)
from app.services.funcoes import sugerir

LIMPEZA_1 = FuncaoOperacionalEnum.LIMPEZA_1
LIMPEZA_1_PESSOA_2 = FuncaoOperacionalEnum.LIMPEZA_1_PESSOA_2
LIMPEZA_2 = FuncaoOperacionalEnum.LIMPEZA_2
LIMPEZA_2_PESSOA_2 = FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_2
LIMPEZA_2_PESSOA_3 = FuncaoOperacionalEnum.LIMPEZA_2_PESSOA_3
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


def test_qualquer_cargo_apto_entra_no_rodizio(db):
    """Cargo não decide mais quem entra no rodízio — só a aptidão e estar ativo."""
    fixa = criar_pessoa(db, "Ana Fixa", cargo=CargoEnum.FIXO)
    criar_pessoa(db, "Bruno Inativo", cargo=CargoEnum.RODIZIO, ativo=0)
    cambono = criar_pessoa(db, "Carla Cambono", cargo=CargoEnum.CAMBONO)

    sugestoes = por_funcao(db)

    # O inativo fica de fora; a fixa e a cambona entram, em ordem alfabética.
    assert sugestoes[PORTEIRA_ATENDIMENTO]["pessoa_id"] == fixa.id
    assert sugestoes[PORTEIRA_SENHA]["pessoa_id"] == cambono.id


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
    for nome in ("Bruno", "Carla", "Diego", "Elena", "Fabio", "Gustavo", "Helo"):
        criar_pessoa(db, nome)

    criar_gira(db, data_em(2026, 1, 5), [(LIMPEZA_1, ana)])

    sugestoes = por_funcao(db)

    # A carga é contada junto: ter feito o "antes da gira" tira a Ana da
    # frente de todas as posições, e não só dessa fila. Fosse por função, ela
    # voltaria já na próxima gira numa das outras — que é o que se quer evitar.
    escolhidos = {s["nome"] for s in sugestoes.values()}
    assert "Ana" not in escolhidos
    # Com sete colegas zerados para sete posições, ela nem é chamada.
    assert escolhidos == {
        "Bruno",
        "Carla",
        "Diego",
        "Elena",
        "Fabio",
        "Gustavo",
        "Helo",
    }


def test_as_posicoes_de_uma_categoria_caem_em_pessoas_diferentes(db):
    for nome in ("Ana", "Bruno", "Carla", "Diego", "Elena", "Fabio", "Gustavo"):
        criar_pessoa(db, nome)

    sugestoes = por_funcao(db)

    antes = {
        sugestoes[LIMPEZA_1]["pessoa_id"],
        sugestoes[LIMPEZA_1_PESSOA_2]["pessoa_id"],
    }
    depois = {
        sugestoes[LIMPEZA_2]["pessoa_id"],
        sugestoes[LIMPEZA_2_PESSOA_2]["pessoa_id"],
        sugestoes[LIMPEZA_2_PESSOA_3]["pessoa_id"],
    }
    assert None not in antes and len(antes) == 2
    assert None not in depois and len(depois) == 3
    # Uma pessoa não ocupa duas posições na mesma gira, nem dentro da mesma
    # categoria nem entre categorias diferentes.
    assert antes.isdisjoint(depois)


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
    assert "apto para Limpeza - Depois da Gira." in detalhe
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


def test_regravar_gira_antiga_nao_esbarra_em_aptidao_retirada_depois(db):
    """Tirar a aptidão de alguém não pode travar a gira em que já trabalhou.

    O usuário abria uma gira antiga, não mexia em nada, clicava em Salvar e
    levava "fulano não está marcado como apto" — sem saída, porque a tela
    mantém quem está gravado justamente para não apagar o histórico.
    """
    ana = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5), [(PORTEIRA_ATENDIMENTO, ana)])

    with TestClient(app) as client:
        # O cadastro muda depois: a Ana deixa de fazer porteira.
        restringida = client.put(
            f"/pessoas/{ana.id}",
            json={
                "nome": "Ana",
                "cargo": CargoEnum.RODIZIO.value,
                "area": AreaEnum.MEDIUNIDADE.value,
                "funcoes_aptas": [LIMPEZA_1.value],
            },
        )
        assert restringida.status_code == 200, restringida.text

        regravar = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": ana.id}
                ],
            },
        )
        assert regravar.status_code == 200, regravar.text

        # E a escalação inédita continua barrada: só o que já estava vale.
        bruno = criar_pessoa(db, "Bruno", funcoes=[LIMPEZA_1])
        nova = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": bruno.id}
                ],
            },
        )
        assert nova.status_code == 400
        assert "não está marcado como apto" in nova.json()["detail"]


def test_mesma_pessoa_nao_ocupa_duas_funcoes_na_mesma_gira(db):
    for nome in ("Ana", "Bruno", "Carla", "Diego", "Elena", "Fabio", "Gustavo"):
        criar_pessoa(db, nome)

    escolhidos = [s["pessoa_id"] for s in sugerir(db)]

    assert len(set(escolhidos)) == 7, "as sete posições devem cair em pessoas distintas"


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
    # mais recente, é a última das quatro a ser escalada — a quarta posição na
    # ordem do rodízio, com só quatro pessoas aptas para sete vagas.
    assert por_funcao(db)[LIMPEZA_1_PESSOA_2]["nome"] == "Zara"
    # Ignorando a gira em edição, a Zara volta a contar como quem não trabalhou
    # e reassume a frente — senão reabrir a gira empurraria a própria escalada
    # para o fim da fila.
    sem_a_gira_aberta = por_funcao(db, ignorar_gira_id=em_edicao.id)
    assert sem_a_gira_aberta[PORTEIRA_ATENDIMENTO]["nome"] == "Zara"


def test_salvar_funcoes_pela_api_aceita_qualquer_cargo_apto(db):
    """Cargo não bloqueia mais a função — só a aptidão marcada no cadastro."""
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

        tambem_ok = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [{"funcao": LIMPEZA_1.value, "pessoa_id": fixo.id}],
            },
        )
        assert tambem_ok.status_code == 200, tambem_ok.text
        salvas = client.get(f"/giras/{gira.id}/funcoes").json()
        assert salvas[0]["pessoa_id"] == fixo.id


def test_mesma_pessoa_pode_ocupar_duas_ou_mais_funcoes(db):
    """Terreiro pequeno: às vezes é a mesma pessoa na limpeza e na porteira."""
    pessoa = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": pessoa.id},
                    {"funcao": LIMPEZA_1.value, "pessoa_id": pessoa.id},
                    {"funcao": LIMPEZA_2.value, "pessoa_id": pessoa.id},
                ],
            },
        )
        assert resposta.status_code == 200, resposta.text

        salvas = {
            f["funcao"]: f["pessoa_id"]
            for f in client.get(f"/giras/{gira.id}/funcoes").json()
        }

    assert salvas[PORTEIRA_ATENDIMENTO.value] == pessoa.id
    assert salvas[LIMPEZA_1.value] == pessoa.id
    assert salvas[LIMPEZA_2.value] == pessoa.id


def test_a_mesma_funcao_nao_pode_ser_informada_duas_vezes(db):
    """O que continua proibido é repetir a função — não a pessoa."""
    ana = criar_pessoa(db, "Ana")
    bruno = criar_pessoa(db, "Bruno")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": LIMPEZA_1.value, "pessoa_id": ana.id},
                    {"funcao": LIMPEZA_1.value, "pessoa_id": bruno.id},
                ],
            },
        )

    assert resposta.status_code == 400
    assert "mais de uma vez" in resposta.json()["detail"]


def test_salvar_gira_com_posicoes_vazias_e_aceito(db):
    """Nem toda gira tem gente para as sete posições — nenhuma é obrigatória."""
    ana = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [],
                "funcoes": [
                    {"funcao": PORTEIRA_ATENDIMENTO.value, "pessoa_id": ana.id}
                ],
            },
        )

    assert resposta.status_code == 200, resposta.text
    salvas = client.get(f"/giras/{gira.id}/funcoes").json()
    assert len(salvas) == 1


def test_migracao_libera_posicao_nova_presa_por_schema_antigo(db):
    """Reproduz o 500 real: banco criado antes de uma posição existir.

    ``funcoes_gira`` nasce, no SQLite, com um CHECK gravado na criação da
    tabela — exatamente o que aconteceu em produção quando a Limpeza 2 virou
    duas posições: o CHECK antigo recusava o quinto valor e o INSERT quebrava
    com IntegrityError, sem chegar a um 400 tratado. É esse crash que a
    migração ``sincronizar_enums`` existe para evitar.
    """
    with engine.begin() as conexao:
        conexao.execute(text("DROP TABLE funcoes_gira"))
        conexao.execute(text("""
            CREATE TABLE funcoes_gira (
                id INTEGER NOT NULL PRIMARY KEY,
                gira_id INTEGER NOT NULL REFERENCES giras(id) ON DELETE CASCADE,
                pessoa_id INTEGER NOT NULL REFERENCES pessoas(id) ON DELETE CASCADE,
                funcao VARCHAR(21) NOT NULL,
                CONSTRAINT uq_funcao_gira UNIQUE (gira_id, funcao),
                CHECK (funcao IN ("PORTEIRA_ATENDIMENTO","PORTEIRA_SENHA","LIMPEZA_1","LIMPEZA_2"))
            )
        """))

    ana = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with pytest.raises(IntegrityError):
        db.add(FuncaoGira(gira_id=gira.id, pessoa_id=ana.id, funcao=LIMPEZA_2_PESSOA_3))
        db.commit()
    db.rollback()

    migracoes.aplicar(engine)
    db.expire_all()

    # A mesma gravação que quebrava antes agora funciona, sem precisar de
    # nenhum ajuste manual no banco.
    db.add(FuncaoGira(gira_id=gira.id, pessoa_id=ana.id, funcao=LIMPEZA_2_PESSOA_3))
    db.commit()
    assert db.query(FuncaoGira).filter(FuncaoGira.gira_id == gira.id).count() == 1


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
    # Cargo não tira ninguém da planilha: Ana e Bruno (fixo) são ambos aptos e
    # aparecem, sugeridos ou na lista de integrantes para preencher à mão.
    assert "Ana" in texto
    assert "Bruno" in texto


def test_quem_nao_e_marcado_na_escala_entra_como_falta(db):
    """Quem some da lista de trabalhadores não some do registro — vira falta."""
    presente = criar_pessoa(db, "Ana")
    ausente = criar_pessoa(db, "Bruno")
    inativo = criar_pessoa(db, "Carla Inativa", ativo=0)
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [
                    {"pessoa_id": presente.id, "presente": True, "atendeu": False}
                ],
                "funcoes": [],
            },
        )
        assert resposta.status_code == 200, resposta.text
        escalas = {
            e["pessoa_id"]: e for e in client.get(f"/escalas/gira/{gira.id}").json()
        }

    assert escalas[presente.id]["presente"] is True
    assert escalas[ausente.id]["presente"] is False
    assert escalas[ausente.id]["atendeu"] is False
    # Quem está inativo não polui a escala de faltas.
    assert inativo.id not in escalas


def test_atender_sem_informar_o_guia_e_aceito(db):
    """ "Atendeu" não obriga escolher qual guia incorporou — fica opcional."""
    ana = criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [
                    {"pessoa_id": ana.id, "presente": True, "atendeu": True}
                ],
                "funcoes": [],
            },
        )
        assert resposta.status_code == 200, resposta.text
        escala = client.get(f"/escalas/gira/{gira.id}").json()[0]

    assert escala["atendeu"] is True
    assert escala["entidade_id"] is None


def test_entidade_sem_atender_e_ignorada(db):
    """Sem marcar "atendeu", a entidade enviada não é gravada."""
    ana = criar_pessoa(db, "Ana")
    entidade = Entidade(
        nome="Vovó Maria", tipo=TipoGiraEnum.PRETO_VELHO, medium_id=ana.id
    )
    db.add(entidade)
    db.commit()
    db.refresh(entidade)
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        resposta = client.put(
            f"/giras/{gira.id}/escala",
            json={
                "trabalhadores": [
                    {
                        "pessoa_id": ana.id,
                        "presente": True,
                        "atendeu": False,
                        "entidade_id": entidade.id,
                    }
                ],
                "funcoes": [],
            },
        )
        assert resposta.status_code == 200, resposta.text
        escala = client.get(f"/escalas/gira/{gira.id}").json()[0]

    assert escala["entidade_id"] is None


def test_corrigir_presenca_e_atendimento_depois_da_gira(db):
    """A aba operacional corrige o que foi marcado errado no cadastro."""
    criar_pessoa(db, "Ana")
    gira = criar_gira(db, data_em(2026, 1, 5))

    with TestClient(app) as client:
        client.put(
            f"/giras/{gira.id}/escala", json={"trabalhadores": [], "funcoes": []}
        )
        escala_id = client.get(f"/escalas/gira/{gira.id}").json()[0]["id"]

        corrigida = client.patch(
            f"/escalas/{escala_id}", json={"presente": True, "atendeu": True}
        )

    assert corrigida.status_code == 200, corrigida.text
    assert corrigida.json()["presente"] is True
    assert corrigida.json()["atendeu"] is True
