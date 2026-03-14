
import asyncio
import os
import sys

# Disable proxies
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
for key in ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"]:
    if key in os.environ:
        del os.environ[key]

from zep_python.client import AsyncZep
from dotenv import load_dotenv

load_dotenv()

async def main():
    zep_api_url = os.getenv("ZEP_API_URL", "http://localhost:8000")
    zep_api_key = os.getenv("ZEP_API_KEY", "this_is_a_secret_key_for_zep_ce_1234567890")
    
    print(f"Connecting to Zep at: {zep_api_url}")
    client = AsyncZep(base_url=zep_api_url, api_key=zep_api_key)
    
    try:
        # List sessions
        response = await client.memory.list_sessions()
        
        # In newer SDKs, list_sessions returns a response object with a sessions list
        sessions = getattr(response, 'sessions', response)
        if not isinstance(sessions, list):
            print(f"DEBUG: Response type is {type(response)}")
            print(f"DEBUG: Sessions type is {type(sessions)}")
            return
            
        novel_sessions = [s for s in sessions if s.session_id.startswith("novel_")]
        
        if not novel_sessions:
            print("No sessions starting with 'novel_' found.")
            return
            
        # Latest by ID
        latest_session = sorted(novel_sessions, key=lambda s: s.session_id, reverse=True)[0]
        session_id = latest_session.session_id
        print(f"Checking session: {session_id}")
        
        memory = await client.memory.get(session_id)
        messages = memory.messages or []
        print(f"Found {len(messages)} messages in Zep memory.")
        
        for i, msg in enumerate(messages[:5]):
            print(f"[{i}] {msg.role}: {msg.content[:100]}...")
            
    except Exception as e:
        print(f"Error during Zep diagnostic: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
