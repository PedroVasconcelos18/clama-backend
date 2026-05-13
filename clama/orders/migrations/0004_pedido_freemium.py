import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_add_cpf_cnpj'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pedidos', to=settings.AUTH_USER_MODEL, verbose_name='Usuário'),
        ),
        migrations.AddField(
            model_name='pedido',
            name='eh_gratuito',
            field=models.BooleanField(default=False, help_text='Pedido do fluxo freemium — não passa pelo gateway de pagamento.', verbose_name='É gratuito'),
        ),
    ]
