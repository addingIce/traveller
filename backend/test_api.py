import asyncio
import os
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:8080/api/v1/graph/test_novel?mode=auto') as resp:
            text = await resp.text()
            print("Response:", text)

asyncio.run(main())
