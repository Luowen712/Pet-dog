"""把FastAPI抛出的错误改造成统一外壳"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.resp import fail


def register_handlers(app: FastAPI) -> None:
    """异常处理器"""

    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, exc: HTTPException):

        detail = exc.detail
        if isinstance(detail, dict):
            code = int(detail.get("code", 40000))
            message = str(detail.get("message", "请求失败"))
        else:
            code = 40000
            message = str(detail) if detail else "请求失败"
        return JSONResponse(status_code=exc.status_code, content=fail(code, message))

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        """参数缺失或类型不对"""
        return JSONResponse(
            status_code=200, content=fail(40000, message="参数缺失或类型不对")
        )

    @app.exception_handler(Exception)
    async def on_exception(request: Request, exc: Exception):
        """其它异常或未捕获异常"""
        return JSONResponse(
            status_code=200, content=fail(50000, message="服务器内部错误")
        )
