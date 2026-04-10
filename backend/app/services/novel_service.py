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

def smart_chunk_content(content: str, min_length: int = 100, max_length: int = 2000) -> list[str]:
    """
    智能分块函数：
    1. 优先按章节边界分割
    2. 段落优先合并
    3. 超长段落按句子分割（支持中英文标点）
    """
    chunks = []
    
    # 章节标题正则：第X章/节/回/部/卷，必须独立成行（前后为换行或文本边界）
    chapter_pattern = r'(^|\n)(第[一二三四五六七八九十百千万零\d]+[章节回部卷][^\n]*)'
    
    # 按章节分割
    chapter_parts = re.split(chapter_pattern, content, flags=re.MULTILINE)
    
    # 如果有章节结构，按章节处理
    if len(chapter_parts) > 1:
        current_chapter = ""
        i = 0
        while i < len(chapter_parts):
            part = chapter_parts[i]
            
            # 跳过空部分和前导换行符
            if not part or part == '\n':
                i += 1
                continue
            
            # 检查是否是章节标题（成对出现：前导符 + 标题）
            if i + 1 < len(chapter_parts) and re.match(r'第[一二三四五六七八九十百千万零\d]+[章节回部卷]', chapter_parts[i + 1] if i + 1 < len(chapter_parts) else ''):
                # 下一个是章节标题，当前是前导内容
                if current_chapter:
                    chunks.extend(_split_long_chunk(current_chapter, min_length, max_length))
                current_chapter = ""
                i += 1
                continue
            
            # 判断是否是章节标题
            if re.match(r'第[一二三四五六七八九十百千万零\d]+[章节回部卷]', part):
                # 保存上一章节
                if current_chapter:
                    chunks.extend(_split_long_chunk(current_chapter, min_length, max_length))
                current_chapter = part.strip()  # 不添加 \n\n，让标题和内容自然连接
            else:
                # 内容部分：添加换行后连接到 current_chapter
                if current_chapter:
                    current_chapter += "\n" + part.strip()
                else:
                    current_chapter = part.strip()
            
            i += 1
        
        # 处理最后一章节
        if current_chapter:
            chunks.extend(_split_long_chunk(current_chapter, min_length, max_length))
    else:
        # 无章节结构，按段落处理
        chunks = _split_by_paragraphs(content, min_length, max_length)
    
    return chunks


def _split_long_chunk(content: str, min_length: int, max_length: int) -> list[str]:
    """将超长内容按段落和句子分割，保持章节标题在开头"""
    if len(content) <= max_length:
        return [content] if len(content) >= min_length else []
    
    # 检查是否以章节标题开头
    chapter_title_pattern = re.compile(r'^(第[一二三四五六七八九十百千万零\d]+[章节回部卷][^\n]*)')
    title_match = chapter_title_pattern.match(content)
    chapter_title = title_match.group(1) if title_match else None
    
    # 如果有章节标题，从内容中分离出来
    if chapter_title:
        content_without_title = content[len(chapter_title):].lstrip('\n')
        return _split_by_paragraphs_with_title(content_without_title, chapter_title, min_length, max_length)
    
    return _split_by_paragraphs(content, min_length, max_length)


def _split_by_paragraphs_with_title(content: str, title: str, min_length: int, max_length: int) -> list[str]:
    """按段落分割，确保每个chunk都以章节标题开头"""
    chunks = []
    paragraphs = re.split(r'\n\s*\n', content)
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # 预留标题的空间
        available_length = max_length - len(title) - 1
        
        if len(current_chunk) + len(para) + 2 <= available_length:
            current_chunk += (("\n" if current_chunk else "") + para)
        else:
            # 保存当前 chunk（添加标题前缀）
            if current_chunk:
                chunks.append(title + "\n" + current_chunk)
            
            # 处理超长段落
            if len(para) > available_length:
                # 按句子分割
                sentences = _split_sentences(para)
                if any(len(s) > available_length for s in sentences):
                    sub_chunks = _split_by_characters(para, min_length - len(title) - 1, available_length)
                    for sub in sub_chunks:
                        chunks.append(title + "\n" + sub)
                    current_chunk = ""
                else:
                    temp_chunk = ""
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if not sentence:
                            continue
                        if len(temp_chunk) + len(sentence) + 1 <= available_length:
                            temp_chunk += (sentence + "。")
                        else:
                            if temp_chunk:
                                chunks.append(title + "\n" + temp_chunk.strip())
                            temp_chunk = sentence + "。"
                    current_chunk = temp_chunk.strip()
            else:
                current_chunk = para
    
    # 处理最后一个 chunk
    if current_chunk:
        chunks.append(title + "\n" + current_chunk)
    
    return chunks


