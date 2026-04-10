import asyncio
import os
import uuid
from neo4j import AsyncGraphDatabase
from app.services.novel_service import (
    deduplicate_entities_in_collection,
    deduplicate_relationships,
    prune_minor_entities
)

# 配置
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"
TEST_GROUP = "test_opt_group_" + str(uuid.uuid4())[:8]

async def run_test():
    print(f"Starting test for group: {TEST_GROUP}")
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    try:
        async with driver.session() as session:
            # 1. 注入测试数据
            print("Injecting test data...")
            await session.run("""
                CREATE (e1:Entity {uuid: 'u1', name: '唐三', group_id: $group, created_at: '2024-01-01'})
                CREATE (e2:Entity {uuid: 'u2', name: '唐三', group_id: $group, created_at: '2024-01-02'})
                CREATE (e3:Entity {uuid: 'u3', name: '小舞', group_id: $group})
                CREATE (n1:Entity {uuid: 'n1', name: '老者', group_id: $group}) // 噪声实体
                
                // 冗余关系
                CREATE (e1)-[:RELATES_TO {uuid: 'r1', fact: '是小舞的朋友'}]->(e3)
                CREATE (e1)-[:RELATES_TO {uuid: 'r2', fact: '朋友'}]->(e3)
                CREATE (e1)-[:RELATES_TO {uuid: 'r3', fact: '认识小舞'}]->(e3)
                
                // 噪声实体关系 (低出度)
                CREATE (n1)-[:RELATES_TO {uuid: 'r4', fact: '路过'}]->(e1)
            """, group=TEST_GROUP)
            
            print("Data injected.")
            
            # 2. 执行去重
            print("Running deduplicate_entities_in_collection...")
            await deduplicate_entities_in_collection(TEST_GROUP, driver)
            
            # 3. 执行关系合并
            print("Running deduplicate_relationships...")
            await deduplicate_relationships(TEST_GROUP, driver)
            
            # 4. 执行剪枝
            print("Running prune_minor_entities...")
            await prune_minor_entities(TEST_GROUP, driver, min_rel_score=2)
            
            # 5. 验证结果
            print("\n--- Verification ---")
            
            # 检查实体数量
            res = await session.run("MATCH (e:Entity {group_id: $group}) RETURN e.name as name", group=TEST_GROUP)
            entities = [r["name"] for r in await res.data()]
            print(f"Entities remaining: {entities}")
            # 预期：唐三(合并后1路), 小舞(1个)。老者应该被剪枝（rel < 2）。
            
            # 检查关系
            res = await session.run("MATCH (s:Entity {group_id: $group})-[r:RELATES_TO]->(t) RETURN r.fact as fact", group=TEST_GROUP)
            rels = [r["fact"] for r in await res.data()]
            print(f"Relationships fact: {rels}")
            # 预期：事实应该合并为 "是小舞的朋友 认识小舞" (去重后的一条边)
            
    finally:
        # 清理
        async with driver.session() as session:
            await session.run("MATCH (e:Entity {group_id: $group}) DETACH DELETE e", group=TEST_GROUP)
        await driver.close()

if __name__ == "__main__":
    asyncio.run(run_test())
