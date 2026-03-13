import re
import time
import asyncio
from datetime import datetime
from zep_python.client import AsyncZep
from zep_python import Message

def generate_collection_name(title: str) -> str:
    """生成唯一的集合名称"""
    timestamp = int(time.time())
    import hashlib
    title_hash = hashlib.md5(title.encode()).hexdigest()[:8]
    return f"novel_{timestamp}_{title_hash}"

def smart_chunk_content(content: str, min_length: int = 100, max_length: int = 500) -> list[str]:
    chunks = []
    paragraphs = content.split("\n\n")
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        if len(current_chunk) + len(para) + 2 <= max_length:
            current_chunk += (("\n\n" if current_chunk else "") + para)
        else:
            if len(current_chunk) >= min_length:
                chunks.append(current_chunk)
            
            if len(para) > max_length:
                sentences = re.split(r'[。！？\n]', para)
                temp_chunk = ""
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if len(temp_chunk) + len(sentence) + 1 <= max_length:
                        temp_chunk += (sentence + "。")
                    else:
                        if len(temp_chunk) >= min_length:
                            chunks.append(temp_chunk)
                        temp_chunk = sentence + "。"
                current_chunk = temp_chunk
            else:
                current_chunk = para
    
    if len(current_chunk) >= min_length:
        chunks.append(current_chunk)
    
    return chunks

async def monitor_entity_extraction(
    collection_name: str,
    neo4j_driver,
    status_store: dict
) -> None:
    if not neo4j_driver:
        return
    
    max_check_count = 60
    check_interval = 10
    min_monitor_time = 180
    stable_count = 0
    stable_threshold = 7
    last_entity_count = 0
    
    try:
        for i in range(max_check_count):
            await asyncio.sleep(check_interval)
            time_elapsed = (i + 1) * check_interval
            
            try:
                async with neo4j_driver.session() as session:
                    count_query = """
                    MATCH (e:Entity {group_id: $group_id})
                    RETURN COUNT(DISTINCT e) as count
                    """
                    result = await session.run(count_query, group_id=collection_name)
                    record = await result.single()
                    entity_count = record["count"] if record else 0
            except Exception as e:
                print(f"[ERROR] Failed to check entity count: {e}")
                continue
            
            if entity_count == 0:
                print(f"[DEBUG] {collection_name}: Waiting for entities (0/{i+1})")
                continue
            elif entity_count > 0:
                if status_store.get(collection_name, {}).get("status") == "completed":
                    status_store[collection_name]["status"] = "extracting"
                    try:
                        async with neo4j_driver.session() as session:
                            update_query = """
                            MATCH (n:Novel {collection_name: $collection_name})
                            SET n.status = 'extracting'
                            RETURN n
                            """
                            await session.run(update_query, collection_name=collection_name)
                            print(f"[INFO] {collection_name}: Entity extraction started ({entity_count} entities)")
                    except Exception as e:
                        print(f"[ERROR] Failed to update Novel node status: {e}")
                
                if time_elapsed >= min_monitor_time:
                    if entity_count == last_entity_count:
                        stable_count += 1
                        print(f"[DEBUG] {collection_name}: Stable count {stable_count}/{stable_threshold} ({entity_count} entities)")
                        
                        if stable_count >= stable_threshold:
                            status_store[collection_name]["status"] = "ready"
                            try:
                                async with neo4j_driver.session() as session:
                                    update_query = """
                                    MATCH (n:Novel {collection_name: $collection_name})
                                    SET n.status = 'ready'
                                    RETURN n
                                    """
                                    await session.run(update_query, collection_name=collection_name)
                                    print(f"[INFO] {collection_name}: Entity extraction completed ({entity_count} entities)")
                            except Exception as e:
                                print(f"[ERROR] Failed to update Novel node status: {e}")
                            return
                    else:
                        stable_count = 0
                        last_entity_count = entity_count
                        print(f"[DEBUG] {collection_name}: Extracting ({entity_count} entities)")
                else:
                    last_entity_count = entity_count
                    print(f"[DEBUG] {collection_name}: Monitoring ({entity_count} entities, {time_elapsed}s elapsed)")
        
        if last_entity_count > 0:
            status_store[collection_name]["status"] = "ready"
            try:
                async with neo4j_driver.session() as session:
                    update_query = """
                    MATCH (n:Novel {collection_name: $collection_name})
                    SET n.status = 'ready'
                    RETURN n
                    """
                    await session.run(update_query, collection_name=collection_name)
                    print(f"[INFO] {collection_name}: Entity extraction completed (timeout, {last_entity_count} entities)")
            except Exception as e:
                print(f"[ERROR] Failed to update Novel node status: {e}")
        else:
            print(f"[WARNING] {collection_name}: No entities extracted after monitoring")
    
    except Exception as e:
        print(f"[ERROR] Entity extraction monitoring failed: {e}")

