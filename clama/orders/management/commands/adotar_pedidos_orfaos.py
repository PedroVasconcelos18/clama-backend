"""Liga pedidos órfãos ao usuário dono do e-mail.

**O buraco que este comando fecha.** `Pedido.user` só é preenchido por
`provisionar_conta_do_doador`, e ele é chamado de um lugar só: o webhook de
pagamento (`clama/payments/api/webhooks.py`). Pedido gratuito custa R$ 0,00,
não gera cobrança e portanto **nunca gera webhook** — então nunca passa pelo
provisionamento e fica com `user` nulo para sempre.

Nada adota pedido órfão depois: nem o login, nem o cadastro. O efeito é o
pedido existir, aparecer no admin com o e-mail certo, e sumir da conta de quem
o fez.

A `CustomerPedidosListView` já cobre a listagem casando por e-mail, mas isso é
remendo de leitura: o dado continua errado, e todo lugar que faz join por
`user` (relatório, dashboard, `related_name="pedidos"`) continua sem enxergar.
Este comando corrige o dado.

⚠️ **Rode com `--dry-run` primeiro.** Vincular por e-mail é decisão de produto:
quem controla a conta passa a ver pedidos feitos anonimamente com aquele
e-mail. É a mesma regra que o provisionamento aplica quando roda — mas aqui
ela é aplicada em lote e retroativamente, então merece ser olhada antes.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from clama.freemium.hashing import normalizar_email
from clama.orders.models import Pedido


class Command(BaseCommand):
    help = "Vincula pedidos sem user ao usuário dono do e-mail do pedido."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria vinculado, sem gravar.",
        )
        parser.add_argument(
            "--email",
            default="",
            help="Restringe a um e-mail — útil para conferir um caso antes do lote.",
        )

    def handle(self, *args, **opcoes):
        seco = opcoes["dry_run"]
        so_email = normalizar_email(opcoes["email"] or "")

        # 🔴 `Pedido.email` e EncryptedEmailField: o banco guarda cifra, entao
        # NAO da para filtrar nem comparar por e-mail em SQL. `email__iexact`
        # devolve zero silenciosamente mesmo com o valor igual — nao levanta
        # erro, so nao casa.
        #
        # E por isso que o vinculo tem que ser feito linha a linha, em Python,
        # onde a descriptografia acontece no acesso ao atributo. Tambem e por
        # isso que a listagem NAO pode resolver isso por query: o unico
        # caminho e o dado estar certo.
        orfaos = Pedido.objects.filter(user__isnull=True)

        total = orfaos.count()
        self.stdout.write(f"Pedidos órfãos com e-mail: {total}")

        if not total:
            return

        UserModel = get_user_model()
        # Um mapa de e-mail normalizado → user evita uma query por pedido.
        usuarios = {
            normalizar_email(u.email): u
            for u in UserModel.objects.exclude(email="").only("id", "email")
        }

        vinculaveis, sem_conta = [], 0

        for pedido in orfaos.only("id", "email"):
            email = normalizar_email(pedido.email or "")  # descriptografa aqui
            if not email:
                sem_conta += 1
                continue
            if so_email and email != so_email:
                continue

            user = usuarios.get(email)
            if user is None:
                sem_conta += 1
                continue
            vinculaveis.append((pedido, user))

        self.stdout.write(f"  com conta correspondente: {len(vinculaveis)}")
        self.stdout.write(f"  sem conta (ficam órfãos):  {sem_conta}")

        for pedido, user in vinculaveis[:20]:
            self.stdout.write(f"    {pedido.id} · {pedido.email} → user {user.id}")
        if len(vinculaveis) > 20:
            self.stdout.write(f"    … e mais {len(vinculaveis) - 20}")

        if seco:
            self.stdout.write(self.style.WARNING("\n--dry-run: nada foi gravado."))
            return

        # Em transação: ou vincula tudo, ou nada. Um backfill parcial deixaria
        # o estado pela metade sem ninguém saber onde parou.
        with transaction.atomic():
            for pedido, user in vinculaveis:
                pedido.user = user
                pedido.save(update_fields=["user"])

        self.stdout.write(
            self.style.SUCCESS(f"\n{len(vinculaveis)} pedido(s) vinculado(s).")
        )
