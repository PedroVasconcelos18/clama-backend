"""
Factories e helpers para testes do app freemium.
"""

from clama.plans.models import Complexidade, Plan


def get_or_create_plano_gratuito() -> Plan:
    """
    Garante que existe o Plan "Gratuito" (visivel=False, ativo=True,
    complexidade=SIMPLES_GRATUITA) que a saga procura. Útil em testes que
    não dependem do seed via migration.
    """
    plano, _ = Plan.objects.get_or_create(
        complexidade=Complexidade.SIMPLES_GRATUITA,
        defaults={
            "nome": "Gratuito",
            "valor_centavos": 0,
            "descricao": "Plano do fluxo freemium — não visível.",
            "ordem": 99,
            "ativo": True,
            "visivel": False,
        },
    )
    # Garante visibilidade/ativação corretas mesmo se já existir.
    if plano.visivel or not plano.ativo:
        plano.visivel = False
        plano.ativo = True
        plano.save()
    return plano
