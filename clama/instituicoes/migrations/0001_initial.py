import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orders', '0009_pedido_pix_qr_code_pedido_pix_qr_code_base64'),
    ]

    operations = [
        migrations.CreateModel(
            name='Instituicao',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('nome', models.CharField(max_length=120)),
                ('logo_slug', models.CharField(choices=[('casa-de-apoio', 'Casa de Apoio'), ('lar-esperanca', 'Lar Esperança'), ('rede-solidaria', 'Rede Solidária')], max_length=40)),
                ('ativo', models.BooleanField(default=True)),
                ('ordem', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name': 'Instituição',
                'verbose_name_plural': 'Instituições',
                'ordering': ['ordem', 'nome'],
            },
        ),
        migrations.CreateModel(
            name='Repasse',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('valor_base_centavos', models.IntegerField()),
                ('percentual', models.PositiveSmallIntegerField()),
                ('valor_centavos', models.IntegerField()),
                ('status', models.CharField(choices=[('registrado', 'Registrado')], default='registrado', max_length=20)),
                ('pedido', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='repasse', to='orders.pedido')),
                ('instituicao', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='repasses', to='instituicoes.instituicao')),
            ],
            options={
                'verbose_name': 'Repasse',
                'verbose_name_plural': 'Repasses',
            },
        ),
    ]
