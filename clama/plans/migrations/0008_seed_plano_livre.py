"""
Data migration: seed do Plan "Livre" para o fluxo de valor livre.

Contexto: quando todos os tiers pagos (visíveis) são desativados, restando
apenas o "Gratuito" (invisível), o `infer_from_valor` do valor livre passa a
retornar None e a criação do pedido pago quebra com "Nenhum plano disponível".
Como `Pedido.plano` é FK obrigatória e é o `complexidade` do plano que resolve
a instrução do prompt, o valor livre precisa de um plano de fallback.

O plano nasce com:
- complexidade='simples' (resolve para o "prompt de estrutura simples" —
  chave já existente no template ativo).
- visivel=False (não aparece na LP/formulário como card de tier; só é
  atribuído server-side pelo fluxo de valor livre — ver
  `PlanManager.fallback_valor_livre`).
- ativo=True.
- valor_centavos placeholder (1): o valor real do pedido vem do que o usuário
  ofertou no valor livre (`Pedido.valor_centavos`), não deste plano.

Idempotente (P-32): `get_or_create` por (nome, visivel=False) — chave estável
já que `complexidade='simples'` sozinho NÃO é único (o tier "Pedido de Oração"
também é simples, porém visível).
"""
from django.db import migrations

PLANO_LIVRE_NOME = "Livre"
PLANO_LIVRE_DESCRICAO = "Oração de estrutura simples — valor livre"


def create_plano_livre(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")

    Plan.objects.get_or_create(
        nome=PLANO_LIVRE_NOME,
        visivel=False,
        defaults={
            "valor_centavos": 1,
            "descricao": PLANO_LIVRE_DESCRICAO,
            "complexidade": "simples",
            "ordem": 98,
            "ativo": True,
        },
    )


def remove_plano_livre(apps, schema_editor):
    Plan = apps.get_model("plans", "Plan")
    Plan.objects.filter(nome=PLANO_LIVRE_NOME, visivel=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('plans', '0007_seed_plano_gratuito'),
    ]

    operations = [
        migrations.RunPython(create_plano_livre, remove_plano_livre),
    ]
