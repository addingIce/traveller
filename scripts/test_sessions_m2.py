import asyncio
import httpx
import uuid
import json
import time
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
            start_chapter_id = chapters[0]["id"] if chapters else None
            session_payload = {
                "novel_id": novel_id,
                "user_id": user_id,
                "session_name": "我的平行宇宙",
                "start_chapter_id": start_chapter_id
            }
            resp = await client.post(f"{BASE_URL}/sessions", json=session_payload)
            resp.raise_for_status()
            new_session = resp.json()
            session_id = new_session["session_id"]
            print(f"Created session: {session_id}")
        except Exception as e:
            print(f"Error in Step 3: {e}")
            return

        print("--- Step 4: Chat interact (single) ---")
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

        print("--- Step 4.1: 50-turn stability check ---")
        failures = 0
        latencies = []
        for i in range(50):
            msg = f"第{i+1}轮：我继续探索当前场景。"
            payload = {
                "session_id": session_id,
                "novel_id": novel_id,
                "message": msg
            }
            start = time.perf_counter()
            try:
                resp = await client.post(f"{BASE_URL}/chat/interact", json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not data.get("story_text"):
                    failures += 1
                    print(f"[FAIL] Round {i+1}: empty story_text")
                latencies.append(time.perf_counter() - start)
            except Exception as e:
                failures += 1
                print(f"[FAIL] Round {i+1}: {e}")

        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            p95_latency = sorted(latencies)[int(len(latencies) * 0.95) - 1]
            print(f"50-turn summary: failures={failures}, avg_latency={avg_latency:.2f}s, p95_latency={p95_latency:.2f}s")
        else:
            print("50-turn summary: no successful responses")

        print("--- Step 5: List sessions ---")
        try:
            resp = await client.get(f"{BASE_URL}/sessions/{novel_id}")
            resp.raise_for_status()
            all_sessions = resp.json()
            print(f"Total sessions for novel: {len(all_sessions)}")
        except Exception as e:
            print(f"Error in Step 5: {e}")

        print("--- Testing Complete ---")

        print("--- Step 6: Branch flow check ---")
        try:
            # Create a bookmark
            bm_payload = {"name": "回归检查书签"}
            resp = await client.post(f"{BASE_URL}/sessions/{session_id}/bookmark", json=bm_payload)
            resp.raise_for_status()
            bookmark = resp.json()
            bookmark_id = bookmark["id"]
            print(f"Created bookmark: {bookmark_id}")

            # Branch from bookmark
            branch_payload = {"bookmark_id": bookmark_id, "new_session_name": "回归分支A"}
            resp = await client.post(f"{BASE_URL}/sessions/{session_id}/branch", json=branch_payload)
            resp.raise_for_status()
            branch_session = resp.json()
            branch_session_id = branch_session["session_id"]
            print(f"Branched session: {branch_session_id}")

            # Re-branch from the new session
            resp = await client.post(f"{BASE_URL}/sessions/{branch_session_id}/bookmark", json={"name": "二级书签"})
            resp.raise_for_status()
            bookmark2 = resp.json()
            branch_payload2 = {"bookmark_id": bookmark2["id"], "new_session_name": "回归分支B"}
            resp = await client.post(f"{BASE_URL}/sessions/{branch_session_id}/branch", json=branch_payload2)
            resp.raise_for_status()
            branch_session2 = resp.json()
            print(f"Re-branched session: {branch_session2['session_id']}")
        except Exception as e:
            print(f"Error in Step 6: {e}")

        print("--- Step 7: A/B mode switching check ---")
        try:
            for mode in ["SANDBOX", "CONVERGENCE"]:
                payload = {
                    "session_id": session_id,
                    "novel_id": novel_id,
                    "message": f"模式测试：{mode}。",
                    "mode": mode
                }
                resp = await client.post(f"{BASE_URL}/chat/interact", json=payload)
                resp.raise_for_status()
                data = resp.json()
                print(f"Mode {mode} ok, story_text_len={len(data.get('story_text',''))}")
        except Exception as e:
            print(f"Error in Step 7: {e}")

if __name__ == "__main__":
    asyncio.run(test_sessions_flow())
