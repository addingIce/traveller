# 穿越者引擎 (Traveller Engine)

基于大语言模型（LLM）与智能上下文记忆系统（Zep）的泛沉浸式小说内容消费与二次创作平台。

## 项目愿景

打破传统小说"作者写、读者看"的单向传递模式，将读者转化为"亲历者"或"变量"，允许用户以第一视角（角色扮演）或上帝视角（大纲改写）介入剧情。

## 核心功能

### 1. 小说智能解析与知识图谱可视化
- 支持长篇小说文本（百万字级别）的切片、向量化存储
- 自动提取人物、地点、派系、核心道具及其关系
- 美观的知识图谱展示人物关系网
- 支持动态查询角色背景故事和近期经历

### 2. 动态图谱生成与状态监控
- 实时实体提取监控，自动检测提取完成状态
- 智能状态恢复机制，后端重启后自动恢复小说状态
- 支持手动强制刷新图谱数据

### 3. 角色扮演与实时对话演进
- 自定义人设构建（扮演原著角色或创建原创角色）
- 行动/对话/心理活动三合一输入系统
- AI 导演调度，智能抛出事件和线索

### 4. 多分支剧情管理
- 时光回溯功能，支持返回任意剧情节点
- 平行宇宙分支，不同选择导向不同结局
- 大纲导向续写，AI 自动补全剧情

## 技术栈

### 后端
- **FastAPI**: Python Web 框架
- **Zep**: 长期记忆与上下文管理
- **Neo4j**: 图数据库，存储实体与关系
- **Graphiti**: 智能实体与关系提取
- **Docker**: 容器化部署

### 前端
- **React**: 用户界面框架
- **TypeScript**: 类型安全
- **TailwindCSS**: 样式框架
- **Vite**: 构建工具

### 核心依赖
- Zep Client (端口 8000)
- Neo4j (端口 7687)
- Graphiti (端口 8003)
- PostgreSQL (端口 5432)

## 快速开始

### 环境要求
- Python 3.9+
- Node.js 16+
- Docker & Docker Compose

### 安装步骤

1. **克隆仓库**
```bash
git clone git@github.com:addingIce/traveller.git
cd traveller
```

2. **启动 Docker 服务**
```bash
cd backend
docker-compose up -d
```

3. **配置后端**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows 使用 venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # 配置环境变量
```

4. **启动后端**
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

5. **配置前端**
```bash
cd frontend
npm install
```

6. **启动前端**
```bash
npm run dev
```

7. **访问应用**
打开浏览器访问 http://localhost:3000

### 服务管理

使用提供的脚本管理服务：
```bash
# 查看所有服务状态
bash scripts/manage.sh status

# 启动所有服务
bash scripts/manage.sh start

# 停止所有服务
bash scripts/manage.sh stop

# 重启所有服务
bash scripts/manage.sh restart

# 查看后端日志
bash scripts/manage.sh logs backend

# 健康检查
bash scripts/manage.sh health
```

## 项目结构

```
novel/
├── backend/           # 后端服务
│   ├── app/          # FastAPI 应用
│   ├── scripts/      # 辅助脚本
│   └── docker-compose.yml  # Docker 服务配置
├── frontend/         # 前端应用
│   ├── src/
│   │   ├── api/      # API 客户端
│   │   ├── components/  # React 组件
│   │   └── styles/   # 样式文件
│   └── package.json
├── data/            # 数据目录
│   └── novels/      # 小说文本文件
├── docs/            # 项目文档
└── scripts/         # 管理脚本
```

## 功能演示

### 上传小说
1. 点击"上传小说"按钮
2. 输入小说标题
3. 选择或粘贴小说文本
4. 系统自动处理并提取实体

### 查看知识图谱
1. 在作品档案库中选择小说
2. 切换到"知识图谱"标签
3. 浏览实体关系网络
4. 点击节点查看详细信息

### 剧情推演
1. 切换到"剧情时间线推演"标签
2. 输入行动或对话
3. AI 生成剧情推进
4. 查看分支剧情

## 配置说明

### 环境变量 (.env)
```bash
# Zep 配置
ZEP_API_URL=http://localhost:8000
ZEP_API_KEY=your_api_key

# Neo4j 配置
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# OpenAI 兼容接口
OPENAI_API_KEY=your_openai_key
OPENAI_BASE_URL=https://api.openai.com/v1

# 模型配置
MODEL_DIRECTOR=gpt-4o
MODEL_PARSER=gpt-4o-mini
```

### 前端配置
在配置页面可以调整：
- 模型选择
- 实体提取参数
- 图谱显示设置
- 剧情推演参数

## 开发指南

### 添加新功能
1. 后端: 在 `backend/app/api/endpoints/` 添加新的 API 端点
2. 前端: 在 `frontend/src/components/` 添加新的组件
3. 样式: 使用 TailwindCSS 类名

### 运行测试
```bash
# 后端测试
cd backend
python -m pytest

# 前端测试
cd frontend
npm test
```

## 常见问题

### Q: 小说上传后一直显示"处理中"？
A: 检查 Docker 服务是否正常运行，特别是 Zep 和 Graphiti 服务。

### Q: 知识图谱显示为空？
A: 可能是实体提取还在进行中，等待几分钟后再试。可以点击"强制刷新"按钮。

### Q: 如何重启服务？
A: 使用 `bash scripts/manage.sh restart` 命令。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## 许可证

Apache License 2.0

## 联系方式

- GitHub: https://github.com/addingIce/traveller