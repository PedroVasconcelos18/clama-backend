"""Repontamento das FKs de `Comentario` e `Reacao` (Story 4.4).

🔴 **É o ponto de não retorno do rollback do conteúdo.**

Depois desta migration, remover o rewrite devolve `/blog` ao Vike — mas as
páginas restauradas continuam encontrando os comentários, **porque a coluna FK
legada permanece preenchida em paralelo**. É isso, e só isso, que preserva a
reversibilidade.

Remover a coluna legada é a **Story 7.4**, depois do portão de validação da
7.1. Enquanto ela existir e estiver populada, o rollback é completo. Sem ela,
o rollback vira parcial: volta o conteúdo, some a interação.

**Falha explícita, nunca órfão.** Se houver comentário ou reação cujo post não
tem espelho, esta migration levanta com a lista dos registros. Uma migration
que passasse deixando linhas nulas produziria um sistema que parece funcionar e
perde vínculo em silêncio — o pior desfecho possível aqui.

⚠️ **Antes de rodar em produção:** backup verificado, e a checagem de duplicata
latente de `Reacao`. A `UniqueConstraint` paralela criada na Story 3.1 não
bloqueava as linhas legadas porque `post_espelho` era nulo (o Postgres trata
NULL como distinto). Depois deste backfill ela passa a valer para tudo — e se
houver duplicata nos dados, a migration falha aqui. A checagem está em
`_conferir_duplicatas_de_reacao` e roda **antes** de qualquer escrita.
"""

from django.db import migrations

# Quantos identificadores mostrar na mensagem de erro. O suficiente para
# começar a investigar sem transformar o traceback em despejo de banco.
LIMITE_DE_EXEMPLOS = 20


class BackfillIncompleto(Exception):
    """Levantada quando há linha sem espelho correspondente."""


def _conferir_duplicatas_de_reacao(apps, schema_editor):
    """Duplicata latente que só apareceria depois do backfill.

    Mesmo customer, mesmo post, mesmo tipo, em duas linhas: hoje passa, porque
    a constraint nova não alcança linhas com `post_espelho` nulo. Depois do
    backfill as duas passariam a ter o mesmo espelho e a constraint estouraria
    no meio da migration.
    """
    Reacao = apps.get_model("blog", "Reacao")

    vistos = {}
    duplicatas = []

    campos = ("id", "post_id", "customer_id", "tipo")
    for reacao_id, post_id, customer_id, tipo in Reacao.objects.filter(
        post__isnull=False, post_espelho__isnull=True
    ).values_list(*campos):
        chave = (post_id, customer_id, tipo)
        if chave in vistos:
            duplicatas.append((vistos[chave], reacao_id, chave))
        else:
            vistos[chave] = reacao_id

    if duplicatas:
        exemplos = "\n".join(
            f"  post={p} customer={c} tipo={t}: reações {a} e {b}"
            for a, b, (p, c, t) in duplicatas[:LIMITE_DE_EXEMPLOS]
        )
        raise BackfillIncompleto(
            f"{len(duplicatas)} duplicatas de Reação impediriam a "
            "UniqueConstraint depois do backfill.\n"
            "Resolva os dados antes de migrar — apagar a linha mais nova é "
            "normalmente o certo, mas é decisão, não automatismo.\n"
            f"{exemplos}"
        )


def repontar(apps, schema_editor):
    Comentario = apps.get_model("blog", "Comentario")
    Reacao = apps.get_model("blog", "Reacao")
    PostEspelho = apps.get_model("blog", "PostEspelho")

    _conferir_duplicatas_de_reacao(apps, schema_editor)

    # Mapeamento gravado pela exportação da Story 4.3.
    espelho_por_post = dict(
        PostEspelho.objects.filter(post_legado__isnull=False).values_list(
            "post_legado_id", "id"
        )
    )

    for modelo, nome in ((Comentario, "Comentario"), (Reacao, "Reacao")):
        # Só o que ainda não foi repontado — a migration é reexecutável em
        # ambiente de teste sem efeito acumulado.
        pendentes = modelo.objects.filter(post__isnull=False, post_espelho__isnull=True)

        sem_espelho = [
            (str(pk), str(post_id))
            for pk, post_id in pendentes.values_list("id", "post_id")
            if post_id not in espelho_por_post
        ]

        if sem_espelho:
            exemplos = "\n".join(
                f"  {nome} {pk} → Post {post_id}"
                for pk, post_id in sem_espelho[:LIMITE_DE_EXEMPLOS]
            )
            raise BackfillIncompleto(
                f"{len(sem_espelho)} registros de {nome} apontam para posts "
                "sem espelho. Rode `exportar_posts_para_wp` e confira o "
                "relatório de cobertura antes de migrar — deixá-los órfãos "
                "perderia o vínculo em silêncio.\n"
                f"{exemplos}"
            )

        # `update` em lote por post: o volume é o histórico inteiro do blog, e
        # iterar linha a linha faria uma query por comentário.
        for post_id, espelho_id in espelho_por_post.items():
            modelo.objects.filter(post_id=post_id, post_espelho__isnull=True).update(
                post_espelho_id=espelho_id
            )


def desrepontar(apps, schema_editor):
    """Reverso: limpa só o que este backfill preencheu.

    Comentário criado **depois** do cutover tem `post` nulo e `post_espelho`
    preenchido — esse não pode ser tocado, senão a reversão viola a
    `CheckConstraint` e apaga o vínculo do que nasceu no WordPress.
    """
    for nome in ("Comentario", "Reacao"):
        apps.get_model("blog", nome).objects.filter(post__isnull=False).update(
            post_espelho=None
        )


class Migration(migrations.Migration):
    dependencies = [
        ("blog", "0006_mapeamento_post_legado_no_espelho"),
    ]

    operations = [
        migrations.RunPython(repontar, desrepontar),
    ]
