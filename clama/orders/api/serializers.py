"""
Serializers para a API de pedidos.
"""

from django.utils import timezone
from rest_framework import serializers

from clama.core.legal import POLITICA_VERSAO_ATUAL
from clama.core.pastoral_messages import MSG_ERRO_CREDITOS_24H
from clama.core.validators_documento import (
    is_valid_cnpj as _is_valid_cnpj,
)
from clama.core.validators_documento import (
    is_valid_cpf as _is_valid_cpf,
)
from clama.orders.models import CanalEntrega, Pedido, PedidoStatus
from clama.plans.models import Plan


class PedidoCreateSerializer(serializers.ModelSerializer):
    """Serializer para criação de pedidos."""

    plano = serializers.PrimaryKeyRelatedField(
        queryset=Plan.objects.all(),
        required=False,
        allow_null=True,
    )
    valor_reais_str = serializers.CharField(read_only=True)
    consent_aceito = serializers.BooleanField(required=True, write_only=True)

    class Meta:
        model = Pedido
        fields = [
            # Campos de entrada
            "nome",
            "email",
            "telefone",
            "cpf_cnpj",
            "idade",
            "sexo",
            "pedido_oracao",
            "plano",
            "valor_centavos",
            "canal_entrega",
            "consent_aceito",
            # Campos de saída (read-only)
            "id",
            "status",
            "valor_reais_str",
            "created_at",
        ]
        read_only_fields = ["id", "status", "valor_reais_str", "created_at"]
        extra_kwargs = {
            "nome": {
                "min_length": 2,
                "error_messages": {
                    "blank": "Por favor, digite seu nome.",
                    "min_length": "Conta um pouco de você no nome — pelo menos 2 letras.",
                },
            },
            "email": {
                "error_messages": {
                    "blank": "Por favor, digite seu e-mail.",
                    "invalid": "Confira seu e-mail — parece que faltou algo.",
                },
            },
            "cpf_cnpj": {
                "required": True,
                "error_messages": {
                    "blank": "Por favor, digite seu CPF ou CNPJ.",
                },
            },
            "valor_centavos": {
                "min_value": 599,
                "error_messages": {
                    "min_value": "O valor mínimo é R$ 5,99 — qualquer oferta acima ajuda o Clama.",
                },
            },
            "canal_entrega": {
                "error_messages": {
                    "invalid_choice": "Por favor, escolha entre E-mail ou WhatsApp.",
                },
            },
        }

    def validate_plano(self, value):
        """
        Valida que o plano está ativo E é visível.

        `visivel=False` é usado por planos internos (ex.: "Gratuito" do
        fluxo freemium). Permitir um atacante referenciar esse UUID no
        fluxo pago expõe pricing não-pretendido — sempre rejeite no entry
        do serializer pago (P-14).
        """
        if value is None:
            return value
        if not value.ativo:
            raise serializers.ValidationError(
                "Esse plano não está disponível no momento."
            )
        if not value.visivel:
            raise serializers.ValidationError(
                "Esse plano não está disponível."
            )
        return value

    def validate_cpf_cnpj(self, value):
        """
        Valida CPF (11 dígitos) ou CNPJ (14 dígitos), incluindo dígito verificador.

        Algoritmo portado de `clama-frontend/src/lib/validators/cpfCnpj.ts` para
        manter paridade entre validação de cliente e servidor.
        """
        # Remove caracteres não numéricos
        digits = "".join(c for c in value if c.isdigit())

        if len(digits) == 11:
            if not _is_valid_cpf(digits):
                raise serializers.ValidationError(
                    "Confira seu CPF — parece que tem algum dígito errado."
                )
            return digits
        if len(digits) == 14:
            if not _is_valid_cnpj(digits):
                raise serializers.ValidationError(
                    "Confira seu CNPJ — parece que tem algum dígito errado."
                )
            return digits

        raise serializers.ValidationError(
            "CPF deve ter 11 dígitos ou CNPJ deve ter 14 dígitos."
        )

    def validate_consent_aceito(self, value):
        """Valida que o consentimento foi aceito."""
        if not value:
            raise serializers.ValidationError(
                "Para enviar seu pedido, é preciso concordar com a política de privacidade."
            )
        return value

    def validate(self, data):
        """Validação cross-field: WhatsApp requer telefone; deriva plano se omitido."""
        canal = data.get("canal_entrega")
        telefone = data.get("telefone", "")

        if canal == CanalEntrega.WHATSAPP and not telefone.strip():
            raise serializers.ValidationError(
                {"telefone": "Para receber no WhatsApp, precisamos do seu telefone."}
            )

        # Valor Livre: deriva plano a partir do valor ("par abaixo").
        if data.get("plano") is None:
            inferido = Plan.objects.infer_from_valor(data["valor_centavos"])
            if inferido is None:
                raise serializers.ValidationError(
                    {"plano": "Nenhum plano disponível no momento."}
                )
            data["plano"] = inferido

        return data

    def create(self, validated_data):
        """Cria o pedido com campos de consentimento LGPD + vínculo com user."""
        # Remove consent_aceito do validated_data (será setado manualmente)
        consent_aceito = validated_data.pop("consent_aceito", False)

        # Obtém o IP do request (passado pelo context na view)
        request = self.context.get("request")
        consent_ip = None
        if request:
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                consent_ip = x_forwarded_for.split(",")[0].strip()
            else:
                consent_ip = request.META.get("REMOTE_ADDR")

        # Adiciona campos de consentimento
        validated_data["consent_aceito"] = consent_aceito
        validated_data["consent_versao"] = POLITICA_VERSAO_ATUAL
        validated_data["consent_aceito_at"] = timezone.now()
        validated_data["consent_ip"] = consent_ip

        # Spec lp-user-existence-gate (2026-05-10): vincula Pedido ao User
        # autenticado. PedidoCreateView usa IsAuthenticated, então
        # request.user nunca é AnonymousUser aqui.
        if request and getattr(request, "user", None) and request.user.is_authenticated:
            validated_data["user"] = request.user

        return super().create(validated_data)


class PedidoGratuitoCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para criação de pedidos gratuitos por usuário autenticado
    (card "Gratuito" em Minha Conta).

    Diferenças em relação ao fluxo pago:
    - Não recebe `plano` nem `valor_centavos`: o plano gratuito (invisível,
      complexidade SIMPLES_GRATUITA) é forçado no `create`, valor zerado.
    - Não passa pelo Asaas: o pedido já nasce `eh_gratuito=True` e em
      `GERANDO_ORACAO`. A view dispara a geração da oração.
    - Sem trava freemium (1-por-usuário): nesta tela autenticada, grátis é
      ilimitado por decisão de produto.

    Reaproveita as validações de CPF/CNPJ e consentimento do fluxo pago.
    """

    consent_aceito = serializers.BooleanField(required=True, write_only=True)
    valor_reais_str = serializers.CharField(read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "nome",
            "email",
            "telefone",
            "cpf_cnpj",
            "idade",
            "sexo",
            "pedido_oracao",
            "canal_entrega",
            "consent_aceito",
            # saída
            "id",
            "status",
            "valor_reais_str",
            "created_at",
        ]
        read_only_fields = ["id", "status", "valor_reais_str", "created_at"]
        extra_kwargs = {
            "nome": {
                "min_length": 2,
                "error_messages": {
                    "blank": "Por favor, digite seu nome.",
                    "min_length": "Conta um pouco de você no nome — pelo menos 2 letras.",
                },
            },
            "email": {
                "error_messages": {
                    "blank": "Por favor, digite seu e-mail.",
                    "invalid": "Confira seu e-mail — parece que faltou algo.",
                },
            },
            "cpf_cnpj": {
                "required": True,
                "error_messages": {
                    "blank": "Por favor, digite seu CPF ou CNPJ.",
                },
            },
            "canal_entrega": {
                "error_messages": {
                    "invalid_choice": "Por favor, escolha entre E-mail ou WhatsApp.",
                },
            },
        }

    # Reaproveita as validações de campo do fluxo pago.
    validate_cpf_cnpj = PedidoCreateSerializer.validate_cpf_cnpj
    validate_consent_aceito = PedidoCreateSerializer.validate_consent_aceito

    def validate(self, data):
        """WhatsApp requer telefone (mesma regra cross-field do fluxo pago)."""
        canal = data.get("canal_entrega")
        telefone = data.get("telefone", "")
        if canal == CanalEntrega.WHATSAPP and not telefone.strip():
            raise serializers.ValidationError(
                {"telefone": "Para receber no WhatsApp, precisamos do seu telefone."}
            )
        return data

    def create(self, validated_data):
        """
        Cria o pedido gratuito: plano gratuito forçado, valor 0,
        eh_gratuito=True, status GERANDO_ORACAO, vinculado ao user.
        """
        # Import local para evitar acoplamento de import no topo (o helper
        # vive em freemium e já encapsula o guard 503 do plano ausente).
        from clama.freemium.api.views import _get_plano_gratuito

        consent_aceito = validated_data.pop("consent_aceito", False)

        request = self.context.get("request")
        consent_ip = None
        if request:
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                consent_ip = x_forwarded_for.split(",")[0].strip()
            else:
                consent_ip = request.META.get("REMOTE_ADDR")

        validated_data["plano"] = _get_plano_gratuito()
        validated_data["valor_centavos"] = 0
        validated_data["eh_gratuito"] = True
        validated_data["status"] = PedidoStatus.GERANDO_ORACAO
        validated_data["consent_aceito"] = consent_aceito
        validated_data["consent_versao"] = POLITICA_VERSAO_ATUAL
        validated_data["consent_aceito_at"] = timezone.now()
        validated_data["consent_ip"] = consent_ip

        if request and getattr(request, "user", None) and request.user.is_authenticated:
            validated_data["user"] = request.user

        return super().create(validated_data)


class PedidoResponseSerializer(serializers.ModelSerializer):
    """Serializer para resposta de criação de pedido (sem dados sensíveis)."""

    valor_reais_str = serializers.CharField(read_only=True)

    class Meta:
        model = Pedido
        fields = [
            "id",
            "status",
            "valor_reais_str",
            "canal_entrega",
            "created_at",
        ]


class PedidoStatusSerializer(serializers.ModelSerializer):
    """Serializer para consulta de status do pedido (campos públicos apenas)."""

    plano = serializers.CharField(source="plano.nome", read_only=True)
    valor_reais_str = serializers.CharField(read_only=True)
    pastoral_message = serializers.SerializerMethodField()
    oracao_gerada = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = [
            "id",
            "status",
            "plano",
            "valor_reais_str",
            "canal_entrega",
            "created_at",
            "pastoral_message",
            "oracao_gerada",
        ]

    def get_pastoral_message(self, obj: Pedido) -> str | None:
        """Mensagem pastoral contextual (ex.: 24h quando créditos esgotaram)."""
        if obj.status == PedidoStatus.ERRO and obj.last_error == "credit_balance":
            return MSG_ERRO_CREDITOS_24H
        return None

    def get_oracao_gerada(self, obj: Pedido) -> str | None:
        # Só expõe a oração após a entrega; antes disso o front recebe None.
        if obj.status == PedidoStatus.ENVIADA:
            return obj.oracao_gerada or None
        return None
