"""Ошибки служб согласований: код и русский текст (PLAN-014, CONTRACT-014)."""


class ApprovalError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
