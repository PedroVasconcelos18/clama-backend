"""
Migration P-V5 wave 2 — idempotência do e-mail final (freemium).

Adiciona `Pedido.oracao_email_sent_at` (DateTimeField nullable) usado pela
`_enviar_email_freemium` task como flag de idempotência: após delivery
confirmada do e-mail com oração + credenciais, o campo recebe `now()`. Re-
execuções da task (Celery retry, double dispatch) ficam no-op.

Race fechada: entre o `cache.delete(senha_temp)` e o `pedido.status = ENVIADA`
save, uma re-execução da task encontrava cache vazio e mandava email sem
credenciais. Agora o guard fica no campo do Pedido (ACID), não no cache (TTL).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0005_pedido_aguardando_confirmacao"),
    ]

    operations = [
        migrations.AddField(
            model_name="pedido",
            name="oracao_email_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text=(
                    "Marcado após delivery confirmada do e-mail final com a "
                    "oração (fluxo freemium). Re-execuções da task ficam "
                    "no-op se setado."
                ),
                null=True,
                verbose_name="E-mail da oração enviado em",
            ),
        ),
    ]
