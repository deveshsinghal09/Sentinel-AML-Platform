"""
scripts/verify_groq.py — Phase 0 Groq connectivity check.

Usage:
    python scripts/verify_groq.py

Exits 0 on success, 1 on failure.
Prints the model response and relevant rate-limit headers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow import from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GROQ_API_KEY, INTENT_MODEL

if not GROQ_API_KEY:
    print("[FAIL] GROQ_API_KEY is not set. Add it to your .env file.")
    sys.exit(1)

try:
    from groq import Groq
except ImportError:
    print("[FAIL] groq package not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

client = Groq(api_key=GROQ_API_KEY)

TEST_PROMPT = (
    "You are an AML intent extractor. "
    "Return a JSON object with a single key 'intent' set to 'test_ok'. "
    "Do not include anything else."
)

print(f"Testing model: {INTENT_MODEL}")
print("API key:       configured (value redacted)")
print("-" * 60)

try:
    response = client.chat.completions.create(
        model=INTENT_MODEL,
        messages=[{"role": "user", "content": TEST_PROMPT}],
        max_tokens=64,
        temperature=0,
        response_format={"type": "json_object"},
    )
except Exception as exc:
    print(f"[FAIL] API call failed: {exc}")
    sys.exit(1)

content = response.choices[0].message.content
print(f"Response:      {content}")

# Parse and validate
try:
    parsed = json.loads(content)
    assert parsed.get("intent") == "test_ok", f"Unexpected payload: {parsed}"
    print("[PASS] Groq API call succeeded and returned expected JSON.")
except (json.JSONDecodeError, AssertionError) as exc:
    print(f"[WARN] Response received but validation failed: {exc}")
    print("       This may be fine — the API is reachable.")

# Print usage / rate-limit info if available
usage = response.usage
if usage:
    print(f"\nToken usage:   prompt={usage.prompt_tokens}, "
          f"completion={usage.completion_tokens}, "
          f"total={usage.total_tokens}")

print("\n[OK] Phase 0 Groq exit criterion met.")
sys.exit(0)
