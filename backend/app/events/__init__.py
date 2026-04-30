"""事件模块统一导出。"""
from app.events.outbox_publisher import OutboxPublisher

__all__ = ["OutboxPublisher"]