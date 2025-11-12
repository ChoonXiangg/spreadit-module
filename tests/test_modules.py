import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.main import app, get_db
from app.models import Base
import app.database as database  # <-- needed to override engine + SessionLocal
from sqlalchemy.pool import StaticPool

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool) 
TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False) 
 

@event.listens_for(engine, "connect") 
def _fk_on(dbapi_conn, _): 
    dbapi_conn.execute("PRAGMA foreign_keys=ON") 

@pytest.fixture(autouse=True) 
def _schema(): 
    Base.metadata.create_all(bind=engine) 
    yield 
    Base.metadata.drop_all(bind=engine) 
 
@pytest.fixture 
def client(): 
    def override_get_db(): 
        db = TestingSessionLocal() 
        try: 
            yield db 
        finally: 
            db.close() 
    app.dependency_overrides[get_db] = override_get_db 
    with TestClient(app) as c: 
        # hand the client to the test 
        yield c 
    app.dependency_overrides.clear() 

def module_payload(module_id = 1000, module_name = "CICD2"):
    return {"id_module": module_id, "name": module_name}

##############################################################################################################################################

def add_module_ok(client):
    r = client.post("/api/module", json = module_payload())
    assert r.status_code == 201

def test_module_id_duplicate_conflict(client):
    client.post("/api/module", json = module_payload())
    r = client.post("/api/module", json = module_payload(module_name = "CICD1"))
    assert r.status_code == 409
    assert "module already exists" in r.json()["detail"].lower() 

def test_list_module(client):
    client.post("/api/module", json = module_payload())
    r = client.get("/api/module")
    assert r.status_code == 200
    assert r.json() == [module_payload()]

def test_list_module_empty(client):
    r = client.get("/api/module")
    assert r.status_code == 200
    assert r.json() == []

def test_get_module_by_id_ok(client):
    client.post("/api/module", json = module_payload())
    r = client.get("api/module/1000")
    assert r.status_code == 200
    assert r.json() == module_payload()

def test_get_module_by_id_not_found(client):
    client.post("/api/module", json = module_payload())
    #module id is 1000, use 1001 here to cause error
    r = client.get("api/module/1001")
    assert r.status_code == 404
    assert "module not found" in r.json()["detail"].lower() 

def test_full_replace_module_ok(client):
    client.post("/api/module", json = module_payload())
    r = client.put("/api/module/1000", json = module_payload(module_id = 1001, module_name = "CICD 1"))
    assert r.status_code == 200
    assert r.json() == module_payload(module_id = 1001, module_name = "CICD 1")

def test_full_replace_module_not_found(client):
    client.post("/api/module", json = module_payload())
    #module id is 1000, use 1001 here to cause error
    r = client.put("/api/module/1001", json = module_payload(module_id = 1001, module_name = "CICD 1"))
    assert r.status_code == 404
    assert "module not found" in r.json()["detail"].lower()

def test_full_replace_module_already_exists(client):
    client.post("/api/module", json = module_payload())
    #Create two module to test
    client.post("/api/module", json = module_payload(module_id = 1001))
    r = client.put("/api/module/1000", json = module_payload(module_id = 1001, module_name = "CICD 1"))
    assert r.status_code == 409
    assert "module id already exists" in r.json()["detail"].lower()    

def test_partial_replace_module_ok(client):
    client.post("/api/module", json = module_payload())
    r = client.patch("/api/module/1000", json = module_payload(module_id = 1001))
    assert r.status_code == 200
    assert r.json() == module_payload(module_id = 1001)

def test_partial_replace_module_not_found(client):
    client.post("/api/module", json = module_payload())
    #module id is 1000, use 1001 here to cause error
    r = client.patch("/api/module/1001", json = module_payload(module_id = 1001))
    assert r.status_code == 404
    assert "module not found" in r.json()["detail"].lower()

def test_partial_replace_module_already_exists(client):
    client.post("/api/module", json = module_payload())
    #Create two module to test
    client.post("/api/module", json = module_payload(module_id = 1001))
    r = client.patch("/api/module/1000", json = module_payload(module_id = 1001))
    assert r.status_code == 409
    assert "module id already exists" in r.json()["detail"].lower()

def test_delete_module_ok(client):
    client.post("/api/module", json = module_payload())
    r = client.delete("/api/module/1000")
    assert r.status_code == 204

def test_delete_module_not_found(client):
    client.post("/api/module", json = module_payload())
    r = client.delete("/api/module/1001")
    assert r.status_code == 404
    assert "module not found" in r.json()["detail"].lower()    