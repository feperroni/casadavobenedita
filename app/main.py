import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import auth, migracoes
from app.database import Base, engine
from app.routers import (
    dashboard,
    entidades,
    escalas,
    estoque,
    giras,
    mensagens,
    pagamentos,
    pessoas,
    planilhas,
)

# Configuração por ambiente
APP_ENV = os.getenv("APP_ENV", "development").lower()
# ALLOWED_ORIGINS: vírgula-separado (ex: https://meusite.com,https://outro.com)
_allowed = os.getenv("ALLOWED_ORIGINS")
if _allowed:
    ALLOWED_ORIGINS = [o.strip() for o in _allowed.split(",") if o.strip()]
else:
    # Em produção, exigir explícito; em desenvolvimento permitir qualquer origem
    ALLOWED_ORIGINS = [] if APP_ENV == "production" else ["*"]

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Sistema de Gestão de Giras",
    description="API para gerenciar médiuns, entidades, giras e escalas de terreiro.",
    version="1.0.0",
)

# CORS: usar ALLOWED_ORIGINS em produção; em desenvolvimento é '*' por padrão
if APP_ENV == "production" and not ALLOWED_ORIGINS:
    # Segurança: não deixar CORS aberto em produção sem configuração explícita
    raise RuntimeError(
        "ALLOWED_ORIGINS must be set in production as a comma-separated list of allowed origins."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # "Access-Control-Allow-Origin: *" com credentials é combinação inválida
    # (o navegador recusa); só habilita credentials quando as origens são explícitas.
    allow_credentials=ALLOWED_ORIGINS != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def exigir_login(request: Request, call_next):
    """Bloqueia toda a aplicação quando o login Google está configurado."""
    livre = request.url.path.startswith(auth.CAMINHOS_LIVRES)
    if auth.auth_habilitada() and not livre and not auth.usuario_logado(request):
        return RedirectResponse("/login")
    return await call_next(request)


# Adicionado depois de exigir_login para ficar por fora dele: o Starlette executa
# os middlewares na ordem inversa do cadastro, e a sessão precisa existir antes.
app.add_middleware(
    SessionMiddleware, secret_key=auth.SECRET_KEY, https_only=auth.COOKIE_HTTPS_ONLY
)


@app.on_event("startup")
async def startup_event():
    """Operações de inicialização que tinham efeitos colaterais no import.

    - Verifica SECRET_KEY em produção (não permite o valor padrão inseguro).
    - Cria tabelas e aplica migrações (antes isso era feito em import e causava efeitos colaterais).
    """
    # Em produção, recusar startup com SECRET_KEY inseguro
    if APP_ENV == "production" and (
        not auth.SECRET_KEY or auth.SECRET_KEY == "troque-esta-chave-em-producao"
    ):
        raise RuntimeError(
            "SECRET_KEY está ausente ou é inseguro em produção. Defina a variável de ambiente SECRET_KEY com um valor aleatório e forte."
        )

    # Cria as tabelas e aplica migrações de forma explícita na inicialização
    Base.metadata.create_all(bind=engine)
    migracoes.aplicar(engine)


# Registro das rotas
app.include_router(pessoas.router)
app.include_router(entidades.router)
app.include_router(giras.router)
app.include_router(escalas.router)
app.include_router(pagamentos.router)
app.include_router(mensagens.router)
app.include_router(dashboard.router)
app.include_router(planilhas.router)
app.include_router(estoque.router)
app.include_router(auth.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "online", "mensagem": "API de Gestão de Giras funcionando!"}


@app.get("/", include_in_schema=False)
def ui():
    """Serve a interface web (visão geral, financeiro/operacional e espiritual)."""
    return FileResponse(STATIC_DIR / "index.html")
