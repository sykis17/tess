from fastapi import FastAPI

from app.api.health import router as health_router
from app.api import ws_router

app = FastAPI(title="TESS Engine API")
app.include_router(health_router)
app.include_router(ws_router)


@app.get("/")
async def read_root():
    return {"status": "TESS Engine is running and awaiting instructions."}
