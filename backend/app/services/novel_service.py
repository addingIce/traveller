import re
import time
import asyncio
import unicodedata
from datetime import datetime
from typing import Any
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


def _normalize_entity_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name or "")
    return normalized.strip().lower()


def _split_summary_sentences(summary: str) -> list[str]:
    if not summary:
        return []
    raw_parts = re.split(r"[。！？.!?\n]+", summary)
    return [part.strip() for part in raw_parts if part and part.strip()]


def _merge_entity_summaries(summaries: list[str], max_length: int = 1200) -> str:
    ordered_summaries = sorted((s.strip() for s in summaries if s and s.strip()), key=len, reverse=True)
    seen: set[str] = set()
    merged_parts: list[str] = []
    for summary in ordered_summaries:
        for sentence in _split_summary_sentences(summary):
            if sentence in seen:
                continue
            seen.add(sentence)
            merged_parts.append(sentence)
    merged = "。".join(merged_parts)
    if merged and not merged.endswith("。"):
        merged += "。"
    return merged[:max_length]


def _select_master_entity(entities: list[dict[str, Any]]) -> dict[str, Any]:
    def _score(item: dict[str, Any]) -> tuple[int, int, int, str]:
        rel_score = int(item.get("rel_score") or 0)
        attr_score = int(item.get("attr_score") or 0)
        has_summary = 1 if (item.get("summary") or "").strip() else 0
        created_at = item.get("created_at") or ""
        # rel/attr/summary 越高越优先；created_at 越早越优先
        return (-rel_score, -attr_score, -has_summary, created_at)

    return sorted(entities, key=_score)[0]


async def deduplicate_entities_in_collection(
    collection_name: str,
    neo4j_driver,
    summary_max_length: int = 1200
) -> dict[str, int]:
    if not neo4j_driver:
        return {"merged_groups": 0, "removed_nodes": 0}

    async with neo4j_driver.session() as session:
        query = """
        MATCH (e:Entity {group_id: $group_id})
        RETURN
            e.uuid AS uuid,
            COALESCE(e.name, '') AS name,
            COALESCE(e.summary, '') AS summary,
            COALESCE(e.created_at, '') AS created_at,
            size([(e)-[:RELATES_TO]-() | 1]) + size([(e)-[:MENTIONS]-() | 1]) AS rel_score,
            CASE WHEN e.attributes IS NULL THEN 0 ELSE size(keys(e.attributes)) END AS attr_score
        """
        result = await session.run(query, group_id=collection_name)
        entities = [record async for record in result]

        groups: dict[str, list[dict[str, Any]]] = {}
        for record in entities:
            normalized_name = _normalize_entity_name(record["name"])
            if not normalized_name:
                continue
            groups.setdefault(normalized_name, []).append(
                {
                    "uuid": record["uuid"],
                    "name": record["name"],
                    "summary": record["summary"] or "",
                    "created_at": record["created_at"] or "",
                    "rel_score": int(record["rel_score"] or 0),
                    "attr_score": int(record["attr_score"] or 0),
                }
            )

        merged_groups = 0
        removed_nodes = 0
        for normalized_name, bucket in groups.items():
            if len(bucket) <= 1:
                continue

            merged_groups += 1
            master = _select_master_entity(bucket)
            merged_summary = _merge_entity_summaries(
                [item.get("summary", "") for item in bucket],
                max_length=summary_max_length,
            )
            print(
                f"[WARNING] Duplicate entities detected: group={collection_name}, "
                f"name={normalized_name}, count={len(bucket)}, master={master['uuid']}"
            )

            await session.run(
                """
                MATCH (master:Entity {uuid: $master_uuid})
                SET master.summary = $summary
                """,
                master_uuid=master["uuid"],
                summary=merged_summary,
            )

            for duplicate in bucket:
                duplicate_uuid = duplicate["uuid"]
                if duplicate_uuid == master["uuid"]:
                    continue

                await session.run(
                    """
                    MATCH (dup:Entity {uuid: $dup_uuid}), (master:Entity {uuid: $master_uuid})
                    MATCH (dup)-[r:RELATES_TO]->(t)
                    WHERE t.uuid <> $master_uuid
                    MERGE (master)-[nr:RELATES_TO {
                        fact: COALESCE(r.fact, ''),
                        name: COALESCE(r.name, '')
                    }]->(t)
                    ON CREATE SET nr.uuid = COALESCE(r.uuid, randomUUID())
                    """,
                    dup_uuid=duplicate_uuid,
                    master_uuid=master["uuid"],
                )

                await session.run(
                    """
                    MATCH (dup:Entity {uuid: $dup_uuid}), (master:Entity {uuid: $master_uuid})
                    MATCH (s)-[r:RELATES_TO]->(dup)
                    WHERE s.uuid <> $master_uuid
                    MERGE (s)-[nr:RELATES_TO {
                        fact: COALESCE(r.fact, ''),
                        name: COALESCE(r.name, '')
                    }]->(master)
                    ON CREATE SET nr.uuid = COALESCE(r.uuid, randomUUID())
                    """,
                    dup_uuid=duplicate_uuid,
                    master_uuid=master["uuid"],
                )

                await session.run(
                    """
                    MATCH (dup:Entity {uuid: $dup_uuid}), (master:Entity {uuid: $master_uuid})
                    MATCH (x)-[:MENTIONS]->(dup)
                    MERGE (x)-[:MENTIONS]->(master)
                    """,
                    dup_uuid=duplicate_uuid,
                    master_uuid=master["uuid"],
                )

                await session.run(
                    """
                    MATCH (dup:Entity {uuid: $dup_uuid}), (master:Entity {uuid: $master_uuid})
                    MATCH (dup)-[:MENTIONS]->(x)
                    MERGE (master)-[:MENTIONS]->(x)
                    """,
                    dup_uuid=duplicate_uuid,
                    master_uuid=master["uuid"],
                )

                await session.run(
                    """
                    MATCH (dup:Entity {uuid: $dup_uuid})
                    DETACH DELETE dup
                    """,
                    dup_uuid=duplicate_uuid,
                )
                removed_nodes += 1

        return {"merged_groups": merged_groups, "removed_nodes": removed_nodes}

