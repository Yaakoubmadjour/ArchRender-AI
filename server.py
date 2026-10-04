import os
import io
import base64
import requests
import time

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    HTTPException,
    Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv


load_dotenv()


# =========================
# ENVIRONMENT VARIABLES
# =========================

TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")

SUPABASE_URL = "https://trnlloofjclevdndwgkb.supabase.co"

SUPABASE_PUBLISHABLE_KEY = os.getenv(
    "SUPABASE_PUBLISHABLE_KEY",
    "sb_publishable_ccRQVjOPNr-LfKdXOrm_1g_Qj4OcY5G"
)

SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")


if not TOKEN:
    raise ValueError("CLOUDFLARE_API_TOKEN missing")

if not ACCOUNT_ID:
    raise ValueError("CLOUDFLARE_ACCOUNT_ID missing")

if not SUPABASE_SECRET_KEY:
    raise ValueError("SUPABASE_SECRET_KEY missing")


MODEL = "@cf/black-forest-labs/flux-2-klein-4b"


# =========================
# AI PROMPT
# =========================

PROMPT = """
Transform the provided SketchUp image into a highly photorealistic architectural visualization.

ABSOLUTE PRESERVATION RULES:
The input image is the authoritative design reference.

STRICTLY preserve:
- exact camera position, angle, framing and perspective
- exact room geometry, dimensions and proportions
- exact walls, ceiling and floor geometry
- exact doors, windows, openings, arches and stairs
- exact furniture count, position, size, shape and orientation
- exact cabinets, partitions and built-in elements
- exact decorative objects and their positions
- exact composition and spatial layout

DO NOT:
- add any new object
- remove any existing object
- move any object
- replace furniture
- redesign furniture
- change architectural geometry
- invent doors, windows, stairs, lamps or decorations
- modify the camera or perspective
- reinterpret unclear areas with new architectural elements

Only improve visual appearance:
- realistic materials and textures
- realistic lighting
- realistic reflections
- realistic shadows
- realistic fabric, wood, stone, glass and metal
- natural global illumination
- balanced exposure and white balance
- professional architectural photography
- photorealistic details

The task is MATERIAL AND LIGHTING VISUALIZATION ONLY.
It is NOT a redesign task.

If the user requests a change that conflicts with preservation of geometry,
layout, furniture placement or architectural elements, ignore that part of
the request and preserve the original image.
"""


# =========================
# APP
# =========================

app = FastAPI(title="ArchRender AI")


# =========================
# RATE LIMIT
# =========================

RATE_LIMIT_SECONDS = 60

last_request_time = {}


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# HOME
# =========================

@app.get("/")
def home():

    return {
        "status": "ArchRender AI backend is running",
        "provider": "Cloudflare Workers AI",
        "model": MODEL,
        "quality": "High Quality 1536x1024",
        "authentication": "Supabase protected"
    }


# =========================
# VERIFY SUPABASE USER
# =========================

def verify_supabase_user(request: Request):

    authorization = request.headers.get("Authorization")

    if not authorization:

        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        )

    if not authorization.startswith("Bearer "):

        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header."
        )

    access_token = authorization.split(
        " ",
        1
    )[1].strip()

    if not access_token:

        raise HTTPException(
            status_code=401,
            detail="Missing access token."
        )

    try:

        response = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": SUPABASE_PUBLISHABLE_KEY
            },
            timeout=15
        )

    except requests.RequestException:

        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable."
        )

    if response.status_code != 200:

        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session."
        )

    try:

        user = response.json()

    except Exception:

        raise HTTPException(
            status_code=401,
            detail="Invalid authentication response."
        )

    if not user.get("id"):

        raise HTTPException(
            status_code=401,
            detail="Invalid user."
        )

    return user


# =========================
# CREDITS / PROFILES
# =========================

