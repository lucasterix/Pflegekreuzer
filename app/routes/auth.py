"""
Authentifizierungs-Routen für Pflegekreuzer.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import verify_password, create_signed_cookie
from app.config import (
    APP_LOGIN_USER,
    APP_LOGIN_PASSWORD,
    APP_AUTH_COOKIE_NAME,
    APP_AUTH_COOKIE_SECRET,
    SESSION_COOKIE_SECURE,
    SESSION_COOKIE_SAMESITE,
    AUTH_COOKIE_NAME,
    CFG_AUTH_COOKIE_SECRET,
    CONFIG_PASSWORD,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    u = (username or "").strip()
    p = (password or "").strip()

    if u == APP_LOGIN_USER and verify_password(p, APP_LOGIN_PASSWORD):
        resp = RedirectResponse(url="/", status_code=303)
        token = create_signed_cookie("ok", APP_AUTH_COOKIE_SECRET)
        resp.set_cookie(
            APP_AUTH_COOKIE_NAME,
            token,
            max_age=60 * 60 * 8,
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE,
        )
        return resp

    # Falsche Logindaten → Fehler anzeigen
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": "Benutzername oder Passwort ist falsch.",
        },
        status_code=401,
    )


@router.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    # Cookie löschen
    resp.delete_cookie(APP_AUTH_COOKIE_NAME)
    return resp


@router.get("/config/login")
def config_login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "config_login.html",
        {"request": request, "error": error},
    )


@router.post("/config/login")
async def config_login_submit(
    request: Request,
    password: str = Form(...),
):
    p = (password or "").strip()

    if verify_password(p, CONFIG_PASSWORD):
        resp = RedirectResponse(url="/config", status_code=303)
        token = create_signed_cookie("ok", CFG_AUTH_COOKIE_SECRET)
        resp.set_cookie(
            AUTH_COOKIE_NAME,
            token,
            max_age=60 * 60 * 8,
            httponly=True,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE,
        )
        return resp

    # Falsche Logindaten → Fehler anzeigen
    return templates.TemplateResponse(
        "config_login.html",
        {
            "request": request,
            "error": "Passwort ist falsch.",
        },
        status_code=401,
    )


@router.get("/config/logout")
def config_logout():
    resp = RedirectResponse(url="/config/login", status_code=303)
    # Cookie löschen
    resp.delete_cookie(AUTH_COOKIE_NAME)
    return resp