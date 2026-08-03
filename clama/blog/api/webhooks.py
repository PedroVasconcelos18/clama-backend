"""Webhook de publicação do WordPress (Story 3.2).

Idempotência por `WebhookEvento` com `provider=WORDPRESS`, autenticação pelo
`WordPressWebhookAuthMiddleware`, processamento sempre assíncrono.

Fica em `api/` e não no `urls.py` flat do app para ficar fiel ao padrão que
está sendo copiado (`clama/payments/api/webhooks.py`). Registrado em
`clama/blog/urls.py`.
"""

import logging

from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status as http
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from clama.payments.models import WebhookEvento, WebhookEventoStatus, WebhookProvider

logger = logging.getLogger("clama.blog.webhook")

# Só estes curto-circuitam como já processado. `RECEBIDO`/`ERRO` são
# reprocessáveis — se o Clama devolveu 500, o WordPress reenvia e a gente
# quer que reprocesse de verdade.
_ESTADOS_TERMINAIS = {
    WebhookEventoStatus.PROCESSADO,
    WebhookEventoStatus.IGNORADO,
}

# Eventos que mexem no espelho. Qualquer outro é ignorado com 200 — devolver
# erro faria o WordPress retriar um evento que nunca vai nos interessar.
EVENTOS_ACEITOS = {"post_publicado", "post_atualizado", "post_removido"}


@method_decorator(csrf_exempt, name="dispatch")
class WordPressWebhookView(APIView):
    """Recebe eventos de publicação do WordPress.

    Fluxo:
    - A assinatura já foi validada pelo middleware; chegar aqui significa que
      o corpo veio de quem tem o segredo.
    - Idempotência por `(provider, external_event_id)`; curto-circuita só em
      estado terminal.
    - Evento fora de `EVENTOS_ACEITOS` → marca `IGNORADO` e 200.
    - Enfileira a task e responde 200 **imediatamente**. Nada é processado
      síncrono: o WordPress não pode ficar esperando o Clama escrever no banco.
    """

    permission_classes = [AllowAny]
    # Sem throttle: o WordPress retria legitimamente, e limitar aqui
    # transformaria retry em perda de evento.
    throttle_classes = []

    @extend_schema(exclude=True)
    def post(self, request):
        # Form-encoded, não JSON (AC4). O `hash_hmac` do PHP assina o corpo
        # que o `wp_remote_post` monta, e esse corpo é form-encoded por
        # default. Assumir JSON aqui daria 400 em todo evento legítimo.
        dados = request.data

        evento_id = str(dados.get("evento_id") or "").strip()
        tipo = str(dados.get("tipo") or "").strip()

        if not evento_id or not tipo:
            logger.warning(
                "wordpress_webhook_payload_invalido",
                extra={
                    "event": "wordpress_webhook_payload_invalido",
                    "tem_evento_id": bool(evento_id),
                    "tem_tipo": bool(tipo),
                },
            )
            return Response(
                {"status": "invalid_payload"},
                status=http.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            registro, criado = WebhookEvento.objects.try_register(
                provider=WebhookProvider.WORDPRESS,
                external_event_id=evento_id,
                event_type=tipo,
                payload=dict(dados.items()),
            )

            if not criado and registro.status in _ESTADOS_TERMINAIS:
                logger.info(
                    "wordpress_webhook_ja_processado",
                    extra={
                        "event": "wordpress_webhook_ja_processado",
                        "evento_id": evento_id,
                        "status": registro.status,
                    },
                )
                return Response({"status": "already_processed"})

            if tipo not in EVENTOS_ACEITOS:
                registro.status = WebhookEventoStatus.IGNORADO
                registro.save(update_fields=["status", "updated_at"])
                logger.info(
                    "wordpress_webhook_ignorado",
                    extra={"event": "wordpress_webhook_ignorado", "tipo": tipo},
                )
                return Response({"status": "ignored"})

            # Import local: a task importa modelos do blog, e o módulo de
            # tasks importa daqui em nenhum ponto — mas o import no topo
            # criaria o ciclo assim que isso mudar.
            from clama.blog.tasks import sincronizar_post_espelho

            # `on_commit` dentro do `atomic`: sem isso a task pode rodar antes
            # de o `WebhookEvento` existir para o worker, e a idempotência
            # dele não encontraria a linha.
            registro_id = str(registro.id)
            transaction.on_commit(lambda: sincronizar_post_espelho.delay(registro_id))

        return Response({"status": "ok"})