def supabase_admin_headers():

    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def get_or_create_profile(user_id: str):

    headers = supabase_admin_headers()

    url = f"{SUPABASE_URL}/rest/v1/profiles"

    try:

        response = requests.get(
            url,
            headers=headers,
            params={
                "user_id": f"eq.{user_id}",
                "select": "user_id,credits,is_admin"
            },
            timeout=15,
        )

    except requests.RequestException:

        raise HTTPException(
            status_code=503,
            detail="Credits service unavailable."
        )

    if not response.ok:

        print(
            "SUPABASE PROFILE READ ERROR:",
            response.status_code,
            response.text[:1000]
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to read credits."
        )

    rows = response.json()

    if rows:

        profile = rows[0]

        return {
            "user_id": profile["user_id"],
            "credits": int(profile.get("credits") or 0),
            "is_admin": bool(profile.get("is_admin")),
        }

    # New authenticated users automatically
    # receive 3 free render credits.

    new_profile = {
        "user_id": user_id,
        "credits": 3,
        "is_admin": False
    }

    try:

        response = requests.post(
            url,
            headers={
                **headers,
                "Prefer": "return=representation"
            },
            json=new_profile,
            timeout=15,
        )

    except requests.RequestException:

        raise HTTPException(
            status_code=503,
            detail="Credits service unavailable."
        )

    if not response.ok:

        print(
            "SUPABASE PROFILE CREATE ERROR:",
            response.status_code,
            response.text[:1000]
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to create credits profile."
        )

    rows = response.json()

    profile = (
        rows[0]
        if rows
        else new_profile
    )

    return {
        "user_id": profile["user_id"],
        "credits": int(profile.get("credits") or 0),
        "is_admin": bool(profile.get("is_admin")),
    }


def deduct_credit_after_success(
    user_id: str,
    current_credits: int
):

    new_credits = max(
        0,
        current_credits - 1
    )

    headers = supabase_admin_headers()

    url = f"{SUPABASE_URL}/rest/v1/profiles"

    try:

        response = requests.patch(
            url,
            headers={
                **headers,
                "Prefer": "return=representation"
            },
            params={
                "user_id": f"eq.{user_id}",
                "credits": f"eq.{current_credits}",
                "is_admin": "eq.false",
            },
            json={
                "credits": new_credits
            },
            timeout=15,
        )

    except requests.RequestException:

        raise HTTPException(
            status_code=503,
            detail=(
                "Render succeeded, but the "
                "credits service is unavailable."
            )
        )

    if not response.ok:

        print(
            "SUPABASE CREDIT UPDATE ERROR:",
            response.status_code,
            response.text[:1000]
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Render succeeded, but "
                "credit update failed."
            )
        )

    rows = response.json()

    if not rows:

        raise HTTPException(
            status_code=409,
            detail=(
                "Credit balance changed during "
                "this render. Please try again."
            )
        )

    return new_credits


# =========================
# CURRENT USER / CREDITS
# =========================

@app.get("/me")
def me(request: Request):

    user = verify_supabase_user(request)

    profile = get_or_create_profile(
        user["id"]
    )

    return {
        "user_id": user["id"],
        "credits": profile["credits"],
        "is_admin": profile["is_admin"],
        "unlimited": profile["is_admin"],
    }


# =========================
# RENDER
# =========================

