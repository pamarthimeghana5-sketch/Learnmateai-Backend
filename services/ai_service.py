import requests
from config import Config


def get_ai_response(conversation_history):
    """
    conversation_history: list of {"role": "user"|"assistant", "content": "..."}
    Returns the AI's reply text as a string.

    Calls Google Gemini's generateContent API (free tier available at
    https://aistudio.google.com/apikey). Put your key in .env as AI_API_KEY.
    """
    if not Config.AI_API_KEY:
        # Friendly fallback so the app still "works" during development
        # even before an API key is added.
        return ("AI service is not configured yet. Add AI_API_KEY in your "
                ".env file to get real answers here.")

    model = Config.AI_MODEL or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={Config.AI_API_KEY}"

    # Gemini uses "user" / "model" roles (not "assistant"), and wraps text in "parts"
    contents = []
    for msg in conversation_history:
        role = "model" if msg.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7},
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except requests.exceptions.RequestException as e:
        return f"Sorry, the AI service could not be reached right now. ({str(e)})"
    except (KeyError, IndexError):
        return "Sorry, the AI service returned an unexpected response."
