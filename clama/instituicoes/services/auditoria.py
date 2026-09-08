"""
Conciliação do ledger de repasse — acha o que o relatório não consegue ver.

**Por que existe.** `relatorio_repasse` percorre a tabela `Repasse`. Isso o torna
estruturalmente cego ao pior caso: pedido pago, com instituição escolhida, que
nunca gerou linha no ledger. O dinheiro entrou e o relatório jura que não.

`registrar_repasse` é chamado de um lugar só — o webhook do Mercado Pago
(`payments/api/webhooks.py:204`). Webhook que não chega, chega fora de ordem ou
estoura antes do commit deixa exatamente esse rastro.

**Cinco achados que este módulo procura:**

- `orfao`: pedido pós-pagamento com instituição e sem `Repasse` — dinheiro devido
  que não aparece em relatório nenhum.
- `divergencia_de_base`: `valor_base_centavos` do ledger != valor atual do pedido.
- `calculo_errado`: `valor_centavos` != `valor_base * percentual // 100`.
- `pedido_nao_pago`: existe `Repasse` para pedido que ainda aguarda pagamento —
  repasse cobrável sem dinheiro correspondente.
- `sem_id_de_pagamento`: `Repasse` cujo pedido não tem `provider_payment_id`,
  logo não há como conciliar com o extrato do Mercado Pago.
"""

from dataclasses import dataclass
from enum import StrEnum

from clama.instituicoes.models import Instituicao, Repasse
from clama.orders.models import Pedido, PedidoStatus

# Tudo que não é "ainda esperando" conta como pós-pagamento. ERRO entra de
# propósito: o pagamento pode ter passado e a falha ser da geração da oração.
# Auditoria erra pro lado de reportar demais, não de menos.
STATUS_POS_PAGAMENTO = frozenset(
    status
    for status in PedidoStatus.values
    if status
    not in {
        PedidoStatus.AGUARDANDO_PAGAMENTO,
        PedidoStatus.AGUARDANDO_CONFIRMACAO_EMAIL,
    }
)


class TipoAchado(StrEnum):
    ORFAO = "orfao"
    DIVERGENCIA_DE_BASE = "divergencia_de_base"
    CALCULO_ERRADO = "calculo_errado"
    PEDIDO_NAO_PAGO = "pedido_nao_pago"
    SEM_ID_DE_PAGAMENTO = "sem_id_de_pagamento"


GRAVIDADE = {
    TipoAchado.ORFAO: "CRÍTICO",
    TipoAchado.PEDIDO_NAO_PAGO: "CRÍTICO",
    TipoAchado.CALCULO_ERRADO: "CRÍTICO",
    TipoAchado.DIVERGENCIA_DE_BASE: "ATENÇÃO",
    TipoAchado.SEM_ID_DE_PAGAMENTO: "ATENÇÃO",
}


@dataclass(frozen=True)
class Achado:
    tipo: TipoAchado
    instituicao: str
    pedido_id: str
    detalhe: str
    valor_em_jogo_centavos: int

    @property
    def gravidade(self) -> str:
        return GRAVIDADE[self.tipo]


def auditar(instituicao: Instituicao | None = None) -> list[Achado]:
    """Roda as cinco checagens. `instituicao=None` audita todas."""
    achados: list[Achado] = []
    achados.extend(_orfaos(instituicao))
    achados.extend(_problemas_no_ledger(instituicao))
    return sorted(achados, key=lambda a: (a.gravidade != "CRÍTICO", a.tipo))


def _orfaos(instituicao: Instituicao | None) -> list[Achado]:
    pedidos = Pedido.objects.filter(
        instituicao__isnull=False,
        eh_gratuito=False,
        status__in=STATUS_POS_PAGAMENTO,
        valor_centavos__gt=0,
    ).select_related("instituicao")
    if instituicao is not None:
        pedidos = pedidos.filter(instituicao=instituicao)

    com_repasse = set(Repasse.objects.values_list("pedido_id", flat=True))
    return [
        Achado(
            tipo=TipoAchado.ORFAO,
            instituicao=pedido.instituicao.nome,
            pedido_id=str(pedido.id),
            detalhe=(
                f"pedido {pedido.status} de {pedido.valor_centavos} centavos "
                f"sem linha no ledger (repasse devido: "
                f"{pedido.valor_centavos * 20 // 100} centavos)"
            ),
            valor_em_jogo_centavos=pedido.valor_centavos * 20 // 100,
        )
        for pedido in pedidos
        if pedido.id not in com_repasse
    ]


def _problemas_no_ledger(instituicao: Instituicao | None) -> list[Achado]:
    repasses = Repasse.objects.select_related("pedido", "instituicao")
    if instituicao is not None:
        repasses = repasses.filter(instituicao=instituicao)

    achados: list[Achado] = []
    for repasse in repasses:
        pedido = repasse.pedido
        nome = repasse.instituicao.nome
        pedido_id = str(repasse.pedido_id)

        esperado = repasse.valor_base_centavos * repasse.percentual // 100
        if repasse.valor_centavos != esperado:
            achados.append(
                Achado(
                    tipo=TipoAchado.CALCULO_ERRADO,
                    instituicao=nome,
                    pedido_id=pedido_id,
                    detalhe=(
                        f"ledger diz {repasse.valor_centavos} centavos; "
                        f"{repasse.percentual}% de {repasse.valor_base_centavos} "
                        f"dá {esperado}"
                    ),
                    valor_em_jogo_centavos=abs(repasse.valor_centavos - esperado),
                )
            )

        if pedido.status not in STATUS_POS_PAGAMENTO:
            achados.append(
                Achado(
                    tipo=TipoAchado.PEDIDO_NAO_PAGO,
                    instituicao=nome,
                    pedido_id=pedido_id,
                    detalhe=f"repasse registrado mas pedido está {pedido.status}",
                    valor_em_jogo_centavos=repasse.valor_centavos,
                )
            )

        if pedido.valor_centavos != repasse.valor_base_centavos:
            achados.append(
                Achado(
                    tipo=TipoAchado.DIVERGENCIA_DE_BASE,
                    instituicao=nome,
                    pedido_id=pedido_id,
                    detalhe=(
                        f"ledger registrou base {repasse.valor_base_centavos}; "
                        f"pedido hoje vale {pedido.valor_centavos} centavos"
                    ),
                    valor_em_jogo_centavos=0,
                )
            )

        if not pedido.provider_payment_id:
            achados.append(
                Achado(
                    tipo=TipoAchado.SEM_ID_DE_PAGAMENTO,
                    instituicao=nome,
                    pedido_id=pedido_id,
                    detalhe="sem provider_payment_id — não concilia com o extrato do MP",
                    valor_em_jogo_centavos=0,
                )
            )
    return achados
