"""Exclusão e mudança de slug preservam o vínculo (Story 3.4).

Risco **R14** em uma frase: sem `PROTECT` e sem a regra de nunca apagar linha,
apagar um post no admin do WordPress apagaria comentários e os IPs sob
retenção de 6 meses do Marco Civil — perda de dado com consequência legal,
acionada por um clique num sistema de terceiros.
"""

import pytest
from django.db.models import ProtectedError

from clama.blog.models import (
    Comentario,
    PostEspelho,
    PostEspelhoStatus,
    Reacao,
    RemocaoDeEspelhoProibida,
)
from clama.blog.tasks import sincronizar_post_espelho
from clama.blog.tests.factories import (
    ComentarioFactory,
    PostEspelhoFactory,
    PostFactory,
    ReacaoFactory,
)
from clama.payments.models import WebhookEvento, WebhookProvider

pytestmark = pytest.mark.django_db


def evento(tipo: str, **payload) -> WebhookEvento:
    base = {
        "wp_post_id": "31",
        "slug": "post-original",
        "titulo": "Post original",
        "status": "publish",
        "url": "https://clama.me/blog/post-original",
    }
    base.update(payload)
    registro, _ = WebhookEvento.objects.try_register(
        provider=WebhookProvider.WORDPRESS,
        external_event_id=f"{tipo}-{base['slug']}-{base['status']}",
        event_type=tipo,
        payload=base,
    )
    return registro


class TestExclusaoNoWordPress:
    def test_post_apagado_muda_status_e_nao_remove_linha(self):
        # AC1. É a regra que fecha dois riscos de uma vez — exclusão no
        # WordPress e reconciliação com o WordPress indisponível são a mesma
        # classe de problema vista de dois ângulos.
        sincronizar_post_espelho(str(evento("post_publicado").id))
        assert PostEspelho.objects.get(wp_post_id=31).status == (
            PostEspelhoStatus.PUBLICADO
        )

        sincronizar_post_espelho(str(evento("post_removido").id))

        espelho = PostEspelho.objects.get(wp_post_id=31)
        assert espelho.status == PostEspelhoStatus.LIXEIRA
        assert PostEspelho.objects.count() == 1

    def test_comentarios_e_ips_sobrevivem_a_exclusao(self):
        # AC3. O caminho completo: o comentário existe, o post some do
        # WordPress, e o comentário — com o IP encriptado — continua lá.
        sincronizar_post_espelho(str(evento("post_publicado").id))
        espelho = PostEspelho.objects.get(wp_post_id=31)
        comentario = ComentarioFactory(post_espelho=espelho, ip_address="203.0.113.7")

        sincronizar_post_espelho(str(evento("post_removido").id))

        comentario.refresh_from_db()
        assert Comentario.objects.count() == 1
        assert comentario.ip_address == "203.0.113.7"
        assert comentario.post_espelho_id == espelho.id

    def test_a_lixeira_nao_aceita_mais_interacao(self):
        sincronizar_post_espelho(str(evento("post_publicado").id))
        assert PostEspelho.objects.get(wp_post_id=31).aceita_interacao is True

        sincronizar_post_espelho(str(evento("post_removido").id))

        assert PostEspelho.objects.get(wp_post_id=31).aceita_interacao is False


