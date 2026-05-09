from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0004_update_planos_textos'),
    ]

    operations = [
        migrations.AddField(
            model_name='plan',
            name='visivel',
            field=models.BooleanField(default=True, help_text='Indica se o plano aparece para o usuário final (LP, formulário). Planos invisíveis (ex.: Gratuito do freemium) só são usados via fluxos dedicados.'),
        ),
    ]
