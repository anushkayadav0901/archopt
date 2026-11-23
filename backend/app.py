"""ArchOpt FastAPI service: validation, persistence, and C++ engine orchestration."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).parent
DB_URL = f"sqlite:///{ROOT / 'archopt.db'}"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase): pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    project_type: Mapped[str] = mapped_column(String(60), default="Residential")
    plot_width: Mapped[float] = mapped_column(Float)
    plot_height: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(30), default="Draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    rooms: Mapped[list["Room"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    relationships: Mapped[list["SpatialRelationship"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    layouts: Mapped[list["Layout"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(120))
    room_type: Mapped[str] = mapped_column(String(60), default="Custom Room")
    required_area: Mapped[float] = mapped_column(Float)
    min_width: Mapped[float] = mapped_column(Float, default=2)
    min_height: Mapped[float] = mapped_column(Float, default=2)
    preferred_width: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="Medium")
    project: Mapped[Project] = relationship(back_populates="rooms")


class SpatialRelationship(Base):
    __tablename__ = "relationships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    room_a: Mapped[str] = mapped_column(String(120))
    room_b: Mapped[str] = mapped_column(String(120))
    relationship_type: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(Float, default=1)
    project: Mapped[Project] = relationship(back_populates="relationships")


class Layout(Base):
    __tablename__ = "layouts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    name: Mapped[str] = mapped_column(String(120))
    plan_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    selected: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    project: Mapped[Project] = relationship(back_populates="layouts")


class OptimizationJob(Base):
    __tablename__ = "optimization_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    algorithm: Mapped[str] = mapped_column(String(40))
    candidates_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    feasible_count: Mapped[int] = mapped_column(Integer, default=0)
    execution_ms: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="Queued")


def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    room_type: str = "Custom Room"
    required_area: float = Field(gt=0)
    min_width: float = Field(gt=0)
    min_height: float = Field(gt=0)
    preferred_width: float | None = Field(default=None, gt=0)
    preferred_height: float | None = Field(default=None, gt=0)
    priority: Literal["Low", "Medium", "High"] = "Medium"


class RelationshipIn(BaseModel):
    room_a: str
    room_b: str
    relationship_type: Literal["Must be adjacent", "Prefer adjacent", "Prefer nearby", "No preference", "Must be separated"]
    weight: float = Field(default=1, ge=0, le=10)


class ProjectIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    project_type: str = "Residential"
    plot_width: float = Field(gt=0, le=500)
    plot_height: float = Field(gt=0, le=500)
    rooms: list[RoomIn] = Field(default_factory=list)
    relationships: list[RelationshipIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def requirements_fit_plot(self):
        if sum(r.required_area for r in self.rooms) > self.plot_width * self.plot_height * .95:
            raise ValueError("Required room area exceeds 95% of the plot; reserve circulation space.")
        return self


class OptimizeIn(BaseModel):
    algorithm: Literal["Constraint-Based Generation", "Simulated Annealing", "Genetic Algorithm"] = "Simulated Annealing"
    candidate_count: int = Field(default=3, ge=1, le=5)
    iterations: int = Field(default=180, ge=10, le=5000)
    seed: int = Field(default=42, ge=0)


def room_out(r: Room) -> dict:
    return {key: getattr(r, key) for key in ("id", "name", "room_type", "required_area", "min_width", "min_height", "preferred_width", "preferred_height", "priority")}


def project_out(p: Project) -> dict:
    return {"id": p.id, "name": p.name, "project_type": p.project_type, "plot_width": p.plot_width, "plot_height": p.plot_height, "plot_area": p.plot_width*p.plot_height, "status": p.status, "created_at": p.created_at.isoformat(), "room_count": len(p.rooms), "layout_count": len(p.layouts), "rooms": [room_out(r) for r in p.rooms], "relationships": [{"id":x.id,"room_a":x.room_a,"room_b":x.room_b,"relationship_type":x.relationship_type,"weight":x.weight} for x in p.relationships]}


def layout_out(layout: Layout) -> dict:
    return {"id":layout.id, "project_id":layout.project_id, "name":layout.name, "plan":json.loads(layout.plan_json), "metrics":json.loads(layout.metrics_json), "selected":bool(layout.selected), "created_at":layout.created_at.isoformat()}


app = FastAPI(title="ArchOpt API", version="1.0.0", description="Deterministic architectural layout optimization APIs")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def init_database(): Base.metadata.create_all(engine)


@app.get("/api/health")
def health(): return {"status":"ok", "engine": (ROOT / "engine" / ("archopt_engine.exe" if sys.platform.startswith("win") else "archopt_engine")).exists()}


@app.post("/api/auth/login")
def login(payload: dict):
    if not payload.get("username"): raise HTTPException(422, "Username is required")
    if payload.get("username") != "demo" or payload.get("password") != "12345678": raise HTTPException(401, "Incorrect demo credentials")
    return {"token":"demo-session", "username":"demo", "message":"Demo authentication only; not for production."}


@app.post("/api/auth/logout", status_code=204)
def logout(): return None


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    layouts = db.scalars(select(Layout)).all()
    efficiencies = [json.loads(x.metrics_json).get("efficiency",0) for x in layouts]
    return {"total_projects":len(projects), "generated_layouts":len(layouts), "average_efficiency":round(sum(efficiencies)/len(efficiencies),1) if efficiencies else 0, "completed_optimizations":sum(p.status=="Optimized" for p in projects), "recent_projects":[project_out(p) for p in projects[:5]], "efficiency_series":[{"name":x.name,"efficiency":json.loads(x.metrics_json).get("efficiency",0)} for x in layouts[-7:]]}


@app.get("/api/projects")
def projects(search: str = "", db: Session = Depends(get_db)):
    rows = db.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [project_out(p) for p in rows if search.lower() in p.name.lower()]


@app.post("/api/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectIn, db: Session = Depends(get_db)):
    if db.scalar(select(Project).where(Project.name == payload.name)): raise HTTPException(409, "A project with this name already exists")
    p = Project(name=payload.name, project_type=payload.project_type, plot_width=payload.plot_width, plot_height=payload.plot_height)
    p.rooms = [Room(**r.model_dump()) for r in payload.rooms]; p.relationships = [SpatialRelationship(**r.model_dump()) for r in payload.relationships]
    db.add(p); db.commit(); db.refresh(p); return project_out(p)


@app.get("/api/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, "Project not found")
    return project_out(p)


@app.put("/api/projects/{project_id}")
def update_project(project_id: int, payload: ProjectIn, db: Session = Depends(get_db)):
    p = db.get(Project, project_id)
    if not p: raise HTTPException(404, "Project not found")
    p.name,p.project_type,p.plot_width,p.plot_height = payload.name,payload.project_type,payload.plot_width,payload.plot_height
    p.rooms = [Room(**r.model_dump()) for r in payload.rooms]; p.relationships = [SpatialRelationship(**r.model_dump()) for r in payload.relationships]
    db.commit(); db.refresh(p); return project_out(p)


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"Project not found")
    db.delete(p); db.commit(); return None


@app.get("/api/projects/{project_id}/rooms")
def rooms(project_id:int, db: Session=Depends(get_db)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"Project not found")
    return [room_out(r) for r in p.rooms]


@app.post("/api/projects/{project_id}/rooms", status_code=201)
def add_room(project_id:int, payload:RoomIn, db:Session=Depends(get_db)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    r=Room(project_id=project_id,**payload.model_dump()); db.add(r); db.commit(); db.refresh(r); return room_out(r)


@app.put("/api/rooms/{room_id}")
def edit_room(room_id:int,payload:RoomIn,db:Session=Depends(get_db)):
    r=db.get(Room,room_id)
    if not r: raise HTTPException(404,"Room not found")
    for k,v in payload.model_dump().items(): setattr(r,k,v)
    db.commit(); return room_out(r)


@app.delete("/api/rooms/{room_id}",status_code=204)
def remove_room(room_id:int,db:Session=Depends(get_db)):
    r=db.get(Room,room_id)
    if not r: raise HTTPException(404,"Room not found")
    db.delete(r);db.commit();return None


def run_engine(project_id: int, job_id: str, options: dict):
    db=SessionLocal(); job=db.get(OptimizationJob,job_id); project=db.get(Project,project_id)
    if not job or not project: return
    job.status="running"; job.message="C++ engine is evaluating candidates"; db.commit(); started=time.perf_counter()
    try:
        binary=ROOT/"engine"/("archopt_engine.exe" if sys.platform.startswith("win") else "archopt_engine")
        if not binary.exists(): subprocess.run([sys.executable,"build_engine.py"],cwd=ROOT,check=True,capture_output=True,text=True)
        request={"plot":{"width":project.plot_width,"height":project.plot_height},"rooms":[room_out(r) for r in project.rooms], **options}
        completed=subprocess.run([str(binary)],input=json.dumps(request),cwd=ROOT,text=True,capture_output=True,check=True,timeout=30)
        output=json.loads(completed.stdout)
        layouts=output.get("layouts",[])
        for index,item in enumerate(layouts):
            metrics={"efficiency":round(item["efficiency"],1),"adjacency":round(item["adjacency"],1),"circulation":round(item["circulation"],1),"accessibility":round(max(0,item["circulation"]-5),1),"cost":round(item["cost"],2),"violations":[] if item["feasible"] else ["Candidate does not meet all hard geometry constraints"]}
            db.add(Layout(project_id=project_id,name=f"Alternative {index+1}",plan_json=json.dumps({"rooms":item["rooms"]}),metrics_json=json.dumps(metrics)))
        job.status="completed";job.message="Optimization completed";job.candidates_evaluated=output.get("evaluated",0);job.feasible_count=sum(1 for x in layouts if x["feasible"]);job.execution_ms=round((time.perf_counter()-started)*1000);project.status="Optimized";db.commit()
    except Exception as exc:
        job.status="failed";job.message=str(exc);job.execution_ms=round((time.perf_counter()-started)*1000);db.commit()
    finally: db.close()


@app.post("/api/projects/{project_id}/optimize",status_code=202)
def optimize(project_id:int,payload:OptimizeIn,tasks:BackgroundTasks,db:Session=Depends(get_db)):
    p=db.get(Project,project_id)
    if not p: raise HTTPException(404,"Project not found")
    if not p.rooms: raise HTTPException(422,"Add at least one room before optimizing")
    job=OptimizationJob(id=str(uuid.uuid4()),project_id=project_id,algorithm=payload.algorithm);db.add(job);db.commit()
    tasks.add_task(run_engine,project_id,job.id,payload.model_dump()); return {"job_id":job.id,"status":job.status}


@app.get("/api/optimization/{job_id}")
def job_status(job_id:str,db:Session=Depends(get_db)):
    j=db.get(OptimizationJob,job_id)
    if not j: raise HTTPException(404,"Optimization job not found")
    return {"id":j.id,"status":j.status,"algorithm":j.algorithm,"candidates_evaluated":j.candidates_evaluated,"feasible_count":j.feasible_count,"execution_ms":j.execution_ms,"message":j.message}


@app.post("/api/optimization/{job_id}/cancel")
def cancel_job(job_id:str,db:Session=Depends(get_db)):
    j=db.get(OptimizationJob,job_id)
    if not j: raise HTTPException(404,"Optimization job not found")
    if j.status in {"completed","failed"}: raise HTTPException(409,"A finished job cannot be cancelled")
    j.status="cancelled";j.message="Cancelled before completion";db.commit();return {"status":"cancelled"}


@app.get("/api/projects/{project_id}/layouts")
def project_layouts(project_id:int,db:Session=Depends(get_db)):
    if not db.get(Project,project_id): raise HTTPException(404,"Project not found")
    return [layout_out(x) for x in db.scalars(select(Layout).where(Layout.project_id==project_id).order_by(Layout.created_at.desc())).all()]


@app.get("/api/layouts/{layout_id}")
def get_layout(layout_id:int,db:Session=Depends(get_db)):
    x=db.get(Layout,layout_id)
    if not x: raise HTTPException(404,"Layout not found")
    return layout_out(x)


@app.put("/api/layouts/{layout_id}")
def update_layout(layout_id:int,payload:dict,db:Session=Depends(get_db)):
    x=db.get(Layout,layout_id)
    if not x: raise HTTPException(404,"Layout not found")
    if payload.get("selected"):
        db.query(Layout).filter(Layout.project_id==x.project_id).update({Layout.selected:0});x.selected=1
    if "plan" in payload: x.plan_json=json.dumps(payload["plan"])
    db.commit();return layout_out(x)


@app.delete("/api/layouts/{layout_id}",status_code=204)
def delete_layout(layout_id:int,db:Session=Depends(get_db)):
    x=db.get(Layout,layout_id)
    if not x:raise HTTPException(404,"Layout not found")
    db.delete(x);db.commit();return None


def validate_layout(layout: Layout, project: Project) -> list[dict]:
    rooms=layout_out(layout)["plan"].get("rooms",[]); issues=[]
    for i,r in enumerate(rooms):
        if r["x"]<0 or r["y"]<0 or r["x"]+r["width"]>project.plot_width or r["y"]+r["height"]>project.plot_height: issues.append({"type":"boundary","room":r["name"],"passed":False,"message":"Room extends beyond plot boundary"})
        for other in rooms[i+1:]:
            overlap=r["x"]<other["x"]+other["width"] and r["x"]+r["width"]>other["x"] and r["y"]<other["y"]+other["height"] and r["y"]+r["height"]>other["y"]
            if overlap: issues.append({"type":"overlap","room":r["name"],"passed":False,"message":f"Overlaps {other['name']}"})
    return [{"type":"geometry","passed":True,"message":"All rooms are inside the plot and non-overlapping"}] if not issues else issues


@app.post("/api/layouts/{layout_id}/validate")
def validate(layout_id:int,db:Session=Depends(get_db)):
    x=db.get(Layout,layout_id)
    if not x: raise HTTPException(404,"Layout not found")
    return {"issues":validate_layout(x,x.project)}


@app.get("/api/layouts/{layout_id}/metrics")
def metrics(layout_id:int,db:Session=Depends(get_db)):
    x=db.get(Layout,layout_id)
    if not x: raise HTTPException(404,"Layout not found")
    return json.loads(x.metrics_json)


@app.get("/api/layouts/{layout_id}/circulation")
def circulation(layout_id:int,db:Session=Depends(get_db)):
    x=db.get(Layout,layout_id)
    if not x: raise HTTPException(404,"Layout not found")
    rooms=json.loads(x.plan_json).get("rooms",[]); edges=[]
    for i,r in enumerate(rooms):
        if i: edges.append({"from":rooms[0]["name"],"to":r["name"],"distance":round(abs(r["x"]-rooms[0]["x"])+abs(r["y"]-rooms[0]["y"]),2)})
    return {"entrance_room":rooms[0]["name"] if rooms else None,"connected_rooms":len(rooms),"disconnected_rooms":[],"paths":edges}


SAMPLES = {
 "Community Centre": ("Community Centre",30,20,[('Reception',30,5,5),('Classroom 1',48,6,6),('Classroom 2',48,6,6),('Office',20,4,4),('Toilet 1',12,3,3),('Toilet 2',12,3,3),('Storage',12,3,3),('Multipurpose Hall',100,10,8),('Corridor',40,2,2)]),
 "Neighbourhood Office": ("Office",24,18,[('Reception',20,4,4),('Open Office',72,7,6),('Meeting Room',24,4,4),('Manager Office',18,3,3),('Toilet',10,2,2),('Storage',8,2,2)]),
 "Compact Home": ("Residential",18,14,[('Living Room',28,5,4),('Bedroom',20,4,4),('Kitchen',14,3,3),('Dining Area',16,3,3),('Toilet',8,2,2),('Balcony',8,2,2)]),
 "Learning Studio": ("Educational",28,16,[('Reception',24,4,4),('Studio A',54,6,6),('Studio B',54,6,6),('Faculty Room',20,4,4),('Toilet',12,3,3),('Storage',10,2,2)]) }

@app.get("/api/samples")
def samples(): return [{"name":k,"project_type":v[0],"plot_width":v[1],"plot_height":v[2],"room_count":len(v[3])} for k,v in SAMPLES.items()]


@app.post("/api/samples/{sample_name}", status_code=201)
def load_sample(sample_name:str,db:Session=Depends(get_db)):
    if sample_name not in SAMPLES: raise HTTPException(404,"Sample not found")
    kind,w,h,rooms=SAMPLES[sample_name]; name=f"{sample_name} Demo"
    existing=db.scalar(select(Project).where(Project.name==name))
    if existing:return project_out(existing)
    p=Project(name=name,project_type=kind,plot_width=w,plot_height=h,status="Ready")
    p.rooms=[Room(name=n,room_type=n,required_area=a,min_width=mw,min_height=mh) for n,a,mw,mh in rooms]
    db.add(p);db.commit();db.refresh(p);return project_out(p)


@app.post("/api/requirements/parse")
def parse_requirements(payload:dict):
    # Transparent deterministic helper; it never claims to be an LLM parser.
    text=str(payload.get("text", "")).lower(); detected=[]
    for term,area in [("bedroom",18),("kitchen",12),("office",20),("classroom",42),("reception",20),("toilet",8)]:
        if term in text: detected.append({"name":term.title(),"room_type":term.title(),"required_area":area,"min_width":3,"min_height":3,"priority":"Medium"})
    return {"rooms":detected,"note":"Keyword-assisted draft; review before saving."}
