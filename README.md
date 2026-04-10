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
