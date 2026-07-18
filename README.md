# Clama Backend

Backend do Clama - Plataforma de oração pastoral personalizada.

## URLs

- **Produção:** `https://clama-backend.up.railway.app` (atualizar após configurar Railway)
- **Local:** `http://localhost:8000`

## Stack

- Django 4.2
- Django REST Framework
- PostgreSQL 16
- Celery + Redis
- Docker Compose

## Pré-requisitos

- Docker e Docker Compose

## Início Rápido

### 1. Copiar arquivos de ambiente

```bash
# Os arquivos de env já estão em .envs/.local/
# Para produção, crie .envs/.production/ com suas configurações
```

### 2. Subir o stack

```bash
docker-compose -f docker-compose.local.yml up -d
```

### 3. Aplicar migrações

```bash
docker-compose -f docker-compose.local.yml run --rm django python manage.py migrate
```

### 4. Criar superusuário

```bash
docker-compose -f docker-compose.local.yml run --rm django python manage.py createsuperuser
```

### 5. Acessar a aplicação

- API: http://localhost:8000/api/
- Admin: http://localhost:8000/admin/
- Flower (Celery): http://localhost:5555/

## Comandos Úteis

### Rodar testes

```bash
docker-compose -f docker-compose.local.yml run --rm django pytest
```

### Ver logs

```bash
docker-compose -f docker-compose.local.yml logs -f
```

### Parar containers

```bash
docker-compose -f docker-compose.local.yml down
```

### Criar novas migrações

```bash
docker-compose -f docker-compose.local.yml run --rm django python manage.py makemigrations
```

## Containers Docker

O projeto usa 6 containers para desenvolvimento local:

### django
**Servidor web principal** - Executa a API Django REST Framework.
- Porta: `8000`
- Processa requests HTTP (criação de pedidos, checkout, webhooks)
- Comando: `python manage.py runserver`

### postgres
**Banco de dados relacional** - Armazena todos os dados persistentes.
- Pedidos, planos, usuários, prompts, eventos de webhook
- Campos sensíveis (nome, email, telefone, oração) são criptografados
- Volume persistente para não perder dados ao reiniciar

### redis
**Broker de mensagens** - Fila para comunicação entre Django e Celery.
- Quando uma task é disparada, ela vai para uma fila no Redis
- Workers leem dessa fila e executam as tasks
- Também usado como cache

### celeryworker
**Executor de tasks em background** - Processa tarefas assíncronas.
- `gerar_oracao_task` - Chama API do Claude para gerar oração
- `enviar_oracao_task` - Envia email ou WhatsApp com a oração
- `enviar_alerta_admin_task` - Notifica admin em caso de erro
- **Essencial**: Sem ele, as tasks ficam na fila mas nunca executam

### celerybeat
**Agendador de tasks periódicas** - Dispara tasks em horários programados (tipo cron).
- Reprocessamento de pedidos com erro
- Limpeza de dados antigos
- Relatórios periódicos

### flower
**Dashboard de monitoramento do Celery** - Interface web para debug.
- Porta: `5555`
- Login: `admin` / `admin`
- Mostra tasks em execução, concluídas e com erro
- Histórico e tempo de execução
- **Opcional** em produção

### Fluxo de uma Task

```
┌─────────────┐     ┌─────────┐     ┌────────────────┐
│   Django    │────▶│  Redis  │◀────│ Celery Worker  │
│  (Backend)  │     │ (Fila)  │     │ (Executa tasks)│
└─────────────┘     └─────────┘     └────────────────┘
                         ▲
                         │
                    ┌────┴─────┐
                    │  Beat    │  (Dispara tasks agendadas)
                    └──────────┘

                    ┌──────────┐
                    │  Flower  │  (Monitora tudo)
                    └──────────┘
```

### Comandos Úteis para Containers

```bash
# Ver status de todos os containers
docker ps

# Ver logs de um container específico
docker compose -f docker-compose.local.yml logs celeryworker --tail=50

# Reiniciar um container específico
docker compose -f docker-compose.local.yml restart celeryworker

# Parar e remover todos os containers
docker compose -f docker-compose.local.yml down

# Subir todos os containers
docker compose -f docker-compose.local.yml up -d

# Forçar rebuild das imagens
docker compose -f docker-compose.local.yml up -d --build
```

