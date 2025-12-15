# main.py
from datetime import datetime, timezone
import os
import secrets

from fastapi import FastAPI, HTTPException, Form, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from db import SessionLocal
from models import PromoCode, PromoRedemption

app = FastAPI(title="Stablfy Promo Service", version="1.0.0")

# Simple admin guard so the create-codes UI isn't totally open
ADMIN_TOKEN = os.getenv("PROMO_ADMIN_TOKEN")


def require_admin(token: str):
    if not ADMIN_TOKEN:
        # If you forget to set it, block admin completely
        raise HTTPException(status_code=500, detail="admin_token_not_configured")
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="forbidden")


# --------------------------------------------------------------------
# Schemas for the iOS app
# --------------------------------------------------------------------

class PromoRedeemIn(BaseModel):
    code: str
    device_id: str


class PromoRedeemOut(BaseModel):
    bonusQuestions: int
    expiresAt: datetime | None


# --------------------------------------------------------------------
# Health check
# --------------------------------------------------------------------

@app.get("/healthz")
async def healthz():
    return {"ok": True}


# --------------------------------------------------------------------
# Public: redeem promo code (used by iOS app)
# --------------------------------------------------------------------

@app.post("/promo/redeem", response_model=PromoRedeemOut)
async def redeem_promo(body: PromoRedeemIn):
    code_val = body.code.strip().upper()
    now = datetime.now(timezone.utc)

    try:
        with SessionLocal() as db:
            # 1) Look up promo code
            stmt = select(PromoCode).where(PromoCode.code == code_val)
            promo: PromoCode | None = db.execute(stmt).scalar_one_or_none()

            if promo is None:
                raise HTTPException(status_code=400, detail="invalid_code")

            # 2) Expiry check
            if promo.expires_at is not None and promo.expires_at <= now:
                raise HTTPException(status_code=400, detail="expired")

            # 3) Global max redemptions
            if promo.redemptions_used >= promo.max_redemptions:
                raise HTTPException(status_code=400, detail="max_redemptions")

            # 4) Optional: block a device from reusing the same code
            stmt2 = select(PromoRedemption).where(
                PromoRedemption.promo_code_id == promo.id,
                PromoRedemption.device_id == body.device_id,
            )
            already = db.execute(stmt2).scalar_one_or_none()
            if already is not None:
                raise HTTPException(status_code=400, detail="already_redeemed")

            # 5) Record redemption
            redemption = PromoRedemption(
                promo_code_id=promo.id,
                device_id=body.device_id,
                redeemed_at=now,
            )
            db.add(redemption)

            promo.redemptions_used += 1
            db.add(promo)

            db.commit()

            return PromoRedeemOut(
                bonusQuestions=promo.bonus_questions,
                expiresAt=promo.expires_at,
            )

    except SQLAlchemyError:
        raise HTTPException(status_code=500, detail="server_error")


# --------------------------------------------------------------------
# Simple admin HTML UI to create codes
# --------------------------------------------------------------------

def _random_code(prefix: str, length: int) -> str:
    # Drop 0/O/1/I to avoid confusion
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    body = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}{body}"


def _create_codes_in_db(
    *,
    count: int,
    bonus_questions: int,
    max_redemptions: int,
    note: str,
    prefix: str,
    code_length: int,
    expires_at: datetime | None,
):
    codes: list[str] = []

    with SessionLocal() as db:
        for _ in range(count):
            code_val = _random_code(prefix=prefix, length=code_length)

            promo = PromoCode(
                code=code_val,
                bonus_questions=bonus_questions,
                expires_at=expires_at,
                max_redemptions=max_redemptions,
                redemptions_used=0,
                notes=note,
            )
            db.add(promo)
            codes.append(code_val)

        db.commit()

    return codes


@app.get("/admin", response_class=HTMLResponse)
async def admin_form(token: str = Query(..., description="admin token")):
    # Access: /admin?token=YOUR_TOKEN
    require_admin(token)

    # Minimal HTML – enough to generate codes safely
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Stablfy Promo Admin</title>
    <style>
      body {{
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        max-width: 640px;
        margin: 2rem auto;
        padding: 0 1rem;
      }}
      label {{
        display: block;
        margin-top: 0.75rem;
      }}
      input[type="text"], input[type="number"] {{
        width: 100%;
        padding: 0.4rem;
        margin-top: 0.25rem;
      }}
      button {{
        margin-top: 1rem;
        padding: 0.5rem 1.25rem;
      }}
      pre {{
        background: #111;
        color: #0f0;
        padding: 0.75rem;
        white-space: pre-wrap;
        word-break: break-all;
      }}
    </style>
  </head>
  <body>
    <h1>Stablfy Promo Admin</h1>
    <form action="/admin/create" method="post">
      <input type="hidden" name="token" value="{token}" />

      <label>
        Prefix (optional)
        <input type="text" name="prefix" value="STAB" />
      </label>

      <label>
        Number of codes
        <input type="number" name="count" value="10" min="1" max="1000" />
      </label>

      <label>
        Bonus questions per code
        <input type="number" name="bonus_questions" value="50" min="1" />
      </label>

      <label>
        Max redemptions per code
        <input type="number" name="max_redemptions" value="1" min="1" />
      </label>

      <label>
        Code length (characters after prefix)
        <input type="number" name="code_length" value="6" min="4" max="16" />
      </label>

      <label>
        Note / campaign label
        <input type="text" name="note" value="Manual create" />
      </label>

      <label>
        Expiry (YYYY-MM-DD, optional – empty for no expiry)
        <input type="text" name="expires_date" placeholder="2026-12-31" />
      </label>

      <button type="submit">Create codes</button>
    </form>
  </body>
</html>
"""


@app.post("/admin/create", response_class=HTMLResponse)
async def admin_create(
    token: str = Form(...),
    prefix: str = Form("STAB"),
    count: int = Form(10),
    bonus_questions: int = Form(50),
    max_redemptions: int = Form(1),
    code_length: int = Form(6),
    note: str = Form(""),
    expires_date: str = Form(""),
):
    require_admin(token)

    expires_at: datetime | None = None
    if expires_date.strip():
        try:
            # Interpret the date in UTC midnight
            dt = datetime.strptime(expires_date.strip(), "%Y-%m-%d")
            expires_at = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_expires_date")

    codes = _create_codes_in_db(
        count=count,
        bonus_questions=bonus_questions,
        max_redemptions=max_redemptions,
        note=note,
        prefix=prefix,
        code_length=code_length,
        expires_at=expires_at,
    )

    codes_block = "\n".join(codes)

    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Codes created</title>
  </head>
  <body>
    <h1>Codes created</h1>
    <p>Created <strong>{len(codes)}</strong> codes.</p>
    <p><strong>Bonus per code:</strong> {bonus_questions}</p>
    <p><strong>Max redemptions per code:</strong> {max_redemptions}</p>
    <p><strong>Note:</strong> {note or "(none)"} </p>
    <pre>{codes_block}</pre>

    <p><a href="/admin?token={token}">Create more</a></p>
  </body>
</html>
"""
