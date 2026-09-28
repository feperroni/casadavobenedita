# Sistema de Gestão de Giras

API desenvolvida em **FastAPI** para gerenciamento de terreiros: médiuns, entidades, giras e escalas de atendimento.

## Funcionalidades

- Cadastro de pessoas (médiuns, cambonos, etc.)
- Cadastro de entidades espirituais vinculadas a médiuns
- Cadastro e organização de giras (datas, tipos, observações)
- Geração automática de escala para uma gira
- Geração de relatórios (JSON e texto) por gira
- Interface web com três visões: Visão Geral, Financeiro/Operacional e Espiritual
- Controle de contribuições mês a mês, inadimplência e evolução financeira do ano
- Registro de presença (quem atendeu em cada gira)
- Módulo de mensagens reutilizável: gera links de WhatsApp para os integrantes selecionados

## Tecnologias

- Python 3.11+
- FastAPI
- SQLAlchemy
- SQLite (padrão) — pode ser adaptado para PostgreSQL/MySQL
- Nota: o projeto usa `psycopg2-binary` no requirements por conveniência; em alguns cenários de produção prefira `psycopg2` e gerencie a instalação do binário de forma controlada.
- Pydantic

## Como executar

1. Clone o repositório:
```bash
git clone https://github.com/feperroni/casadavobenedita.git
cd casadavobenedita
```

2. Crie o ambiente virtual e instale as dependências:
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3. Configure as variáveis de ambiente (opcional — sem `.env` usa SQLite local):
```bash
cp env.example .env
```

4. Suba a API:
```bash
uvicorn app.main:app --reload
```

5. Acesse a interface em http://127.0.0.1:8000 e a documentação da API em http://127.0.0.1:8000/docs

## Interface web

- **Visão Geral**: contadores de mediunidade/liderança/curimba, lista de integrantes com adicionar/editar/remover, panorama das últimas giras e cadastro de giras (data, nome, linha e quem trabalhou).
- **Financeiro / Operacional**: previsto x recebido x pendente do mês, gráfico de evolução anual, registro de pagamento por integrante, marcação de presença por gira e envio de mensagens aos selecionados.
- **Espiritual**: guias/entidades de cada integrante, com cadastro de novos guias.

### Cadastro de gira

O botão **Adicionar gira** abre um formulário com data, nome, linha e observações. Em seguida os
integrantes aparecem agrupados por função (médium fixo, rodízio e cambono): marque quem trabalhou e,
para cada um, escolha a entidade incorporada ou deixe **Sem incorporação** — o cambono pode trabalhar
sem incorporar ou com o próprio guia. O contador mostra quantos trabalharam em cada função. Editar a
gira reabre o mesmo formulário com a escala atual.

## Módulo de mensagens (WhatsApp)

`POST /mensagens/whatsapp` recebe `pessoa_ids` e `mensagem` e devolve um link `wa.me` por integrante,
já com o texto preenchido — sem necessidade de credenciais. Marcadores aceitos na mensagem:
`{nome}`, `{primeiro_nome}` e `{valor}` (mensalidade do integrante).
O módulo é genérico: serve para cobrança, avisos de gira ou qualquer comunicado.

## Acesso (login Google)

O acesso web é restrito por allowlist de e-mail. Defina `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET` e `EMAILS_PERMITIDOS` (padrão: `casadavobenedita@gmail.com`);
qualquer outra conta Google recebe 403. Sem as credenciais definidas o login fica
desativado (útil em desenvolvimento local).

No Google Cloud Console → *APIs e serviços* → *Credenciais* → *ID do cliente OAuth*
(tipo "Aplicativo da Web"), cadastre como URI de redirecionamento autorizado:

```
http://localhost:8000/auth/google/callback          # desenvolvimento
https://SEU-APP.up.railway.app/auth/google/callback # produção
```

## Importar as planilhas do Google Forms

```bash
python -m scripts.importar_planilhas \
  --integrantes "Informações de contato (respostas).xlsx" \
  --entidades "Formulário sem título (respostas).xlsx" \
  --dry-run   # remova para gravar de verdade
```

As colunas são detectadas por palavras-chave no cabeçalho. A desduplicação usa o
nome normalizado (sem acentos/maiúsculas) e reporta os casos parecidos que foram
unificados, para revisão.

## Deploy no Railway

1. Crie o projeto a partir deste repositório (o `railway.json`/`Procfile` já definem o start command).
2. Adicione o plugin **PostgreSQL** — o Railway injeta `DATABASE_URL` automaticamente (o `postgres://` é convertido para `postgresql://` na aplicação).
3. Configure as variáveis: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `EMAILS_PERMITIDOS`, `SECRET_KEY` e `COOKIE_HTTPS_ONLY=true`.
4. Adicione a URL pública do Railway nas URIs de redirecionamento do OAuth.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
| --- | --- | --- |
| `DATABASE_URL` | não | URL do banco. Padrão: `sqlite:///./gestao_giras.db` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | não | Credenciais OAuth. Se ausentes, o login fica desativado |
| `EMAILS_PERMITIDOS` | não | E-mails autorizados, separados por vírgula. Padrão: `casadavobenedita@gmail.com` |
| `SECRET_KEY` | em produção | Assina o cookie de sessão. Em produção, defina um valor forte e único (ex.: gerado por `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Não comite este valor. |
| `COOKIE_HTTPS_ONLY` | não | `true` em produção (HTTPS) |

Nota: o arquivo `env.example` fornece variáveis de exemplo; sempre use um `.env` local não versionado e garanta que `SECRET_KEY` e `ALLOWED_ORIGINS` (quando em produção) estejam configurados.

## Endpoints principais

- `POST /pessoas/`, `GET /pessoas/`, `PUT /pessoas/{id}`, `DELETE /pessoas/{id}`
- `POST /entidades/`, `GET /entidades/`, `GET /entidades/medium/{medium_id}`
- `POST /giras/`, `GET /giras/`, `PUT /giras/{id}`, `DELETE /giras/{id}`
- `PUT /giras/{id}/escala` — define manualmente quem trabalhou (entidade opcional)
- `PATCH /escalas/{id}/presenca` — marca se o integrante atendeu na gira
- `POST /pagamentos/`, `GET /pagamentos/?ano=&mes=` — contribuições mensais
- `GET /pagamentos/resumo?ano=&mes=` — previsto/recebido/pendente + inadimplentes
- `GET /pagamentos/evolucao?ano=` — recebido mês a mês
- `GET /dashboard/visao-geral`, `GET /dashboard/espiritual`
- `POST /mensagens/whatsapp` — links de WhatsApp para os selecionados
- `POST /giras/{gira_id}/gerar-escala` — gera a escala automática
- `GET /giras/{gira_id}/relatorio` — relatório em JSON
- `GET /giras/{gira_id}/relatorio-texto` — relatório em texto
