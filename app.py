import os
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Callable, Any

from flask import Flask, request, jsonify, render_template

# Third-party AI SDKs
from openai import OpenAI  # OpenAI-compatible client (also used for xAI and DeepSeek)
import google.generativeai as genai


# -----------------------------------------------------------------------------
# Flask app setup
# -----------------------------------------------------------------------------
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_aggregator")


# -----------------------------------------------------------------------------
# Configuration and constants
# -----------------------------------------------------------------------------
REQUEST_TIMEOUT_SECONDS = int(os.getenv("AI_API_TIMEOUT_SECONDS", "25"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "2000"))
MAX_OUTPUT_CHARS = int(os.getenv("MAX_OUTPUT_CHARS", "4000"))

# Model names (override via env vars if desired)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-beta")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Human-friendly names for UI
MODEL_DISPLAY_NAMES: Dict[str, str] = {
    "openai": "ChatGPT (OpenAI)",
    "xai": "Grok (xAI)",
    "gemini": "Gemini (Google)",
    "deepseek": "DeepSeek",
}


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def sanitize_question(question: str) -> str:
    """Basic validation/sanitization for the user question.

    - Trim whitespace
    - Enforce a max length
    - Remove very long runs of whitespace/control characters
    """
    if question is None:
        return ""
    q = question.strip()
    if len(q) > MAX_QUESTION_CHARS:
        q = q[:MAX_QUESTION_CHARS]
    # Normalize whitespace (avoid odd control characters)
    q = " ".join(q.split())
    return q


def truncate_output(text: str) -> str:
    if text is None:
        return ""
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS] + "\n\n[truncated]"
    return text


def build_synthesis_prompt(original_question: str, initial_responses: Dict[str, str]) -> str:
    lines = [
        f"Original question: {original_question}",
        "",
        "Initial responses:",
    ]
    for key in ["openai", "xai", "gemini", "deepseek"]:
        model_title = MODEL_DISPLAY_NAMES.get(key, key)
        initial = initial_responses.get(key, "(no response)")
        lines.append(f"- {model_title}: {initial}")

    lines.extend([
        "",
        (
            "Based on these, provide a concise, improved final synthesized answer "
            "that combines the best insights and resolves any contradictions."
        ),
    ])
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Model caller functions
# -----------------------------------------------------------------------------
def call_openai_chat(prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY")

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=512,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return resp.choices[0].message.content.strip()


def call_xai_grok(prompt: str) -> str:
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing XAI_API_KEY")

    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    resp = client.chat.completions.create(
        model=XAI_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=512,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return resp.choices[0].message.content.strip()


def call_deepseek(prompt: str) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=512,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return resp.choices[0].message.content.strip()


def call_gemini(prompt: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    # Configure Google Generative AI SDK each call (safe and simple)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.3,
            "max_output_tokens": 512,
        },
    )
    # The SDK returns a rich object; .text gives a safe unified string
    return (response.text or "").strip()


# -----------------------------------------------------------------------------
# Orchestrators
# -----------------------------------------------------------------------------
def run_parallel_calls(prompt: str, callers: Dict[str, Callable[[str], str]]) -> Dict[str, str]:
    """Run model calls in parallel with robust error handling and timeouts."""
    results: Dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(callers)) as executor:
        future_to_key = {executor.submit(func, prompt): key for key, func in callers.items()}

        for future, key in list(future_to_key.items()):
            try:
                # Add a little extra beyond request timeout for Python scheduling
                value = future.result(timeout=REQUEST_TIMEOUT_SECONDS + 5)
                results[key] = truncate_output(value)
            except Exception as e:
                # Hide internals; log details server-side
                logger.exception("Error querying %s", key)
                results[key] = f"Error querying {MODEL_DISPLAY_NAMES.get(key, key)}: {str(e)[:200]}"

    return results


def get_initial_responses(question: str) -> Dict[str, str]:
    callers = {
        "openai": call_openai_chat,
        "xai": call_xai_grok,
        "gemini": call_gemini,
        "deepseek": call_deepseek,
    }
    return run_parallel_calls(question, callers)


def get_final_responses(original_question: str, initial_responses: Dict[str, str]) -> Dict[str, str]:
    synthesis = build_synthesis_prompt(original_question, initial_responses)
    callers = {
        "openai": call_openai_chat,
        "xai": call_xai_grok,
        "gemini": call_gemini,
        "deepseek": call_deepseek,
    }
    return run_parallel_calls(synthesis, callers)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index() -> Any:
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
def ask() -> Any:
    # Accept JSON or form, but prefer JSON
    payload: Dict[str, Any] = {}
    if request.is_json:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
    else:
        payload = request.form.to_dict() if request.form else {}

    question_raw = payload.get("question", "")
    question = sanitize_question(question_raw)

    if not question:
        return jsonify({
            "error": "Please provide a non-empty question.",
        }), 400

    # Orchestrate initial and final responses
    initial = get_initial_responses(question)
    final = get_final_responses(question, initial)

    # Choose a recommended response (default to OpenAI)
    recommended_key = "openai"

    return jsonify({
        "question": question,
        "initial": initial,
        "final": final,
        "recommended": recommended_key,
        "models": MODEL_DISPLAY_NAMES,
    })


# -----------------------------------------------------------------------------
# Entrypoint for local development
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
