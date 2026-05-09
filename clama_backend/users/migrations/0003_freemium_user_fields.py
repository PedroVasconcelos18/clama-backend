import encrypted_model_fields.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0002_alter_user_options_alter_user_managers_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='cpf_cnpj',
            field=encrypted_model_fields.fields.EncryptedCharField(blank=True, null=True, verbose_name='CPF/CNPJ'),
        ),
        migrations.AddField(
            model_name='user',
            name='telefone',
            field=encrypted_model_fields.fields.EncryptedCharField(blank=True, null=True, verbose_name='Telefone'),
        ),
        migrations.AddField(
            model_name='user',
            name='force_change_password',
            field=models.BooleanField(default=False, help_text='Indica que o usuário deve trocar a senha no próximo login.', verbose_name='Forçar troca de senha'),
        ),
    ]
