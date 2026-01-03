# app/main.py
from fastapi import FastAPI
from app.webhook import router as webhook_router
#from app.config import ENV

app = FastAPI()

app.include_router(webhook_router)

#@app.get("/")
#def read_root():
#    return {
#        "message": "Irene AC Bot is running!",
#        "env": ENV
#    }