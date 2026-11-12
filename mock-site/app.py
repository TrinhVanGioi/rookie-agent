from fastapi import FastAPI

app = FastAPI(title="Rookie Agent Mock Site")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "mock-site"}
