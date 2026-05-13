"""
Re-adiciona `telefone_hash` na FreemiumBlacklist (removido em 0002 e
re-introduzido pela spec lp-user-existence-gate em 2026-05-10).

Nullable + indexed. Sem `unique=True` porque entradas legadas (criadas
entre 2026-05-08 e este re-add) ficarão com NULL e Postgres tolera múltiplos
NULLs em coluna unique — mas mantemos sem unique pra evitar surpresa em
re-runs em ambientes que possam ter resíduo de hash de telefone duplicado.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("freemium", "0003_confirmation_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="freemiumblacklist",
            name="telefone_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "HMAC-SHA-256 do telefone (somente dígitos). "
                    "Re-adicionado em 2026-05-10 — nullable pra suportar entries legadas sem telefone."
                ),
                max_length=64,
                null=True,
                verbose_name="Hash do telefone",
            ),
        ),
    ]
