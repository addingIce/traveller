import asyncio
import os
from zep_python.client import AsyncZep
from dotenv import load_dotenv

load_dotenv()

async def test_zep():
    url = os.getenv("ZEP_API_URL", "http://localhost:8000")
    key = os.getenv("ZEP_API_KEY", "")
    print(f"Testing Zep at {url}")
    
    # Explicitly unset proxies for this process
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1'
    if 'http_proxy' in os.environ: del os.environ['http_proxy']
    if 'https_proxy' in os.environ: del os.environ['https_proxy']
    if 'HTTP_PROXY' in os.environ: del os.environ['HTTP_PROXY']
    if 'HTTPS_PROXY' in os.environ: del os.environ['HTTPS_PROXY']

    client = AsyncZep(base_url=url, api_key=key)
    try:
        # Try a simple call
        sessions = await client.memory.list_sessions()
        print(f"Success! Found {len(sessions)} sessions.")
    except Exception as e:
        print(f"Failed: {e}")
    finally:
        await client.close()

if __name__ == "__main__":
    asyncio.run(test_zep())
