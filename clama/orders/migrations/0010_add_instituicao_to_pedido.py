import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0009_pedido_pix_qr_code_pedido_pix_qr_code_base64'),
        ('instituicoes', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='instituicao',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='pedidos', to='instituicoes.instituicao', verbose_name='Instituição'),
        ),
    ]
