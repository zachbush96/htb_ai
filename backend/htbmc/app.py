from fastapi import FastAPI

app = FastAPI(title="HTB Mission Control", version="0.1.0")


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "htb-mission-control"}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "healthy"}
