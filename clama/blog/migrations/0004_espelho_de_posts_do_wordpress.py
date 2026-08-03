"""Espelho local dos posts do WordPress (ADR-02, Story 3.1).

Nenhuma linha existente é lida ou alterada: só criação de tabela, duas colunas
nullable, índices e uma constraint. Não há `RunPython` nem `AlterField`.

⚠️ **A ordem das operações aqui foi corrigida à mão.** O autodetector do Django
emitiu os `AddIndex`/`AddConstraint` de `comentario` e `reacao` **antes** dos
`AddField` que criam a coluna `post_espelho`, e a migration falhava com
`FieldDoesNotExist: Comentario has no field named 'post_espelho'`. Ao reordenar,
mantenha campo antes de índice.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("blog", "0003_add_customer_banido_model"),
    ]

    operations = [
        migrations.CreateModel(
            name="PostEspelho",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("wp_post_id", models.PositiveIntegerField(unique=True)),
                ("slug", models.SlugField(db_index=False, max_length=200)),
                ("titulo", models.CharField(max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("rascunho", "Rascunho"),
                            ("publicado", "Publicado"),
                            ("privado", "Privado"),
                            ("agendado", "Agendado"),
                            ("lixeira", "Lixeira"),
                            ("pendente", "Pendente de revisão"),
                        ],
                        default="rascunho",
                        max_length=20,
                    ),
                ),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                ("url", models.URLField(blank=True, default="", max_length=500)),
            ],
            options={
                "verbose_name": "Post espelhado",
                "verbose_name_plural": "Posts espelhados",
                "ordering": ["-published_at", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="postespelho",
            index=models.Index(fields=["slug"], name="idx_blog_postespelho_slug"),
        ),
        migrations.AddIndex(
            model_name="postespelho",
            index=models.Index(
                fields=["status", "-published_at"],
                name="idx_blog_postesp_status_pub",
            ),
        ),
        # Campos antes dos índices que os referenciam.
        migrations.AddField(
            model_name="comentario",
            name="post_espelho",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="comentarios",
                to="blog.postespelho",
            ),
        ),
        migrations.AddField(
            model_name="reacao",
            name="post_espelho",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reacoes",
                to="blog.postespelho",
            ),
        ),
        migrations.AddIndex(
            model_name="comentario",
            index=models.Index(
                fields=["post_espelho", "-created_at"],
                name="idx_blog_coment_espelho_crtd",
            ),
        ),
        migrations.AddIndex(
            model_name="reacao",
            index=models.Index(
                fields=["post_espelho", "tipo"],
                name="idx_blog_reacao_espelho_tipo",
            ),
        ),
        migrations.AddConstraint(
            model_name="reacao",
            constraint=models.UniqueConstraint(
                fields=("post_espelho", "customer", "tipo"),
                name="uniq_blog_reacao_espelho_customer_tipo",
            ),
        ),
    ]
