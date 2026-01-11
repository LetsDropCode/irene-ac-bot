from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """
You are a friendly but focused athletics club coach.
Tone:
- Encouraging
- Clear
- WhatsApp-friendly
- South African running culture
Rules:
- Never invent data
- Never override system decisions
- Keep replies under 4 lines
"""


def coach_reply(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


# ─────────────────────────────────────────────
# INTENT-BASED HELPERS (SAFE)
# ─────────────────────────────────────────────

def welcome_message():
    return coach_reply(
        "Welcome a runner to a club time trial and explain they need a TT code to continue."
    )


def code_accepted_message():
    return coach_reply(
        "Acknowledge the runner warmly and ask them to select a distance."
    )


def ask_time_message():
    return coach_reply(
        "Ask the runner politely to send their time."
    )


def submission_confirmed_message(distance, time):
    return coach_reply(
        f"Congratulate the runner for completing {distance} in {time}."
    )


def edit_closed_message():
    return coach_reply(
        "Explain politely that editing is closed for tonight."
    )