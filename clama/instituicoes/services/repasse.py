"""
Serviço de registro de repasse a instituições.
"""

from typing import TYPE_CHECKING

from clama.instituicoes.constants import REPASSE_PERCENTUAL_PADRAO
from clama.instituicoes.models import Repasse

if TYPE_CHECKING:
    from clama.orders.models import Pedido


def registrar_repasse(pedido: "Pedido") -> Repasse | None:
    """Registra o repasse de 20% de forma idempotente (get-or-create por pedido)."""
    if not pedido.instituicao_id:
        return None
    valor = pedido.valor_centavos * REPASSE_PERCENTUAL_PADRAO // 100
    if valor <= 0:
        return None
    repasse, _ = Repasse.objects.get_or_create(
        pedido=pedido,
        defaults={
            "instituicao": pedido.instituicao,
            "percentual": REPASSE_PERCENTUAL_PADRAO,
            "valor_base_centavos": pedido.valor_centavos,
            "valor_centavos": valor,
        },
    )
    return repasse
