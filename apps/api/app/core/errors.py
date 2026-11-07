from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, extra: dict | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}
        super().__init__(message)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    body = {"code": exc.code, "message": exc.message, **exc.extra}
    return JSONResponse(status_code=exc.status_code, content=body)


def http_error(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})
