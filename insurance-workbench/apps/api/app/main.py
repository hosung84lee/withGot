from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.coverage import CoverageRequest, CoverageResponse, coverage_candidates

app = FastAPI(title="보험금 검증 워크벤치", version="0.1.0")
CANDIDATES_PATH = "/api/coverage/candidates"


class PrivacyBoundary:
    """Bound JSON reads before validation, without logging or reflecting input."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def no_cache(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
                )
            await send(message)

        path = scope["path"]
        if path.rstrip("/") == CANDIDATES_PATH:
            if path != CANDIDATES_PATH:
                return await JSONResponse({"error": "not_found"}, 404)(scope, receive, no_cache)
            headers = dict(scope["headers"])
            content_type = headers.get(b"content-type", b"").split(b";")[0].strip()
            if scope.get("query_string") or headers.get(b"content-encoding"):
                return await JSONResponse({"error": "invalid_request"}, 400)(
                    scope, receive, no_cache
                )
            if scope["method"] == "POST" and content_type != b"application/json":
                return await JSONResponse({"error": "json_required"}, 415)(scope, receive, no_cache)
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > 32_768:
                    return await JSONResponse({"error": "request_too_large"}, 413)(
                        scope, receive, no_cache
                    )
                body.extend(chunk)
                if not message.get("more_body", False):
                    break

            delivered = False

            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await self.app(scope, bounded_receive, no_cache)
        return await self.app(scope, receive, no_cache)


app.add_middleware(PrivacyBoundary)


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, _error: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "invalid_request"})


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.post(CANDIDATES_PATH, response_model=CoverageResponse)
def candidates(request: CoverageRequest) -> CoverageResponse:
    return coverage_candidates(request)
