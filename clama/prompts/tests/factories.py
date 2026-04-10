"""
Factories para testes do app prompts.
"""
import factory
from factory.django import DjangoModelFactory

from clama.prompts.models import PromptTemplate


class PromptTemplateFactory(DjangoModelFactory):
    class Meta:
        model = PromptTemplate

    nome = factory.Sequence(lambda n: f"Prompt Template {n}")
    versao = factory.Sequence(lambda n: n + 1)
    system_prompt = "Você é um assistente de oração pastoral."
    instrucoes_por_complexidade = factory.LazyFunction(
        lambda: {
            "simples": "Oração curta.",
            "com_versiculo": "Oração com versículo.",
            "com_profecia_e_versiculos": "Oração com profecia e versículos.",
        }
    )
    ativo = False
