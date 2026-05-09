from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0005_plan_visivel'),
    ]

    operations = [
        migrations.AlterField(
            model_name='plan',
            name='complexidade',
            field=models.CharField(
                choices=[
                    ('simples', 'Simples'),
                    ('com_versiculo', 'Com versículo'),
                    ('com_profecia_e_versiculos', 'Com profecia e versículos'),
                    ('simples_gratuita', 'Simples Gratuita'),
                ],
                default='simples',
                max_length=30,
            ),
        ),
    ]
