"""
Adiciona `device_hash` à FreemiumBlacklist.

Anti-bypass: atacante em aba anônima + email temporário + CPF gerado +
telefone falso passava por todos os checks porque cada identificador era
"novo". O `device_hash` (FingerprintJS visitorId) é o mesmo entre abas
do mesmo browser, então gravamos no saga e checamos no submit.

Nullable: FingerprintJS pode falhar (Brave shields, adblockers, browsers
muito antigos). Nesses casos device_hash vem vazio e o check é skipped —
não bloqueia falsos positivos por instrumentação ausente.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("freemium", "0005_backfill_blacklist_telefone_hash"),
    ]

    operations = [
        migrations.AddField(
            model_name="freemiumblacklist",
            name="device_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "visitorId do FingerprintJS coletado no submit. Bloqueia "
                    "submits subsequentes da mesma máquina+browser mesmo com "
                    "CPF/email/telefone diferentes (anti-bypass de aba "
                    "anônima / email temporário). Nullable: pode vir vazio "
                    "se FingerprintJS falhar (Brave shields, adblockers) — "
                    "nesse caso não bloqueia."
                ),
                max_length=128,
                null=True,
                verbose_name="Device fingerprint",
            ),
        ),
    ]
