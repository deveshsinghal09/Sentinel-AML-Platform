"""Translate SDK outages to safe, actionable API errors without exposing data."""


def install_exception_handlers(app):
    from botocore.exceptions import BotoCoreError, ClientError
    from fastapi.responses import JSONResponse
    from api.services.aws.logging import event

    async def unavailable(request, exc):
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        event("aws_request_failed", error_type=type(exc).__name__, error_code=code)
        return JSONResponse(status_code=503, headers={"Retry-After": "2"}, content={
            "detail": "AWS storage is temporarily unavailable. Retry shortly; check CloudWatch if this persists."})

    app.add_exception_handler(BotoCoreError, unavailable)
    app.add_exception_handler(ClientError, unavailable)
