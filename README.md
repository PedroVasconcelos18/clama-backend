# Clama Backend

Backend do Clama - Plataforma de oração pastoral personalizada.

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