async def process_novel_task(
    collection_name: str,
    content: str,
    novel_title: str,
    client: AsyncZep,
    status_store: dict,
    neo4j_driver = None
) -> None:
    try:
        status_store[collection_name]["status"] = "processing"
        
        if neo4j_driver:
            try:
                async with neo4j_driver.session() as session:
                    create_novel_query = """
                    MERGE (n:Novel {collection_name: $collection_name})
                    ON CREATE SET 
                        n.title = $title,
                        n.created_at = $created_at,
                        n.status = 'processing'
                    ON MATCH SET 
                        n.status = 'processing'
                    RETURN n
                    """
                    await session.run(
                        create_novel_query,
                        collection_name=collection_name,
                        title=novel_title,
                        created_at=status_store[collection_name]["created_at"]
                    )
                    print(f"[INFO] Created/Updated Novel node: {collection_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create Novel node: {e}")
        
        chunks = smart_chunk_content(content, min_length=100, max_length=500)
        total_chunks = len(chunks)
        status_store[collection_name]["total_chunks"] = total_chunks
        
        try:
            print(f"[DEBUG] Getting or creating session: {collection_name}")
            session = await client.memory.get_session(collection_name)
            print(f"[DEBUG] Session found: {collection_name}")
        except Exception as e:
            print(f"[DEBUG] Session not found, creating new one: {e}")
            await client.memory.add_session(
                session_id=collection_name,
                metadata={"type": "novel_ingest", "source": novel_title}
            )
            print(f"[DEBUG] Session created: {collection_name}")
        
        batch_size = 2
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            messages = [
                Message(
                    role_type="user",
                    role="讲述者",
                    content=chunk,
                )
                for chunk in batch
            ]
            
            retries = 3
            while retries > 0:
                try:
                    print(f"[DEBUG] Writing batch {i // batch_size + 1}/{(len(chunks) - 1) // batch_size + 1} to Zep...")
                    await client.memory.add(collection_name, messages=messages)
                    print(f"[DEBUG] Batch {i // batch_size + 1} written successfully")
                    break
                except Exception as e:
                    print(f"[DEBUG] Batch {i // batch_size + 1} failed (retries left: {retries}): {e}")
                    retries -= 1
                    if retries == 0:
                        raise e
                    await asyncio.sleep(2)
            
            processed = min(i + batch_size, total_chunks)
            status_store[collection_name]["chunks_processed"] = processed
            status_store[collection_name]["progress"] = (processed / total_chunks) * 100
            
            await asyncio.sleep(1)
        
        status_store[collection_name]["status"] = "completed"
        status_store[collection_name]["progress"] = 100.0
        
        if neo4j_driver:
            try:
                async with neo4j_driver.session() as session:
                    update_novel_query = """
                    MATCH (n:Novel {collection_name: $collection_name})
                    SET n.status = 'completed'
                    RETURN n
                    """
                    await session.run(update_novel_query, collection_name=collection_name)
                    print(f"[INFO] Updated Novel node status to 'completed': {collection_name}")
            except Exception as e:
                print(f"[ERROR] Failed to update Novel node status: {e}")
        
        asyncio.create_task(monitor_entity_extraction(collection_name, neo4j_driver, status_store))
        
    except Exception as e:
        status_store[collection_name]["status"] = "failed"
        status_store[collection_name]["error_message"] = str(e)
        print(f"[ERROR] 小说处理失败 {collection_name}: {e}")

async def get_entity_count(collection_name: str, neo4j_driver) -> int:
    try:
        async with neo4j_driver.session() as session:
            count_query = """
            MATCH (e:Entity {group_id: $group_id})
            RETURN COUNT(DISTINCT e) as count
            """
            result = await session.run(count_query, group_id=collection_name)
            record = await result.single()
            return record["count"] if record else 0
    except Exception as e:
        print(f"[ERROR] Failed to check entity count: {e}")
        return 0

async def check_zep_messages(collection_name: str) -> int:
    try:
        import httpx
        import os
        zep_api_url = os.getenv("ZEP_API_URL", "http://localhost:8000")
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.get(
                f"{zep_api_url}/sessions/{collection_name}/messages",
                params={"limit": 1}
            )
            if response.status_code == 200:
                data = response.json()
                return len(data.get("messages", []))
            elif response.status_code == 404:
                return 0
            else:
                print(f"[WARNING] Failed to check Zep messages: {response.status_code}")
                return 0
    except Exception as e:
        print(f"[ERROR] Failed to check Zep messages: {e}")
        return 0

async def observe_entity_growth(collection_name: str, neo4j_driver) -> tuple[int, bool]:
    check_count = 7
    check_interval = 10
    min_monitor_time = 180
    counts = []
    stable_count = 0
    last_count = 0
    
    for i in range(check_count):
        entity_count = await get_entity_count(collection_name, neo4j_driver)
        counts.append(entity_count)
        time_elapsed = (i + 1) * check_interval
        
        print(f"[DEBUG] {collection_name}: Observation {i+1}/{check_count} - {entity_count} entities ({time_elapsed}s elapsed)")
        
        if time_elapsed >= min_monitor_time:
            if entity_count == last_count:
                stable_count += 1
            else:
                stable_count = 0
                last_count = entity_count
        else:
            last_count = entity_count
        
        if i < check_count - 1:
            await asyncio.sleep(check_interval)
    
    is_stable = stable_count >= check_count
    final_count = counts[-1]
    
    print(f"[DEBUG] {collection_name}: Final count={final_count}, stable={is_stable}")
    return final_count, is_stable
