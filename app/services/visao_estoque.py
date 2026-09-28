"""Leitura do estoque por foto.

Manda as fotos para o Gemini e recebe uma *proposta* — nunca um movimento. Só
o usuário transforma proposta em saldo, conferindo item a item na tela.

Duas regras de desenho que valem a leitura:

- Todas as fotos vão na **mesma** chamada. Os dois ambientes do terreiro rendem
  de duas a quatro fotos, e um item que aparece em duas delas viraria dois
  itens se cada foto fosse analisada sozinha.
- Depois da primeira vez, o catálogo vai junto no prompt. Conferir uma lista
  fechada erra bem menos que descobrir do zero, e é o que faz a precisão
  melhorar com o uso em vez de piorar.

A imagem não é guardada em lugar nenhum: entra na chamada e é descartada.

Usa o Gemini (nível gratuito) em vez do Claude por custo: o volume de uso do
terreiro — algumas conferências por mês — cabe folgado no limite grátis. Se a
contagem se mostrar fraca demais na prática, trocar de provedor aqui dentro é
a única mudança necessária — o contrato do módulo (``configurada()`` /
``analisar()``) não muda para o resto da aplicação.

O nome do modelo é configurável por variável de ambiente de propósito: o
Google tem aposentado modelo do nível gratuito com poucos dias de aviso — o
``gemini-2.5-flash`` que este arquivo usava até então parou de aceitar conta
nova sem passar por deploy nenhum daqui, só pela resposta 404 da API. Com a
variável, uma aposentadoria dessas vira mudança de configuração no Railway,
não código.
"""

import json
import os
import time

from google import genai
from google.genai import types

from app.models import ItemEstoque

# Verificado contra a documentação oficial em 2026-08-16: nível gratuito, com
# suporte a imagem. Se a API voltar a recusar com 404 "no longer available",
# a mensagem de erro do Google costuma dizer o substituto — troque a variável
# GEMINI_MODEL no Railway, sem precisar editar este arquivo.
MODELO_PADRAO = "gemini-3.6-flash"
MAX_TOKENS = 8000
MAX_FOTOS = 4

# Códigos que valem repetir: pico de demanda e instabilidade do provedor
# costumam passar em segundos ("Spikes in demand are usually temporary", nas
# palavras do próprio Google). Os demais — chave errada, modelo aposentado,
# foto recusada — dariam o mesmo erro nas três tentativas e só fariam o
# usuário esperar mais para ler a mesma coisa.
CODIGOS_TEMPORARIOS = frozenset({429, 500, 502, 503, 504})
TENTATIVAS = 3
ESPERA_INICIAL = 2.0

FORMATOS_ACEITOS = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/webp": "image/webp",
    "image/gif": "image/gif",
}

# O schema é o contrato: com saída estruturada a resposta vem validada nele,
# em vez de a gente tentar adivinhar JSON dentro de texto livre.
ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "encontrados": {
            "type": "array",
            "description": "Itens do catálogo que aparecem nas fotos.",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "quantidade": {"type": "integer"},
                    "confianca": {
                        "type": "string",
                        "enum": ["alta", "media", "baixa"],
                        "description": (
                            "baixa quando houver oclusão, empilhamento ou "
                            "dúvida real sobre o número."
                        ),
                    },
                    "observacao": {
                        "type": "string",
                        "description": "Vazio quando não há o que ressalvar.",
                    },
                },
                "required": ["item_id", "quantidade", "confianca", "observacao"],
            },
        },
        "novos": {
            "type": "array",
            "description": "Coisas visíveis que não estão no catálogo.",
            "items": {
                "type": "object",
                "properties": {
                    "nome": {"type": "string"},
                    "quantidade": {"type": "integer"},
                    "unidade": {"type": "string"},
                    "categoria": {"type": "string"},
                    "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
                },
                "required": [
                    "nome",
                    "quantidade",
                    "unidade",
                    "categoria",
                    "confianca",
                ],
            },
        },
    },
    "required": ["encontrados", "novos"],
}

