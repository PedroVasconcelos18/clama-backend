"""
Data migration para seed das instituições placeholder do Clama.
"""
from django.db import migrations

_INSTITUICOES_SEED = [
    ("Casa de Apoio", "casa-de-apoio", 1),
    ("Lar Esperança", "lar-esperanca", 2),
    ("Rede Solidária", "rede-solidaria", 3),
]


def create_instituicoes(apps, schema_editor):
    Instituicao = apps.get_model("instituicoes", "Instituicao")
    for nome, logo_slug, ordem in _INSTITUICOES_SEED:
        Instituicao.objects.create(
            nome=nome,
            logo_slug=logo_slug,
            ordem=ordem,
            ativo=True,
        )


def remove_instituicoes(apps, schema_editor):
    Instituicao = apps.get_model("instituicoes", "Instituicao")
    Instituicao.objects.filter(
        logo_slug__in=[logo_slug for _, logo_slug, _ in _INSTITUICOES_SEED]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("instituicoes", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_instituicoes, remove_instituicoes),
    ]
