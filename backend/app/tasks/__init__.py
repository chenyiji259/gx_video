"""异步任务模块统一导出。"""
from app.tasks.dispatcher import TaskDispatcher, task_dispatcher

# 必须从 worker 模块直接导入单例，因为 handler 注册代码在 worker.py 末尾执行。
# 若在此处 task_worker = TaskWorker()，新实例无任何 handler，导致所有 job 报 no_handler。
from app.tasks.worker import TaskWorker, task_worker  # noqa: F401  # re-export

__all__ = [
    "TaskDispatcher",
    "TaskWorker",
    "task_dispatcher",
    "task_worker",
]
