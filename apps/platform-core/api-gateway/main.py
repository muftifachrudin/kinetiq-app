from fastapi import FastAPI

app = FastAPI(title="Kinetiq API Gateway")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
