import os
from openai import OpenAI

def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


def coach_reply(prompt: str) -> str:
    client = get_client()
    if not client:
        # 🔁 Graceful fallback (NO CRASH)
        return (
            "Nice effort tonight 👏\n\n"
            "Keep showing up consistently — that’s where the gains come from 💪"
        )

    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a friendly, motivating running club coach. "
                        "Keep replies short, positive, and practical."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=120,
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        # 🛡️ Absolute safety net
        print("⚠️ OpenAI error:", e)
        return (
            "Solid session 💥\n"
            "Consistency beats perfection — see you at the next one!"
        )