import uuid
import time
import re
import os
import httpx
from datetime import datetime
from typing import List, Optional, Dict, Any
from zep_python.client import AsyncZep
from zep_python import Message
from neo4j import AsyncDriver

class SessionService:
    def __init__(self, zep_client: AsyncZep, neo4j_driver: AsyncDriver):
        self.zep = zep_client
        self.neo4j = neo4j_driver

    async def create_session(self, novel_id: str, user_id: str, session_name: str, parent_session_id: Optional[str] = None) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        
        try:
            async with self.neo4j.session() as session:
                query = """
                MATCH (n:Novel {collection_name: $novel_id})
                CREATE (s:Session {
                    uuid: $session_id,
                    name: $name,
                    user_id: $user_id,
                    created_at: $created_at,
                    last_interaction_at: $created_at
                })
                CREATE (n)-[:HAS_SESSION]->(s)
                RETURN s.uuid as id
                """
                params = {
                    "novel_id": novel_id,
                    "session_id": session_id,
                    "name": session_name,
                    "user_id": user_id,
                    "created_at": created_at
                }
                
                if parent_session_id:
                    # Append to the query BEFORE return
                    query = query.replace("RETURN s.uuid as id", "")
                    query += """
                    WITH s
                    MATCH (p:Session {uuid: $parent_id})
                    CREATE (p)-[:BRANCHED_TO]->(s)
                    SET s.parent_session_id = $parent_id
                    RETURN s.uuid as id
                    """
                    params["parent_id"] = parent_session_id

                result = await session.run(query, **params)
                await result.single()
        except Exception as ne:
            print(f"[ERROR] Neo4j session creation failed: {ne}")
            import traceback
            traceback.print_exc()
            raise ne

        # 2. Initialize Zep Session
        await self.zep.memory.add_session(
            session_id=session_id,
            metadata={
                "novel_id": novel_id,
                "user_id": user_id,
                "name": session_name,
                "parent_id": parent_session_id or ""
            }
        )
        
        return {
            "session_id": session_id,
            "novel_id": novel_id,
            "user_id": user_id,
            "session_name": session_name,
            "created_at": created_at,
            "parent_session_id": parent_session_id
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
                   s.parent_session_id as parent_session_id, 
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
            checkpoint_id = memory.messages[-1].uuid # Use last message UUID as checkpoint

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
        for msg in source_memory.messages:
            messages_to_copy.append(Message(
                role=msg.role,
                role_type=msg.role_type,
                content=msg.content
            ))
            if msg.uuid == checkpoint_id:
                break
        
        if messages_to_copy:
            await self.zep.memory.add(new_session_id, messages=messages_to_copy)

        return new_session_info

    async def extract_chapters(self, novel_id: str) -> List[Dict[str, Any]]:
        # In this architecture, "novel_id" is actually the session_id for the original ingestion
        # The original storyline messages have role="讲述者"
        try:
            session_id = novel_id if novel_id.startswith("novel_") else f"novel_{novel_id}"
            messages = []
            # 1) Prefer Zep HTTP API (more stable)
            try:
                zep_api_url = os.getenv("ZEP_API_URL", "http://localhost:8000")
                async with httpx.AsyncClient(timeout=10.0) as http_client:
                    resp = await http_client.get(
                        f"{zep_api_url}/sessions/{session_id}/messages",
                        params={"limit": 200}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_messages = data.get("messages") or []
                        for msg in raw_messages:
                            content = (msg.get("content") or "").strip()
                            if not content:
                                continue
                            messages.append(type("Msg", (), {"uuid": msg.get("uuid"), "content": content})())
            except Exception as http_err:
                print(f"Error extracting chapters from Zep HTTP: {http_err}")

            # 2) Fallback to Zep SDK
            if not messages:
                try:
                    memory = await self.zep.memory.get(session_id)
                    messages = memory.messages or []
                except Exception as sdk_err:
                    print(f"Error extracting chapters from Zep SDK: {sdk_err}")
            
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
                
                # Check first line
                first_line = content.split('\n')[0].strip()
                match = chapter_pattern.match(first_line)
                
                # If matched or if it's a very short first line (likely a title)
                if match or (len(first_line) < 30 and first_line.endswith(('：', ':'))):
                    title = first_line
                    # Remove some common symbols from title
                    title = re.sub(r"^[#\s\*\-]+", "", title).strip()
                    
                    preview = content[:200] + "..." if len(content) > 200 else content
                    chapters.append({
                        "id": msg.uuid,
                        "title": title or f"章节 {len(chapters) + 1}",
                        "content_preview": preview,
                        "order": len(chapters) + 1
                    })
            
            # If no chapters found via regex, we might just return the first few chunks as "segments"
            if not chapters and messages:
                for i, msg in enumerate(messages[:10]): # Limit to first 10 for preview
                    chapters.append({
                        "id": msg.uuid,
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
                            LIMIT 10
                            """,
                            group_id=session_id
                        )
                        episodic = [dict(record) async for record in result]
                    for i, record in enumerate(episodic):
                        content = (record.get("content") or "").strip()
                        if not content:
                            continue
                        chapters.append({
                            "id": record.get("uuid") or f"episodic-{i+1}",
                            "title": f"片段 {i+1}",
                            "content_preview": content[:200] + ("..." if len(content) > 200 else ""),
                            "order": i + 1
                        })
                except Exception as neo_err:
                    print(f"Error extracting chapters from Neo4j: {neo_err}")
                    
            return chapters
        except Exception as e:
            print(f"Error extracting chapters: {e}")
            return []
