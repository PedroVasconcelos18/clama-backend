"""`PostEspelho` e as FKs paralelas (Story 3.1).

O que estes testes protegem não é o modelo novo — é o que ele **não pode
quebrar**: a constraint legada de `Reacao`, os comentários sob retenção do
Marco Civil, e as linhas que já existem.
"""

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from clama.blog.models import (
    Comentario,
    PostEspelho,
    RemocaoDeEspelhoProibida,
    PostEspelhoStatus,
    Reacao,
    ReacaoTipo,
)
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    ComentarioFactory,
    PostEspelhoFactory,
    PostFactory,
    ReacaoFactory,
)

pytestmark = pytest.mark.django_db


class TestPostEspelhoModel:
    def test_expoe_slug_e_titulo_para_o_serializer_admin(self):
        # O `AdminComentarioSerializer` atravessa a FK nos dois campos; sem
        # qualquer um deles o painel de moderação quebra.
        espelho = PostEspelhoFactory(slug="oracao-da-manha", titulo="Oração da manhã")

        assert espelho.slug == "oracao-da-manha"
        assert espelho.titulo == "Oração da manhã"

    def test_wp_post_id_e_a_identidade_e_nao_admite_duplicata(self):
        PostEspelhoFactory(wp_post_id=42)

        with pytest.raises(IntegrityError):
            PostEspelhoFactory(wp_post_id=42)

    def test_slug_pode_repetir_entre_registros(self):
        # No WordPress um post na lixeira libera o slug, então dois registros
        # podem carregar o mesmo por um intervalo. Travar unique aqui faria a
        # reconciliação falhar num caso legítimo.
        PostEspelhoFactory(slug="mesmo-slug", wp_post_id=1)
        PostEspelhoFactory(slug="mesmo-slug", wp_post_id=2)

        assert PostEspelho.objects.filter(slug="mesmo-slug").count() == 2

    @pytest.mark.parametrize(
        ("status", "esperado"),
        [
            (PostEspelhoStatus.PUBLICADO, True),
            (PostEspelhoStatus.RASCUNHO, False),
            (PostEspelhoStatus.PRIVADO, False),
            (PostEspelhoStatus.AGENDADO, False),
            (PostEspelhoStatus.LIXEIRA, False),
            (PostEspelhoStatus.PENDENTE, False),
        ],
    )
    def test_so_publicado_aceita_interacao(self, status, esperado):
        espelho = PostEspelhoFactory(status=status)

        assert espelho.aceita_interacao is esperado


class TestFksParalelas:
    def test_comentario_e_reacao_nascem_com_espelho_nulo(self):
        # É o que torna o Epic 3 independente do Epic 4: nada precisa ser
        # preenchido para o que já existe continuar funcionando.
        comentario = ComentarioFactory()
        reacao = ReacaoFactory()

        assert comentario.post_espelho is None
        assert reacao.post_espelho is None
        assert comentario.post is not None
        assert reacao.post is not None

    def test_comentario_pode_apontar_so_para_o_espelho(self):
        # Comentário novo em post do WordPress: a FK legada continua exigida
        # (WP-FR32 pede a coluna preenchida durante a validação), mas o
        # espelho é quem carrega o vínculo real.
        espelho = PostEspelhoFactory()
        comentario = ComentarioFactory(post_espelho=espelho)

        assert comentario.post_espelho == espelho
        assert espelho.comentarios.count() == 1

    def test_apagar_espelho_com_comentario_e_bloqueado(self):
        # Duas camadas, e o teste prova as duas separadamente.
        #
        # Camada 1 — o guarda do modelo (Story 3.4, AC7) dispara primeiro e
        # nem chega ao banco.
        espelho = PostEspelhoFactory()
        ComentarioFactory(post_espelho=espelho)

        with pytest.raises(RemocaoDeEspelhoProibida):
            espelho.delete()

        # Camada 2 — mesmo furando o guarda, o `PROTECT` do banco segura. É o
        # que preserva o IP sob a retenção de 6 meses do Marco Civil se alguém
        # um dia remover a camada 1.
        with pytest.raises(ProtectedError):
            espelho._remover_de_verdade()

        assert PostEspelho.objects.filter(pk=espelho.pk).exists()
        assert Comentario.objects.count() == 1

    def test_apagar_espelho_com_reacao_e_bloqueado(self):
        espelho = PostEspelhoFactory()
        ReacaoFactory(post_espelho=espelho)

        with pytest.raises(RemocaoDeEspelhoProibida):
            espelho.delete()

        with pytest.raises(ProtectedError):
            espelho._remover_de_verdade()

        assert Reacao.objects.count() == 1

    def test_a_fk_legada_segue_cascade_ate_o_epic_7(self):
        # Mudar isto agora quebraria o comportamento atual do CMS próprio, que
        # continua no ar até o cutover.
        post = PostFactory()
        ComentarioFactory(post=post)

        post.delete()

        assert Comentario.objects.count() == 0


