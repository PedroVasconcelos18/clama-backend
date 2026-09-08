"""
Relatório de repasse por instituição — prestação de contas ao parceiro.

**Por que lê o ledger e não o Pedido.** `Repasse` guarda snapshot de
`percentual` e `valor_base_centavos` no instante da confirmação do pagamento.
`Pedido.valor_centavos` é mutável depois disso — `marcar_como_gratuito()` zera
o campo (`orders/models.py:290`). Relatório que somasse o pedido entregaria
R$ 0,00 para doação que de fato entrou. O ledger é a fonte de verdade.

**Por que a data é a do repasse.** `Repasse.created_at` é o instante em que o
webhook do Mercado Pago confirmou o pagamento (`payments/api/webhooks.py:204`),
único ponto que cria a linha. `Pedido.created_at` é quando a pessoa preencheu o
formulário — pode cair no mês anterior e furar o fechamento.

**Por que o nome é abreviado por padrão.** A Política de Privacidade vigente
lista Mercado Pago e autoridades legais como únicos destinatários de dados
(`clama-frontend/src/pages/Privacidade.tsx:120`). `Identificacao.COMPLETO`
existe, mas exige atualizar a política e avisar no formulário antes de usar.
"""

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID

from django.utils import timezone

from clama.instituicoes.models import Instituicao, Repasse, RepasseStatus


class Identificacao(StrEnum):
    """Quanto de PII do doador entra no relatório entregue à instituição."""

    ABREVIADO = "abreviado"  # "Maria S." — padrão
    COMPLETO = "completo"  # "Maria Silva Santos" — exige ajuste na política
    ANONIMO = "anonimo"  # "#a3f2…8b1c" — só a referência do pedido


SEM_NOME = "(sem nome)"


def abreviar_nome(nome: str) -> str:
    """'Maria Silva Santos' -> 'Maria S.'; 'Maria' -> 'Maria'; '' -> '(sem nome)'."""
    partes = nome.split()
    if not partes:
        return SEM_NOME
    if len(partes) == 1:
        return partes[0]
    return f"{partes[0]} {partes[-1][0].upper()}."


def referencia_pedido(pedido_id: UUID) -> str:
    """Referência curta e estável do pedido, sem PII: '#a3f2…8b1c'."""
    hexa = pedido_id.hex
    return f"#{hexa[:4]}…{hexa[-4:]}"


@dataclass(frozen=True)
class LinhaRelatorio:
    """Uma doação direcionada à instituição.

    Os campos de auditoria só são preenchidos com `auditoria=True` — ficam
    `None` no relatório que vai pra instituição, pra que um bug de coluna não
    consiga vazar e-mail nem id de pagamento pra fora do Clama.
    """

    pedido_id: UUID
    referencia: str
    doador: str
    data: date
    valor_doacao_centavos: int
    percentual: int
    valor_repasse_centavos: int

    # --- auditoria interna (nunca sai pra instituição) ---
    email: str | None = None
    status_repasse: str | None = None
    transferido_em: date | None = None
    comprovante: str | None = None
    status_pedido: str | None = None
    provider_payment_id: str | None = None
    pedido_criado_em: date | None = None
    valor_pedido_atual_centavos: int | None = None

    @property
    def divergencia(self) -> str:
        """Sinaliza base do ledger != valor atual do pedido (ex.: convertido em gratuito)."""
        if self.valor_pedido_atual_centavos is None:
            return ""
        if self.valor_pedido_atual_centavos == self.valor_doacao_centavos:
            return ""
        return (
            f"pedido hoje vale {self.valor_pedido_atual_centavos} centavos, "
            f"ledger registrou {self.valor_doacao_centavos}"
        )


@dataclass(frozen=True)
class RelatorioRepasse:
    """Prestação de contas de um período fechado."""

    instituicao: Instituicao
    desde: date | None
    ate: date | None
    linhas: list[LinhaRelatorio]

    @property
    def total_doado_centavos(self) -> int:
        return sum(linha.valor_doacao_centavos for linha in self.linhas)

    @property
    def total_repasse_centavos(self) -> int:
        return sum(linha.valor_repasse_centavos for linha in self.linhas)

    @property
    def quantidade(self) -> int:
        return len(self.linhas)


def _inicio_do_dia(dia: date) -> datetime:
    return timezone.make_aware(datetime.combine(dia, time.min))


def _fim_do_dia(dia: date) -> datetime:
    """Fim inclusivo: `--ate 31/08` cobre até 23:59:59.999999 do dia 31."""
    return timezone.make_aware(datetime.combine(dia, time.max))


def gerar_relatorio(
    instituicao: Instituicao,
    desde: date | None = None,
    ate: date | None = None,
    identificacao: Identificacao = Identificacao.ABREVIADO,
    auditoria: bool = False,
    somente_pendentes: bool = False,
) -> RelatorioRepasse:
    """Monta o relatório de repasse da instituição no período (bordas inclusivas).

    `auditoria=True` acrescenta os campos de conciliação (e-mail, id do
    pagamento no gateway, status). Uso interno — ver docstring do módulo.
    """
    # Conciliar exige identificar o doador sem ambiguidade — nome abreviado
    # não serve. A regra vive aqui, não na CLI, pra valer em qualquer chamador.
    if auditoria:
        identificacao = Identificacao.COMPLETO

    repasses = Repasse.objects.filter(instituicao=instituicao).select_related("pedido")
    if somente_pendentes:
        repasses = repasses.filter(status=RepasseStatus.REGISTRADO)
    if desde is not None:
        repasses = repasses.filter(created_at__gte=_inicio_do_dia(desde))
    if ate is not None:
        repasses = repasses.filter(created_at__lte=_fim_do_dia(ate))

    linhas = [
        _montar_linha(repasse, identificacao, auditoria)
        for repasse in repasses.order_by("created_at")
    ]
    return RelatorioRepasse(
        instituicao=instituicao, desde=desde, ate=ate, linhas=linhas
    )


def _montar_linha(
    repasse: Repasse, identificacao: Identificacao, auditoria: bool = False
) -> LinhaRelatorio:
    referencia = referencia_pedido(repasse.pedido_id)
    match identificacao:
        case Identificacao.ANONIMO:
            doador = referencia
        case Identificacao.COMPLETO:
            # Descriptografa a coluna; só acontece quando pedido explicitamente.
            doador = repasse.pedido.nome or SEM_NOME
        case _:
            doador = abreviar_nome(repasse.pedido.nome)
    extras = {}
    if auditoria:
        pedido = repasse.pedido
        extras = {
            "email": pedido.email or "",
            "status_repasse": repasse.status,
            "transferido_em": (
                timezone.localtime(repasse.transferido_em).date()
                if repasse.transferido_em
                else None
            ),
            "comprovante": repasse.comprovante or "",
            "status_pedido": pedido.status,
            "provider_payment_id": pedido.provider_payment_id or "",
            "pedido_criado_em": timezone.localtime(pedido.created_at).date(),
            "valor_pedido_atual_centavos": pedido.valor_centavos,
        }
    return LinhaRelatorio(
        pedido_id=repasse.pedido_id,
        referencia=referencia,
        doador=doador,
        data=timezone.localtime(repasse.created_at).date(),
        valor_doacao_centavos=repasse.valor_base_centavos,
        percentual=repasse.percentual,
        valor_repasse_centavos=repasse.valor_centavos,
        **extras,
    )
