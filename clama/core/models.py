import uuid

from django.db import models


class TimestampedModel(models.Model):
    """
    Modelo base abstrato que adiciona campos de auditoria automáticos.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDPKModel(models.Model):
    """
    Modelo base abstrato que usa UUID como chave primária.
    Evita enumeração de IDs em URLs públicas.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True