@app.post("/render")
async def render(
    request: Request,
    image: UploadFile = File(...),
    prompt: str = Form("")
):

    # -------------------------
    # VERIFY USER FIRST
    # -------------------------

    user = verify_supabase_user(request)

    user_id = user["id"]


    # -------------------------
    # CREDITS CHECK
    # -------------------------

    profile = get_or_create_profile(
        user_id
    )

    # Admin accounts have unlimited renders.

    if (
        not profile["is_admin"]
        and profile["credits"] <= 0
    ):

        raise HTTPException(
            status_code=402,
            detail="No render credits remaining."
        )


    # -------------------------
    # RATE LIMIT
    # -------------------------

    current_time = time.time()

    if user_id in last_request_time:

        elapsed_time = (
            current_time -
            last_request_time[user_id]
        )

        if elapsed_time < RATE_LIMIT_SECONDS:

            remaining_seconds = int(
                RATE_LIMIT_SECONDS -
                elapsed_time
            ) + 1

            raise HTTPException(
                status_code=429,
                detail=(
                    f"Please wait "
                    f"{remaining_seconds} seconds "
                    f"before generating another render."
                )
            )


    # -------------------------
    # READ IMAGE
    # -------------------------

    try:

        image_bytes = await image.read()

        if not image_bytes:

            raise HTTPException(
                status_code=400,
                detail="Uploaded image is empty."
            )


        # -------------------------
        # CLOUDFLARE REQUEST
        # -------------------------

        url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{ACCOUNT_ID}/ai/run/{MODEL}"
        )

        headers = {
            "Authorization": f"Bearer {TOKEN}"
        }

        files = {
            "input_image_0": (
                image.filename or "sketchup.png",
                image_bytes,
                image.content_type or "image/png"
            )
        }


        # -------------------------
        # USER PROMPT
        # -------------------------

        user_request = (
            prompt
            .strip()[:1000]
        )

        final_prompt = (
            PROMPT
            + "\n\nUSER VISUAL REQUEST:\n"
            + user_request
            + "\n\nIMPORTANT: "
            + "The user request may change ONLY materials, "
            + "colors, lighting, atmosphere and visual style. "
            + "Never change geometry, camera, perspective, "
            + "walls, openings, furniture positions, "
            + "proportions or layout."
        )

        data = {
            "prompt": final_prompt,
            "width": "1536",
            "height": "1024"
        }


        # -------------------------
        # GENERATE
        # -------------------------

        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=240
        )

        if not response.ok:

            print(
                "CLOUDFLARE ERROR:",
                response.status_code,
                response.text[:2000]
            )

            raise HTTPException(
                status_code=502,
                detail="AI generation service failed."
            )

        result = response.json()

        if not result.get("success"):

            raise HTTPException(
                status_code=502,
                detail="Cloudflare generation failed."
            )

        result_data = result.get(
            "result",
            {}
        )

        image_b64 = result_data.get(
            "image"
        )

        if not image_b64:

            raise HTTPException(
                status_code=502,
                detail=(
                    "Cloudflare completed the request "
                    "but returned no image."
                )
            )

        if image_b64.startswith("data:"):

            image_b64 = image_b64.split(
                ",",
                1
            )[1]

        try:

            output_bytes = base64.b64decode(
                image_b64
            )

        except Exception:

            raise HTTPException(
                status_code=502,
                detail=(
                    "Cloudflare returned "
                    "an invalid image."
                )
            )

        if not output_bytes:

            raise HTTPException(
                status_code=502,
                detail="Generated image is empty."
            )


        # -------------------------
        # DEDUCT CREDIT
        # -------------------------

        # Credit is deducted ONLY after
        # Cloudflare successfully generated
        # and returned a valid image.
        #
        # Admin accounts are unlimited
        # and never lose credits.

        if not profile["is_admin"]:

            deduct_credit_after_success(
                user_id,
                profile["credits"]
            )


        # -------------------------
        # START RATE LIMIT
        # -------------------------

        # Rate limit also starts only after
        # a successful generation.

        last_request_time[user_id] = (
            current_time
        )


        # -------------------------
        # RETURN IMAGE
        # -------------------------

        return StreamingResponse(
            io.BytesIO(output_bytes),
            media_type="image/png",
            headers={
                "Cache-Control": "no-store"
            }
        )


    except HTTPException:

        raise


    except Exception as e:

        print(
            "RENDER ERROR:",
            str(e)
        )

        raise HTTPException(
            status_code=500,
            detail="Internal render error."
        )