"""
Serializers para a API de planos.
"""

from rest_framework import serializers

from clama.plans.models import Plan


class PlanSerializer(serializers.ModelSerializer):
    """Serializer para listagem de planos."""

    valor_reais_str = serializers.CharField(read_only=True)

    class Meta:
        model = Plan
        fields = [
            "id",
            "nome",
            "valor_centavos",
            "valor_reais_str",
            "descricao",
            "complexidade",
            "ordem",
        ]