async def monitor_entity_extraction(
    collection_name: str,
    neo4j_driver,
    status_store: dict
) -> None:
    if not neo4j_driver:
        return
    
    # 恢复场景下 status_store 可能不存在该小说，先兜底避免 KeyError
    status_store.setdefault(collection_name, {
        "status": "completed",
        "progress": 100.0,
        "chunks_processed": 0,
        "total_chunks": 0,
        "error_message": None,
        "created_at": datetime.utcnow().isoformat(),
        "title": collection_name,
    })
    
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
                            try:
                                dedup_stats = await deduplicate_entities_in_collection(collection_name, neo4j_driver)
                                if dedup_stats.get("removed_nodes", 0) > 0:
                                    print(
                                        f"[INFO] {collection_name}: Deduplicated entities "
                                        f"(groups={dedup_stats['merged_groups']}, removed={dedup_stats['removed_nodes']})"
                                    )
                            except Exception as dedup_error:
                                print(f"[WARNING] {collection_name}: Deduplication failed: {dedup_error}")

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
            try:
                dedup_stats = await deduplicate_entities_in_collection(collection_name, neo4j_driver)
                if dedup_stats.get("removed_nodes", 0) > 0:
                    print(
                        f"[INFO] {collection_name}: Deduplicated entities "
                        f"(groups={dedup_stats['merged_groups']}, removed={dedup_stats['removed_nodes']})"
                    )
            except Exception as dedup_error:
                print(f"[WARNING] {collection_name}: Deduplication failed: {dedup_error}")

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
                    WITH n
                    MERGE (s:Session {uuid: $collection_name})
                    ON CREATE SET
                        s.name = '原始剧情线',
                        s.user_id = 'system',
                        s.created_at = $created_at,
                        s.last_interaction_at = $created_at,
                        s.is_root = true
                    MERGE (n)-[:HAS_SESSION]->(s)
                    RETURN n
                    """
                    await session.run(
                        create_novel_query,
                        collection_name=collection_name,
                        title=novel_title,
                        created_at=status_store[collection_name]["created_at"]
                    )
                    print(f"[INFO] Created/Updated Novel and root Session node: {collection_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create Novel node: {e}")
        
        chunks = smart_chunk_content(content, min_length=100, max_length=500)
        total_chunks = len(chunks)
        status_store[collection_name]["total_chunks"] = total_chunks

        # 在链路不稳定时对 get_session/add_session 做轻量重试，避免瞬断导致整本小说失败
        session_ready = False
        session_attempts = 3
        for attempt in range(1, session_attempts + 1):
            try:
                print(f"[DEBUG] Getting or creating session ({attempt}/{session_attempts}): {collection_name}")
                try:
                    await client.memory.get_session(collection_name)
                    print(f"[DEBUG] Session found: {collection_name}")
                except Exception as e:
                    print(f"[DEBUG] Session get failed, creating new one: {e}")
                    await client.memory.add_session(
                        session_id=collection_name,
                        metadata={"type": "novel_ingest", "source": novel_title}
                    )
                    print(f"[DEBUG] Session created: {collection_name}")
                session_ready = True
                break
            except Exception as e:
                print(f"[WARNING] Session prepare failed ({attempt}/{session_attempts}): {e}")
                if attempt < session_attempts:
                    await asyncio.sleep(2 ** (attempt - 1))
        if not session_ready:
            raise RuntimeError("Zep 会话初始化失败（服务可能暂时不可用或网络不稳定）")
        
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
    min_monitor_time = 30
    stable_threshold = 3
    counts = []
    stable_count = 0
    last_count = None
    
    for i in range(check_count):
        entity_count = await get_entity_count(collection_name, neo4j_driver)
        counts.append(entity_count)
        time_elapsed = (i + 1) * check_interval
        
        print(f"[DEBUG] {collection_name}: Observation {i+1}/{check_count} - {entity_count} entities ({time_elapsed}s elapsed)")
        
        if time_elapsed < min_monitor_time:
            last_count = entity_count
        else:
            if last_count is None or entity_count != last_count:
                stable_count = 1
                last_count = entity_count
            else:
                stable_count += 1
            
            if entity_count > 0 and stable_count >= stable_threshold:
                print(f"[DEBUG] {collection_name}: Final count={entity_count}, stable=True")
                return entity_count, True
        
        if i < check_count - 1:
            await asyncio.sleep(check_interval)
    
    final_count = counts[-1] if counts else 0
    is_stable = final_count > 0 and stable_count >= stable_threshold
    
    print(f"[DEBUG] {collection_name}: Final count={final_count}, stable={is_stable}")
    return final_count, is_stable
