import os
import requests
from typing import Optional
import json
import time
from dotenv import load_dotenv
load_dotenv()
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LLMService:
    @staticmethod
    def generate_adjustment_code(user_prompt: str, df_metadata: dict) -> Optional[str]:
        """Generates executable Python code for forecast adjustments."""
        hf_token = os.getenv('HF_TOKEN')
        
        # 1. FORCE the 32B model (as we know the 7B throws a 404)
        model_id = os.getenv('LLM_MODEL_ID', 'Qwen/Qwen2.5-Coder-32B-Instruct')
        
        if not hf_token:
            print("\n[LLM SERVICE] ERROR: HF_TOKEN missing")
            return None
            
        # 2. FIX: Put the model_id BACK into the URL path
        API_URL = "https://router.huggingface.co/featherless-ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}
       
        existing_adj = [c for c in df_metadata.keys() if "Adjustment" in str(c)]
        target_col = f"Adjustment {len(existing_adj) + 1}"
 
        dates = df_metadata.get('Date_Range', ['Unknown', 'Unknown'])
        forecast_start = dates[0]
        forecast_end = dates[1]
 
        system_content = (
            "You are a deterministic Python code generation engine. "
            "Generate ONLY executable Python code. No markdown, no backticks, no explanations, no comments. "
            f"VALID FORECAST HORIZON: {forecast_start} to {forecast_end}\n\n"
            "STRICT RULES:\n"
            "1. All DataFrame columns are lowercase. Use df['date'], df['target'], and df['forecast'].\n"
            "2. Modify the DataFrame 'df' in place. Apply ALL changes ONLY to the column named 'target'.\n"
            "3. Use df['actual_combined'] for historical context (mean, median, etc.).\n"
            "4. CRITICAL: You must ONLY modify rows where df['forecast'] is NOT NULL. "
            "Always use: df.loc[df['forecast'].notna() & (filters), 'target'] = ...\n"
            "5. NEVER use the tilde (~) operator with forecast.notna(). This would incorrectly target historical data.\n"
            "6. Do NOT wrap code in 'if-else' blocks for date checks. Use Rule 7 for refusals instead.\n"
            "7. IF the user's requested date or range is ENTIRELY outside the horizon "
            f"({forecast_start} to {forecast_end}), respond EXACTLY with: "
            "'REFUSAL: The requested date range is outside the forecast horizon.'\n"
            "8. IF the request is not a data adjustment, respond exactly with: "
            "'REFUSAL: I am an AI specialized in forecast adjustments.'\n"
            "9. If a location or SKU is mentioned, filter 'df' by 'location' or 'sku' respectively.\n"
            "10. Final Safety: End every script with df['target'] = df['target'].clip(lower=0)"
        )
        
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 500,
            "temperature": 0.0,
            "top_p": 0.9,
            "repetition_penalty": 1.1
        }
        
        print(f"\n[LLM SERVICE] Connecting to Endpoint for: \"{user_prompt}\"")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(API_URL, headers=headers, json=payload, timeout=60, verify=False)
                
                if response.status_code == 200:
                    result = response.json()
                    raw_text = result['choices'][0]['message']['content']
                    clean_code = LLMService._clean_response(raw_text)
                    
                    conversational_keywords = ['sorry', 'assist', 'cannot', 'help', 'request', 'poem', 'joke']
                    if "REFUSAL:" in clean_code or any(word in clean_code.lower() for word in conversational_keywords):
                        msg = clean_code.replace("REFUSAL:", "").strip()
                        return f"REFUSAL:{msg}"
                    
                    print(f"[LLM SERVICE] ✅ Execution Code Prepared for {target_col}:\n{clean_code}")
                    return clean_code
                
                elif response.status_code == 503:
                    # Expect this on the first try! The model is huge.
                    print(f"[LLM SERVICE] 503 Model is waking up. Waiting 15 seconds before retry... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(15)
                else:
                    print(f"[LLM SERVICE] API ERROR {response.status_code}: {response.text}")
                    return None
            except Exception as e:
                print(f"[LLM SERVICE] CONNECTION FAILED: {e}")
                time.sleep(5)
                
        return None

    @staticmethod
    def _clean_response(text: str) -> str:
        """Removes markdown fences and backticks."""
        if "```python" in text:
            text = text.split("```python")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return text.strip().replace("`", "")

    @staticmethod
    def generate_forecast_audit(audit_data: dict) -> Optional[str]:
        try:
            with open("forecast_audit_payload.json", "w") as f:
                json.dump(audit_data, f, indent=4)
        except Exception as e:
            print(f"Error saving audit JSON: {e}")

        hf_token = os.getenv('HF_TOKEN')
        model_id = os.getenv('LLM_MODEL_ID', 'Qwen/Qwen2.5-Coder-32B-Instruct')
        
        # 2. FIX: Put the model_id BACK into the URL path here too
        API_URL = "https://router.huggingface.co/featherless-ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {hf_token}", "Content-Type": "application/json"}

        role = audit_data.get('user_context', {}).get('role', 'Stakeholder')
        domain = audit_data.get('user_context', {}).get('domain', 'Retail')

        system_msg = (
            f"You are a Senior Forecasting Consultant specializing in the {domain} industry. "
            f"Your audience is a {role}. Provide an in-depth, technical yet accessible explanation "
            "of the forecast results based on the provided metadata. Analyze patterns, "
            "holiday impacts, and model reliability. Use professional formatting."
        )

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": f"Analyze the following forecast audit metadata: {json.dumps(audit_data)}"}
            ],
            "temperature": 0.4
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(API_URL, headers=headers, json=payload, timeout=90, verify=False)
                if response.status_code == 200:
                    return response.json()['choices'][0]['message']['content'].strip()
                elif response.status_code == 503:
                    print(f"[LLM SERVICE] 503 Audit Model waking up. Retrying in 15s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(15)
                else:
                    return f"Audit generation failed due to API error: {response.status_code}"
            except Exception:
                time.sleep(5)
                
        return "Audit generation failed. The model took too long to wake up. Please try again."