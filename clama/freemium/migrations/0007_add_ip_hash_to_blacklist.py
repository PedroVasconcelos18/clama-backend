"""
Adiciona `ip_hash` à FreemiumBlacklist.

Motivação: `device_hash` (FingerprintJS v4 open-source) é instável em
modo private/anônimo do Brave, Safari e Firefox com strict mode —
gerando visitorId diferente a cada submit do mesmo browser. Vetor
"aba anônima + email temp + CPF gerado + telefone falso" continua
passando pelo gate de blacklist mesmo com device_hash gravado.

`ip_hash` é a camada complementar: HMAC-SHA-256 do consent_ip,
verificado contra a janela de 24h (IP_BLACKLIST_WINDOW). Falha-fechado:
se o request chega com IP malformado, hash da string vazia não vai bater
com IPs reais.

LGPD: a tabela só armazena hash (não cleartext do IP). Pedido.consent_ip
continua mantendo o IP em claro pra fins forenses.

Trade-off: bloqueia famílias atrás do mesmo IP residencial. Admin
pode desbloquear deletando a entry. Aceitável pra MVP.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("freemium", "0006_add_device_hash_to_blacklist"),
    ]

    operations = [
        migrations.AddField(
            model_name="freemiumblacklist",
            name="ip_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "HMAC-SHA-256 do consent_ip do Pedido. Bloqueia submits "
                    "da mesma rede dentro da janela de IP_BLACKLIST_WINDOW "
                    "(default 24h). Camada extra anti-bypass quando "
                    "device_hash é instável (Brave, Safari, modo private). "
                    "Trade-off: bloqueia famílias atrás do mesmo IP — admin "
                    "pode desbloquear manualmente."
                ),
                max_length=64,
                null=True,
                verbose_name="Hash do IP de origem",
            ),
        ),
    ]
