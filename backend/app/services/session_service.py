import uuid
import time
import re
import os
import asyncio
import httpx
from datetime import datetime
from typing import List, Optional, Dict, Any
from zep_python.client import AsyncZep
from zep_python import Message, Memory
from neo4j import AsyncDriver

class SessionService:
    def __init__(self, zep_client: AsyncZep, neo4j_driver: AsyncDriver):
        self.zep = zep_client
        self.neo4j = neo4j_driver

    async def create_session(self, novel_id: str, user_id: str, session_name: str, parent_session_id: Optional[str] = None, start_chapter_id: Optional[str] = None) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        # 1. Persist in Neo4j
        try:
            async with self.neo4j.session() as session:
                # Ensure the Novel exists first
                novel_check = await session.run("MATCH (n:Novel {collection_name: $novel_id}) RETURN n", novel_id=novel_id)
                if not await novel_check.single():
                    print(f"[WARNING] Creating session for unknown novel_id: {novel_id}")

                query = """
                MATCH (n:Novel {collection_name: $novel_id})
                CREATE (s:Session {
                    uuid: $session_id,
                    name: $session_name,
                    user_id: $user_id,
                    created_at: $created_at,
                    last_interaction_at: $created_at,
                    is_root: $is_root
                })
                CREATE (n)-[:HAS_SESSION]->(s)
                """
                params = {
                    "novel_id": novel_id,
                    "session_id": session_id,
                    "session_name": session_name,
                    "user_id": user_id,
                    "created_at": created_at,
                    "is_root": False
                }
                
                if parent_session_id:
                    query += """
                    WITH s
                    MATCH (p:Session {uuid: $parent_id})
                    CREATE (p)-[:BRANCHED_TO]->(s)
                    SET s.parent_session_id = $parent_id
                    """
                    params["parent_id"] = parent_session_id

                await session.run(query, **params)
                print(f"[DEBUG] Session {session_id} persisted in Neo4j for novel {novel_id}")
        except Exception as ne:
            print(f"[ERROR] Neo4j session creation failed: {ne}")
            import traceback
            traceback.print_exc()
            raise ne

        # 2. Initialize in Zep
        try:
            metadata = {
                "novel_id": novel_id,
                "user_id": user_id,
                "session_name": session_name,
                "parent_id": parent_session_id
            }
            if start_chapter_id:
                metadata["start_chapter_id"] = start_chapter_id

            # Create session with metadata first (retry without user_id if Zep rejects unknown users)
            try:
                await self.zep.memory.add_session(
                    session_id=session_id,
                    user_id=user_id,
                    metadata=metadata
                )
            except Exception as e:
                if "user not found" in str(e).lower():
                    print(f"[WARNING] Zep rejected user_id for {session_id}, retrying without user_id")
                    await self.zep.memory.add_session(
                        session_id=session_id,
                        metadata=metadata
                    )
                else:
                    raise

            # Add initial message
            await self.zep.memory.add(
                session_id,
                messages=[Message(role="system", role_type="system", content="INIT")]
            )
        except Exception as e:
            print(f"[ERROR] Session {session_id} Zep initialization failed: {e}")
            # Roll back Neo4j session node to avoid orphaned sessions
            try:
                async with self.neo4j.session() as session:
                    await session.run(
                        """
                        MATCH (s:Session {uuid: $sid})
                        DETACH DELETE s
                        """,
                        sid=session_id
                    )
            except Exception as cleanup_err:
                print(f"[WARNING] Failed to rollback Neo4j session {session_id}: {cleanup_err}")
            raise
        
        return {
            "session_id": session_id,
            "novel_id": novel_id,
            "user_id": user_id,
            "session_name": session_name,
            "created_at": created_at,
            "parent_session_id": parent_session_id,
            "start_chapter_id": start_chapter_id
        }

    async def list_sessions(self, novel_id: str) -> List[Dict[str, Any]]:
        async with self.neo4j.session() as session:
            query = """
            MATCH (n:Novel {collection_name: $novel_id})-[:HAS_SESSION]->(s:Session)
            RETURN s.uuid as session_id, 
                   n.collection_name as novel_id,
                   s.name as session_name, 
                   s.user_id as user_id, 
                   s.created_at as created_at, 
                   s.last_interaction_at as last_interaction_at,
                   COALESCE(s.parent_session_id, "") as parent_session_id, 
                   COALESCE(s.is_root, false) as is_root
            ORDER BY s.created_at DESC
            """
            result = await session.run(query, novel_id=novel_id)
            return [dict(record) async for record in result]

    async def create_bookmark(self, session_id: str, name: str, description: Optional[str] = None) -> Dict[str, Any]:
        bookmark_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        # Get the latest message from Zep to use as checkpoint
        memory = await self.zep.memory.get(session_id)
        checkpoint_id = ""
        if memory.messages:
            last_msg = memory.messages[-1]
            # Handle different SDK versions where uuid might be under uuid_ or uuid
            checkpoint_id = getattr(last_msg, "uuid_", getattr(last_msg, "uuid", ""))
            print(f"[DEBUG] Creating bookmark {name} with checkpoint {checkpoint_id}")

        async with self.neo4j.session() as session:
            query = """
            MATCH (s:Session {uuid: $session_id})
            CREATE (b:Bookmark {
                uuid: $bookmark_id,
                name: $name,
                description: $description,
                created_at: $created_at,
                checkpoint_id: $checkpoint_id
            })
            CREATE (s)-[:HAS_BOOKMARK]->(b)
            """
            await session.run(query, 
                session_id=session_id, 
                bookmark_id=bookmark_id, 
                name=name, 
                description=description or "",
                created_at=created_at,
                checkpoint_id=checkpoint_id
            )
            
        return {
            "id": bookmark_id,
            "session_id": session_id,
            "name": name,
            "description": description,
            "created_at": created_at,
            "checkpoint_id": checkpoint_id
        }

    async def list_bookmarks(self, session_id: str) -> List[Dict[str, Any]]:
        async with self.neo4j.session() as session:
            query = """
            MATCH (s:Session {uuid: $session_id})-[:HAS_BOOKMARK]->(b:Bookmark)
            RETURN b.uuid as id, 
                   b.name as name, 
                   b.description as description, 
                   b.created_at as created_at,
                   b.checkpoint_id as checkpoint_id,
                   $session_id as session_id
            ORDER BY b.created_at DESC
            """
            result = await session.run(query, session_id=session_id)
            return [dict(record) async for record in result]

    async def branch_from_bookmark(self, session_id: str, bookmark_id: str, new_name: Optional[str] = None) -> Dict[str, Any]:
        # 1. Get bookmark info
        async with self.neo4j.session() as session:
            query = """
            MATCH (s:Session {uuid: $session_id})-[:HAS_BOOKMARK]->(b:Bookmark {uuid: $bookmark_id})
            MATCH (n:Novel)-[:HAS_SESSION]->(s)
            RETURN b.checkpoint_id as checkpoint_id, s.user_id as user_id, n.collection_name as novel_id, s.name as parent_name
            """
            result = await session.run(query, session_id=session_id, bookmark_id=bookmark_id)
            record = await result.single()
            if not record:
                raise ValueError("Bookmark not found")
            
            checkpoint_id = record["checkpoint_id"]
            user_id = record["user_id"]
            novel_id = record["novel_id"]
            parent_name = record["parent_name"]

        # 2. Create new session
        new_session_name = new_name or f"{parent_name} (分支)"
        new_session_info = await self.create_session(novel_id, user_id, new_session_name, parent_session_id=session_id)
        new_session_id = new_session_info["session_id"]

        # 3. Clone Zep messages up to checkpoint
        # Retrieve ALL history from source
        source_memory = await self.zep.memory.get(session_id)
        messages_to_copy = []
        source_ids = []
        for msg in source_memory.messages:
            msg_id = getattr(msg, "uuid_", None) or getattr(msg, "uuid", None)
            is_init = (
                (msg.role_type == "system" or msg.role == "system")
                and (msg.content or "").strip() == "INIT"
            )
            if is_init:
                # Skip INIT to avoid duplicate system messages in branched sessions
                if checkpoint_id and msg_id == checkpoint_id:
                    break
                continue
            messages_to_copy.append(Message(
                role=msg.role,
                role_type=msg.role_type,
                content=msg.content
            ))
            source_ids.append(msg_id)
            if checkpoint_id and msg_id == checkpoint_id:
                break
        
        if messages_to_copy:
            # Add messages to the new session
            await self.zep.memory.add(new_session_id, messages=messages_to_copy)

        # Build old->new checkpoint mapping by order (Zep regenerates UUIDs)
        id_map = {}
        try:
            new_memory = await self.zep.memory.get(new_session_id)
            new_msgs = new_memory.messages or []
            # Drop the initial system INIT message to align with source_ids
            filtered_new_msgs = [
                m for m in new_msgs
                if not (
                    (getattr(m, "role_type", None) == "system" or getattr(m, "role", None) == "system")
                    and (getattr(m, "content", "") or "").strip() == "INIT"
                )
            ]
            if len(filtered_new_msgs) >= len(source_ids):
                new_ids = [getattr(m, "uuid_", None) or getattr(m, "uuid", None) for m in filtered_new_msgs[:len(source_ids)]]
                id_map = {old: new for old, new in zip(source_ids, new_ids) if old and new}
        except Exception as map_err:
            print(f"[WARNING] Failed to build checkpoint id map for {new_session_id}: {map_err}")

        # 4. Clone bookmarks in Neo4j
        async with self.neo4j.session() as session:
            copy_bookmarks_query = """
            MATCH (s:Session {uuid: $old_session_id})-[:HAS_BOOKMARK]->(b:Bookmark)
            MATCH (ns:Session {uuid: $new_session_id})
            CREATE (ns)-[:HAS_BOOKMARK]->(nb:Bookmark)
            SET nb = b, nb.uuid = apoc.create.uuid()
            RETURN count(nb) as count
            """
            # Note: apoc is common, but let's use a simpler way if apoc is missing
            # or just use python to loop if needed. 
            # Given we want to be safe, let's fetch and re-create.
            
            fetch_query = "MATCH (s:Session {uuid: $old_sid})-[:HAS_BOOKMARK]->(b:Bookmark) RETURN b"
            res = await session.run(fetch_query, old_sid=session_id)
            bookmarks = [dict(record["b"]) async for record in res]
            
            for bm in bookmarks:
                old_cp_id = bm.get("checkpoint_id", "")
                if old_cp_id and old_cp_id not in id_map:
                    # Skip bookmarks beyond the branch checkpoint or with unknown mapping
                    continue
                new_cp_id = id_map.get(old_cp_id, "")
                new_bm_id = str(uuid.uuid4())
                create_bm_query = """
                MATCH (ns:Session {uuid: $ns_id})
                CREATE (ns)-[:HAS_BOOKMARK]->(nb:Bookmark {
                    uuid: $uuid,
                    name: $name,
                    description: $desc,
                    created_at: $created,
                    checkpoint_id: $cp_id
                })
                """
                await session.run(create_bm_query, 
                    ns_id=new_session_id,
                    uuid=new_bm_id,
                    name=bm["name"],
                    desc=bm.get("description", ""),
                    created=bm["created_at"],
                    cp_id=new_cp_id
                )

        return new_session_info

    async def extract_chapters(self, novel_id: str) -> List[Dict[str, Any]]:
        # In this architecture, "novel_id" is actually the session_id for the original ingestion
        # The original storyline messages have role="讲述者"
        try:
            session_id = novel_id if novel_id.startswith("novel_") else f"novel_{novel_id}"
            print(f"[DEBUG] extract_chapters: novel_id={novel_id}, session_id={session_id}")
            messages = []
            # 1) Prefer Zep HTTP API (more stable)
            try:
                zep_api_url = os.getenv("ZEP_API_URL", "http://localhost:8000")
                zep_api_key = os.getenv("ZEP_API_KEY", "this_is_a_secret_key_for_zep_ce_1234567890")
                print(f"[DEBUG] Calling Zep HTTP API: {zep_api_url}/api/v1/session/{session_id}/messages")
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    resp = await http_client.get(
                        f"{zep_api_url}/api/v1/session/{session_id}/messages",
                        params={"limit": 1000},  # 增大限制以支持长篇小说
                        headers={"Authorization": f"Bearer {zep_api_key}"}
                    )
                    print(f"[DEBUG] Zep HTTP response status: {resp.status_code}")
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_messages = data.get("messages") or []
                        print(f"[DEBUG] Zep HTTP returned {len(raw_messages)} raw messages")
                        for msg in raw_messages:
                            content = (msg.get("content") or "").strip()
                            if not content:
                                continue
                            messages.append(type("Msg", (), {"uuid": msg.get("uuid"), "content": content})())
                    else:
                        print(f"[DEBUG] Zep HTTP error: {resp.text[:200]}")
            except Exception as http_err:
                print(f"[ERROR] extracting chapters from Zep HTTP: {http_err}")

            # 2) Fallback to Zep SDK
            if not messages:
                print(f"[DEBUG] Falling back to Zep SDK...")
                try:
                    memory = await self.zep.memory.get(session_id)
                    messages = memory.messages or []
                    print(f"[DEBUG] Zep SDK returned {len(messages)} messages")
                except Exception as sdk_err:
                    print(f"[ERROR] extracting chapters from Zep SDK: {sdk_err}")
            
            # 3) Direct PostgreSQL query fallback (bypasses Zep message_window limit)
            # Zep CE has a default message_window limit that restricts returned messages
            # This queries the database directly to get ALL messages
            if not messages or len(messages) < 20:
                print(f"[DEBUG] Trying direct PostgreSQL query for session {session_id}...")
                try:
                    import asyncpg
                    pg_user = os.getenv("POSTGRES_USER", "zep")
                    pg_password = os.getenv("POSTGRES_PASSWORD", "zep")
                    pg_host = os.getenv("POSTGRES_HOST", "localhost")
                    pg_port = os.getenv("POSTGRES_PORT", "5432")
                    pg_db = os.getenv("POSTGRES_DB", "zep")
                    
                    # 连接 PostgreSQL（使用 localhost，因为我们在 host 上运行）
                    conn = await asyncpg.connect(
                        host=pg_host,
                        port=int(pg_port),
                        user=pg_user,
                        password=pg_password,
                        database=pg_db
                    )
                    try:
                        rows = await conn.fetch(
                            """
                            SELECT uuid, content, created_at 
                            FROM messages 
                            WHERE session_id = $1 
                            ORDER BY created_at ASC
                            """,
                            session_id
                        )
                        print(f"[DEBUG] PostgreSQL direct query returned {len(rows)} messages")
                        if rows:
                            messages = [
                                type("Msg", (), {"uuid": row["uuid"], "content": row["content"] or ""})()
                                for row in rows
                                if row["content"]
                            ]
                    finally:
                        await conn.close()
                except Exception as pg_err:
                    print(f"[WARNING] Direct PostgreSQL query failed: {pg_err}")
            
            print(f"[DEBUG] Total messages to process: {len(messages)}")
            
            # Zep 返回的消息默认是倒序的（最新在前），需要反转
            # 尝试按 created_at 排序，如果没有则反转
            try:
                # 尝试获取 created_at 并排序
                def get_created_at(msg):
                    # 尝试多种方式获取创建时间
                    if hasattr(msg, 'created_at'):
                        return msg.created_at or ""
                    if hasattr(msg, 'metadata') and msg.metadata:
                        return msg.metadata.get('created_at', "")
                    return ""
                
                # 检查是否有 created_at 属性
                has_created_at = any(get_created_at(m) for m in messages)
                if has_created_at:
                    messages = sorted(messages, key=lambda m: get_created_at(m) or "")
                    print(f"[DEBUG] Sorted messages by created_at")
                else:
                    # 没有 created_at，直接反转
                    messages = list(reversed(messages))
                    print(f"[DEBUG] Reversed messages order")
            except Exception as sort_err:
                print(f"[WARNING] Failed to sort messages: {sort_err}, reversing instead")
                messages = list(reversed(messages))
            
            chapters = []
            # Regex for Chinese chapter titles: 第[一二三四五六七八九十百千0-9]+[章节回堂回讲课]...
            # Also catch patterns like "1. 引言" or "Chapter 1"
            chapter_pattern = re.compile(
                r"^(第[一二三四五六七八九十百千0-9]+[章节回堂讲课]).*|"  # 第1章
                r"^([一二三四五六七八九十百千0-9]+[\.、\s]).*|"        # 1. 或 一、
                r"^(Chapter\s+\d+).*|"                            # Chapter 1
                r"^(#\s+.*)$",                                   # Markdown # Title
                re.IGNORECASE
            )
            
            for i, msg in enumerate(messages):
                content = msg.content.strip()
                if not content:
                    continue
                
                msg_id = getattr(msg, 'uuid_', None) or getattr(msg, 'uuid', None) or f"msg-{i}"
                lines = content.split('\n')
                
                # Scan all lines to find chapter titles
                chapter_positions = []  # [(line_index, title)]
                for line_idx, line in enumerate(lines):
                    line_stripped = line.strip()
                    match = chapter_pattern.match(line_stripped)
                    if match:
                        title = re.sub(r"^[#\s\*\-]+", "", line_stripped).strip()
                        chapter_positions.append((line_idx, title))
                
                # If found chapters in this message, extract them
                if chapter_positions:
                    print(f"[DEBUG] Found {len(chapter_positions)} chapters in message {i}")
                    for idx, (start_line, title) in enumerate(chapter_positions):
                        # Determine end line (next chapter start or end of content)
                        if idx + 1 < len(chapter_positions):
                            end_line = chapter_positions[idx + 1][0]
                        else:
                            end_line = len(lines)
                        
                        # Extract chapter content
                        chapter_lines = lines[start_line:end_line]
                        chapter_content = '\n'.join(chapter_lines).strip()
                        
                        preview = chapter_content[:200] + "..." if len(chapter_content) > 200 else chapter_content
                        chapters.append({
                            "id": f"{msg_id}-ch{idx+1}",
                            "title": title or f"章节 {len(chapters) + 1}",
                            "content": chapter_content,  # 完整内容
                            "content_preview": preview,
                            "order": len(chapters) + 1
                        })
                else:
                    # No chapters found in this message, check if first line looks like a title
                    first_line = lines[0].strip() if lines else ""
                    if len(first_line) < 30 and first_line.endswith(('：', ':')):
                        title = re.sub(r"^[#\s\*\-]+", "", first_line).strip()
                        preview = content[:200] + "..." if len(content) > 200 else content
                        chapters.append({
                            "id": msg_id,
                            "title": title or f"章节 {len(chapters) + 1}",
                            "content": content,  # 完整内容
                            "content_preview": preview,
                            "order": len(chapters) + 1
                        })
            
            # If no chapters found via regex, we might just return the first few chunks as "segments"
            if not chapters and messages:
                for i, msg in enumerate(messages[:10]): # Limit to first 10 for preview
                    msg_id = getattr(msg, 'uuid_', None) or getattr(msg, 'uuid', None) or f"msg-{i}"
                    chapters.append({
                        "id": msg_id,
                        "title": f"片段 {i+1}",
                        "content_preview": msg.content[:200] + "...",
                        "order": i + 1
                    })

            # If still empty, fallback to episodic nodes in Neo4j
            if not chapters:
                try:
                    async with self.neo4j.session() as session:
                        result = await session.run(
                            """
                            MATCH (e:Episodic {group_id: $group_id})
                            RETURN e.uuid as uuid, e.content as content, e.created_at as created_at
                            ORDER BY e.created_at ASC
                            """,
                            group_id=session_id
                        )
                        episodic = [dict(record) async for record in result]
                    print(f"[DEBUG] Found {len(episodic)} episodic nodes in Neo4j")
                    for i, record in enumerate(episodic):
                        content = (record.get("content") or "").strip()
                        if not content:
                            continue
                        chapters.append({
                            "id": record.get("uuid") or f"episodic-{i+1}",
                            "title": f"片段 {i+1}",
                            "content": content,  # 完整内容
                            "content_preview": content[:200] + ("..." if len(content) > 200 else ""),
                            "order": i + 1
                        })
                except Exception as neo_err:
                    print(f"Error extracting chapters from Neo4j: {neo_err}")
                    
            return chapters
        except Exception as e:
            print(f"Error extracting chapters: {e}")
            return []

    async def delete_session(self, session_id: str) -> bool:
        """删除 Session 及其关联数据（Neo4j + Zep）"""
        try:
            # 1. 检查是否是 root session
            async with self.neo4j.session() as session:
                result = await session.run(
                    "MATCH (s:Session {uuid: $sid}) RETURN s.is_root as is_root",
                    sid=session_id
                )
                record = await result.single()
                if record and record.get("is_root"):
                    raise ValueError("不能删除原始剧情线（root session）")

            # 2. 删除 Neo4j 中的 Session 和关联的 Bookmark
            async with self.neo4j.session() as session:
                # 先删除关联的 bookmarks
                await session.run(
                    """
                    MATCH (s:Session {uuid: $sid})-[:HAS_BOOKMARK]->(b:Bookmark)
                    DETACH DELETE b
                    """,
                    sid=session_id
                )
                # 再删除 session 节点
                await session.run(
                    """
                    MATCH (s:Session {uuid: $sid})
                    DETACH DELETE s
                    """,
                    sid=session_id
                )
                print(f"[INFO] Deleted session {session_id} from Neo4j")

            # 3. 删除 Graphiti Entity（group_id = session_id）
            async with self.neo4j.session() as session:
                entity_result = await session.run(
                    """
                    MATCH (e:Entity {group_id: $sid})
                    WITH e
                    OPTIONAL MATCH (e)-[r]-()
                    DELETE r
                    DELETE e
                    RETURN count(e) as deleted_entities
                    """,
                    sid=session_id
                )
                entity_record = await entity_result.single()
                deleted_count = entity_record.get("deleted_entities", 0) if entity_record else 0
                print(f"[INFO] Deleted {deleted_count} entities for session {session_id}")

            # 4. 删除 Zep memory
            try:
                await self.zep.memory.delete(session_id)
                print(f"[INFO] Deleted session {session_id} from Zep")
            except Exception as zep_err:
                print(f"[WARNING] Failed to delete Zep memory for {session_id}: {zep_err}")
                # 不抛出异常，因为 Neo4j 已删除成功

            # 5. 后台异步清理孤儿 Entity（不阻塞响应）
            asyncio.create_task(self._cleanup_orphan_entities())

            return True
        except ValueError:
            raise
        except Exception as e:
            print(f"[ERROR] Failed to delete session {session_id}: {e}")
            raise

    async def delete_bookmark(self, session_id: str, bookmark_id: str) -> bool:
        """删除 Bookmark"""
        try:
            async with self.neo4j.session() as session:
                result = await session.run(
                    """
                    MATCH (s:Session {uuid: $sid})-[:HAS_BOOKMARK]->(b:Bookmark {uuid: $bid})
                    DETACH DELETE b
                    RETURN count(b) as deleted
                    """,
                    sid=session_id, bid=bookmark_id
                )
                record = await result.single()
                if record and record.get("deleted", 0) > 0:
                    print(f"[INFO] Deleted bookmark {bookmark_id} from session {session_id}")
                    return True
                else:
                    print(f"[WARNING] Bookmark {bookmark_id} not found in session {session_id}")
                    return False
        except Exception as e:
            print(f"[ERROR] Failed to delete bookmark {bookmark_id}: {e}")
            raise

    async def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """获取 Session 的历史消息"""
        try:
            memory = await self.zep.memory.get(session_id)
            messages = []
            for msg in memory.messages or []:
                messages.append({
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": getattr(msg, 'created_at', None),
                })
            print(f"[INFO] Retrieved {len(messages)} messages for session {session_id}")
            return messages
        except Exception as e:
            print(f"[ERROR] Failed to get messages for session {session_id}: {e}")
            return []

    async def get_session_waypoints(self, session_id: str) -> List[Dict[str, Any]]:
        """获取 Session 的路标达成状态 (M3)"""
        print(f"[DEBUG] get_session_waypoints: session_id={session_id}")
        try:
            async with self.neo4j.session() as session:
                # 若没有任何 Waypoint 节点，直接返回，避免 UnknownPropertyKeyWarning
                count_result = await session.run(
                    "MATCH (w:Waypoint) RETURN count(w) as count"
                )
                count_record = await count_result.single()
                if count_record and (count_record.get("count") or 0) == 0:
                    return []

                query = """
                MATCH (s:Session {uuid: $sid})
                MATCH (n:Novel)-[:HAS_SESSION]->(s)
                MATCH (w:Waypoint {group_id: n.collection_name})
                OPTIONAL MATCH (s)-[r:TRIGGERED]->(w)
                RETURN w.title as title, 
                       w.description as description,
                       w.requirement as requirement,
                       w.order as order,
                       w.category as category,
                       r IS NOT NULL as reached,
                       r.at as reached_at
                ORDER BY w.order ASC
                """
                result = await session.run(query, sid=session_id)
                waypoints = [dict(record) async for record in result]
                print(f"[DEBUG] get_session_waypoints: found {len(waypoints)} waypoints for {session_id}")
                return waypoints
        except Exception as e:
            print(f"[ERROR] Failed to get waypoints for session {session_id}: {e}")
            return []

    async def _cleanup_orphan_entities(self) -> int:
        """
        清理孤儿 Entity 数据（group_id 没有对应 Session 的 Entity）
        用于处理竞态条件：删除 session 时，后台实体提取任务可能还在进行
        
        Returns:
            清理的 Entity 数量
        """
        try:
            async with self.neo4j.session() as session:
                result = await session.run(
                    """
                    // 找出所有不存在对应 Session 的 Entity（排除原始剧情线）
                    MATCH (e:Entity)
                    WHERE NOT e.group_id STARTS WITH 'novel_'
                    AND NOT EXISTS { MATCH (s:Session {uuid: e.group_id}) }
                    WITH e
                    OPTIONAL MATCH (e)-[r]-()
                    DELETE r, e
                    RETURN count(e) as cleaned
                    """
                )
                record = await result.single()
                cleaned = record.get("cleaned", 0) if record else 0
                if cleaned > 0:
                    print(f"[INFO] Cleaned up {cleaned} orphan entities")
                return cleaned
        except Exception as e:
            print(f"[ERROR] Failed to cleanup orphan entities: {e}")
            return 0
