"""
HuggingFace Connection Debugger  v5
=====================================
Home network confirmed. Focuses on:
  - Correct current HF Router URL format (updated Nov 2024+)
  - Wide scan of ALL Qwen coder models actually listed on HF
  - Handles cold-start 503 with a single retry
  - Prints the exact working URL + model to paste into llm_service.py

Usage:
    python hf_debug.py
"""

import os
import time
import requests
import urllib3
from dotenv import load_dotenv

load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HF_TOKEN   = os.getenv("HF_TOKEN", "")
VERIFY_SSL = False
TEST_MSG   = [{"role": "user", "content": "Reply with only the word OK"}]

HEADERS = {
    "Authorization": f"Bearer {HF_TOKEN}",
    "Content-Type": "application/json",
}

SEP  = "─" * 64
SEP2 = "═" * 64

def section(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")

# ─────────────────────────────────────────────────────────────
# All Qwen Coder models on HF hub, largest → smallest
# ─────────────────────────────────────────────────────────────
QWEN_MODELS = [
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "Qwen/Qwen2.5-Coder-14B-Instruct",
    "Qwen/Qwen2.5-Coder-7B-Instruct",
    "Qwen/Qwen2.5-Coder-3B-Instruct",
    "Qwen/Qwen2.5-Coder-1.5B-Instruct",
    "Qwen/Qwen2.5-Coder-0.5B-Instruct",
    # Qwen3 coder (newest family, released May 2025)
    "Qwen/Qwen3-30B-A3B",
    "Qwen/Qwen3-14B",
    "Qwen/Qwen3-8B",
    "Qwen/Qwen3-4B",
    "Qwen/Qwen3-1.7B",
    "Qwen/Qwen3-0.6B",
]

# ─────────────────────────────────────────────────────────────
# URL templates to try for each model
# HF keeps changing these — test all known patterns
# ─────────────────────────────────────────────────────────────
def url_templates(model_id):
    return [
        # Current recommended (as of early 2025)
        ("router/hf-inference",
         f"https://router.huggingface.co/hf-inference/models/{model_id}/v1/chat/completions"),
        # Featherless (specialises in serving large models free)
        ("router/featherless",
         f"https://router.huggingface.co/featherless-ai/v1/chat/completions"),
        # Hyperbolic (another HF partner)
        ("router/hyperbolic",
         f"https://router.huggingface.co/hyperbolic/v1/chat/completions"),
    ]


def call(url, model_id, retry_503=True):
    """POST to url, return (status_code, description, reply_text)."""
    payload = {
        "model": model_id,
        "messages": TEST_MSG,
        "max_tokens": 10,
        "temperature": 0.0,
    }
    try:
        r = requests.post(url, headers=HEADERS, json=payload, timeout=25, verify=VERIFY_SSL)
        code = r.status_code
        try:    body = r.json()
        except: body = {}

        if code == 200:
            reply = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            return code, "✅ 200 WORKS", reply

        elif code == 503:
            if retry_503:
                print(f"      ⏳ Cold start (503) — waiting 20s then retrying...")
                time.sleep(20)
                return call(url, model_id, retry_503=False)
            return code, "⏳ 503 cold (still loading after retry)", ""

        elif code == 400:
            err = body.get("error", "")
            if "not supported" in err.lower():
                return code, "❌ 400 not supported by this provider", ""
            return code, f"⚠️  400 {err[:60]}", ""

        elif code == 401:
            return code, "🔑 401 token rejected", ""
        elif code == 402:
            return code, "💳 402 billing needed (model IS available)", ""
        elif code == 403:
            return code, "🔒 403 provider not available for your account", ""
        elif code == 404:
            return code, "❌ 404 route not found", ""
        elif code == 410:
            return code, "🗑️  410 model deprecated by this provider", ""
        elif code == 429:
            return code, "⏳ 429 rate limited (token works, model works!)", ""
        else:
            return code, f"⚠️  {code} {str(body)[:60]}", ""

    except requests.exceptions.Timeout:
        return 0, "⏱️  timeout (25s)", ""
    except Exception as e:
        return 0, f"❌ exception: {str(e)[:60]}", ""


# ─────────────────────────────────────────────────────────────
# STEP 1 — Token check
# ─────────────────────────────────────────────────────────────
def check_token():
    section("STEP 1 · Token Validity")
    try:
        r = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            timeout=10, verify=VERIFY_SSL,
        )
        if r.status_code == 200:
            d = r.json()
            print(f"  ✅  Valid  |  user: {d.get('name')}  |  plan: {'PRO' if d.get('isPro') else 'FREE'}")
            # Check inference permission
            auth_info = d.get("auth", {}).get("accessToken", {})
            perms = auth_info.get("fineGrained", {}).get("global", [])
            has_inference = any("inference" in str(p).lower() for p in perms)
            if perms:
                print(f"  Permissions: {perms}")
                if has_inference:
                    print(f"  ✅  Inference permission detected")
                else:
                    print(f"  ⚠️   No inference permission found in token scopes!")
                    print(f"      Regenerate with 'Make calls to Inference Providers' checked.")
            return True
        else:
            print(f"  ❌  {r.status_code}: {r.text[:100]}")
            return False
    except Exception as e:
        print(f"  ❌  {e}")
        return False


# ─────────────────────────────────────────────────────────────
# STEP 2 — Scan models × URL templates
# ─────────────────────────────────────────────────────────────
def scan():
    section("STEP 2 · Scanning Qwen Models × Providers")
    print(f"  {len(QWEN_MODELS)} models × 3 URL patterns")
    print(f"  503s get one automatic 20s retry (cold start handling)\n")

    hits = []

    for model in QWEN_MODELS:
        short = model.split("/")[-1]
        print(f"  {short}")
        for label, url in url_templates(model):
            code, desc, reply = call(url, model)
            tag = f"    {label:<28}  {desc}"
            if reply:
                tag += f"  →  '{reply[:20]}'"
            print(tag)

            if code in (200, 402, 429, 503):
                hits.append({
                    "model"  : model,
                    "label"  : label,
                    "url"    : url,
                    "code"   : code,
                    "desc"   : desc,
                    "reply"  : reply,
                })
        print()

    return hits


# ─────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────
def summarise(hits):
    print(f"\n{SEP2}")
    print("  RESULTS")
    print(SEP2)

    if not hits:
        print("""
  ❌  Nothing worked.

  Most likely: your token is missing the inference permission scope.
  Fix:
    1. Go to https://huggingface.co/settings/tokens
    2. Delete current token
    3. Create new Fine-grained token with:
         User permissions → Inference → ✅ Make calls to Inference Providers
    4. Update HF_TOKEN in .env and re-run
""")
        return

    # Rank: 200 > 429 > 503 > 402
    rank = {200: 0, 429: 1, 503: 2, 402: 3}
    hits.sort(key=lambda h: (rank.get(h["code"], 9), QWEN_MODELS.index(h["model"])))

    print(f"\n  {'MODEL':<38} {'PROVIDER':<28} STATUS")
    print(f"  {'-'*38} {'-'*28} {'-'*20}")
    for h in hits:
        short = h["model"].split("/")[-1]
        print(f"  {short:<38} {h['label']:<28} {h['desc'][:30]}")

    best = hits[0]
    bmodel = best["model"]
    burl   = best["url"]

    print(f"\n{SEP2}")
    print("  PASTE THIS INTO YOUR PROJECT")
    print(SEP2)
    print(f"""
  ┌─ .env ──────────────────────────────────────────────────────
  │  LLM_MODEL_ID={bmodel}
  └──────────────────────────────────────────────────────────────

  ┌─ llm_service.py  (replace API_URL in BOTH methods) ─────────
  │  model_id = os.getenv('LLM_MODEL_ID', '{bmodel}')
  │  API_URL  = "{burl}"
  └──────────────────────────────────────────────────────────────
""")

    if best["code"] == 402:
        print("  ⚠️  402 means billing needs enabling:")
        print("     https://huggingface.co/settings/billing\n")
    elif best["code"] == 503:
        print("  ⏳  Model was still cold. Your retry logic in llm_service.py handles this.\n")

    print(SEP2 + "\n")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{SEP2}")
    print("  🔍  HuggingFace Debugger  v5  —  Qwen Model Scanner")
    print(f"  Token : {'SET ✓' if HF_TOKEN else 'MISSING ✗'}")
    print(SEP2)

    ok = check_token()
    if ok:
        hits = scan()
        summarise(hits)
    else:
        print("\n  Fix your token first, then re-run.")
        print("  https://huggingface.co/settings/tokens\n")