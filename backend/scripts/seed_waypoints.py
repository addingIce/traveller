
import os
import uuid
from neo4j import GraphDatabase
from dotenv import load_dotenv

def insert_waypoints():
    load_dotenv()
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password123")
    
    novel_id = "novel_1773487373_135dbcb0"
    
    waypoints = [
        {
            "title": "初遇导师",
            "requirement": None,
            "description": "在小镇广场，玩家会遇到一位疯疯癫癫的老人，他其实是前任穿越者。",
            "order": 1,
            "category": "main_quest"
        },
        {
            "title": "遗迹开启",
            "requirement": "初遇导师",
            "description": "玩家从导师处获得线索，进入后山山洞，时空遗迹的大门将缓缓开启。",
            "order": 2,
            "category": "main_quest"
        },
        {
            "title": "时空决战",
            "requirement": "遗迹开启",
            "description": "在虚空的尽头，玩家必须阻止反派篡改历史，修复崩塌的时空。",
            "order": 3,
            "category": "main_quest"
        }
    ]
    
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        # 先清理该小说的旧路标逻辑（可选）
        session.run("MATCH (w:Waypoint {group_id: $group_id}) DELETE w", group_id=novel_id)
        
        for wp in waypoints:
            session.run("""
                MERGE (w:Waypoint {title: $title, group_id: $group_id})
                SET w.uuid = $uuid,
                    w.requirement = $requirement,
                    w.description = $description,
                    w.order = $order,
                    w.category = $category,
                    w.created_at = datetime()
            """, title=wp["title"], group_id=novel_id, uuid=str(uuid.uuid4()), 
                requirement=wp["requirement"], description=wp["description"],
                order=wp.get("order"), category=wp.get("category"))
            print(f"Inserted/Merged Waypoint: {wp['title']}")
            
    driver.close()

if __name__ == "__main__":
    insert_waypoints()