def _split_by_paragraphs(content: str, min_length: int, max_length: int) -> list[str]:
    """按段落分割，段落优先合并"""
    chunks = []
    paragraphs = re.split(r'\n\s*\n', content)  # 按空行分割
    current_chunk = ""
    
    # 章节标题模式
    chapter_title_pattern = re.compile(r'^第[一二三四五六七八九十百千万零\d]+[章节回部卷]')
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # 检查是否是章节标题（短且匹配章节模式）
        is_chapter_title = len(para) < 50 and chapter_title_pattern.match(para)
        
        # 如果当前段落加上新段落不超过限制，合并
        if len(current_chunk) + len(para) + 2 <= max_length:
            current_chunk += (("\n\n" if current_chunk else "") + para)
        else:
            # 保存当前 chunk（但如果是短标题，不要单独保存，而是作为新chunk的开头）
            if len(current_chunk) >= min_length:
                # 检查 current_chunk 是否只是章节标题
                is_current_chapter_title = len(current_chunk) < 50 and chapter_title_pattern.match(current_chunk.strip())
                if is_current_chapter_title:
                    # 不单独保存标题，作为新chunk的开头
                    pass
                else:
                    chunks.append(current_chunk)
            
            # 处理超长段落
            if len(para) > max_length:
                # 如果有章节标题作为前缀，添加到内容前面
                prefix = current_chunk + "\n\n" if current_chunk and len(current_chunk) < 50 and chapter_title_pattern.match(current_chunk.strip()) else ""
                
                # 先尝试按句子分割
                sentences = _split_sentences(para)
                
                # 如果分割后仍有超长句子，按字符强制分割
                if any(len(s) > max_length for s in sentences):
                    sub_chunks = _split_by_characters(para, min_length, max_length)
                    if prefix and sub_chunks:
                        # 将标题添加到第一个子chunk
                        sub_chunks[0] = prefix + sub_chunks[0]
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    temp_chunk = prefix
                    for sentence in sentences:
                        sentence = sentence.strip()
                        if not sentence:
                            continue
                        if len(temp_chunk) + len(sentence) + 1 <= max_length:
                            temp_chunk += (sentence + "。")
                        else:
                            if len(temp_chunk) >= min_length:
                                chunks.append(temp_chunk.strip())
                            temp_chunk = sentence + "。"
                    current_chunk = temp_chunk.strip()
            else:
                # 如果是章节标题，保留作为新chunk的开头
                current_chunk = para
    
    # 处理最后一个 chunk
    if len(current_chunk) >= min_length:
        chunks.append(current_chunk)
    
    return chunks


def _split_by_characters(content: str, min_length: int, max_length: int) -> list[str]:
    """按字符强制分割（最后手段）"""
    chunks = []
    for i in range(0, len(content), max_length):
        chunk = content[i:i + max_length]
        if len(chunk) >= min_length:
            chunks.append(chunk)
    return chunks


def _split_sentences(text: str) -> list[str]:
    """按中英文句子分割"""
    # 支持中文句号、问号、感叹号、英文标点
    sentences = re.split(r'[。！？.!?\n]+', text)
    return [s for s in sentences if s.strip()]


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
            CASE WHEN e.attributes IS NULL OR e.attributes = '' THEN 0 ELSE 1 END AS attr_score
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
                    SET nr += properties(r)
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
                    SET nr += properties(r)
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

