import re

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from tests.helpers import access_token_cookie, create_test_user
from ubiblio import crud, models
from ubiblio.database import SessionLocal
from ubiblio.dependencies import verify_api_key


@pytest.fixture
def client():
    from ubiblio.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def delete_key_rows(db, key):
    db.query(models.apiKey).filter(models.apiKey.keyHash == crud.hashApiKey(key)).delete()
    db.commit()


class TestApiKeyCrud:
    def test_create_key_stores_only_a_hash(self, db):
        key = crud.createApiKey(db, "test label")
        try:
            assert key.startswith(crud.API_KEY_PREFIX)
            row = db.query(models.apiKey).filter(models.apiKey.keyHash == crud.hashApiKey(key)).one()
            assert row.label == "test label"
            assert key not in (row.keyHash, row.prefix)
            assert key.startswith(row.prefix)
        finally:
            delete_key_rows(db, key)

    def test_keys_are_unique(self, db):
        a = crud.createApiKey(db)
        b = crud.createApiKey(db)
        try:
            assert a != b
        finally:
            delete_key_rows(db, a)
            delete_key_rows(db, b)

    def test_is_valid_api_key(self, db):
        key = crud.createApiKey(db)
        try:
            assert crud.isValidApiKey(db, key)
            assert not crud.isValidApiKey(db, key + "x")
            assert not crud.isValidApiKey(db, "")
            assert not crud.isValidApiKey(db, None)
        finally:
            delete_key_rows(db, key)

    def test_delete_api_key(self, db):
        key = crud.createApiKey(db)
        row = db.query(models.apiKey).filter(models.apiKey.keyHash == crud.hashApiKey(key)).one()
        assert crud.deleteApiKey(db, row.id)
        assert not crud.isValidApiKey(db, key)


class TestVerifyApiKey:
    def test_valid_key_passes(self, db):
        key = crud.createApiKey(db)
        try:
            assert verify_api_key(key) is None
        finally:
            delete_key_rows(db, key)

    @pytest.mark.parametrize("key", [None, "", "ubk_not-a-real-key"])
    def test_missing_or_invalid_key_is_401(self, key):
        with pytest.raises(HTTPException) as exc:
            verify_api_key(key)
        assert exc.value.status_code == 401


class TestApiKeyManagementPages:
    def test_requires_admin(self, client):
        with create_test_user(is_admin=False) as user:
            with access_token_cookie(client, user):
                r = client.get("/manageApiKeys", follow_redirects=False)
        assert r.status_code == 403

    def test_requires_login(self, client):
        r = client.get("/manageApiKeys", follow_redirects=False)
        assert r.status_code == 302

    def test_admin_can_create_list_and_delete_key(self, client, db):
        with create_test_user(is_admin=True) as user:
            with access_token_cookie(client, user):
                r = client.post("/addApiKey", data={"label": "Home Assistant"})
                assert r.status_code == 200
                key = re.search(r"<code>(ubk_[^<]+)</code>", r.text).group(1)
                assert crud.isValidApiKey(db, key)

                r = client.get("/manageApiKeys")
                assert r.status_code == 200
                assert "Home Assistant" in r.text
                # The full key is only shown once, on creation.
                assert key not in r.text

                row = db.query(models.apiKey).filter(models.apiKey.keyHash == crud.hashApiKey(key)).one()
                r = client.get(f"/deleteApiKey/{row.id}", follow_redirects=False)
                assert r.status_code == 307
                assert not crud.isValidApiKey(db, key)

    def test_non_admin_cannot_create_key(self, client, db):
        before = db.query(models.apiKey).count()
        with create_test_user(is_admin=False) as user:
            with access_token_cookie(client, user):
                r = client.post("/addApiKey", data={"label": "nope"})
        assert r.status_code == 403
        assert db.query(models.apiKey).count() == before