INSTRUCOES = """\
Você está conferindo o estoque de um terreiro de umbanda a partir de fotos das \
prateleiras. Sua saída vira uma proposta que uma pessoa confere antes de virar \
saldo — ela corrige o que estiver errado, então prefira ser honesto a ser \
categórico.

Como contar:
- Conte unidades inteiras. Uma garrafa pela metade conta como uma.
- Conte apenas o que você realmente vê. Não estime o que está atrás, escondido \
ou fora do enquadramento.
- Item empilhado, encoberto ou parcialmente visível: dê o número que conseguir \
ver e marque confiança "baixa", explicando na observação.
- Muito do estoque fica guardado em caixa organizadora de nichos, com itens \
iguais agrupados por compartimento e apontados para a câmera. Aí você vê a \
ponta de cada um: cada ponta visível é uma unidade, então conte as pontas. \
Isso não é estimar o escondido — é contar o que está à vista. Encostar um no \
outro não torna o item invisível.
- Conte compartimento por compartimento, e não a estante inteira de uma vez. O \
móvel/organizador em si não é item de estoque: o que conta é o conteúdo.
- Cor faz parte da identidade: vela branca, vela vermelha e vela azul são itens \
diferentes e nunca viram um só. Na dúvida entre dois tons próximos, escolha um, \
marque confiança "baixa" e diga na observação qual foi a dúvida.
- As fotos são de ambientes diferentes do mesmo terreiro e podem se sobrepor. \
Se o mesmo item aparece em mais de uma foto, decida se é o mesmo conjunto \
(não some duas vezes) ou conjuntos distintos, e diga na observação o que você \
assumiu.
- Não invente item que você não vê. Item do catálogo que não aparece em foto \
nenhuma deve simplesmente ficar de fora de "encontrados" — não o inclua com \
quantidade zero.

Em "novos", coloque só o que dá para nomear com clareza e que não está no \
catálogo. Sugira uma unidade de contagem ("unidade", "garrafa", "pacote", \
"maço") e uma categoria curta.\
"""


class VisaoIndisponivelError(RuntimeError):
    """A leitura por foto não está configurada ou o provedor recusou a chamada."""


def configurada() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def modelo() -> str:
    return os.getenv("GEMINI_MODEL") or MODELO_PADRAO


def _bloco_catalogo(itens: list[ItemEstoque]) -> str:
    """A lista fechada que a IA deve conferir, quando já existe catálogo."""
    if not itens:
        return (
            "O catálogo está vazio: esta é a primeira leitura. Liste em "
            '"novos" tudo que conseguir identificar nas fotos e deixe '
            '"encontrados" vazio.'
        )

    linhas = "\n".join(
        f"- id {item.id}: {item.nome} (contado em {item.unidade})" for item in itens
    )
    return (
        "Catálogo atual. Procure especificamente por estes itens e devolva o "
        "id exato de cada um que aparecer:\n"
        f"{linhas}\n\n"
        'Qualquer outra coisa visível que não esteja nesta lista vai em "novos".'
    )


def _partes_de_imagem(fotos: list[tuple[bytes, str]]) -> list[types.Part]:
    partes = []
    for conteudo, tipo in fotos:
        media_type = FORMATOS_ACEITOS.get((tipo or "").lower())
        if media_type is None:
            raise VisaoIndisponivelError(
                f"Formato de imagem não suportado: {tipo or 'desconhecido'}."
            )
        partes.append(types.Part.from_bytes(data=conteudo, mime_type=media_type))
    return partes


def _motivo_falha(resposta) -> str:
    """Por que a leitura voltou sem texto — para a mensagem ser específica."""
    feedback = getattr(resposta, "prompt_feedback", None)
    if feedback is not None and feedback.block_reason:
        return f"as fotos foram bloqueadas ({feedback.block_reason.value})"
    candidatos = resposta.candidates or []
    if candidatos and candidatos[0].finish_reason:
        return f"a geração parou antes do fim ({candidatos[0].finish_reason.value})"
    return "motivo desconhecido"


