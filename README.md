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
- **Acesso pela VPN WireGuard:** `http://10.8.0.7:8082` (porta publicada no IP da interface `client`)
- **PostgreSQL 16:** `127.0.0.1:5434` (usuário: `mockbird`, db: `mockbird_v2`)
- **Documentação Interativa Swagger:** `http://127.0.0.1:8082/api/docs` (desabilitada em `ENVIRONMENT=production`)

Se a interface WireGuard não estiver no ar quando o Docker iniciar, o container não
consegue publicar a porta `10.8.0.7:8082`; suba a VPN e rode `docker compose up -d backend`.

O container da API executa `alembic upgrade head` antes de subir o uvicorn — um volume
novo (ou um deploy limpo) já nasce com o esquema aplicado.

### 2. Migrações de banco (Alembic)

```bash
cd backend
alembic upgrade head            # aplica migrações pendentes
alembic revision --autogenerate -m "descricao"   # cria nova migração
```

Nunca edite o banco manualmente: toda mudança de esquema precisa de uma migração em
`backend/migrations/versions`.

### 3. Rodando os testes (Homologação)

```bash
cd backend
pytest -q
```

Os testes unitários (`test_unit_*.py`) rodam sem infraestrutura. Os testes E2E usam
`BASE_URL` (default `http://127.0.0.1:8082`) e são automaticamente marcados como
`skip` quando a stack não está no ar.

Testes de navegador (Playwright, contra a stack já no ar):

```bash
cd frontend
npm run test:e2e        # usa o Chrome instalado; PLAYWRIGHT_CHANNEL=chromium no CI
```

### 4. Frontend para Desenvolvimento

```bash
cd frontend
npm install
npm run dev
```

### 5. Lint e CI

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests
```

O pipeline em `.github/workflows/ci.yml` roda lint + testes unitários no backend e
`tsc -b && vite build` no frontend.

---

## 🔁 Migrar do Mockbird v1 (corpus `design/`)

O repositório [misereitor/mockbird](https://github.com/misereitor/mockbird) não é o
app: é o pacote de skills que gerava, dentro do projeto do cliente, uma pasta
`design/` com `tokens.json` e uma subpasta por canvas (`canvas.json` + telas
`.html`). O v2 importa esse corpus como um projeto novo:

- **Na interface:** em *Projetos*, clique em **Importar design/** e envie um ZIP da
  pasta `design/` (ou do projeto que a contém).
- **Via API:** `POST /api/projects/import/design` (multipart: `file` = ZIP,
  `name` = nome opcional do projeto). O projeto abre direto no editor.

O importador converte cada `canvas.json` em um canvas, cada tela em uma tela do
app (largura/altura/device preservados), achata o `tokens.json` para os tokens do
projeto e inlina CSS/JS locais referenciados por `../algum.css`, para a tela
renderizar dentro do canvas. Pastas `snapshots/`, `.visual/` e backups são
ignoradas para não duplicar telas.

O caminho inverso é `GET /api/projects/{project_id}/export/design`, que devolve um
ZIP no mesmo layout `design/` (tokens.json + canvas.json + telas) — reimportável
no v2 e abrível pelo toolchain antigo.

---

## 🎨 Figma, Penpot e extensão de navegador

O editor exporta o projeto como **camadas editáveis** (retângulos, textos e imagens
em coordenadas absolutas) no botão **Figma/Penpot** da barra superior, gerando
`<projeto>.mockbird.json`. As integrações vivem em `integrations/`:

| Integração | O que faz | Como instalar |
| :--- | :--- | :--- |
| [`figma-plugin`](integrations/figma-plugin/README.md) | frames do Figma com as camadas do bundle | *Plugins → Development → Import plugin from manifest…* |
| [`penpot-plugin`](integrations/penpot-plugin/README.md) | boards do Penpot equivalentes | servir a pasta e instalar o `manifest.json` em `Ctrl+Alt+P` |
| [`browser-extension`](integrations/browser-extension/README.md) | captura qualquer página como um bundle de uma tela | *Carregar sem compactação* em `chrome://extensions` |

O formato do arquivo está documentado em [`docs/design-bundle.md`](docs/design-bundle.md).
A extração roda no navegador (iframe oculto) e reaproveita o mesmo documento do
canvas; não há dependência nova no backend.

---

## 🖱️ Canvas como mock navegável

O canvas abre em **modo mock**: o clique normal se comporta como na página.

- Links `href="02-cadastro.html"` e elementos com `data-go="02-cadastro.html"`
  trocam de tela no editor (o iframe não navega para fora). O alvo é resolvido
  pelo nome da tela, ignorando caminho, extensão e o prefixo numérico do corpus v1.