async def prune_minor_entities(
    collection_name: str,
    neo4j_driver,
    min_rel_score: int = 3
) -> dict[str, int]:
    """
    剪枝：移除关系数量过少且没有摘要的实体
    """
    if not neo4j_driver:
        return {"removed_entities": 0}

    async with neo4j_driver.session() as session:
        # 查询那些由 Zep 自动提取而非用户覆盖的实体
        # 且关系总数（出度+入度）小于阈值，且 summary 为空的实体
        prune_query = """
        MATCH (e:Entity {group_id: $group_id})
        WHERE (e.source IS NULL OR e.source <> 'override')
          AND (e.summary IS NULL OR trim(e.summary) = '')
        WITH e, size([(e)-[:RELATES_TO]-() | 1]) + size([(e)-[:MENTIONS]-() | 1]) AS total_rel
        WHERE total_rel < $min_rel
        DETACH DELETE e
        RETURN count(e) as removed_count
        """
        result = await session.run(prune_query, group_id=collection_name, min_rel=min_rel_score)
        record = await result.single()
        removed_count = record["removed_count"] if record else 0
        
        if removed_count > 0:
            print(f"[INFO] {collection_name}: Pruned {removed_count} minor entities (rel_score < {min_rel_score})")
            
        return {"removed_entities": removed_count}

async def deduplicate_relationships(
    collection_name: str,
    neo4j_driver
) -> dict[str, int]:
    """
    关系去重：合并相同两点之间语义重复的关系
    目前采用简单策略：相同两点间若存在多个 RELATES_TO，合并其 fact
    """
    if not neo4j_driver:
        return {"merged_rels": 0}

    async with neo4j_driver.session() as session:
        # 寻找相同起点和终点，且存在多个 RELATES_TO 关系的对
        find_query = """
        MATCH (s:Entity {group_id: $group_id})-[r:RELATES_TO]->(t:Entity {group_id: $group_id})
        WITH s, t, collect(r) as rels
        WHERE size(rels) > 1
        RETURN s.uuid as s_uuid, t.uuid as t_uuid, rels
        """
        result = await session.run(find_query, group_id=collection_name)
        
        merged_count = 0
        async for record in result:
            rels = record["rels"]
            s_uuid = record["s_uuid"]
            t_uuid = record["t_uuid"]
            
            # 合并 facts：去重 + 排序
            facts = []
            seen_facts = set()
            for r in rels:
                f = (r.get("fact") or "").strip()
                if f and f not in seen_facts:
                    facts.append(f)
                    seen_facts.add(f)
            
            if not facts:
                continue
            
            # 简单去重逻辑：如果一个 fact 是另一个的子串，则只保留长的
            # 注意：这在中文环境下效果较好，例如“是唐三的朋友”包含“朋友”
            facts.sort(key=len, reverse=True)
            final_facts = []
            for f in facts:
                if not any(f in other and f != other for other in final_facts):
                    final_facts.append(f)
            
            combined_fact = " ".join(final_facts)
            
            # 更新 master 边，删除其他边
            master_rel = rels[0]
            for i in range(1, len(rels)):
                await session.run(
                    "MATCH ()-[r:RELATES_TO {uuid: $uuid}]->() DELETE r",
                    uuid=rels[i]["uuid"]
                )
                merged_count += 1
            
            await session.run(
                "MATCH ()-[r:RELATES_TO {uuid: $uuid}]->() SET r.fact = $fact",
                uuid=master_rel["uuid"],
                fact=combined_fact
            )
            
        if merged_count > 0:
            print(f"[INFO] {collection_name}: Merged {merged_count} redundant relationships")
            
        return {"merged_rels": merged_count}