def _mensagem_de_falha(erro) -> str:
    """O erro do provedor em português, sem despejar o JSON cru na tela.

    ``str`` de um ``APIError`` é ``"503 UNAVAILABLE. {'error': {...}}"`` — no
    celular isso vira um parágrafo de chaves e aspas que não diz ao usuário o
    que fazer. Para o caso comum (sobrecarga), a mensagem explica a espera.
    """
    if erro.code in CODIGOS_TEMPORARIOS:
        return (
            "O serviço de leitura por foto está sobrecarregado agora e não "
            "respondeu nem depois de algumas tentativas. Espere alguns "
            "minutos e envie as fotos de novo, ou faça a conferência na mão."
        )
    return f"O serviço de leitura por foto falhou: {erro}"


def _gerar_conferindo(cliente, conteudo):
    """Chama o modelo, repetindo só o que costuma passar sozinho.

    As fotos já foram enviadas e o usuário está parado na tela esperando;
    desistir no primeiro 503 faz ele fotografar tudo de novo por causa de um
    problema que costuma durar segundos. A espera dobra a cada tentativa para
    não insistir em cima de um provedor que já está congestionado.
    """
    espera = ESPERA_INICIAL
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            return cliente.models.generate_content(
                model=modelo(),
                contents=conteudo,
                config=types.GenerateContentConfig(
                    system_instruction=INSTRUCOES,
                    response_mime_type="application/json",
                    response_schema=ESQUEMA_RESPOSTA,
                    max_output_tokens=MAX_TOKENS,
                ),
            )
        except genai.errors.APIError as erro:
            if erro.code not in CODIGOS_TEMPORARIOS or tentativa == TENTATIVAS:
                raise
            time.sleep(espera)
            espera *= 2
    # Inalcançável: o laço ou devolve, ou levanta na última tentativa.
    raise AssertionError("laço de retentativa terminou sem resposta nem erro")


def analisar(fotos: list[tuple[bytes, str]], catalogo: list[ItemEstoque]) -> dict:
    """Devolve ``{"encontrados": [...], "novos": [...]}`` para o usuário conferir.

    ``fotos`` são pares (bytes, content-type). Nada é gravado em disco.
    """
    if not configurada():
        raise VisaoIndisponivelError(
            "A leitura por foto não está configurada: falta a variável "
            "GEMINI_API_KEY."
        )
    if not fotos:
        raise VisaoIndisponivelError("Envie ao menos uma foto.")
    if len(fotos) > MAX_FOTOS:
        raise VisaoIndisponivelError(f"Envie no máximo {MAX_FOTOS} fotos por leitura.")

    cliente = genai.Client()
    conteudo = _partes_de_imagem(fotos)
    conteudo.append(_bloco_catalogo(catalogo))

    try:
        resposta = _gerar_conferindo(cliente, conteudo)
    except genai.errors.APIError as erro:
        raise VisaoIndisponivelError(_mensagem_de_falha(erro)) from erro

    # Recusa/bloqueio volta sem candidato de texto, não como exceção; `.text`
    # devolve None nesse caso em vez de estourar, então dá para checar direto.
    texto = resposta.text
    if not texto:
        raise VisaoIndisponivelError(
            "A leitura destas fotos foi recusada pelo provedor "
            f"({_motivo_falha(resposta)}). Tente outras fotos ou faça a "
            "conferência manualmente."
        )

    try:
        return json.loads(texto)
    except json.JSONDecodeError as erro:
        # Resposta cortada no meio (estante com muitos itens distintos bate no
        # teto de tokens) chega como JSON pela metade: texto tem conteúdo, mas
        # não fecha. Sem este tratamento vira 500 com stack trace na tela.
        raise VisaoIndisponivelError(
            "A leitura veio incompleta do provedor — costuma ser foto com "
            "itens demais de uma vez. Tente fotografar em partes, uma "
            "prateleira por vez."
        ) from erro
