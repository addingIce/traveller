# Traveller Engine

A pan-immersive novel content consumption and secondary creation platform based on Large Language Models (LLMs) and the intelligent context memory system (Zep).

## Project Vision

Breaking the traditional unidirectional "author writes, reader reads" mode of novels, transforming readers into "participants" or "variables", and allowing users to intervene in the plot from a first-person perspective (role-playing) or a god's perspective (outline rewriting).

## Preview

![Traveller Engine Screenshot](docs/screenshot.png)

## Current Progress

| Milestone | Status | Description |
|--------|------|------|
| M1: Data Infrastructure & Knowledge Extraction | ✅ Completed | Includes entity deduplication and pruning optimization |
| M2: Creative Inference Engine | ✅ Completed | Includes dual-track mode and safety protection |
| M3: Interactive Play Client | ⏳ Pending | Character creation flow, immersive UI |
| M4: DM Backend & Loop | ⏳ Pending | Dynamic graph overwriting, god's perspective |

## Core Features

### Implemented

- **Intelligent Novel Parsing & Knowledge Graph Visualization**
  - Supports intelligent chunking and vector storage of full-length novels (millions of words)
  - Automatically extracts characters, locations, factions, core items, and their relationships
  - Knowledge graph displays character relationship networks
  - Supports dynamic querying of character background stories and recent experiences

- **Dynamic Session Management**
  - Independent Zep Session for each player, isolated memory
  - Plot bookmark mechanism, record key nodes at any time
  - Parallel universe branching, start a new timeline from any node

- **Director AI Dual-Track Mode**
  - Sandbox Mode: High freedom, infer freely according to world rules
  - Convergence Mode: Plot waypoint guidance, smoothly return to the main storyline
  - Structured Output: Plot text + intention parsing + world impact + UI prompts

- **Narrative Pacing Controller**
  - Automatically detects plot stagnation (continuous idle chat with no progress)
  - Dynamically injects crises to drive the plot forward

- **Original Plot Timeline**
  - Automatic recognition and display of chapter structure
  - Supports starting a parallel universe from any chapter

### Planned

- **Character Creator**: Play as original characters or create new ones
- **Immersive Interactive UI**: Tabletop RPG style narrative interface
- **Plot Rewriting Panel**: Outline-oriented chapter generation
- **Dynamic Graph Overwriting**: Player actions dynamically impact the worldview in real-time

## Quick Start

### Environment Requirements
- Python 3.9+
- Node.js 16+
- Docker & Docker Compose

### Installation Steps

1. **Clone the repository**
```bash
git clone git@github.com:addingIce/traveller.git
cd traveller
```

2. **Start Docker services**
```bash
cd backend
docker-compose up -d
```

3. **Configure Backend**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows use venv\Scripts\activate
pip install -r requirements.txt
cp app/config.yaml.example app/config.yaml  # Configure parameters
```

4. **Start Backend**
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8088 --reload
```

5. **Configure Frontend**
```bash
cd frontend
npm install
```

6. **Start Frontend**
```bash
npm run dev
```

7. **Access the Application**
Open your browser and visit http://localhost:3000

### Service Management

Manage services using the provided scripts:
```bash
# Check status of all services
bash scripts/manage.sh status

# Start all services
bash scripts/manage.sh start

# Stop all services
bash scripts/manage.sh stop

# Restart all services
bash scripts/manage.sh restart
```

## Project Structure

```
novel/
├── backend/           # Backend services
│   ├── app/          # FastAPI application
│   │   ├── api/      # API endpoints
│   │   ├── services/ # Business logic
│   │   └── models/   # Data models
│   ├── scripts/      # Helper scripts
│   └── docker-compose.yml
├── frontend/         # Frontend application
│   └── src/
│       ├── api/      # API client
│       └── App.tsx   # Main application
├── data/             # Data directory
│   └── novels/       # Novel text files
└── docs/             # Project documentation
```

## Configuration Guide

### Backend Configuration (app/config.yaml)
```yaml
# LLM Configuration
llm:
  model_director: "gpt-4o"
  model_parser: "gpt-4o-mini"
  api_base: "https://api.openai.com/v1"

# Zep Configuration
zep:
  api_url: "http://localhost:8000"

# Neo4j Configuration
neo4j:
  uri: "bolt://localhost:7687"
  user: "neo4j"
  password: "your_password"
```

## Development Roadmap

### M1: Data Infrastructure & Knowledge Extraction ✅
- Text cleaning and vectorization pipeline
- Automatic knowledge graph extraction
- Frontend archive display

### M2: Creative Inference Engine ✅
- [x] Zep dynamic Session management
- [x] Plot bookmarks and parallel universe branching
- [x] Director AI dual-track mode
- [x] Narrative pacing controller
- [x] Original plot timeline interaction
- [x] Instruction injection defense layer
- [x] Automatic triggers for graph changes
- [x] Entity extraction and relationship deduplication optimization

### M3: Interactive Play Client ⏳
- Character creation flow development
- Immersive UI design
- Quick input system

### M4: DM Backend & Product Loop ⏳
- Dynamic graph overwriting mechanism
- God's perspective observation deck
- Safety protection and stress testing

## FAQ

### Q: Does it keep showing "Processing" after uploading a novel?
A: Check if Docker services are running properly, especially Zep and Graphiti services.

### Q: Is the knowledge graph showing empty?
A: Entity extraction might still be in progress, wait a few minutes and try again. You can click the "Force Refresh" button.

### Q: Cannot access Zep via browser?
A: Zep CE is a pure API service without a Web UI, this is normal. Just operate through the frontend interface of this project.

## Contributing

Issues and Pull Requests are welcome!

## License

Apache License 2.0

## Contact

- GitHub: https://github.com/addingIce/traveller
