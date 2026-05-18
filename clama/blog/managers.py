from django.db import models


class PostManager(models.Manager):
    """Manager customizado para o model Post."""

    def publicados(self):
        return self.filter(status="publicado").order_by("-data_publicacao")

    def rascunhos(self):
        return self.filter(status="rascunho").order_by("-updated_at")
