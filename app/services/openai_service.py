# app/services/openai_service.py
import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def coach_reply(prompt: str) -> str:
    """
    Short, friendly, motivating coaching feedback.
    Uses GPT-5.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly Irene AC running club coach. "
                        "Be encouraging, concise, and practical. "
                        "No emojis unless celebratory."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            max_tokens=120,
            temperature=0.5,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        # Fail soft — NEVER crash webhook
        return "Great effort! Consistency beats everything — see you at the next session 💪"