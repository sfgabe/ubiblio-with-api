from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.sql import func

from .. import crud, models, schemas
from ..database import SessionLocal
from ..dependencies import api_key, get_rate_limiter

# Read-only JSON API. Every route needs a valid X-Api-Key header (see /manageApiKeys).
router = APIRouter(
    prefix="/api/v1",
    tags=["api"],
    dependencies=[api_key, get_rate_limiter(times=10, seconds=1)],
)

MAX_LIMIT = 100


def image_urls(request: Request, filenames):
    return [str(request.url_for("static", path=f"bookImages/{name}.jpg")) for name in filenames]


def to_api_books(request: Request, db, books):
    images = crud.getImagesForBooks(db, [book.id for book in books])
    return [
        schemas.ApiBook.model_validate(book).model_copy(
            update={"images": image_urls(request, images.get(book.id, []))})
        for book in books
    ]


@router.get("/books", response_model=schemas.ApiBookList)
def list_books(request: Request, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=MAX_LIMIT),
               collection: Optional[str] = None):
    db = SessionLocal()
    try:
        books, count = crud.getBooks(db, skip=skip, limit=limit, collection=collection)
        return schemas.ApiBookList(count=count, skip=skip, limit=limit, books=to_api_books(request, db, books))
    finally:
        db.close()


@router.get("/books/recent", response_model=list[schemas.ApiBook])
def recent_books(request: Request, limit: int = Query(10, ge=1, le=MAX_LIMIT)):
    db = SessionLocal()
    try:
        return to_api_books(request, db, crud.getRecentBooks(db, limit))
    finally:
        db.close()


@router.get("/books/random", response_model=schemas.ApiBook)
def random_book(request: Request, collection: Optional[str] = None):
    db = SessionLocal()
    try:
        book = crud.getRandomBook(db, collection)
        if book is None:
            detail = "No books in that collection." if collection is not None else "The library has no books."
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return to_api_books(request, db, [book])[0]
    finally:
        db.close()


@router.get("/books/{bookId}", response_model=schemas.ApiBook)
def get_book(request: Request, bookId: int):
    db = SessionLocal()
    try:
        book = crud.getBookById(db, bookId)
        if not book:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found.")
        return to_api_books(request, db, [book])[0]
    finally:
        db.close()


@router.get("/stats", response_model=schemas.ApiStats)
def library_stats():
    db = SessionLocal()
    try:
        def count(*where):
            return db.query(func.count(models.Book.id)).filter(*where).scalar()

        def grouped(field):
            # Books with no genre (None or "") are counted together under "".
            totals = {}
            for key, n in crud.stats(db, False, field, field).items():
                totals[key or ""] = totals.get(key or "", 0) + n
            return totals

        return schemas.ApiStats(
            books=count(),
            ebooks=count(models.Book.ebook == True),
            withdrawn=count(models.Book.withdrawn == True),
            byGenre=grouped("genre"),
            byCollection=crud.getCollections(db),
        )
    finally:
        db.close()


@router.get("/collections", response_model=list[schemas.ApiCollection])
def list_collections():
    db = SessionLocal()
    try:
        # Books with no collection are listed under "".
        return [schemas.ApiCollection(name=name, count=n) for name, n in sorted(crud.getCollections(db).items())]
    finally:
        db.close()
