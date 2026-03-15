import asyncio
import httpx
import uuid
import json
import sys
import os

BASE_URL = "http://localhost:8080/api/v1"

# 隔离代理干扰
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
if "http_proxy" in os.environ: del os.environ["http_proxy"]
if "https_proxy" in os.environ: del os.environ["https_proxy"]

async def test_sessions_flow():
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("--- Step 1: List novels ---")
        try:
            resp = await client.get(f"{BASE_URL}/novels")
            resp.raise_for_status()
            novels = resp.json()
            if not novels["novels"]:
                print("No novels found. Please upload one first.")
                return
            novel_id = novels["novels"][0]["collection_name"]
            print(f"Testing with novel: {novel_id}")
        except Exception as e:
            print(f"Error in Step 1: {e}")
            return

        print("--- Step 2: Check chapters ---")
        try:
            resp = await client.get(f"{BASE_URL}/sessions/{novel_id}/chapters")
            resp.raise_for_status()
            chapters = resp.json()
            print(f"Found {len(chapters)} chapters in original storyline.")
        except Exception as e:
            print(f"Error in Step 2: {e}")
            # Continue anyway

        print("--- Step 3: Create session ---")
        try:
            user_id = f"test_user_{uuid.uuid4().hex[:6]}"
            session_payload = {
                "novel_id": novel_id,
                "user_id": user_id,
                "session_name": "我的平行宇宙"
            }
            resp = await client.post(f"{BASE_URL}/sessions", json=session_payload)
            resp.raise_for_status()
            new_session = resp.json()
            session_id = new_session["session_id"]
            print(f"Created session: {session_id}")
        except Exception as e:
            print(f"Error in Step 3: {e}")
            return

        print("--- Step 4: Chat interact ---")
        try:
            chat_payload = {
                "session_id": session_id,
                "novel_id": novel_id,
                "message": "我要去酒馆喝一杯。"
            }
            resp = await client.post(f"{BASE_URL}/chat/interact", json=chat_payload)
            resp.raise_for_status()
            chat_resp = resp.json()
            print(f"AI response: {chat_resp['story_text'][:50]}...")
        except Exception as e:
            print(f"Error in Step 4: {e}")

        print("--- Step 5: List sessions ---")
        try:
            resp = await client.get(f"{BASE_URL}/sessions/{novel_id}")
            resp.raise_for_status()
            all_sessions = resp.json()
            print(f"Total sessions for novel: {len(all_sessions)}")
        except Exception as e:
            print(f"Error in Step 5: {e}")

    print("--- Testing Complete ---")

if __name__ == "__main__":
    asyncio.run(test_sessions_flow())
