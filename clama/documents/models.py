"""
Models para gestão de documentos de contexto.

Documentos são enviados para a Files API da Anthropic e usados como
contexto adicional na geração de orações personalizadas.
"""

from django.core.validators import FileExtensionValidator
from django.db import models

from clama.core.models import TimestampedModel, UUIDPKModel


def documento_upload_path(instance: "DocumentoContexto", filename: str) -> str:
    """Gera path para upload: documents/{uuid}/{filename}"""
    return f"documents/{instance.id}/{filename}"


class DocumentoContextoManager(models.Manager):
    """Manager customizado para DocumentoContexto."""

    def ativos(self):
        """Retorna apenas documentos ativos."""
        return self.filter(ativo=True)

    def sincronizados(self):
        """Retorna documentos com file_id da Anthropic."""
        return self.filter(anthropic_file_id__isnull=False)

    def ativos_sincronizados(self):
        """Retorna documentos ativos e sincronizados com a Anthropic."""
        return self.ativos().exclude(anthropic_file_id__isnull=True).exclude(anthropic_file_id="")


class DocumentoContexto(UUIDPKModel, TimestampedModel):
    """
    Documento de contexto para enriquecer geração de orações.

    Documentos são sincronizados com a Files API da Anthropic.
    O arquivo é armazenado localmente e o file_id da Anthropic é
    mantido para referência nas chamadas da API.

    TIPOS SUPORTADOS:
    - application/pdf
    - text/plain

    LIMITE: 100MB por arquivo (margem de segurança abaixo do limite de 500MB da Anthropic)
    """

    # Tipos MIME permitidos
    ALLOWED_MIME_TYPES = [
        "application/pdf",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    ]
    # Tamanho máximo em bytes (100MB)
    MAX_FILE_SIZE = 100 * 1024 * 1024

    nome = models.CharField(
        max_length=200,
        help_text="Nome identificador do documento",
    )
    descricao = models.TextField(
        blank=True,
        help_text="Descrição do conteúdo e propósito do documento",
    )
    arquivo = models.FileField(
        upload_to=documento_upload_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "txt", "docx"])],
        help_text="Arquivo PDF, DOCX ou texto plano (máx 100MB)",
    )
    tipo_mime = models.CharField(
        max_length=100,
        help_text="Tipo MIME do arquivo",
    )
    tamanho_bytes = models.PositiveIntegerField(
        help_text="Tamanho do arquivo em bytes",
    )

    # Sincronização com Anthropic Files API
    anthropic_file_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="ID do arquivo na Files API da Anthropic",
    )
    data_sincronizacao = models.DateTimeField(
        blank=True,
        null=True,
        help_text="Data/hora da última sincronização com Anthropic",
    )

    # Status
    ativo = models.BooleanField(
        default=False,
        help_text="Se ativo, será incluído no contexto das orações. Ativar sincroniza automaticamente.",
    )

    objects = DocumentoContextoManager()

    class Meta:
        verbose_name = "Documento de Contexto"
        verbose_name_plural = "Documentos de Contexto"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        status = "✓" if self.anthropic_file_id else "⏳"
        return f"{self.nome} [{status}]"

    @property
    def esta_sincronizado(self) -> bool:
        """Verifica se o documento está sincronizado com a Anthropic."""
        return bool(self.anthropic_file_id)

    @property
    def tamanho_formatado(self) -> str:
        """Retorna tamanho formatado (ex: '2.5 MB')."""
        if self.tamanho_bytes < 1024:
            return f"{self.tamanho_bytes} B"
        elif self.tamanho_bytes < 1024 * 1024:
            return f"{self.tamanho_bytes / 1024:.1f} KB"
        else:
            return f"{self.tamanho_bytes / (1024 * 1024):.1f} MB"
