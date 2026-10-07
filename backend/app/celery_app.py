from celery import Celery
from celery.signals import worker_process_init

from app.config import settings

celery_app = Celery("antirisk", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    task_acks_late=True,  # задача не теряется, если воркер упал посреди обработки
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # тяжёлые задачи: не набирать очередь в один процесс
    task_soft_time_limit=60 * 30,
    task_time_limit=60 * 35,
    broker_connection_retry_on_startup=True,
    timezone="Europe/Moscow",
)


@worker_process_init.connect
def _reset_db_pool(**_) -> None:
    # Пул соединений не должен наследоваться от родительского процесса prefork
    from app.db import engine

    engine.dispose(close=False)
