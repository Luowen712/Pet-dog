"""把FastAPI抛出的错误改造成统一外壳"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.resp import fail

logger = logging.getLogger(__name__)



def register_handlers(app: FastAPI) -> None:
    """异常处理器"""

    @app.exception_handler(HTTPException)
    async def on_http_error(request: Request, exc: HTTPException):
        """把 HTTPException 转成统一响应外壳，并按需透出 reason、retry_after。"""
        detail = exc.detail
        headers: dict[str, str] = {}
        if isinstance(detail, dict):
            code = int(detail.get("code", 40000))
            message = str(detail.get("message", "请求失败"))
            body = fail(code, message)
            # 契约 06§2：错误可加 reason / retry_after，前端不得解析 message。
            # 限流（42900）靠 retry_after 告诉客户端该等多久。
            if detail.get("retry_after") is not None:
                body["retry_after"] = detail["retry_after"]
                headers["Retry-After"] = str(detail["retry_after"])
            if detail.get("reason") is not None:
                body["reason"] = detail["reason"]
        else:
            code = 40000
            message = str(detail) if detail else "请求失败"
            body = fail(code, message)
        return JSONResponse(status_code=exc.status_code, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        """参数缺失或类型不对"""
        return JSONResponse(
            status_code=200, content=fail(40000, message="参数缺失或类型不对")
        )

    @app.exception_handler(Exception)
    async def on_exception(request: Request, exc: Exception):
        """其它异常或未捕获异常：记录堆栈并按 06:19 返回 HTTP 500 + 50000。"""
        logger.exception("未捕获异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content=fail(50000, message="服务器内部错误")
        )
