"""
Serializers para gestão de documentos de contexto no admin.
"""

import mimetypes

from rest_framework import serializers

from clama.documents.models import DocumentoContexto


def detect_mime_type(uploaded_file) -> str:
    """
    Detecta o tipo MIME do arquivo de forma confiável.

    Ordem de prioridade:
    1. Extensão do arquivo (mais confiável para docx)
    2. Content-Type enviado pelo browser (fallback)
    """
    filename = uploaded_file.name or ""

    # Detecta pela extensão
    mime_type, _ = mimetypes.guess_type(filename)

    if mime_type:
        return mime_type

    # Fallback: usa o content_type do browser
    return uploaded_file.content_type or "application/octet-stream"


class AdminDocumentoContextoSerializer(serializers.ModelSerializer):
    """
    Serializer para CRUD de documentos de contexto no admin.

    UPLOAD:
    - Aceita PDF, DOCX e texto plano
    - Limite de 100MB por arquivo
    - Tipo MIME é detectado automaticamente pela extensão do arquivo

    SINCRONIZAÇÃO:
    - Documentos são criados localmente primeiro
    - Sincronização com Anthropic é feita via action separada
    """

    esta_sincronizado = serializers.BooleanField(read_only=True)
    tamanho_formatado = serializers.CharField(read_only=True)

    class Meta:
        model = DocumentoContexto
        fields = [
            "id",
            "nome",
            "descricao",
            "arquivo",
            "tipo_mime",
            "tamanho_bytes",
            "tamanho_formatado",
            "anthropic_file_id",
            "data_sincronizacao",
            "ativo",
            "esta_sincronizado",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tipo_mime",
            "tamanho_bytes",
            "tamanho_formatado",
            "anthropic_file_id",
            "data_sincronizacao",
            "esta_sincronizado",
            "created_at",
            "updated_at",
        ]

    def validate_arquivo(self, value):
        """
        Valida tipo MIME e tamanho do arquivo.
        Detecta o tipo MIME automaticamente pela extensão.
        """
        # Detecta tipo MIME pela extensão
        detected_mime = detect_mime_type(value)

        # Valida tipo MIME
        if detected_mime not in DocumentoContexto.ALLOWED_MIME_TYPES:
            allowed = "PDF, DOCX ou TXT"
            raise serializers.ValidationError(
                f"Formato não suportado. Use {allowed}. "
                f"Detectado: {detected_mime}"
            )

        # Valida tamanho
        if value.size > DocumentoContexto.MAX_FILE_SIZE:
            max_mb = DocumentoContexto.MAX_FILE_SIZE / (1024 * 1024)
            file_mb = value.size / (1024 * 1024)
            raise serializers.ValidationError(
                f"Arquivo excede limite de {max_mb:.0f}MB. "
                f"Tamanho: {file_mb:.1f}MB"
            )

        # Armazena o tipo detectado para uso no create
        value._detected_mime_type = detected_mime

        return value

    def create(self, validated_data):
        """
        Cria documento extraindo metadados do arquivo.
        """
        arquivo = validated_data["arquivo"]

        # Usa o tipo MIME detectado na validação
        validated_data["tipo_mime"] = getattr(
            arquivo, "_detected_mime_type", arquivo.content_type
        )
        validated_data["tamanho_bytes"] = arquivo.size

        return super().create(validated_data)


class AdminDocumentoContextoListSerializer(serializers.ModelSerializer):
    """
    Serializer simplificado para listagem de documentos.

    Não inclui o campo arquivo para reduzir payload.
    """

    esta_sincronizado = serializers.BooleanField(read_only=True)
    tamanho_formatado = serializers.CharField(read_only=True)

    class Meta:
        model = DocumentoContexto
        fields = [
            "id",
            "nome",
            "descricao",
            "tipo_mime",
            "tamanho_bytes",
            "tamanho_formatado",
            "anthropic_file_id",
            "data_sincronizacao",
            "ativo",
            "esta_sincronizado",
            "created_at",
            "updated_at",
        ]