async def monitor_entity_extraction(
    collection_name: str,
    neo4j_driver,
    status_store: dict
) -> None:
    """监控实体提取进度，直到完成或小说被删除
    
    改进：使用 Episodic 节点计数判断处理是否完成，更精确可靠
    """
    if not neo4j_driver:
        return
    
    async def check_novel_exists() -> bool:
        """检查小说是否仍存在（未被删除）"""
        try:
            async with neo4j_driver.session() as session:
                result = await session.run(
                    "MATCH (n:Novel {collection_name: $cn}) RETURN n",
                    cn=collection_name
                )
                record = await result.single()
                return record is not None
        except Exception:
            return False
    
    async def get_episodic_count() -> int:
        """获取已创建的 Episodic 节点数"""
        try:
            async with neo4j_driver.session() as session:
                result = await session.run(
                    "MATCH (e:Episodic {group_id: $group_id}) RETURN COUNT(e) as count",
                    group_id=collection_name
                )
                record = await result.single()
                return record["count"] if record else 0
        except Exception:
            return 0
    
    async def get_entity_count() -> int:
        """获取实体数量"""
        try:
            async with neo4j_driver.session() as session:
                result = await session.run(
                    "MATCH (e:Entity {group_id: $group_id}) RETURN COUNT(DISTINCT e) as count",
                    group_id=collection_name
                )
                record = await result.single()
                return record["count"] if record else 0
        except Exception:
            return 0
    
    # 首先检查小说是否存在，不存在则直接退出
    if not await check_novel_exists():
        print(f"[INFO] {collection_name}: Novel not found, skipping monitoring (may have been deleted)")
        return
    
    # 仅当小说存在且 status_store 中没有条目时才创建（恢复场景）
    if collection_name not in status_store:
        status_store[collection_name] = {
            "status": "completed",
            "progress": 100.0,
            "chunks_processed": 0,
            "total_chunks": 0,
            "error_message": None,
            "created_at": datetime.utcnow().isoformat(),
            "title": collection_name,
        }
    
    max_check_count = 120  # 增加最大检查次数
    check_interval = 10
    stable_count = 0
    stable_threshold = 3  # 减少稳定阈值，因为 Episodic 已确认完成
    last_entity_count = 0
    all_episodics_created = False
    
    # 获取预期的总 chunk 数
    total_chunks = status_store.get(collection_name, {}).get("total_chunks", 0)
    print(f"[INFO] {collection_name}: Monitoring started, expecting {total_chunks} chunks")
    
    try:
        for i in range(max_check_count):
            await asyncio.sleep(check_interval)
            time_elapsed = (i + 1) * check_interval
            
            # 每次迭代检查小说是否已被删除
            if not await check_novel_exists():
                print(f"[INFO] {collection_name}: Novel deleted during monitoring, stopping")
                return
            
            # 检查 status_store 中是否仍有条目（被删除则退出）
            if collection_name not in status_store:
                print(f"[INFO] {collection_name}: Removed from status_store, stopping monitoring")
                return
            
            # 获取 Episodic 和 Entity 计数
            episodic_count = await get_episodic_count()
            entity_count = await get_entity_count()
            
            # 更新 status_store 中的进度
            if total_chunks > 0:
                status_store[collection_name]["chunks_processed"] = min(episodic_count, total_chunks)
                # 计算实体提取进度百分比
                progress = (episodic_count / total_chunks) * 100
                status_store[collection_name]["progress"] = round(progress, 1)
            
            # 阶段 1：等待所有 Episodic 节点创建完成
            if not all_episodics_created:
                if total_chunks > 0 and episodic_count >= total_chunks:
                    all_episodics_created = True
                    status_store[collection_name]["progress"] = 100.0  # 所有 Episodic 已创建
                    print(f"[INFO] {collection_name}: All {episodic_count} Episodic nodes created, watching entity stability")
                elif time_elapsed > 300:  # 5 分钟后假设已完成
                    all_episodics_created = True
                    status_store[collection_name]["progress"] = 100.0
                    print(f"[INFO] {collection_name}: Timeout waiting for Episodics ({episodic_count}/{total_chunks}), proceeding with entity check")
                else:
                    print(f"[DEBUG] {collection_name}: Waiting for Episodics ({episodic_count}/{total_chunks}), {entity_count} entities")
                    continue
            
            # 阶段 2：检查实体稳定性
            if entity_count == 0:
                print(f"[DEBUG] {collection_name}: Waiting for entities (Episodics: {episodic_count})")
                continue
            
            # 更新状态为 extracting
            if status_store.get(collection_name, {}).get("status") == "completed":
                status_store[collection_name]["status"] = "extracting"
                try:
                    async with neo4j_driver.session() as session:
                        await session.run(
                            "MATCH (n:Novel {collection_name: $cn}) SET n.status = 'extracting'",
                            cn=collection_name
                        )
                        print(f"[INFO] {collection_name}: Entity extraction started ({entity_count} entities)")
                except Exception as e:
                    print(f"[ERROR] {collection_name}: Failed to update status: {e}")
            
            # 检查实体稳定性
            if entity_count == last_entity_count:
                stable_count += 1
                print(f"[DEBUG] {collection_name}: Entity stable {stable_count}/{stable_threshold} ({entity_count} entities)")
                
                if stable_count >= stable_threshold:
                    # 实体稳定，执行去重并标记完成
                    status_store[collection_name]["stage"] = "dedup"
                    try:
                        # 阶梯式清理：去重 -> 关系合并 -> 剪枝
                        dedup_stats = await deduplicate_entities_in_collection(collection_name, neo4j_driver)
                        await deduplicate_relationships(collection_name, neo4j_driver)
                        await prune_minor_entities(collection_name, neo4j_driver)
                        
                        if dedup_stats.get("removed_nodes", 0) > 0:
                            print(
                                f"[INFO] {collection_name}: Deduplicated entities "
                                f"(groups={dedup_stats['merged_groups']}, removed={dedup_stats['removed_nodes']})"
                            )
                    except Exception as dedup_error:
                        print(f"[WARNING] {collection_name}: Post-processing failed: {dedup_error}")

                    status_store[collection_name]["status"] = "ready"
                    status_store[collection_name]["stage"] = "completed"
                    try:
                        async with neo4j_driver.session() as session:
                            await session.run(
                                "MATCH (n:Novel {collection_name: $cn}) SET n.status = 'ready'",
                                cn=collection_name
                            )
                            print(f"[INFO] {collection_name}: Entity extraction completed ({entity_count} entities)")
                    except Exception as e:
                        print(f"[ERROR] {collection_name}: Failed to update status: {e}")
                    return
            else:
                stable_count = 0
                print(f"[DEBUG] {collection_name}: Entity count changed ({last_entity_count} -> {entity_count})")
            
            last_entity_count = entity_count
        
        # 超时处理
        if last_entity_count > 0:
            status_store[collection_name]["stage"] = "dedup"
            try:
                # 阶梯式清理
                dedup_stats = await deduplicate_entities_in_collection(collection_name, neo4j_driver)
                await deduplicate_relationships(collection_name, neo4j_driver)
                await prune_minor_entities(collection_name, neo4j_driver)
                
                if dedup_stats.get("removed_nodes", 0) > 0:
                    print(
                        f"[INFO] {collection_name}: Deduplicated entities "
                        f"(groups={dedup_stats['merged_groups']}, removed={dedup_stats['removed_nodes']})"
                    )
            except Exception as dedup_error:
                print(f"[WARNING] {collection_name}: Post-processing failed: {dedup_error}")

            status_store[collection_name]["status"] = "ready"
            status_store[collection_name]["stage"] = "completed"
            try:
                async with neo4j_driver.session() as session:
                    await session.run(
                        "MATCH (n:Novel {collection_name: $cn}) SET n.status = 'ready'",
                        cn=collection_name
                    )
                    print(f"[INFO] {collection_name}: Entity extraction completed (timeout, {last_entity_count} entities)")
            except Exception as e:
                print(f"[ERROR] Failed to update Novel node status: {e}")
        else:
            print(f"[WARNING] {collection_name}: No entities extracted after monitoring")
    
    except asyncio.CancelledError:
        print(f"[INFO] {collection_name}: Monitoring task cancelled")
        raise  # 重新抛出以便 asyncio 正确处理
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
    # 延迟导入避免循环依赖
    from app.api.endpoints.config import runtime_config
    import time
    
    try:
        # 记录开始时间
        status_store[collection_name]["start_time"] = time.time()
        status_store[collection_name]["status"] = "processing"
        status_store[collection_name]["stage"] = "chunking"
        
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
        
        chunks = smart_chunk_content(
            content, 
            min_length=runtime_config.business.chunk_min_length, 
            max_length=runtime_config.business.chunk_max_length
        )
        total_chunks = len(chunks)
        status_store[collection_name]["total_chunks"] = total_chunks
        status_store[collection_name]["stage"] = "writing"  # 进入写入阶段

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
        
        batch_size = runtime_config.performance.batch_size
        batch_delay = runtime_config.performance.batch_delay
        total_batches = (len(chunks) - 1) // batch_size + 1
        
        # 断点续传：检查已处理的批次
        processed_chunks = status_store[collection_name].get("chunks_processed", 0)
        failed_batches = status_store[collection_name].get("failed_batches", [])
        start_batch_index = processed_chunks // batch_size
        
        # 记录开始时间用于预估
        import time
        start_time = time.time()
        
        for i in range(start_batch_index * batch_size, len(chunks), batch_size):
            batch_num = i // batch_size + 1
            
            # 跳过已成功的批次
            if batch_num <= start_batch_index and batch_num not in failed_batches:
                continue
            
            batch = chunks[i:i + batch_size]
            messages = [
                Message(
                    role_type="user",
                    role="",  # 空角色，避免 LLM 将"讲述者"识别为实体
                    content=chunk,
                )
                for chunk in batch
            ]
            
            retries = 3
            batch_success = False
            while retries > 0:
                try:
                    print(f"[DEBUG] Writing batch {batch_num}/{total_batches} to Zep...")
                    await client.memory.add(collection_name, messages=messages)
                    print(f"[DEBUG] Batch {batch_num} written successfully")
                    batch_success = True
                    break
                except Exception as e:
                    print(f"[DEBUG] Batch {batch_num} failed (retries left: {retries}): {e}")
                    retries -= 1
                    if retries == 0:
                        # 记录失败批次
                        if batch_num not in failed_batches:
                            failed_batches.append(batch_num)
                        status_store[collection_name]["failed_batches"] = failed_batches
                        raise e
                    await asyncio.sleep(2)
            
            # 成功后从失败列表移除
            if batch_success and batch_num in failed_batches:
                failed_batches.remove(batch_num)
                status_store[collection_name]["failed_batches"] = failed_batches
            
            processed = min(i + batch_size, total_chunks)
            status_store[collection_name]["chunks_processed"] = processed
            
            # 计算进度和预估时间
            progress = (processed / total_chunks) * 100
            status_store[collection_name]["progress"] = progress
            
            # 预估剩余时间
            elapsed = time.time() - start_time
            if processed > 0 and elapsed > 0:
                rate = processed / elapsed  # chunks per second
                remaining = total_chunks - processed
                eta = remaining / rate if rate > 0 else 0
                status_store[collection_name]["eta_seconds"] = int(eta)
            
            await asyncio.sleep(batch_delay)
        
        # 写入完成，直接进入实体提取阶段
        status_store[collection_name]["status"] = "extracting"
        status_store[collection_name]["stage"] = "extracting"
        status_store[collection_name]["progress"] = 0.0  # 实体提取进度从 0 开始
        
        if neo4j_driver:
            try:
                async with neo4j_driver.session() as session:
                    update_novel_query = """
                    MATCH (n:Novel {collection_name: $collection_name})
                    SET n.status = 'extracting'
                    RETURN n
                    """
                    await session.run(update_novel_query, collection_name=collection_name)
                    print(f"[INFO] Updated Novel node status to 'extracting': {collection_name}")
            except Exception as e:
                print(f"[ERROR] Failed to update Novel node status: {e}")
        
        # 启动监控任务并保存引用
        monitor_task = asyncio.create_task(monitor_entity_extraction(collection_name, neo4j_driver, status_store))
        status_store[collection_name]["_monitor_task"] = monitor_task
        
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
        zep_api_key = os.getenv("ZEP_API_KEY", "this_is_a_secret_key_for_zep_ce_1234567890")
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.get(
                f"{zep_api_url}/api/v1/session/{collection_name}/messages",
                params={"limit": 1},
                headers={"Authorization": f"Bearer {zep_api_key}"}
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
