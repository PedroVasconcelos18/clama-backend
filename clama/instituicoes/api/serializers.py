"""
Serializers da API de instituições.
"""

import base64

from rest_framework import serializers

from clama.instituicoes.models import (
    LOGO_ALLOWED_MIME,
    LOGO_MAX_BYTES,
    Instituicao,
)


class InstituicaoSerializer(serializers.ModelSerializer):
    """Serializer público de leitura de instituições."""

    class Meta:
        model = Instituicao
        fields = ["id", "nome", "logo"]


def _arquivo_para_data_uri(arquivo) -> str:
    """Codifica um arquivo de upload como data-URI base64 (guardado no banco)."""
    mime = getattr(arquivo, "content_type", "") or "application/octet-stream"
    conteudo = arquivo.read()
    b64 = base64.b64encode(conteudo).decode("ascii")
    return f"data:{mime};base64,{b64}"


class AdminInstituicaoSerializer(serializers.ModelSerializer):
    """CRUD admin de instituições. A logo é enviada como arquivo (`logo_file`)
    e guardada como data-URI base64 em `logo`."""

    logo_file = serializers.FileField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = Instituicao
        fields = [
            "id",
            "nome",
            "logo",
            "logo_file",
            "ativo",
            "ordem",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "logo", "created_at", "updated_at"]

    def validate_logo_file(self, value):
        if value is None:
            return value
        content_type = getattr(value, "content_type", "") or ""
        if content_type not in LOGO_ALLOWED_MIME:
            raise serializers.ValidationError(
                "Formato de imagem não suportado. Use PNG, JPG, SVG, WEBP ou GIF."
            )
        if value.size > LOGO_MAX_BYTES:
            limite_kb = LOGO_MAX_BYTES // 1024
            raise serializers.ValidationError(
                f"A imagem excede o limite de {limite_kb} KB. Envie uma versão menor."
            )
        return value

    def create(self, validated_data):
        arquivo = validated_data.pop("logo_file", None)
        if arquivo is not None:
            validated_data["logo"] = _arquivo_para_data_uri(arquivo)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        arquivo = validated_data.pop("logo_file", None)
        if arquivo is not None:
            validated_data["logo"] = _arquivo_para_data_uri(arquivo)
        return super().update(instance, validated_data)
