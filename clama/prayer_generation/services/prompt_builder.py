"""
Builder de prompts para geração de orações.
"""

from clama.orders.models import Pedido
from clama.prompts.models import PromptTemplate


def build_prompt(pedido: Pedido, template: PromptTemplate) -> tuple[str, str]:
    """
    Monta o prompt completo para geração de oração.

    Args:
        pedido: Pedido de oração
        template: Template de prompt ativo

    Returns:
        Tupla (system_prompt, user_message)
    """
    # System prompt vem direto do template
    system_prompt = template.system_prompt

    # Obtém instrução por complexidade do plano
    complexidade = pedido.plano.complexidade
    instrucao_complexidade = template.instrucoes_por_complexidade.get(
        complexidade, ""
    )

    # Trata pedido vazio (FR17)
    pedido_oracao = pedido.pedido_oracao.strip() if pedido.pedido_oracao else ""
    if not pedido_oracao:
        pedido_oracao = "[pedido vazio]"

    # Trata sexo e idade opcionais
    sexo = pedido.sexo if pedido.sexo else "não informado"
    idade = str(pedido.idade) if pedido.idade else "não informada"

    # Monta user_message
    user_message = f"""{instrucao_complexidade}

Nome: {pedido.nome}
Sexo: {sexo}
Idade: {idade}

Pedido: {pedido_oracao}"""

    return system_prompt, user_message


def build_prompt_for_preview(
    nome: str,
    sexo: str,
    pedido_oracao: str,
    plano_complexidade: str,
    template: PromptTemplate,
) -> tuple[str, str]:
    """
    Monta o prompt para preview (sem pedido real).

    Args:
        nome: Nome da pessoa
        sexo: Sexo da pessoa
        pedido_oracao: Texto do pedido de oração
        plano_complexidade: Complexidade do plano (simples, com_versiculo, etc)
        template: Template de prompt a usar

    Returns:
        Tupla (system_prompt, user_message)
    """
    # System prompt vem direto do template
    system_prompt = template.system_prompt

    # Obtém instrução por complexidade
    instrucao_complexidade = template.instrucoes_por_complexidade.get(
        plano_complexidade, ""
    )

    # Trata pedido vazio
    pedido_oracao = pedido_oracao.strip() if pedido_oracao else "[pedido vazio]"

    # Monta user_message
    user_message = f"""{instrucao_complexidade}

Nome: {nome}
Sexo: {sexo}
Idade: não informada

Pedido: {pedido_oracao}"""

    return system_prompt, user_message
