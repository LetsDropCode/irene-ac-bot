# app/services/code_generator.py
import random
import string

SAFE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

def generate_event_code(length=4):
    return "".join(random.choice(SAFE_CHARS) for _ in range(length))