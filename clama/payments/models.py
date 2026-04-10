"""
Models do app payments.
"""

from django.db import IntegrityError, models, transaction

from clama.core.models import TimestampedModel, UUIDPKModel


class WebhookProvider(models.TextChoices):
    """Provedores de webhook suportados."""

    ASAAS = "ASAAS", "Asaas"
    ZAPI = "ZAPI", "Z-API"


class WebhookEventoStatus(models.TextChoices):
    """Status de processamento do evento de webhook."""

    RECEBIDO = "RECEBIDO", "Recebido"
    PROCESSADO = "PROCESSADO", "Processado"
    IGNORADO = "IGNORADO", "Ignorado"
    ERRO = "ERRO", "Erro"


class WebhookEventoManager(models.Manager):
    """Manager customizado para WebhookEvento com método de idempotência."""

    def try_register(
        self,
        *,
        provider: str,
        external_event_id: str,
        event_type: str,
        payload: dict,
    ) -> tuple["WebhookEvento", bool]:
        """
        Tenta registrar um novo evento de webhook.

        Retorna tupla (objeto, created). Se o evento já existe,
        retorna (existing, False) sem lançar exceção.

        Args:
            provider: Provedor do webhook (ASAAS, ZAPI)
            external_event_id: ID único do evento no provedor
            event_type: Tipo do evento
            payload: Payload completo do webhook

        Returns:
            Tupla (WebhookEvento, bool) onde bool indica se foi criado
        """
        try:
            with transaction.atomic():
                obj = self.create(
                    provider=provider,
                    external_event_id=external_event_id,
                    event_type=event_type,
                    payload=payload,
                    status=WebhookEventoStatus.RECEBIDO,
                )
                return obj, True
        except IntegrityError:
            existing = self.get(provider=provider, external_event_id=external_event_id)
            return existing, False


class WebhookEvento(UUIDPKModel, TimestampedModel):
    """
    Registro de evento de webhook recebido.

    Garante idempotência: o mesmo evento (provider + external_event_id)
    não é processado duas vezes.
    """

    provider = models.CharField(
        max_length=20,
        choices=WebhookProvider.choices,
        help_text="Provedor de origem do webhook",
    )
    external_event_id = models.CharField(
        max_length=120,
        help_text="ID único do evento no provedor",
    )
    event_type = models.CharField(
        max_length=80,
        help_text="Tipo do evento (ex: PAYMENT_CONFIRMED)",
    )
    payload = models.JSONField(
        help_text="Payload completo do webhook",
    )
    status = models.CharField(
        max_length=20,
        choices=WebhookEventoStatus.choices,
        default=WebhookEventoStatus.RECEBIDO,
        help_text="Status de processamento",
    )
    pedido = models.ForeignKey(
        "orders.Pedido",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="webhook_events",
        help_text="Pedido associado (se identificável)",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Mensagem de erro (quando status=ERRO)",
    )

    objects = WebhookEventoManager()

    class Meta:
        verbose_name = "Evento de Webhook"
        verbose_name_plural = "Eventos de Webhook"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_event_id"],
                name="uq_webhook_event_provider_id",
            )
        ]
        indexes = [
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_event_id} ({self.status})"

    def mark_processed(self, pedido=None) -> None:
        """Marca o evento como processado com sucesso."""
        self.status = WebhookEventoStatus.PROCESSADO
        if pedido:
            self.pedido = pedido
        self.save(update_fields=["status", "pedido", "updated_at"])

    def mark_ignored(self, reason: str = "") -> None:
        """Marca o evento como ignorado."""
        self.status = WebhookEventoStatus.IGNORADO
        self.error_message = reason
        self.save(update_fields=["status", "error_message", "updated_at"])

    def mark_error(self, error_message: str) -> None:
        """Marca o evento como erro."""
        self.status = WebhookEventoStatus.ERRO
        self.error_message = error_message
        self.save(update_fields=["status", "error_message", "updated_at"])