- **Shift+clique** (ou Ctrl/Cmd+clique) seleciona um elemento e **acumula** a
  seleção: cada elemento ganha sua caixa, e uma barra no canto superior esquerdo
  mostra a contagem com ações de grupo (duplicar, excluir e limpar).
- **Editar** (canto inferior direito) volta ao comportamento de seleção por
  clique simples. Nos dois modos dá para **arrastar** (no mock, com Shift)
  para mover — com vários selecionados, o grupo inteiro se move junto — e usar
  as **alças** para redimensionar (com um elemento selecionado).
- **Shift+duplo clique** edita o texto inline; setas movem o selecionado (com
  Shift, 10px por vez) e **Esc** limpa a seleção; **Delete** apaga a seleção.
- **Desfazer/Refazer** na barra superior (ou Ctrl+Z, Ctrl+Shift+Z e Ctrl+Y),
  por tela, com até 60 passos. Vale para edições no canvas, da IA e do editor
  de código; a mudança só é gravada no servidor ao clicar em **Salvar**.
  O botão **Histórico** continua sendo o histórico de revisões do servidor.
- Formulários não enviam nada: `submit` é bloqueado e só navega se o form tiver
  `data-go`/`action` apontando para uma tela. Links externos não abrem dentro do mock.

---

## 🔗 Apresentação (Link do CEO)

Um projeto **não é público por padrão**. O endpoint `/api/public/p/<slug>` responde apenas quando:

- o projeto foi publicado (`POST /api/projects/{id}/publish`, usado pelo botão "Apresentar"), ou
- existe um **share link** ativo para ele.

Share links (`POST /api/projects/{id}/share-links`) suportam senha, expiração e revogação,
contam visualizações e podem liberar **comentários de visitantes** (`allow_comments`):
nesses links o visitante vê/comenta via `/api/public/p/<slug>/comments` e o editor mostra
os apontamentos na hora.

---

## 🧩 Assets (imagens)

`POST /api/projects/{id}/assets` (multipart `file`) aceita PNG/JPEG/GIF/WebP até 5 MB,
valida o tipo pelos **magic bytes** (nunca pela extensão) e guarda em `ASSETS_DIR`
(default `/app/assets_storage`, mapeado para `backend/assets_storage` no compose).
A entrega (`GET /api/assets/{id}`) exige sessão com acesso ao projeto ou projeto
publicado/share link ativo; arquivos são servidos com `Cache-Control: immutable`.
No editor, o botão **Imagem** envia e insere a imagem na tela.

---

## 🤝 Colaboração em tempo real

`WS /api/ws/projects/{project_id}` autentica pelo cookie de sessão (**e valida `Origin`**
para impedir cross-site WebSocket hijacking). Eventos:

| Evento | Direção | Efeito |
| :--- | :--- | :--- |
| `presence` | servidor | lista de participantes (avatares no editor) |
| `cursor` | ambos | posição do cursor por tela |
| `screen_updated` | servidor | conteúdo novo após qualquer save/AI patch |
| `comment_created` | servidor | comentário novo aparece para quem está no projeto |

A sala é em memória (uma instância). Para múltiplas réplicas, publique os eventos em
Redis/Postgres NOTIFY mantendo `app/ws.py:broadcaster` como interface.

---

## 🧠 Planos de IA

`GET /api/ai/plans` lista o catálogo (`free`, `pro`, `enterprise`), `PUT /api/org/plan`
(owner) troca o plano da organização e `GET /api/org/ai-usage` devolve consumo/limite
consolidados. Quando a organização tem plano, **o limite do plano substitui o limite
individual** de cada usuário em `enforce_ai_quota`; o limite do provedor BYOK continua
valendo em paralelo. A tela Configurações → Organização mostra o uso e permite a troca.

---

## 📧 E-mail, senhas e administração

A **primeira conta criada na instância** recebe o papel de *administrador do sistema*
(`is_system_admin`). Em bancos que já tinham usuários antes deste recurso, a migração
promove a conta mais antiga; para escolher outra, defina `SYSTEM_ADMIN_EMAIL` — esse
e-mail vira administrador no próximo login/cadastro.

O administrador vê **Configurações → E-mail** e escolhe o transporte:

| Transporte | Campos |
| :--- | :--- |
| **SMTP** | host, porta, usuário, senha/app password, STARTTLS/SSL |
| **Resend** | API key (`re_...`) e domínio remetente verificado |

