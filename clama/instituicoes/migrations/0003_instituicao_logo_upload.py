"""
Troca `logo_slug` (conjunto fixo) por `logo` (data-URI enviada via upload no admin)
e substitui as 3 instituições placeholder pela associação real.
"""
from django.db import migrations, models
from django.db.models.deletion import ProtectedError

_PLACEHOLDER_NOMES = ["Casa de Apoio", "Lar Esperança", "Rede Solidária"]
_ASSOCIACAO_NOME = (
    "Associação dos Doentes Renais Crônicos e Transplantados de "
    "Juiz de Fora e Região"
)


def trocar_por_associacao(apps, schema_editor):
    Instituicao = apps.get_model("instituicoes", "Instituicao")
    # Remove os placeholders; se algum já estiver referenciado por um pedido/repasse
    # (PROTECT), apenas desativa em vez de falhar a migração.
    for inst in Instituicao.objects.filter(nome__in=_PLACEHOLDER_NOMES):
        try:
            inst.delete()
        except ProtectedError:
            inst.ativo = False
            inst.save(update_fields=["ativo"])
    # Cria a associação real (logo vazia — enviada depois via upload no admin).
    Instituicao.objects.get_or_create(
        nome=_ASSOCIACAO_NOME,
        defaults={"ordem": 1, "ativo": True},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("instituicoes", "0002_seed_instituicoes"),
    ]

    operations = [
        migrations.RemoveField(model_name="instituicao", name="logo_slug"),
        migrations.AddField(
            model_name="instituicao",
            name="logo",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunPython(trocar_por_associacao, migrations.RunPython.noop),
    ]
