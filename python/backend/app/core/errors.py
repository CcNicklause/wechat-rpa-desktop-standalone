from fastapi import HTTPException, status


class AppError(HTTPException):
    def __init__(self, code: str, message: str, http_status: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=http_status, detail={'code': code, 'message': message})


def not_found(message: str = '资源不存在') -> AppError:
    return AppError('NOT_FOUND', message, status.HTTP_404_NOT_FOUND)
