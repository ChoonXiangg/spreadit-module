from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from app.database import engine, SessionLocal
from app.models import Base, ModuleDB
from app.schemas import (ModuleCreate, ModuleRead, ModuleUpdate)
import httpx
import os

import os
import aio_pika
import json

POST_SERVICE_URL = os.getenv("POST_SERVICE_URL", "http://localhost:8000")
RABBIT_URL = os.getenv("RABBIT_URL")

async def publish_event(routing_key: str, data: dict):
    if not RABBIT_URL:
        return
        
    try:
        connection = await aio_pika.connect_robust(RABBIT_URL)
        async with connection:
            channel = await connection.channel()
            exchange = await channel.declare_exchange("events_topic", aio_pika.ExchangeType.TOPIC)
            
            message = aio_pika.Message(
                body=json.dumps(data).encode(),
                content_type="application/json"
            )
            await exchange.publish(message, routing_key=routing_key)
    except Exception as e:
        print(f"Failed to publish event {routing_key}: {e}")

import asyncio

async def process_course_deleted(data: dict):
    course_id = data.get("course_id")
    if not course_id:
        return

    print(f"Processing course deletion for course_id: {course_id}")
    db = SessionLocal()
    try:
        # Delete modules linked to this course
        # Note: course_id in database is String, so ensure we query correctly
        modules = db.query(ModuleDB).filter(ModuleDB.course_id == str(course_id)).all()
        for module in modules:
            # Important: Publish event BEFORE deleting so downstream services (Post Service) can clean up
            await publish_event("module.deleted", {"module_id": module.id_module})
            db.delete(module)
        
        db.commit()
        print(f"Removed {len(modules)} modules for course {course_id}")
    except Exception as e:
        print(f"Error processing course deletion: {e}")
        db.rollback()
    finally:
        db.close()

async def consume_events():
    if not RABBIT_URL:
        print("RABBIT_URL not set, skipping consumer")
        return

    while True:
        try:
            connection = await aio_pika.connect_robust(RABBIT_URL)
            async with connection:
                channel = await connection.channel()
                
                await channel.declare_exchange("events_topic", aio_pika.ExchangeType.TOPIC)
                queue = await channel.declare_queue("module_service_queue", durable=True)
                
                # Bind to course.deleted
                await queue.bind("events_topic", routing_key="course.deleted")
                
                print("Module Service Consumer Started")
                
                async with queue.iterator() as iterator:
                    async for message in iterator:
                        async with message.process():
                            data = json.loads(message.body)
                            if message.routing_key == "course.deleted":
                                await process_course_deleted(data)

        except asyncio.CancelledError:
            print("Consumer cancelled")
            break
        except Exception as e:
            print(f"Consumer connection lost: {e}, retrying in 5s...")
            await asyncio.sleep(5)

#Replacing @app.on_event("startup")
@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(consume_events())
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
async def add_module(payload: ModuleCreate, db: Session = Depends(get_db)):
    module = ModuleDB(**payload.model_dump())
    db.add(module)
    try:
        db.commit()
        db.refresh(module)
        await publish_event("module.created", {
            "module_id": module.id_module, 
            "name": module.name,
            "course_id": module.course_id
        })
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Module already exists")
    return module

from typing import Optional

# ... imports ...

@app.get("/api/module", response_model=list[ModuleRead])
def list_modules(course_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(ModuleDB)
    if course_id is not None:
        stmt = stmt.where(ModuleDB.course_id == course_id)
    stmt = stmt.order_by(ModuleDB.id_module)
    #Useful for debugging
    result = db.execute(stmt)
    modules = result.scalars().all()
    return modules

@app.get("/api/module/{id_module}", response_model=ModuleRead)
def get_module(id_module: int, db: Session = Depends(get_db)):
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return module

#Full replace module
@app.put("/api/module/{id_module}", response_model=ModuleRead, status_code=200)
async def full_replace_module(id_module: int, payload: ModuleCreate, db: Session = Depends(get_db)):
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    module.id_module = payload.id_module
    module.name = payload.name
    module.course_id = payload.course_id
    try:
        db.commit()
        db.refresh(module)
        await publish_event("module.replaced", {
            "module_id": module.id_module, 
            "name": module.name,
            "course_id": module.course_id
        })
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Module ID already exists")
    return module

#Partial update module
@app.patch("/api/module/{id_module}", response_model=ModuleRead)
async def partial_update_module(id_module: int, payload: ModuleUpdate, db: Session = Depends(get_db)):
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
        await publish_event("module.updated", {"module_id": module.id_module, "updates": update_payload})
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Module ID already exists")
    return module

# DELETE a module
@app.delete("/api/module/{id_module}", status_code=204)
async def delete_module(id_module: int, db: Session = Depends(get_db)) -> Response:
    stmt = select(ModuleDB).where(ModuleDB.id_module == id_module)
    module = db.execute(stmt).scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    db.delete(module)
    db.commit()
    await publish_event("module.deleted", {"module_id": id_module})
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@app.get("/api/proxy/posts")
def proxy_posts():
    with httpx.Client() as client:
        response = client.get(f"{POST_SERVICE_URL}/api/get-all-posts")
    return response.json()

@app.post("/api/modules/{module_id}/enroll/{user_id}", status_code=status.HTTP_200_OK)
async def enroll_user(module_id: int, user_id: str, db: Session = Depends(get_db)):
    # Get module
    module = db.query(ModuleDB).filter(ModuleDB.id_module == module_id).first()

    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    # Initialize list if null (though default=list handles this for new rows)
    if module.enrolled_users is None:
        module.enrolled_users = []

    # Prevent duplicates
    if user_id in module.enrolled_users:
        raise HTTPException(status_code=409, detail="User already enrolled in module")

    # Add user id to module
    # Important: MutableList needs to detect change, append usually works but reassigning ensures it
    module.enrolled_users.append(user_id)
    # Trigger update explicitly for some JSON types
    # module.enrolled_users = list(module.enrolled_users) 
    
    db.commit()
    db.refresh(module)

    # Publish event
    await publish_event("module.enrolled", {
        "module_id": module_id,
        "user_id": user_id
    })

    return {"message": f"User {user_id} enrolled in module {module_id}"}

@app.post("/api/modules/{module_id}/unenroll/{user_id}", status_code=status.HTTP_200_OK)
async def unenroll_user(module_id: int, user_id: str, db: Session = Depends(get_db)):
    module = db.query(ModuleDB).filter(ModuleDB.id_module == module_id).first()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    if user_id in module.enrolled_users:
        module.enrolled_users.remove(user_id)
        flag_modified(module, "enrolled_users")
        db.commit()
        db.refresh(module)

        await publish_event("module.unenrolled", {
            "module_id": module_id,
            "user_id": user_id
        })
        return {"message": f"User {user_id} unenrolled from module {module_id}"}
    
    return {"message": "User was not enrolled"}