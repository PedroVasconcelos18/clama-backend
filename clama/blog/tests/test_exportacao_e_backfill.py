"""Exportação, mapeamento e repontamento (Epic 4).

O que estes testes protegem: nada se perde na travessia. Slug, data, status e
vínculo de comentário — cada um tem um jeito próprio de sumir em silêncio.
"""

from datetime import UTC, datetime
from io import StringIO
from unittest.mock import Mock, patch

import pytest
import requests
from django.core.management import call_command

from clama.blog.models import (
    Comentario,
    PostEspelho,
    PostStatus,
    Reacao,
    ReacaoTipo,
)
from clama.blog.tests.factories import (
    BlogCustomerFactory,
    ComentarioFactory,
    PostFactory,
    ReacaoFactory,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def com_wordpress(settings):
    settings.WORDPRESS_API_URL = "https://wp-teste.clama.me"
    settings.WORDPRESS_API_USER = "clama-django-sync"
    settings.WORDPRESS_API_APP_PASSWORD = "chave"


def resposta_wp(wp_id=201, slug="post-1", status="publish"):
    resposta = Mock(spec=requests.Response)
    resposta.status_code = 201
    resposta.json.return_value = {
        "id": wp_id,
        "slug": slug,
        "status": status,
        "link": f"https://clama.me/blog/{slug}",
    }
    resposta.raise_for_status.return_value = None
    return resposta


def exportar(**opcoes):
    saida = StringIO()
    call_command("exportar_posts_para_wp", stdout=saida, stderr=saida, **opcoes)
    return saida.getvalue()


class TestExportacao:
    """Story 4.1."""

    def test_cria_post_no_wordpress_e_grava_o_mapeamento(self, com_wordpress):
        post = PostFactory(slug="post-1", status=PostStatus.PUBLICADO)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        espelho = PostEspelho.objects.get(wp_post_id=201)
        assert espelho.post_legado_id == post.id
        assert espelho.slug == "post-1"

    def test_preserva_slug_data_e_status(self, com_wordpress):
        # AC3, AC4 e AC5. Slug perdido quebra as URLs indexadas; data perdida
        # embaralha arquivo e feed.
        publicado_em = datetime(2025, 3, 14, 9, 30, tzinfo=UTC)
        PostFactory(
            slug="oracao-da-manha",
            status=PostStatus.PUBLICADO,
            data_publicacao=publicado_em,
        )

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp(slug="oracao-da-manha")
            exportar()

        enviado = envio.call_args.kwargs["json"]
        assert enviado["slug"] == "oracao-da-manha"
        assert enviado["status"] == "publish"
        assert enviado["date_gmt"] == publicado_em.isoformat()

    def test_rascunho_vira_draft(self, com_wordpress):
        PostFactory(slug="rascunho-1", status=PostStatus.RASCUNHO)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp(slug="rascunho-1", status="draft")
            exportar()

        assert envio.call_args.kwargs["json"]["status"] == "draft"

    def test_historia_ilustrativa_atravessa(self, com_wordpress):
        # O aviso do CDC art. 37 é exigência legal; a migração não pode
        # apagá-lo por omissão.
        PostFactory(slug="post-1", historia_ilustrativa=True)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        meta = envio.call_args.kwargs["json"].get("meta") or {}
        assert meta.get("clama_historia_ilustrativa") is True

    def test_rodar_duas_vezes_produz_o_mesmo_estado(self, com_wordpress):
        # AC2, e é a propriedade que permite refinar contra staging sem medo.
        PostFactory(slug="post-1", status=PostStatus.PUBLICADO)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()
            exportar()

        assert PostEspelho.objects.count() == 1

    def test_a_segunda_execucao_atualiza_pelo_id(self, com_wordpress):
        # Sem passar o `wp_post_id`, a REST API criaria um post novo a cada
        # execução — e o slug duplicado viraria `post-1-2`.
        PostFactory(slug="post-1")

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()
            exportar()

        primeiro, segundo = envio.call_args_list
        assert primeiro.args[0].endswith("/wp/v2/posts")
        assert segundo.args[0].endswith("/wp/v2/posts/201")

    def test_falha_parcial_nao_e_destrutiva_e_converge(self, com_wordpress):
        # AC6. O primeiro post exporta, o segundo falha; a re-execução
        # completa sem desfazer nada.
        PostFactory(slug="post-a", status=PostStatus.PUBLICADO)
        PostFactory(slug="post-b", status=PostStatus.PUBLICADO)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.side_effect = [
                resposta_wp(201, "post-a"),
                requests.Timeout("caiu"),
                requests.Timeout("caiu"),
                requests.Timeout("caiu"),
            ]
            with patch("clama.core.retry.time.sleep"):
                saida = exportar()

        assert PostEspelho.objects.count() == 1
        assert "post-b" in saida

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.side_effect = [
                resposta_wp(201, "post-a"),
                resposta_wp(202, "post-b"),
            ]
            exportar()

        assert PostEspelho.objects.count() == 2

    def test_o_que_falhou_e_reportado_nominalmente(self, com_wordpress):
        # AC7. "1 falhou" manda alguém procurar do zero.
        PostFactory(slug="post-problematico", status=PostStatus.PUBLICADO)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.side_effect = requests.Timeout("caiu")
            with patch("clama.core.retry.time.sleep"):
                saida = exportar()

        assert "post-problematico" in saida

    def test_dry_run_nao_toca_em_nada(self, com_wordpress):
        PostFactory(slug="post-1")

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            saida = exportar(dry_run=True)

        envio.assert_not_called()
        assert PostEspelho.objects.count() == 0
        assert "dry-run" in saida

    def test_a_exportacao_nao_salva_o_post(self, com_wordpress):
        # ⚠️ `Post.save()` re-sanitiza `conteudo_html` a cada gravação. Um
        # script que salvasse o Post alteraria o conteúdo que está tentando
        # preservar.
        post = PostFactory(slug="post-1")
        antes = post.updated_at

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        post.refresh_from_db()
        assert post.updated_at == antes


class TestCoberturaDoMapeamento:
    """Story 4.3."""

    def test_relata_100_por_cento_quando_tudo_migrou(self, com_wordpress):
        PostFactory(slug="post-1")

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            saida = exportar()

        assert "100%" in saida

    def test_lista_com_motivo_quem_ficou_de_fora(self, com_wordpress):
        # AC3: a ausência tem que ser **decidida**, não descoberta na hora do
        # backfill.
        PostFactory(slug="post-migrado", status=PostStatus.PUBLICADO)
        PostFactory(slug="rascunho-nao-migrado", status=PostStatus.RASCUNHO)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp(slug="post-migrado")
            saida = exportar(somente_publicados=True)

        assert "rascunho-nao-migrado" in saida
        assert "fora do filtro" in saida

    def test_o_mapeamento_converge_em_vez_de_acumular(self, com_wordpress):
        # AC4.
        post = PostFactory(slug="post-1")

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            for _ in range(3):
                exportar()

        assert PostEspelho.objects.filter(post_legado=post).count() == 1


class TestRepontamento:
    """Story 4.4 — a de maior risco do épico."""

    def _migrar(self):
        """Roda a função de backfill da 0007.

        Chamo a função direto em vez de montar o `MigrationExecutor`: o estado
        de modelo entre a 0006 e o atual é o mesmo para os campos que ela
        toca, e o executor exigiria reconstruir o histórico inteiro só para
        obter um `apps` equivalente.
        """
        import importlib

        from django.apps import apps as apps_reais
        from django.db import connection

        # O módulo começa com dígito, então não dá para usar `from ... import`.
        modulo = importlib.import_module(
            "clama.blog.migrations.0007_repontar_comentarios_e_reacoes"
        )
        modulo.repontar(apps_reais, connection.schema_editor())

    def test_reponta_comentarios_e_reacoes(self, com_wordpress):
        # AC1.
        post = PostFactory(slug="post-1", status=PostStatus.PUBLICADO)
        comentario = ComentarioFactory(post=post)
        reacao = ReacaoFactory(post=post)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        self._migrar()

        comentario.refresh_from_db()
        reacao.refresh_from_db()
        espelho = PostEspelho.objects.get(wp_post_id=201)
        assert comentario.post_espelho_id == espelho.id
        assert reacao.post_espelho_id == espelho.id

    def test_a_coluna_legada_continua_preenchida(self, com_wordpress):
        # AC4, e é **o que preserva a reversibilidade**. Enquanto ela existir
        # e estiver populada, o rollback é completo; sem ela, volta o
        # conteúdo e some a interação.
        post = PostFactory(slug="post-1")
        comentario = ComentarioFactory(post=post)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        self._migrar()

        comentario.refresh_from_db()
        assert comentario.post_id == post.id
        assert comentario.post_espelho_id is not None

    def test_falha_explicitamente_com_comentario_sem_espelho(self):
        # AC3, e é regra dura. Uma migration que passasse deixando linhas
        # nulas produziria um sistema que parece funcionar e perde vínculo em
        # silêncio.
        post = PostFactory(slug="post-sem-espelho")
        comentario = ComentarioFactory(post=post)

        with pytest.raises(Exception) as erro:
            self._migrar()

        mensagem = str(erro.value)
        assert "sem espelho" in mensagem
        # Com o registro identificado, não só contado.
        assert str(comentario.id) in mensagem

    def test_detecta_duplicata_latente_de_reacao_antes_de_escrever(self):
        # A `UniqueConstraint` paralela da Story 3.1 não alcançava linhas com
        # `post_espelho` nulo (o Postgres trata NULL como distinto). Depois do
        # backfill ela passa a valer para tudo — e uma duplicata nos dados
        # estouraria no meio da migration, com metade das linhas repontadas.
        #
        # Testo a checagem direto, com um `apps` de mentira: criar a duplicata
        # de verdade exigiria derrubar a constraint com ALTER TABLE, e o
        # Postgres recusa isso dentro da transação de teste ("pending trigger
        # events"). O que importa aqui é a lógica de detecção.
        import importlib
        from unittest.mock import MagicMock

        modulo = importlib.import_module(
            "clama.blog.migrations.0007_repontar_comentarios_e_reacoes"
        )

        duplicadas = [
            ("r1", "p1", "c1", "like"),
            ("r2", "p1", "c1", "like"),  # mesma tripla
            ("r3", "p2", "c1", "like"),
        ]
        apps_falso = MagicMock()
        (
            apps_falso.get_model.return_value.objects.filter.return_value.values_list.return_value
        ) = duplicadas

        with pytest.raises(Exception) as erro:
            modulo._conferir_duplicatas_de_reacao(apps_falso, None)

        mensagem = str(erro.value)
        assert "duplicata" in mensagem.lower()
        # Nomeia os registros, não só conta.
        assert "r1" in mensagem and "r2" in mensagem
        # E não acusa a que é legítima.
        assert "r3" not in mensagem

    def test_e_reexecutavel_sem_efeito_acumulado(self, com_wordpress):
        post = PostFactory(slug="post-1")
        ComentarioFactory(post=post)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        self._migrar()
        self._migrar()

        assert Comentario.objects.count() == 1
        assert Comentario.objects.get().post_espelho is not None

    def test_a_constraint_nova_vale_depois_do_backfill(self, com_wordpress):
        # AC7. Antes do backfill ela não alcançava as linhas legadas; depois,
        # alcança.
        from django.db import IntegrityError, transaction

        post = PostFactory(slug="post-1")
        customer = BlogCustomerFactory()
        ReacaoFactory(post=post, customer=customer, tipo=ReacaoTipo.LIKE)

        with patch("clama.blog.services.wordpress_client.requests.post") as envio:
            envio.return_value = resposta_wp()
            exportar()

        self._migrar()

        espelho = PostEspelho.objects.get(wp_post_id=201)
        with pytest.raises(IntegrityError), transaction.atomic():
            Reacao.objects.create(
                post=None,
                post_espelho=espelho,
                customer=customer,
                tipo=ReacaoTipo.LIKE,
            )


class TestInventarioDeImagens:
    """Story 4.2 — a premissa do épico está errada e isto verifica o que sobra."""

    def _inventariar(self, **opcoes):
        saida = StringIO()
        call_command(
            "inventariar_imagens_do_blog", stdout=saida, stderr=saida, **opcoes
        )
        return saida.getvalue()

    def test_sem_imagem_nao_ha_nada_a_migrar(self):
        PostFactory(slug="post-1", conteudo_html="<p>Sem imagem.</p>")

        assert "Nenhuma imagem" in self._inventariar()

    def test_inventaria_capa_e_corpo_por_host(self):
        # AC1: de onde cada imagem é servida hoje.
        PostFactory(
            slug="post-1",
            imagem_capa_url="https://images.exemplo.com/capa.jpg",
            conteudo_html='<p>a</p><img src="https://cdn.outro.com/foto.png" alt="">',
        )

        saida = self._inventariar()

        assert "images.exemplo.com" in saida
        assert "cdn.outro.com" in saida

    def test_avisa_sobre_host_fora_do_dominio(self):
        # É o risco **real** que sobrou depois que a premissa da mídia caiu:
        # link podre externo quebra o post sem aviso.
        PostFactory(
            slug="post-1",
            conteudo_html='<img src="https://conta-pessoal.imgur.com/x.png" alt="">',
        )

        assert "fora do domínio do Clama" in self._inventariar()

    def test_reporta_nominalmente_a_imagem_que_falha(self):
        # AC4 e AC5: nome, e migração considerada incompleta.
        PostFactory(
            slug="post-quebrado",
            conteudo_html='<img src="https://exemplo.com/sumiu.png" alt="">',
        )

        with patch("requests.head") as head:
            resposta = Mock(spec=requests.Response)
            resposta.status_code = 404
            head.return_value = resposta
            with patch("requests.get") as get:
                get.return_value = resposta
                saida = self._inventariar(verificar=True)

        assert "post-quebrado" in saida
        assert "sumiu.png" in saida
        assert "INCOMPLETA" in saida

    def test_todas_200_libera_o_cutover(self):
        PostFactory(
            slug="post-1",
            conteudo_html='<img src="https://exemplo.com/ok.png" alt="">',
        )

        with patch("requests.head") as head:
            resposta = Mock(spec=requests.Response)
            resposta.status_code = 200
            head.return_value = resposta
            saida = self._inventariar(verificar=True)

        assert "não está bloqueado por imagem" in saida
