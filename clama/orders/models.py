"""
Modelos do app orders - Pedidos de oração.

Campos sensíveis (nome, email, telefone, cpf_cnpj, pedido_oracao, oracao_gerada) são
criptografados em coluna via django-encrypted-model-fields para conformidade LGPD.
"""

from django.conf import settings
from django.db import models
from encrypted_model_fields.fields import (
    EncryptedCharField,
    EncryptedEmailField,
    EncryptedTextField,
)

from clama.core.exceptions import PastoralAPIException
from clama.core.models import TimestampedModel, UUIDPKModel
from clama.core.money import centavos_to_reais_str
from clama.plans.models import Plan


class Sexo(models.TextChoices):
    """Opções de sexo/gênero para o pedido."""

    FEMININO = "feminino", "Feminino"
    MASCULINO = "masculino", "Masculino"
    NAO_INFORMADO = "nao_informado", "Não informado"


class CanalEntrega(models.TextChoices):
    """Canal de entrega da oração."""

    EMAIL = "email", "E-mail"
    WHATSAPP = "whatsapp", "WhatsApp"


class PedidoStatus(models.TextChoices):
    """Status do pedido no fluxo de processamento."""

    AGUARDANDO_PAGAMENTO = "aguardando_pagamento", "Aguardando pagamento"
    # Pós-renegociação 2026-05-08: pedidos do fluxo freemium ficam neste
    # status entre a submissão do form e o clique no link de confirmação
    # por e-mail (double opt-in). Não passa pelo Asaas.
    AGUARDANDO_CONFIRMACAO_EMAIL = (
        "aguardando_confirmacao_email",
        "Aguardando confirmação por e-mail",
    )
    PAGO = "pago", "Pago"
    GERANDO_ORACAO = "gerando_oracao", "Gerando oração"
    ORACAO_GERADA = "oracao_gerada", "Oração gerada"
    ENVIADA = "enviada", "Enviada"
    AGUARDANDO_REENVIO = "aguardando_reenvio", "Aguardando reenvio"
    ERRO = "erro", "Erro"


class Pedido(UUIDPKModel, TimestampedModel):
    """
    Pedido de oração da Juliana.

    Campos sensíveis (nome, email, telefone, pedido_oracao, oracao_gerada)
    são criptografados em coluna para conformidade LGPD.
    """

    # Dados pessoais (criptografados)
    nome = EncryptedCharField(max_length=120, verbose_name="Nome")
    email = EncryptedEmailField(verbose_name="E-mail")
    telefone = EncryptedCharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name="Telefone",
    )
    cpf_cnpj = EncryptedCharField(
        max_length=18,
        blank=True,
        default="",
        verbose_name="CPF/CNPJ",
    )

    # Dados opcionais
    idade = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Idade",
    )
    sexo = models.CharField(
        max_length=20,
        choices=Sexo.choices,
        blank=True,
        default="",
        verbose_name="Sexo",
    )

    # Conteúdo do pedido (criptografado)
    pedido_oracao = EncryptedTextField(
        blank=True,
        default="",
        verbose_name="Pedido de oração",
    )
    oracao_gerada = EncryptedTextField(
        blank=True,
        default="",
        verbose_name="Oração gerada",
    )

    # Plano e valor
    plano = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="pedidos",
        verbose_name="Plano",
    )
    valor_centavos = models.IntegerField(verbose_name="Valor (centavos)")

    # Vínculo com User (criado no fluxo freemium; nullable para pedidos pagos
    # que ainda não tem conta associada).
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pedidos",
        verbose_name="Usuário",
    )

    # Marca pedidos do fluxo freemium (gratuitos, não passam pelo Asaas).
    eh_gratuito = models.BooleanField(
        default=False,
        verbose_name="É gratuito",
        help_text="Pedido do fluxo freemium — não passa pelo gateway de pagamento.",
    )

    # Canal e status
    canal_entrega = models.CharField(
        max_length=20,
        choices=CanalEntrega.choices,
        default=CanalEntrega.EMAIL,
        verbose_name="Canal de entrega",
    )
    status = models.CharField(
        max_length=40,
        choices=PedidoStatus.choices,
        default=PedidoStatus.AGUARDANDO_PAGAMENTO,
        verbose_name="Status",
    )

    # Integração Asaas
    asaas_charge_id = models.CharField(
        max_length=80,
        blank=True,
        default="",
        verbose_name="ID da cobrança Asaas",
    )
    asaas_invoice_url = models.URLField(
        blank=True,
        default="",
        verbose_name="URL do checkout Asaas",
    )

    # Integração WhatsApp (Z-API)
    whatsapp_message_id = models.CharField(
        max_length=120,
        blank=True,
        default="",
        verbose_name="ID da mensagem WhatsApp",
    )
    whatsapp_delivered_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data de entrega WhatsApp",
    )
    whatsapp_read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data de leitura WhatsApp",
    )

    # Controle de retries
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Contagem de retentativas",
    )
    last_error = models.TextField(
        blank=True,
        default="",
        verbose_name="Último erro registrado",
    )

    # Campos de consentimento LGPD
    consent_aceito = models.BooleanField(
        default=False,
        verbose_name="Consentimento aceito",
    )
    consent_versao = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name="Versão da política aceita",
    )
    consent_aceito_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data do consentimento",
    )
    consent_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name="IP do consentimento",
    )

    # Anti-fraude (pós-renegociação 2026-05-08): hash do device fingerprint
    # capturado no frontend (FingerprintJS). No MVP é apenas observação —
    # ainda não bloqueia. Vira critério de bloqueio quando o dataset mostrar
    # padrão de fraude.
    device_hash = models.CharField(
        max_length=128,
        blank=True,
        default="",
        verbose_name="hash do device fingerprint",
    )

    # P-V5 wave 2 — idempotência da entrega do e-mail final com a oração.
    # Setado pela `_enviar_email_freemium` task APÓS o email_sender retornar
    # sucesso e ANTES do `cache.delete` da senha temp. Re-execução da task
    # (Celery retry, double dispatch) lê este campo e retorna early sem
    # reenviar — evita race entre `cache.delete` e o save do `Pedido.status`
    # mandar email duplicado SEM o bloco de credenciais (cache já limpo).
    # Campo aplica-se ao fluxo freemium (`eh_gratuito=True`); pedidos pagos
    # continuam usando `Pedido.status == ENVIADA` como guard de idempotência.
    oracao_email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="E-mail da oração enviado em",
        help_text=(
            "Marcado após delivery confirmada do e-mail final com a oração "
            "(fluxo freemium). Re-execuções da task ficam no-op se setado."
        ),
    )

    class Meta:
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Pedido {self.id} - {self.nome}"

    @property
    def valor_reais_str(self) -> str:
        """Retorna o valor formatado em reais (ex: 'R$ 20,00')."""
        return centavos_to_reais_str(self.valor_centavos)

    def marcar_como_pago(self) -> None:
        """
        Transiciona o pedido para status PAGO.

        Raises:
            PastoralAPIException: Se o pedido não estiver em AGUARDANDO_PAGAMENTO.
        """
        if self.status != PedidoStatus.AGUARDANDO_PAGAMENTO:
            raise PastoralAPIException(
                code="invalid_state_transition",
                message="Pedido não está aguardando pagamento",
                pastoral_message="Esse pedido já foi processado. Vamos te encaminhar para a confirmação.",
                status_code=409,
            )
        self.status = PedidoStatus.PAGO
        self.save(update_fields=["status", "updated_at"])
