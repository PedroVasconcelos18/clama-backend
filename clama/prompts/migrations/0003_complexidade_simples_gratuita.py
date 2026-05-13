"""
Data migration: adiciona a entrada `simples_gratuita` em
`instrucoes_por_complexidade` do PromptTemplate ATIVO.

Texto cru do prompt para o fluxo freemium — 3 parágrafos curtos, sem
versículos, sem profecia, tom acolhedor mas conciso.
"""
from django.db import migrations

CHAVE_COMPLEXIDADE = "simples_gratuita"
INSTRUCAO_SIMPLES_GRATUITA = (
    "Gere uma oração pastoral em exatamente 3 parágrafos curtos. "
    "Sem versículos bíblicos. Sem profecia. Tom acolhedor e pessoal, "
    "mas conciso. Foque no pedido específico do usuário sem digressões."
)


def add_simples_gratuita(apps, schema_editor):
    PromptTemplate = apps.get_model("prompts", "PromptTemplate")
    template = PromptTemplate.objects.filter(ativo=True).first()
    if template is None:
        # Sem template ativo — nada a fazer (ambiente vazio / fresh setup).
        return
    instrucoes = dict(template.instrucoes_por_complexidade or {})
    instrucoes[CHAVE_COMPLEXIDADE] = INSTRUCAO_SIMPLES_GRATUITA
    template.instrucoes_por_complexidade = instrucoes
    template.save(update_fields=["instrucoes_por_complexidade", "updated_at"])


def remove_simples_gratuita(apps, schema_editor):
    PromptTemplate = apps.get_model("prompts", "PromptTemplate")
    template = PromptTemplate.objects.filter(ativo=True).first()
    if template is None:
        return
    instrucoes = dict(template.instrucoes_por_complexidade or {})
    instrucoes.pop(CHAVE_COMPLEXIDADE, None)
    template.instrucoes_por_complexidade = instrucoes
    template.save(update_fields=["instrucoes_por_complexidade", "updated_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("prompts", "0002_seed_prompt_pastoral"),
    ]

    operations = [
        migrations.RunPython(add_simples_gratuita, remove_simples_gratuita),
    ]
