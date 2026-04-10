"""
Data migration para seed dos 3 planos canônicos do Clama.
"""
from django.db import migrations


def create_planos(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")

    Plan.objects.create(
        nome="Pedido de Oração",
        valor_centavos=2000,
        descricao="Oração pastoral escrita especialmente para o seu pedido.",
        complexidade="simples",
        ordem=1,
        ativo=True,
    )

    Plan.objects.create(
        nome="Oração + Versículo",
        valor_centavos=5000,
        descricao="Oração com versículo bíblico selecionado conforme o seu pedido.",
        complexidade="com_versiculo",
        ordem=2,
        ativo=True,
    )

    Plan.objects.create(
        nome="Oração + Profecia + Versículos",
        valor_centavos=10000,
        descricao="Palavra profética encorajadora com 2-3 versículos relevantes para sua situação.",
        complexidade="com_profecia_e_versiculos",
        ordem=3,
        ativo=True,
    )


def remove_planos(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")
    Plan.objects.filter(
        nome__in=[
            "Pedido de Oração",
            "Oração + Versículo",
            "Oração + Profecia + Versículos",
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_planos, remove_planos),
    ]