class TestRemocaoDeLinhaEInvariante:
    """AC7 — invariante do modelo, não convenção."""

    def test_delete_de_instancia_levanta(self):
        espelho = PostEspelhoFactory()

        with pytest.raises(RemocaoDeEspelhoProibida):
            espelho.delete()

        assert PostEspelho.objects.filter(pk=espelho.pk).exists()

    def test_delete_de_queryset_levanta(self):
        # Bloquear só a instância deixaria passar
        # `PostEspelho.objects.filter(...).delete()` — que é justamente o
        # caminho que um script de limpeza usaria.
        PostEspelhoFactory()

        with pytest.raises(RemocaoDeEspelhoProibida):
            PostEspelho.objects.all().delete()

        assert PostEspelho.objects.count() == 1

    def test_delete_de_queryset_filtrado_tambem_levanta(self):
        PostEspelhoFactory(status=PostEspelhoStatus.LIXEIRA)

        with pytest.raises(RemocaoDeEspelhoProibida):
            PostEspelho.objects.filter(status=PostEspelhoStatus.LIXEIRA).delete()

        assert PostEspelho.objects.count() == 1

    def test_espelho_sem_comentario_tambem_e_protegido(self):
        # Este é o caso que só o guarda do modelo pega: sem comentário, o
        # `PROTECT` do banco não teria nada a proteger e a linha sumiria,
        # deixando espelho e WordPress divergentes sem sinal nenhum.
        espelho = PostEspelhoFactory()

        with pytest.raises(RemocaoDeEspelhoProibida):
            espelho.delete()

        assert PostEspelho.objects.count() == 1

    def test_a_escotilha_existe_e_e_a_unica_saida(self):
        # Um espelho criado por engano (id de teste, ambiente trocado) precisa
        # de alguma saída. O nome feio é de propósito.
        espelho = PostEspelhoFactory()

        espelho._remover_de_verdade()

        assert PostEspelho.objects.count() == 0

    def test_nem_a_escotilha_fura_o_protect_do_banco(self):
        espelho = PostEspelhoFactory()
        ComentarioFactory(post_espelho=espelho)

        with pytest.raises(ProtectedError):
            espelho._remover_de_verdade()

        assert Comentario.objects.count() == 1


class TestMudancaDeSlug:
    def test_slug_e_url_sao_atualizados(self):
        # AC4. Sem isso a URL indexada vira 404 e o painel de moderação passa
        # a linkar para endereço morto — o mesmo fato visto do leitor e do
        # operador.
        sincronizar_post_espelho(str(evento("post_publicado").id))

        sincronizar_post_espelho(
            str(
                evento(
                    "post_atualizado",
                    slug="post-renomeado",
                    url="https://clama.me/blog/post-renomeado",
                ).id
            )
        )

        espelho = PostEspelho.objects.get(wp_post_id=31)
        assert espelho.slug == "post-renomeado"
        assert espelho.url == "https://clama.me/blog/post-renomeado"

    def test_a_mudanca_de_slug_nao_cria_linha_nova(self):
        # A identidade é `wp_post_id`, não o slug. Se fosse o slug, renomear
        # criaria um segundo espelho e os comentários ficariam no antigo.
        sincronizar_post_espelho(str(evento("post_publicado").id))
        sincronizar_post_espelho(str(evento("post_atualizado", slug="outro-slug").id))

        assert PostEspelho.objects.count() == 1

    def test_os_comentarios_seguem_o_post_renomeado(self):
        # AC5. O painel de moderação atravessa a FK para pegar slug e título;
        # com o espelho atualizado, o link continua vivo sem tocar em
        # `Comentario`.
        sincronizar_post_espelho(str(evento("post_publicado").id))
        espelho = PostEspelho.objects.get(wp_post_id=31)
        comentario = ComentarioFactory(post_espelho=espelho)

        sincronizar_post_espelho(
            str(
                evento(
                    "post_atualizado",
                    slug="post-renomeado",
                    url="https://clama.me/blog/post-renomeado",
                ).id
            )
        )

        comentario.refresh_from_db()
        assert comentario.post_espelho.slug == "post-renomeado"
        assert comentario.post_espelho.url.endswith("post-renomeado")

    def test_reacoes_tambem_seguem(self):
        sincronizar_post_espelho(str(evento("post_publicado").id))
        espelho = PostEspelho.objects.get(wp_post_id=31)
        ReacaoFactory(post=PostFactory(), post_espelho=espelho)

        sincronizar_post_espelho(
            str(evento("post_atualizado", slug="post-renomeado").id)
        )

        assert Reacao.objects.get().post_espelho.slug == "post-renomeado"
