import os
import io
import base64
import requests
import time
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")

if not TOKEN:
    raise ValueError("CLOUDFLARE_API_TOKEN missing")

if not ACCOUNT_ID:
    raise ValueError("CLOUDFLARE_ACCOUNT_ID missing")

MODEL = "@cf/black-forest-labs/flux-2-klein-4b"


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


app = FastAPI(title="ArchRender AI")

RATE_LIMIT_SECONDS = 60
last_request_time = {}
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "status": "ArchRender AI backend is running",
        "provider": "Cloudflare Workers AI",
        "model": MODEL,
        "quality": "High Quality 1536x1024"
    }


@app.post("/render")
async def render(request: Request, image: UploadFile = File(...), prompt: str = Form("")):
    client_ip = request.client.host
    current_time = time.time()

    if client_ip in last_request_time:
        if current_time - last_request_time[client_ip] < RATE_LIMIT_SECONDS:
            raise HTTPException(
                status_code=429,
                detail="Please wait 60 seconds before generating another render."
            )

    last_request_time[client_ip] = current_time
    try:

        image_bytes = await image.read()

        if not image_bytes:
            raise Exception("Uploaded image is empty")

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
        user_request = prompt.strip()[:1000]
        data = {
            "prompt": PROMPT + "\n\nUSER VISUAL REQUEST:\n" + user_request + "\n\nIMPORTANT: The user request may change ONLY materials, colors, lighting, atmosphere and visual style. Never change geometry, camera, perspective, walls, openings, furniture positions, proportions or layout.",
            "width": "1536",
            "height": "1024"
        }

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

            raise Exception(
                f"Cloudflare error {response.status_code}: "
                f"{response.text[:1000]}"
            )

        result = response.json()

        if not result.get("success"):
            raise Exception(
                f"Cloudflare generation failed: {result}"
            )

        result_data = result.get("result", {})

        image_b64 = result_data.get("image")

        if not image_b64:
            raise Exception(
                "Cloudflare completed the request but returned no image"
            )

        if image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]

        try:
            output_bytes = base64.b64decode(image_b64)
        except Exception:
            raise Exception(
                "Cloudflare returned an invalid image"
            )

        if not output_bytes:
            raise Exception(
                "Generated image is empty"
            )

        return StreamingResponse(
            io.BytesIO(output_bytes),
            media_type="image/png",
            headers={
                "Cache-Control": "no-store"
            }
        )

    except Exception as e:

        print("RENDER ERROR:", str(e))

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )