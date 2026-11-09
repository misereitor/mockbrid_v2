# 🦅 Mockbird v2

Mockbird v2 é uma plataforma para prototipação e geração de frontends completos em tempo recorde com auxílio de IA, modo de apresentação executável (Link do CEO), anotações pinadas no DOM e MCP para integração direta com agentes de desenvolvimento.

---

## 🚀 Ambiente de Homologação

> **Regra Obrigatória:** Todo e qualquer teste ou validação deve ser executado exclusivamente em ambiente de homologação. Nunca execute testes destrutivos em produção.

### 1. Subindo a infraestrutura local (Docker)

```bash
docker compose up -d --build
```

Serviços:
- **API FastAPI & Frontend Estático:** `http://127.0.0.1:8082`
- **PostgreSQL 16:** `127.0.0.1:5434` (usuário: `mockbird`, db: `mockbird_v2`)
- **Documentação Interativa Swagger:** `http://127.0.0.1:8082/api/docs`

### 2. Rodando os testes (Homologação)

```bash
cd backend
pytest -v
```

### 3. Frontend para Desenvolvimento

```bash
cd frontend
npm install
npm run dev
```

---

## 🛡️ Segurança & Boas Práticas

- **Multi-tenancy:** Isolamento estrito por `organization_id` em todos os recursos (projetos, telas, tokens, comentários).
- **Proteção CSRF:** Tokens de sessão com cookies HTTP-only e cabeçalho `X-CSRF-Token`.
- **Criptografia BYOK:** Chaves de API de provedores de IA são criptografadas em repouso no banco de dados.

