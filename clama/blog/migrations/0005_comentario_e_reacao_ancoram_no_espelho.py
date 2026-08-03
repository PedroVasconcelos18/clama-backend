"""Comentário e reação podem ancorar só no espelho (Story 3.10).

**Por que a FK legada vira nullable.** A Story 3.1 instruía não mexer nas FKs
legadas. O que aquela instrução protege é o `on_delete=CASCADE`, e ele continua
intacto — o que muda é só a obrigatoriedade.

Sem essa mudança a Story 3.10 é inimplementável: um post criado no WordPress
depois do cutover não tem linha em `blog_post`, e um `NOT NULL` ali impediria
qualquer comentário nele. Entre Epic 6 (cutover) e Epic 7 (remoção do modelo
`Post`) existe exatamente essa janela.

Relaxar `NOT NULL` é operação aditiva: nenhuma linha existente é lida ou
alterada, e nada que já funcionava passa a falhar. As duas `CheckConstraint`
garantem que pelo menos uma âncora esteja preenchida — comentário pendurado em
nada seria pior que o problema original.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("blog", "0004_espelho_de_posts_do_wordpress"),
    ]

    operations = [
        migrations.AlterField(
            model_name="comentario",
            name="post",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="comentarios",
                to="blog.post",
            ),
        ),
        migrations.AlterField(
            model_name="reacao",
            name="post",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reacoes",
                to="blog.post",
            ),
        ),
        migrations.AddConstraint(
            model_name="comentario",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("post__isnull", False),
                    ("post_espelho__isnull", False),
                    _connector="OR",
                ),
                name="ck_blog_comentario_tem_post",
            ),
        ),
        migrations.AddConstraint(
            model_name="reacao",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("post__isnull", False),
                    ("post_espelho__isnull", False),
                    _connector="OR",
                ),
                name="ck_blog_reacao_tem_post",
            ),
        ),
    ]
