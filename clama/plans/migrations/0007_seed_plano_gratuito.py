"""
Data migration: seed do Plan "Gratuito" para o fluxo freemium.

O plano nasce com:
- valor_centavos=0 (não passa pelo gateway de pagamento).
- complexidade='simples_gratuita' (resolução para a nova entrada do prompt).
- visivel=False (não aparece na LP/formulário pago — só é usado pelo fluxo
  dedicado /api/freemium).
- ativo=True.
"""
from django.db import migrations

PLANO_GRATUITO_NOME = "Gratuito"
PLANO_GRATUITO_DESCRICAO = "Sua primeira oração — por nossa conta"


def create_plano_gratuito(apps, schema_editor):
    """
    Idempotente (P-32). Usa `get_or_create` para que migrations rerun
    (após rollback parcial / migrate --fake) não estourem com
    IntegrityError quando o plano já existe. Lookup por `complexidade`
    (campo único de fato neste contexto — o plano gratuito é o único com
    `simples_gratuita`).
    """
    Plan = apps.get_model("plans", "Plan")

    Plan.objects.get_or_create(
        complexidade="simples_gratuita",
        defaults={
            "nome": PLANO_GRATUITO_NOME,
            "valor_centavos": 0,
            "descricao": PLANO_GRATUITO_DESCRICAO,
            "ordem": 99,
            "ativo": True,
            "visivel": False,
        },
    )


def remove_plano_gratuito(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")
    Plan.objects.filter(nome=PLANO_GRATUITO_NOME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0006_complexidade_simples_gratuita'),
    ]

    operations = [
        migrations.RunPython(create_plano_gratuito, remove_plano_gratuito),
    ]
