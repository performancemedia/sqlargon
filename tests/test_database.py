from sqlargon import Database


def test_create_database():
    db = Database(url="sqlite+aiosqlite:///:memory:")
    assert isinstance(db, Database)


def test_database_from_env():
    db = Database.from_env()
    assert isinstance(db, Database)


def test_database_supports(db):
    assert db.supports_returning
    assert db.supports_on_conflict
