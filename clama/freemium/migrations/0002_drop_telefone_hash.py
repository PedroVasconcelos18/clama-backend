"""
Migration pós-renegociação 2026-05-08:
- Remove o campo `telefone_hash` da `FreemiumBlacklist`.

Sem OTP confirmando posse do número, hash de telefone era falso-positivo
(qualquer um podia digitar um número arbitrário e bloquear outra pessoa).
A blacklist passa a ser somente (CPF, e-mail).

Em ambientes que já tenham dados, isso descarta o histórico de
`telefone_hash` — aceitável (ainda pré-prod).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("freemium", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="freemiumblacklist",
            name="telefone_hash",
        ),
    ]
