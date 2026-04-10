"""
Serializers para API admin de pedidos.
"""

from rest_framework import serializers

from clama.orders.models import Pedido
from clama.payments.models import WebhookEvento


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
        ]


class AdminPedidoDetailSerializer(serializers.ModelSerializer):
    """
    Serializer para detalhes completos de um pedido no admin.

    Expõe TODOS os campos incluindo dados sensíveis (LGPD).
    Acesso restrito a is_clama_admin=True.
    """

    plano_nome = serializers.CharField(source="plano.nome", read_only=True)
    plano_complexidade = serializers.CharField(source="plano.complexidade", read_only=True)
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
            "plano_nome",
            "plano_complexidade",
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