Também define remetente, reply-to, URL pública (`APP_BASE_URL` como fallback) e se a
confirmação de e-mail é exigida. As credenciais são cifradas com Fernet no banco; a API
nunca devolve a senha/API key, apenas `has_smtp_password` / `has_resend_api_key`. O botão
**Enviar e-mail de teste** valida a configuração antes de depender dela.

Fluxos cobertos:

- `POST /api/auth/forgot-password` → link de uso único (1h), revoga todas as sessões ao redefinir.
- `POST /api/auth/verify-email` → confirmação; o aviso no app aparece quando a exigência está ligada.
- `POST /api/org/members/invite` → envia o convite por e-mail (48h). Sem transporte configurado,
  o admin recebe o link para repassar manualmente.
- Tokens são guardados só como hash SHA-256 em `auth_tokens`; os links usam `/reset-password`,
  `/verify-email` e `/accept-invite` no frontend.

> Ao atualizar uma instalação existente, rode `docker compose up -d --build` para instalar
> `aiosmtplib` na imagem e aplicar a migração `a1c9f2d7e4b3` automaticamente no boot.

---

## ✨ Geração por IA: validação e resiliência

O agente não aplica HTML "no escuro". Todo patch passa por `agent/htmlkit.py`
antes de chegar ao canvas:

1. **Extração** do bloco `` ```html `` (aceita cerca aberta/truncada e ignora texto explicativo).
2. **Sanitização**: remove `<script>`, atributos `on*`, `javascript:` e documentos aninhados.
3. **Reconstrução/balanceamento** de tags e remoção de `<style>` inacabado.
4. **`data-mb-id`**: injeta nos elementos editáveis e renomeia duplicados.
5. **Validação** (estrutura, volume de texto, placeholders, qualidade) → se falhar, o
   modelo recebe a lista de erros como prompt de correção (até `AI_AGENT_MAX_REPAIRS`).

Páginas inteiras são geradas **por seção** (planejadas pelo LangGraph), cada uma
validada/reparada antes de entrar no documento final; um truncamento pede continuação
e um provedor com erro real propaga a mensagem (nada de tela fictícia de fallback).

Variáveis de ambiente relevantes (defaults entre parênteses):

| Variável | Para que serve |
| :--- | :--- |
| `AI_LLM_CONNECT_TIMEOUT` (10s) | abertura de conexão com o provedor |
| `AI_LLM_READ_TIMEOUT` (900s) | leitura de stream — modelos locais lentos precisam disso |
| `AI_LLM_MAX_TOKENS` (8192) | orçamento de um patch/edição completa |
| `AI_SECTION_MAX_TOKENS` (2600) | orçamento por seção na geração de página |
| `AI_VISION_MAX_TOKENS` (2400) | refino visual (`/api/ai/vision-critique`) |
| `AI_LLM_MAX_ATTEMPTS` (2) | tentativas de rede/truncamento por chamada |
| `AI_AGENT_MAX_REPAIRS` (1) | rodadas de correção com base nos erros de validação |
| `AI_DISABLE_THINKING` (true) | em endpoints **locais**, envia `chat_template_kwargs.enable_thinking=false` |

> Modelos de raciocínio (Qwen3/bonsai) gastam todo o `max_tokens` "pensando" e devolvem
> conteúdo vazio. Por isso o thinking é desligado em endpoints locais; se ainda assim o
> modelo responder só raciocínio, o agente pede explicitamente o bloco HTML e, em último
> caso, recupera o HTML de dentro do `reasoning_content`.

---

## 🛡️ Segurança & Boas Práticas

- **Multi-tenancy:** Isolamento estrito por `organization_id` em todos os recursos (projetos, telas, tokens, comentários, logs de IA).
- **Proteção CSRF:** Tokens de sessão com cookies HTTP-only e cabeçalho `X-CSRF-Token`.
- **Sessões revogáveis:** o banco guarda apenas o hash SHA-256 do JWT; logout encerra somente a sessão atual.
- **Criptografia BYOK:** Chaves de API de provedores de IA são criptografadas em repouso no banco de dados.
- **Isolamento de HTML gerado:** canvas do editor e apresentação renderizam em iframe com `sandbox` (sem `allow-same-origin`).
- **Cotas e rate limit:** plano da organização, limite por usuário e por provedor; login/registro/IA/comentários públicos têm rate limit por IP.
- **WebSocket autenticado:** sessão validada no handshake e `Origin` conferido contra `ALLOW_ORIGINS`.
- **SSRF:** endpoints de IA validam esquema, DNS, IPs privados e portas proibidas.

---

## 📚 Documentação

- `docs/plano-arquitetura-mockbird-v2.md` — arquitetura, modelo de dados e roadmap (inclui a seção
  "Status real" com o que já existe e o que é roadmap).
