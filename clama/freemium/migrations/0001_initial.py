import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FreemiumBlacklist',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('cpf_hash', models.CharField(db_index=True, help_text='SHA-256 do CPF/CNPJ normalizado (somente dígitos).', max_length=64, unique=True, verbose_name='Hash do CPF/CNPJ')),
                ('email_hash', models.CharField(db_index=True, help_text='SHA-256 do e-mail normalizado (lowercase + strip).', max_length=64, unique=True, verbose_name='Hash do e-mail')),
                ('telefone_hash', models.CharField(db_index=True, help_text='SHA-256 do telefone normalizado (somente dígitos, E.164).', max_length=64, unique=True, verbose_name='Hash do telefone')),
            ],
            options={
                'verbose_name': 'Entrada da Blacklist Freemium',
                'verbose_name_plural': 'Blacklist Freemium',
                'ordering': ['-created_at'],
            },
        ),
    ]
