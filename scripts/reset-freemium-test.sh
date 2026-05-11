#!/usr/bin/env bash
#
# Reseta o estado de teste do fluxo freemium em dev local.
#
# - Apaga pedidos, tokens de confirmação, webhook events de pagamento.
# - Apaga blacklist (todas as entries — cpf, email, telefone, device, ip).
# - Apaga JWT blacklist (refresh tokens revogados).
# - Apaga users que NÃO são admin do Clama (`is_clama_admin=false`).
# - Limpa cache Redis (senha temp em trânsito, locks etc).
#
# **Não apaga:**
# - Schema (migrations permanecem aplicadas).
# - Planos, prompts, configurações.
# - Superusers / admins do Clama.
#
# Uso:
#   ./scripts/reset-freemium-test.sh
#
# Pressuposto: containers Docker já estão rodando
# (`docker compose -f docker-compose.local.yml up -d`).

set -euo pipefail

COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/docker-compose.local.yml"
PG_USER="${POSTGRES_USER:-clama_backend}"
PG_DB="${POSTGRES_DB:-clama_backend}"

echo "→ Limpando banco de testes (mantém schema, admins, configs)..."
docker compose -f "$COMPOSE_FILE" exec -T postgres \
  psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -c "
BEGIN;

-- Filhos de Pedido (FKs)
DELETE FROM payments_webhookevento;
DELETE FROM freemium_freemiumconfirmationtoken;

-- Pedidos
DELETE FROM orders_pedido;

-- JWT blacklist + outstanding (FK -> User)
DELETE FROM token_blacklist_blacklistedtoken;
DELETE FROM token_blacklist_outstandingtoken;

-- Auxiliares Django ligados a non-admin users
DELETE FROM django_admin_log WHERE user_id IN (
  SELECT id FROM users_user WHERE is_clama_admin = false
);
DELETE FROM users_user_groups WHERE user_id IN (
  SELECT id FROM users_user WHERE is_clama_admin = false
);
DELETE FROM users_user_user_permissions WHERE user_id IN (
  SELECT id FROM users_user WHERE is_clama_admin = false
);

-- Blacklist freemium (cpf, email, telefone, device, ip)
DELETE FROM freemium_freemiumblacklist;

-- Users de teste (preserva admins)
DELETE FROM users_user WHERE is_clama_admin = false;

COMMIT;
"

echo "→ Limpando cache Redis DB 1 (senha temp + cache app)..."
docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli -n 1 FLUSHDB > /dev/null

echo "✓ Reset completo. Você pode submeter um pedido freemium novo."