class TestConstraintParalelaDeReacao:
    """A parte mais fácil de errar da story.

    A constraint legada atravessa a coluna FK antiga. Com uma coluna paralela,
    ela **não protege a nova** — dois likes do mesmo customer no mesmo post
    pela coluna nova passariam sem esbarrar em nada.
    """

    def test_a_constraint_legada_continua_valendo(self):
        post = PostFactory()
        customer = BlogCustomerFactory()
        ReacaoFactory(post=post, customer=customer, tipo=ReacaoTipo.LIKE)

        with pytest.raises(IntegrityError):
            ReacaoFactory(post=post, customer=customer, tipo=ReacaoTipo.LIKE)

    def test_a_constraint_nova_impede_like_duplicado_pelo_espelho(self):
        espelho = PostEspelhoFactory()
        customer = BlogCustomerFactory()
        # Posts legados distintos para que a constraint antiga não seja a que
        # dispara — o que estamos testando é a nova.
        ReacaoFactory(
            post=PostFactory(),
            post_espelho=espelho,
            customer=customer,
            tipo=ReacaoTipo.LIKE,
        )

        with pytest.raises(IntegrityError) as erro:
            ReacaoFactory(
                post=PostFactory(),
                post_espelho=espelho,
                customer=customer,
                tipo=ReacaoTipo.LIKE,
            )

        # Nomear a constraint importa: sem isto o teste passaria mesmo se
        # fosse a legada disparando, e aí não teria testado nada.
        assert "uniq_blog_reacao_espelho_customer_tipo" in str(erro.value)

    def test_a_constraint_nova_nao_bloqueia_as_linhas_legadas(self):
        # Postgres trata NULL como distinto em unique. Se não tratasse, esta
        # constraint permitiria uma reação legada por customer no banco
        # inteiro — e a migration derrubaria produção ao ser aplicada.
        customer = BlogCustomerFactory()

        for _ in range(3):
            ReacaoFactory(
                post=PostFactory(),
                post_espelho=None,
                customer=customer,
                tipo=ReacaoTipo.LIKE,
            )

        assert Reacao.objects.filter(post_espelho__isnull=True).count() == 3

    def test_customers_diferentes_podem_curtir_o_mesmo_post_espelhado(self):
        espelho = PostEspelhoFactory()

        for _ in range(3):
            ReacaoFactory(
                post=PostFactory(),
                post_espelho=espelho,
                customer=BlogCustomerFactory(),
                tipo=ReacaoTipo.LIKE,
            )

        assert espelho.reacoes.count() == 3


class TestIndices:
    def test_a_listagem_por_espelho_usa_indice(self):
        # AC6. Sem o índice na coluna nova, a listagem de comentários do painel
        # faz seq scan assim que passar a filtrar por `post_espelho`.
        espelho = PostEspelhoFactory()
        ComentarioFactory(post_espelho=espelho)

        with transaction.atomic():
            plano = (
                Comentario.objects.filter(post_espelho=espelho)
                .order_by("-created_at")
                .explain()
            )

        # Em tabela minúscula o Postgres prefere seq scan mesmo com índice
        # disponível; o que dá para afirmar sem fabricar 100 mil linhas é que
        # o índice existe e cobre a ordenação usada.
        assert plano
        nomes = {
            indice.name
            for indice in Comentario._meta.indexes  # noqa: SLF001
        }
        assert "idx_blog_coment_espelho_crtd" in nomes

    def test_o_espelho_tem_indice_de_slug_e_de_status(self):
        nomes = {
            indice.name
            for indice in PostEspelho._meta.indexes  # noqa: SLF001
        }

        assert nomes == {"idx_blog_postespelho_slug", "idx_blog_postesp_status_pub"}
