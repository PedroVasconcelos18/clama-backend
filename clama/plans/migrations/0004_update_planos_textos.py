"""
Atualiza nome/descrição dos planos seedados em 0002.

- "Pedido de Oração": descrição sem a palavra "pastoral".
- "Oração + Profecia + Versículos": renomeado para "Oração + Reflexão + Versículos"
  com descrição atualizada ("Oração + Reflexão Pública + 2-3 versículos…").
"""
from django.db import migrations


NEW_DESCRICAO_SIMPLES = "Oração escrita especialmente para o seu pedido."
OLD_DESCRICAO_SIMPLES = "Oração pastoral escrita especialmente para o seu pedido."

OLD_NOME_PROFECIA = "Oração + Profecia + Versículos"
NEW_NOME_PROFECIA = "Oração + Reflexão + Versículos"
NEW_DESCRICAO_PROFECIA = (
    "Oração + Reflexão Pública + 2-3 versículos relevantes para sua situação."
)
OLD_DESCRICAO_PROFECIA = (
    "Palavra profética encorajadora com 2-3 versículos relevantes para sua situação."
)


def update_planos(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")

    Plan.objects.filter(nome="Pedido de Oração").update(
        descricao=NEW_DESCRICAO_SIMPLES,
    )

    Plan.objects.filter(nome=OLD_NOME_PROFECIA).update(
        nome=NEW_NOME_PROFECIA,
        descricao=NEW_DESCRICAO_PROFECIA,
    )


def revert_planos(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")

    Plan.objects.filter(nome="Pedido de Oração").update(
        descricao=OLD_DESCRICAO_SIMPLES,
    )

    Plan.objects.filter(nome=NEW_NOME_PROFECIA).update(
        nome=OLD_NOME_PROFECIA,
        descricao=OLD_DESCRICAO_PROFECIA,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0003_alter_plan_valor_centavos"),
    ]

    operations = [
        migrations.RunPython(update_planos, revert_planos),
    ]
