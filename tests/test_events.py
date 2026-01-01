import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import process_course_deleted, process_course_unenrolled, publish_event
from app.models import Base, ModuleDB
import json

TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

@pytest.fixture(autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.mark.anyio
async def test_publish_event_without_rabbit_url(monkeypatch):
    """Test that publish_event returns early if RABBIT_URL is not set"""
    monkeypatch.setenv("RABBIT_URL", "")

    # Should not raise any errors
    await publish_event("test.event", {"data": "test"})

@pytest.mark.anyio
async def test_publish_event_with_exception(monkeypatch):
    """Test publish_event handles exceptions gracefully"""
    monkeypatch.setenv("RABBIT_URL", "amqp://guest:guest@localhost/")

    with patch("app.main.aio_pika.connect_robust", AsyncMock(side_effect=Exception("Connection failed"))):
        # Should not raise, just print error
        await publish_event("test.event", {"data": "test"})

@pytest.mark.anyio
async def test_process_course_deleted_with_course_db_id(monkeypatch, db_session):
    """Test processing course deletion with course_db_id"""
    # Patch SessionLocal to return our test session
    with patch("app.main.SessionLocal", return_value=db_session):
        with patch("app.main.publish_event", new_callable=AsyncMock) as mock_publish:
            # Create test modules
            module1 = ModuleDB(id_module=1000, name="Module 1", course_id=100, enrolled_users=[])
            module2 = ModuleDB(id_module=1001, name="Module 2", course_id=100, enrolled_users=[])
            module3 = ModuleDB(id_module=1002, name="Module 3", course_id=200, enrolled_users=[])
            db_session.add_all([module1, module2, module3])
            db_session.commit()

            # Process deletion for course 100
            await process_course_deleted({"course_id": "100", "course_db_id": "100"})

            # Check that modules for course 100 were deleted
            remaining = db_session.query(ModuleDB).all()
            assert len(remaining) == 1
            assert remaining[0].id_module == 1002

            # Check that publish_event was called for each deleted module
            assert mock_publish.call_count == 2

@pytest.mark.anyio
async def test_process_course_deleted_no_target_id(db_session):
    """Test process_course_deleted returns early if no target_id"""
    with patch("app.main.SessionLocal", return_value=db_session):
        # Should not raise errors
        await process_course_deleted({})

@pytest.mark.anyio
async def test_process_course_deleted_with_exception(monkeypatch, db_session):
    """Test process_course_deleted handles exceptions"""
    # Create a mock that raises an exception when querying
    def mock_sessionlocal():
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("DB Error")
        mock_db.close = MagicMock()
        return mock_db

    with patch("app.main.SessionLocal", mock_sessionlocal):
        # Should not raise, just print error
        await process_course_deleted({"course_id": "100", "course_db_id": "100"})

@pytest.mark.anyio
async def test_process_course_unenrolled(monkeypatch, db_session):
    """Test processing course unenrollment"""
    with patch("app.main.SessionLocal", return_value=db_session):
        with patch("app.main.publish_event", new_callable=AsyncMock) as mock_publish:
            # Create test modules with enrolled users
            module1 = ModuleDB(id_module=1000, name="Module 1", course_id=100, enrolled_users=["user1", "user2"])
            module2 = ModuleDB(id_module=1001, name="Module 2", course_id=100, enrolled_users=["user1"])
            db_session.add_all([module1, module2])
            db_session.commit()

            # Process unenrollment
            await process_course_unenrolled({"course_db_id": "100", "user_id": "user1"})

            # Refresh from DB
            db_session.expire_all()
            module1_updated = db_session.query(ModuleDB).filter(ModuleDB.id_module == 1000).first()
            module2_updated = db_session.query(ModuleDB).filter(ModuleDB.id_module == 1001).first()

            # Check that user1 was removed
            assert "user1" not in module1_updated.enrolled_users
            assert "user2" in module1_updated.enrolled_users
            assert "user1" not in module2_updated.enrolled_users

            # Check that publish_event was called
            assert mock_publish.call_count == 2

@pytest.mark.anyio
async def test_process_course_unenrolled_no_data(db_session):
    """Test process_course_unenrolled returns early if no data"""
    with patch("app.main.SessionLocal", return_value=db_session):
        # Should not raise errors
        await process_course_unenrolled({})
        await process_course_unenrolled({"course_db_id": "100"})
        await process_course_unenrolled({"user_id": "user1"})

@pytest.mark.anyio
async def test_process_course_unenrolled_with_exception(monkeypatch, db_session):
    """Test process_course_unenrolled handles exceptions"""
    # Create a mock that raises an exception when querying
    def mock_sessionlocal():
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("DB Error")
        mock_db.close = MagicMock()
        return mock_db

    with patch("app.main.SessionLocal", mock_sessionlocal):
        # Should not raise, just print error
        await process_course_unenrolled({"course_db_id": "100", "user_id": "user1"})

@pytest.mark.anyio
async def test_consume_events_without_rabbit_url(monkeypatch, capsys):
    """Test consume_events returns early without RABBIT_URL"""
    monkeypatch.delenv("RABBIT_URL", raising=False)

    from app.main import consume_events
    await consume_events()

    captured = capsys.readouterr()
    assert "RABBIT_URL not set" in captured.out

@pytest.mark.anyio
async def test_consume_events_cancelled(monkeypatch):
    """Test consume_events handles CancelledError"""
    import asyncio
    monkeypatch.setenv("RABBIT_URL", "amqp://guest:guest@localhost/")

    async def mock_connect(*args, **kwargs):
        raise asyncio.CancelledError()

    with patch("app.main.aio_pika.connect_robust", mock_connect):
        from app.main import consume_events
        await consume_events()  # Should exit cleanly
