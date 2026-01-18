# test_sf.py 用于测试单个程序能否正确调用硅基流动的API
import os, requests

BASE = "https://api.deepseek.com"
MODEL = "deepseek-chat"
KEY = os.getenv("DS_API_KEY", "")

print("key prefix:", (KEY[:8] + "****") if KEY else "<EMPTY>")

payload = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user",   "content": "Say hello in one short sentence."}
    ],
    "temperature": 0.2,
}
r = requests.post(
    f"{BASE}/v1/chat/completions",
    json=payload,
    headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    timeout=30,
)
print("status:", r.status_code)
print(r.text)
