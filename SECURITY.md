# Security guidelines

- Nunca comitar arquivos .env com segredos.
- Gere SECRET_KEY forte: python -c "import secrets; print(secrets.token_urlsafe(48))"
- Configure ALLOWED_ORIGINS em produção (ex: ALLOWED_ORIGINS=https://meusite.com)
- Use scans de segurança em CI (ex.: gitleaks) para detectar segredos acidentalmente comitados
- Para PostgreSQL em produção, avalie usar `psycopg2` ao invés de `psycopg2-binary` para controle de builds e compatibilidade com políticas de segurança.