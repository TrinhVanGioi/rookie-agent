from fastapi import FastAPI

app = FastAPI(title="Rookie Agent Server")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "server"}
