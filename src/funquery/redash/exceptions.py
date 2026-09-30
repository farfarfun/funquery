"""Redash 查询领域异常。"""


class QueryJobError(RuntimeError):
    """Redash 查询任务失败或取消时抛出的异常。"""

    def __init__(self, job_id: int, status: int, detail: object = None) -> None:
        self.job_id = job_id
        self.status = status
        self.detail = detail
        super().__init__(f"Redash query job {job_id} status={status}: {detail or '无详细信息'}")