## Estrutura do Projeto

```
clama-backend/
├── manage.py
├── docker-compose.local.yml
├── docker-compose.production.yml
├── .envs/
│   ├── .local/
│   │   ├── .django
│   │   └── .postgres
│   └── .production/
├── requirements/
│   ├── base.txt
│   ├── local.txt
│   └── production.txt
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── local.py
│   │   ├── production.py
│   │   └── test.py
│   ├── urls.py
│   ├── celery_app.py
│   ├── wsgi.py
│   └── asgi.py
└── clama_backend/
    └── users/
```

## Variáveis de Ambiente

### Django (.envs/.local/.django)

- `USE_DOCKER`: yes
- `DJANGO_SETTINGS_MODULE`: config.settings.local
- `DJANGO_SECRET_KEY`: (auto-gerado)
- `DJANGO_DEBUG`: True
- `REDIS_URL`: redis://redis:6379/0
- `CELERY_BROKER_URL`: redis://redis:6379/0

### PostgreSQL (.envs/.local/.postgres)

- `POSTGRES_HOST`: postgres
- `POSTGRES_PORT`: 5432
- `POSTGRES_DB`: clama_backend
- `POSTGRES_USER`: clama_backend
- `POSTGRES_PASSWORD`: (senha local)

## Observabilidade

### Sentry

O projeto usa Sentry para captura de erros e performance monitoring.

**Variáveis de ambiente (obrigatórias em produção):**

- `SENTRY_DSN`: DSN do projeto Sentry (obtido em https://sentry.io/settings/projects/{project}/keys/)
- `SENTRY_ENVIRONMENT`: Ambiente (local, staging, production)

**Configuração:**

1. Crie um projeto no Sentry (https://sentry.io)
2. Copie o DSN do projeto
3. Configure as variáveis de ambiente em `.envs/.production/.django`

**Validação da integração (apenas em DEBUG):**

```bash
# Acesse o endpoint de debug para verificar se o Sentry está configurado
curl http://localhost:8000/api/_sentry-debug/
# Este endpoint lança um ZeroDivisionError que aparecerá no dashboard Sentry
```

### Logging

O logging usa formato JSON estruturado via `python-json-logger`.

**Regras de PII (Dados Pessoais):**

NUNCA logar:
- Nome completo da usuária
- E-mail, telefone
- Conteúdo do pedido de oração
- Texto da oração gerada

Logar apenas:
- `pedido.id` (UUID)
- `plano.slug`
- Status
- Timestamps
- Códigos de erro

## Deploy (Railway)

### Serviços Railway

| Serviço | Tipo | Comando |
|---|---|---|
| `web` | Dockerfile | `gunicorn config.wsgi --bind 0.0.0.0:$PORT` |
| `worker` | Dockerfile | `celery -A config.celery_app worker -l INFO` |
| `postgres` | Managed addon | - |
| `redis` | Managed addon | - |

### Variáveis de Ambiente (Produção)

```
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=<secreto>
DJANGO_ALLOWED_HOSTS=*.up.railway.app,clama.com.br
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}
DJANGO_CORS_ALLOWED_ORIGINS=https://clama.vercel.app,https://clama.com.br
SENTRY_DSN=<do dashboard>
SENTRY_ENVIRONMENT=production
ANTHROPIC_API_KEY=<quando disponível>
MERCADOPAGO_ACCESS_TOKEN=<access token do Mercado Pago (Checkout Pro)>
MERCADOPAGO_WEBHOOK_SECRET=<secret de assinatura do webhook Mercado Pago>
RESEND_API_KEY=<quando disponível>
```

> `MERCADOPAGO_MIN_VALOR_CENTAVOS` é opcional (default `1`). Migração Asaas → Mercado Pago (Epic MP): adicionar `MERCADOPAGO_*` no Railway **antes** do deploy que passa a usar o gateway.

### Forçar Redeploy

```bash
git commit --allow-empty -m "trigger deploy" && git push
```
