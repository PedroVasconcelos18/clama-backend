"""Signal handlers do app blog.

Anti-pattern (arch): logica complexa em signal handler. Aqui apenas
disparamos tasks Celery — a logica vive nas tasks, que sao testaveis
isoladamente e retryable.
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Comentario, Post, PostStatus
from .moderation import eh_comentario_suspeito
from .tasks import notificar_indexnow, regenerar_blog_ssg


@receiver(post_save, sender=Post)
def on_post_saved(sender, instance, created, **kwargs):
    """Dispara regen SSG e (se publicado) notifica IndexNow.

    Despublicar tambem dispara regen — o site SSG precisa rebuild
    pra remover o post das listagens.
    """
    post_id = str(instance.id)
    regenerar_blog_ssg.delay(post_id)
    if instance.status == PostStatus.PUBLICADO:
        notificar_indexnow.delay(post_id)


@receiver(pre_save, sender=Comentario)
def flag_comentario_suspeito(sender, instance, **kwargs):
    """Atualiza `is_suspeito` antes de salvar, com base na lista de palavras
    suspeitas (vide `moderation.eh_comentario_suspeito`).

    Sempre re-avalia: edits que limparam o conteúdo ofensivo deflag automatico;
    se conteúdo novo bate, flag de novo.
    """
    instance.is_suspeito = eh_comentario_suspeito(instance.conteudo or "")
