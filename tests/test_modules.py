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

def module_payload(module_id = 1000, module_name = "CICD2", course_id = 100):
    return {"id_module": module_id, "name": module_name, "course_id": course_id, "enrolled_users": []}

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

# Test filtering by course_id
def test_list_modules_by_course_id(client):
    client.post("/api/module", json = module_payload(module_id=1000, course_id=100))
    client.post("/api/module", json = module_payload(module_id=1001, course_id=100))
    client.post("/api/module", json = module_payload(module_id=1002, course_id=200))

    r = client.get("/api/module?course_id=100")
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/api/module?course_id=200")
    assert r.status_code == 200
    assert len(r.json()) == 1

# Test enrollment functionality
def test_enroll_user_ok(client):
    client.post("/api/module", json = module_payload())
    r = client.post("/api/modules/1000/enroll/user123")
    assert r.status_code == 200
    assert "enrolled" in r.json()["message"].lower()

    # Verify user is enrolled
    r = client.get("/api/module/1000")
    assert r.status_code == 200
    assert "user123" in r.json()["enrolled_users"]

def test_enroll_user_module_not_found(client):
    r = client.post("/api/modules/9999/enroll/user123")
    assert r.status_code == 404
    assert "module not found" in r.json()["detail"].lower()

def test_enroll_user_already_enrolled(client):
    client.post("/api/module", json = module_payload())
    client.post("/api/modules/1000/enroll/user123")
    r = client.post("/api/modules/1000/enroll/user123")
    assert r.status_code == 409
    assert "already enrolled" in r.json()["detail"].lower()

# Test unenrollment functionality
def test_unenroll_user_ok(client):
    client.post("/api/module", json = module_payload())
    client.post("/api/modules/1000/enroll/user123")

    r = client.post("/api/modules/1000/unenroll/user123")
    assert r.status_code == 200
    assert "unenrolled" in r.json()["message"].lower()

    # Verify user is unenrolled
    r = client.get("/api/module/1000")
    assert r.status_code == 200
    assert "user123" not in r.json()["enrolled_users"]

def test_unenroll_user_module_not_found(client):
    r = client.post("/api/modules/9999/unenroll/user123")
    assert r.status_code == 404
    assert "module not found" in r.json()["detail"].lower()

def test_unenroll_user_not_enrolled(client):
    client.post("/api/module", json = module_payload())
    r = client.post("/api/modules/1000/unenroll/user123")
    assert r.status_code == 200
    assert "not enrolled" in r.json()["message"].lower()

# Test partial update with different fields
def test_partial_update_module_name_only(client):
    client.post("/api/module", json = module_payload())
    r = client.patch("/api/module/1000", json = {"name": "Updated Name"})
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Name"
    assert r.json()["id_module"] == 1000  # Should remain unchanged

def test_partial_update_module_course_id_only(client):
    client.post("/api/module", json = module_payload())
    r = client.patch("/api/module/1000", json = {"course_id": 999})
    assert r.status_code == 200
    assert r.json()["course_id"] == 999
    assert r.json()["id_module"] == 1000  # Should remain unchanged

# Test proxy endpoint
def test_proxy_posts(client, monkeypatch):
    from unittest.mock import patch, MagicMock

    # Mock the httpx.Client context manager and get method
    class MockResponse:
        def json(self):
            return [{"id": 1, "title": "Test Post"}]

    mock_client = MagicMock()
    mock_client.get.return_value = MockResponse()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client):
        r = client.get("/api/proxy/posts")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["title"] == "Test Post"

# Test helper functions
def test_get_db():
    """Test the get_db dependency"""
    from app.main import get_db

    db_gen = get_db()
    db = next(db_gen)
    assert db is not None

    # Clean up
    try:
        next(db_gen)
    except StopIteration:
        pass  # Expected

def test_commit_or_rollback_success():
    """Test commit_or_rollback with successful commit"""
    from app.main import commit_or_rollback
    from unittest.mock import MagicMock

    mock_db = MagicMock()
    commit_or_rollback(mock_db, "Test error")
    mock_db.commit.assert_called_once()

def test_commit_or_rollback_integrity_error():
    """Test commit_or_rollback handles IntegrityError"""
    from app.main import commit_or_rollback
    from sqlalchemy.exc import IntegrityError
    from unittest.mock import MagicMock

    mock_db = MagicMock()
    mock_db.commit.side_effect = IntegrityError("test", "params", "orig")

    with pytest.raises(Exception) as exc_info:
        commit_or_rollback(mock_db, "Test error message")

    assert exc_info.value.status_code == 409
    assert "Test error message" in str(exc_info.value.detail)
    mock_db.rollback.assert_called_once()