# app/config.py
from dotenv import load_dotenv
import os

load_dotenv()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
ENV = os.getenv("ENV", "development")

ADMIN_NUMBERS = {
    "27722125094", #Lindsay
    "27738870757", #Jacqueline
    "27829370733", #Wynand
    "27818513864", #Johan
    "27828827067", #Janine
}