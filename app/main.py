from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import engine, SessionLocal
from app.models import Base, ModuleDB
from app.schemas import (ModuleCreate, ModuleRead, ModuleUpdate)
import httpx
import os

POST_SERVICE_URL = os.getenv("POST_SERVICE_URL", "http://localhost:8000")

#Replacing @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
app = FastAPI(lifespan=lifespan)

# CORS (add this block)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # dev-friendly; tighten in prod
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def commit_or_rollback(db: Session, error_msg: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=error_msg)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/module", response_model=ModuleRead, status_code=status.HTTP_201_CREATED)
def add_module(payload: ModuleCreate, db: Session = Depends(get_db)):
    module = ModuleDB(**payload.model_dump())
    db.add(module)
    try:
        db.commit()
        db.refresh(module)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Module already exists")
    return module

@app.get("/api/module", response_model=list[ModuleRead])
def list_modules(db: Session = Depends(get_db)):
    stmt = select(ModuleDB).order_by(ModuleDB.id_module)
    #Useful for debugging
    result = db.execute(stmt)
    modules = result.scalars().all()
    return modules
    #return list(db.execute(stmt).scalars())

@app.get("/api/module/{id_module}", response_model=ModuleRead)
def get_module(id_module: int, db: Session = Depends(get_db)):
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return module

#Full replace module
@app.put("/api/module/{id_module}", response_model=ModuleRead, status_code=200)
def full_replace_module(id_module: int, payload: ModuleCreate, db: Session = Depends(get_db)):
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    module.id_module = payload.id_module
    module.name = payload.name
    try:
        db.commit()
        db.refresh(module)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Module ID already exists")
    return module

#Partial update module
@app.patch("/api/module/{id_module}", response_model=ModuleRead)
def partial_update_module(id_module: int, payload: ModuleUpdate, db: Session = Depends(get_db)):
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    update_payload = payload.model_dump(exclude_unset=True)
    for key, value in update_payload.items():
        setattr(module, key, value)
    try:
        db.commit()
        db.refresh(module)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Module ID already exists")
    return module

# DELETE a module
@app.delete("/api/module/{id_module}", status_code=204)
def delete_module(id_module: int, db: Session = Depends(get_db)) -> Response:
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    db.delete(module)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/api/proxy/posts")
def proxy_posts():
    with httpx.Client() as client:
        response = client.get(f"{POST_SERVICE_URL}/api/get-all-posts")
    return response.json()