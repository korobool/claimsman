from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from apps.web import __version__
from apps.web.config import settings
from apps.web.logging_setup import configure_logging, logger
from apps.web.routers import (
    audit,
    claims,
    dev,
    domains,
    health as health_router,
    llm,
    schemas as schemas_router,
    system,
)

STATIC_APP_DIR = Path(__file__).parent / "static" / "app"
STATIC_APP_INDEX = STATIC_APP_DIR / "index.html"


class SPAStaticFiles(StaticFiles):
    """StaticFiles subclass that serves index.html as a fallback so the SPA
    router can handle deep links like /app/new or /app/claims/<id>."""

    async def get_response(self, path: str, scope: Scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("assets/"):
                return await super().get_response("index.html", scope)
            raise

PLACEHOLDER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Claimsman — frontend not built</title>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif;
           background:#0b0d10; color:#e6ebf1; margin:0; padding:48px;
           line-height:1.5; }
    code { background:#12161b; padding:2px 6px; border-radius:4px; }
    h1 { font-size:18px; margin:0 0 12px; }
    p  { color:#9aa4ae; max-width:640px; }
  </style>
</head>
<body>
  <h1>Claimsman backend is up, but the React SPA has not been built yet.</h1>
  <p>Run the frontend build to produce <code>apps/web/static/app/index.html</code>:</p>
  <p><code>npm --prefix apps/frontend ci &amp;&amp; npm --prefix apps/frontend run build</code></p>
  <p>Then reload this page.</p>
</body>
</html>
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    logger.info(
        "claimsman.startup",
        version=__version__,
        env=settings.env,
        static_app_exists=STATIC_APP_DIR.exists(),
        static_app_dir=str(STATIC_APP_DIR),
    )
    yield
    logger.info("claimsman.shutdown")


app = FastAPI(
    title="Claimsman",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.include_router(system.router, prefix="/api/v1")
app.include_router(claims.router, prefix="/api/v1")
app.include_router(domains.router, prefix="/api/v1")
app.include_router(schemas_router.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(health_router.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(dev.router, prefix="/api/v1")


@app.get("/healthz")
async def root_healthz() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/", include_in_schema=False)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/app/")


if STATIC_APP_INDEX.exists():
    app.mount("/app", SPAStaticFiles(directory=STATIC_APP_DIR, html=True), name="app")
else:
    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    @app.get("/app/{path:path}", include_in_schema=False)
    async def app_not_built(path: str = "") -> HTMLResponse:
        return HTMLResponse(content=PLACEHOLDER_HTML, status_code=503)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "apps.web.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    run()
