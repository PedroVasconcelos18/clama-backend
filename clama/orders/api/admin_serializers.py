"""
Serializers para API admin de pedidos.
"""

from rest_framework import serializers

from clama.orders.models import Pedido
from clama.payments.models import WebhookEvento
from clama.plans.models import Plan


class WebhookEventoSerializer(serializers.ModelSerializer):
    """Serializer para WebhookEvento em detalhes do pedido."""

    class Meta:
        model = WebhookEvento
        fields = [
            "id",
            "provider",
            "external_event_id",
            "event_type",
            "status",
            "error_message",
            "created_at",
        ]


class PlanoNestedSerializer(serializers.ModelSerializer):
    """Serializer nested para plano em detalhes do pedido."""

    valor_reais_str = serializers.CharField(read_only=True)

    class Meta:
        model = Plan
        fields = ["id", "nome", "valor_reais_str"]


class AdminPedidoListSerializer(serializers.ModelSerializer):
    """
    Serializer para listagem de pedidos no admin.

    Expõe dados básicos incluindo dados pessoais (admin tem acesso).
    """

    plano_nome = serializers.CharField(source="plano.nome", read_only=True)
    valor_reais_str = serializers.CharField(read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "created_at",
            "nome",
            "email",
            "telefone",
            "plano_nome",
            "valor_centavos",
            "valor_reais_str",
            "status",
            "canal_entrega",
            "eh_gratuito",
        ]


class AdminPedidoDetailSerializer(serializers.ModelSerializer):
    """
    Serializer para detalhes completos de um pedido no admin.

    Expõe TODOS os campos incluindo dados sensíveis (LGPD).
    Acesso restrito a is_clama_admin=True.
    """

    plano = PlanoNestedSerializer(read_only=True)
    valor_reais_str = serializers.CharField(read_only=True)
    webhook_events = WebhookEventoSerializer(many=True, read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "created_at",
            "updated_at",
            # Dados pessoais
            "nome",
            "email",
            "telefone",
            "idade",
            "sexo",
            # Conteúdo
            "pedido_oracao",
            "oracao_gerada",
            # Plano e valor
            "plano",
            "valor_centavos",
            "valor_reais_str",
            # Status e canal
            "status",
            "canal_entrega",
            # Integrações
            "asaas_charge_id",
            "asaas_invoice_url",
            "whatsapp_message_id",
            "whatsapp_delivered_at",
            "whatsapp_read_at",
            # Retries
            "retry_count",
            "last_error",
            # Relacionados
            "webhook_events",
        ]
