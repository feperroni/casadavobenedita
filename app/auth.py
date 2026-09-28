"""Login com Google restrito a uma allowlist de e-mails.

Ativado quando `GOOGLE_CLIENT_ID` e `GOOGLE_CLIENT_SECRET` estão definidos.
Sem essas variáveis (ex.: desenvolvimento local) a aplicação fica aberta.

Variáveis:
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: credenciais OAuth do Google Cloud.
- `EMAILS_PERMITIDOS`: e-mails autorizados, separados por vírgula.
- `SECRET_KEY`: chave usada para assinar o cookie de sessão.
"""

import os

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SECRET_KEY = os.getenv(
    "SECRET_KEY", "troque-esta-chave-em-producao"
)  # manter o default histórico para compatibilidade em dev; em produção o startup bloqueia esse valor padrão
# Em produção (Railway) o cookie de sessão deve ser enviado só por HTTPS.
COOKIE_HTTPS_ONLY = os.getenv("COOKIE_HTTPS_ONLY", "false").lower() in (
    "1",
    "true",
    "sim",
)

CAMINHOS_LIVRES = (
    "/login",
    "/auth/google",
    "/auth/google/callback",
    "/health",
    "/static",
)

router = APIRouter(tags=["Autenticação"])


def auth_habilitada() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def emails_permitidos() -> set[str]:
    brutos = os.getenv("EMAILS_PERMITIDOS", "casadavobenedita@gmail.com")
    return {email.strip().lower() for email in brutos.split(",") if email.strip()}


oauth = OAuth()
if auth_habilitada():
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def usuario_logado(request: Request):
    return request.session.get("usuario")


@router.get("/login", include_in_schema=False)
def login(request: Request):
    if not auth_habilitada():
        return RedirectResponse("/")
    return HTMLResponse(
        """<!DOCTYPE html><html lang="pt-br"><head><meta charset="utf-8">
        <title>Entrar — Gestão do Terreiro — Casa da Vó Benedita</title>
        <link rel="stylesheet" href="/static/styles.css"></head>
        <body><main style="display:flex;min-height:80vh;align-items:center;justify-content:center">
        <div class="painel" style="text-align:center;max-width:380px">
        <h2>Gestão do Terreiro — Casa da Vó Benedita</h2>
        <p class="dica">Acesso restrito à conta autorizada do terreiro.</p>
        <a class="btn btn-primario" href="/auth/google">Entrar com Google</a>
        </div></main></body></html>"""
    )


@router.get("/auth/google", include_in_schema=False)
async def entrar_com_google(request: Request):
    if not auth_habilitada():
        raise HTTPException(status_code=503, detail="Login Google não configurado.")
    redirect_uri = request.url_for("callback_google")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


@router.get("/auth/google/callback", name="callback_google", include_in_schema=False)
async def callback_google(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as erro:
        raise HTTPException(status_code=401, detail=f"Falha no login: {erro.error}")

    dados = token.get("userinfo") or {}
    email = (dados.get("email") or "").lower()
    if not email or email not in emails_permitidos():
        raise HTTPException(
            status_code=403,
            detail="Esta conta Google não tem acesso ao sistema do terreiro.",
        )

    request.session["usuario"] = {"email": email, "nome": dados.get("name") or email}
    return RedirectResponse("/")


@router.get("/logout", include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")


@router.get("/auth/eu", include_in_schema=False)
def eu(request: Request):
    """Quem está logado (a UI usa para mostrar o e-mail e o botão de sair)."""
    return {"auth_habilitada": auth_habilitada(), "usuario": usuario_logado(request)}
