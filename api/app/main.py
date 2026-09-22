from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Infinite Media Canvas")

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
