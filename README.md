# ArchOpt

**Intelligent Architectural Space & Circulation Optimizer** - a full-stack, deterministic floor-plan exploration tool for rectangular spaces.

ArchOpt turns a spatial brief into persistent requirements, generates feasible alternatives through a C++20 optimization engine, and presents them in a responsive Next.js workspace.

## Architecture

```text
Next.js + TypeScript  ->  FastAPI + SQLite  ->  C++20 optimization engine
```

The engine owns the geometry, candidate evaluation, weighted relationship scoring, Dijkstra circulation graph, and parallel candidate scoring. The API validates and persists data; the UI is a practical editor and analysis workspace.

## Quick start (Windows PowerShell)

```powershell
# Terminal 1
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python build_engine.py
uvicorn app:app --reload --port 8000

# Terminal 2
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, then sign in with `demo` / `12345678`.

## Highlights

- SQLite persistence, project CRUD, dynamic rooms and weighted relationships
- Seedable Community Centre, Office, Compact Home, and Learning Studio samples
- C++20 constraint placement, simulated-annealing perturbation, GA-inspired population search, and parallel scoring
- SVG floor-plan workspace with selectable rooms, grid, zoom, undo, validation and metric panels
- Side-by-side alternatives, circulation diagnostics and constraint validation
- REST API docs at `http://localhost:8000/docs`

## Tests

```powershell
cd backend
pytest -q
g++ -std=c++20 -O2 engine/archopt_engine.cpp -o engine/archopt_engine.exe
echo '{"plot":{"width":20,"height":15},"rooms":[{"id":1,"name":"Studio","required_area":24,"min_width":4,"min_height":4}]}' | .\engine\archopt_engine.exe
```
