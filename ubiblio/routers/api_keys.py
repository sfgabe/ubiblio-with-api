from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import crud
from ..database import SessionLocal
from ..dependencies import admin_user, get_rate_limiter, templates

router = APIRouter()

MAX_LABEL_LENGTH = 100


# --------------------------------------------------------------------------
# API key management (admin only)
# --------------------------------------------------------------------------
def render_api_keys(request: Request, user, newKey=None, errors=None):
    db = SessionLocal()
    try:
        context = {
            "apiKeys": crud.getAllApiKeys(db),
            "newKey": newKey,
            "errors": errors or [],
            "user": user,
            "request": request,
        }
        return templates.TemplateResponse(request, "apiKeyManagement.html", context)
    finally:
        db.close()


@router.get("/manageApiKeys", dependencies=[get_rate_limiter(times=1, seconds=3)], response_class=HTMLResponse)
async def manage_api_keys(request: Request, user: admin_user):
    try:
        return render_api_keys(request, user)
    except Exception as e:
        print(e)
        return "Could not load API keys."


@router.post("/addApiKey", dependencies=[get_rate_limiter(times=2, seconds=2)], response_class=HTMLResponse)
async def add_api_key(request: Request, user: admin_user):
    form = await request.form()
    label = (form.get("label") or "").strip()[:MAX_LABEL_LENGTH] or None
    db = SessionLocal()
    try:
        newKey = crud.createApiKey(db, label)
    finally:
        db.close()
    if not newKey:
        return render_api_keys(request, user, errors=["Could not create API key."])
    # The key is only shown on this response; only its hash is stored.
    return render_api_keys(request, user, newKey=newKey)


@router.get("/deleteApiKey/{keyId}", dependencies=[get_rate_limiter(times=1, seconds=2)], response_class=HTMLResponse)
async def delete_api_key(request: Request, keyId: int, user: admin_user):
    db = SessionLocal()
    try:
        crud.deleteApiKey(db, keyId)
        return RedirectResponse(url='/manageApiKeys')
    except Exception as e:
        print(e)
        return "Could not delete API key."
    finally:
        db.close()
