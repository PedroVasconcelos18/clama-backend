"""Signal handlers do app blog.

Anti-pattern (arch): logica complexa em signal handler. Aqui apenas
disparamos tasks Celery — a logica vive nas tasks, que sao testaveis
isoladamente e retryable.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Post, PostStatus
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
