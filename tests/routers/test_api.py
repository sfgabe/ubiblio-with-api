import uuid

from fastapi.testclient import TestClient
import pytest

from ubiblio import crud, models
from ubiblio.database import SessionLocal


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


@pytest.fixture
def key(db):
    key = crud.createApiKey(db, "test")
    yield key
    db.query(models.apiKey).filter(models.apiKey.keyHash == crud.hashApiKey(key)).delete()
    db.commit()


@pytest.fixture
def headers(key):
    return {"X-Api-Key": key}


@pytest.fixture
def books(db):
    """Three books with a unique genre, the last one withdrawn and with a cover image."""
    tag = f"test_{uuid.uuid4().hex[:8]}"
    rows = [
        models.Book(title=f"{tag} one", author="A", genre=tag, collection=tag, owned=True, withdrawn=False, ebook=False),
        models.Book(title=f"{tag} two", author="B", genre=tag, collection=None, owned=True, withdrawn=False, ebook=True),
        models.Book(title=f"{tag} three", author="C", genre=tag, collection="", owned=True,
                    withdrawn=True, withdrawnBy="someuser", ebook=False),
    ]
    db.add_all(rows)
    db.commit()
    image = models.bookImage(bookId=rows[2].id, filename=f"{rows[2].id}_{tag}")
    db.add(image)
    db.commit()
    yield tag, rows
    db.query(models.bookImage).filter(models.bookImage.id == image.id).delete()
    db.query(models.Book).filter(models.Book.id.in_([b.id for b in rows])).delete()
    db.commit()


class TestApiAuth:
    @pytest.mark.parametrize("path", [
        "/api/v1/books", "/api/v1/books/recent", "/api/v1/books/random", "/api/v1/books/1", "/api/v1/stats",
    ])
    def test_missing_key_is_401(self, client, path):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 401
        assert r.json() == {"detail": "Invalid or missing API key."}

    def test_wrong_key_is_401(self, client):
        r = client.get("/api/v1/books", headers={"X-Api-Key": "ubk_wrong"}, follow_redirects=False)
        assert r.status_code == 401

    def test_revoked_key_is_401(self, client, db, headers, key):
        row = db.query(models.apiKey).filter(models.apiKey.keyHash == crud.hashApiKey(key)).one()
        crud.deleteApiKey(db, row.id)
        assert client.get("/api/v1/books", headers=headers).status_code == 401

    def test_api_is_read_only(self, client, headers):
        assert client.post("/api/v1/books", headers=headers).status_code == 405
        assert client.delete("/api/v1/books/1", headers=headers).status_code == 405


class TestBooks:
    def test_list_books_paginates(self, client, headers, books):
        r = client.get("/api/v1/books", headers=headers, params={"skip": 0, "limit": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["skip"] == 0 and body["limit"] == 2
        assert len(body["books"]) == 2
        assert body["count"] >= 3

    @pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"skip": -1}])
    def test_list_books_rejects_bad_paging(self, client, headers, params):
        assert client.get("/api/v1/books", headers=headers, params=params).status_code == 422

    def test_get_book(self, client, headers, books):
        _, rows = books
        withdrawn = rows[2]
        r = client.get(f"/api/v1/books/{withdrawn.id}", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["title"] == withdrawn.title
        assert body["withdrawn"] is True
        # Who borrowed a book is not exposed through the API.
        assert "withdrawnBy" not in body
        assert body["images"] == [f"http://testserver/static/bookImages/{withdrawn.id}_{books[0]}.jpg"]

    def test_get_missing_book_is_404(self, client, headers):
        r = client.get("/api/v1/books/999999999", headers=headers)
        assert r.status_code == 404

    def test_recent_books_are_newest_first(self, client, headers, books):
        _, rows = books
        r = client.get("/api/v1/books/recent", headers=headers, params={"limit": 3})
        assert r.status_code == 200
        assert [b["id"] for b in r.json()] == [b.id for b in reversed(rows)]

    def test_random_book(self, client, headers, books):
        r = client.get("/api/v1/books/random", headers=headers)
        assert r.status_code == 200
        assert "title" in r.json()


class TestStats:
    def test_stats(self, client, headers, books):
        tag, _ = books
        r = client.get("/api/v1/stats", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["books"] >= 3
        assert body["ebooks"] >= 1
        assert body["withdrawn"] >= 1
        assert body["byGenre"][tag] == 3
        assert body["byCollection"][tag] == 1
        # None and "" collections are counted together.
        assert body["byCollection"][""] >= 2
