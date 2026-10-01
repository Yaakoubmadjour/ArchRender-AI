import os
import io
import base64
import requests

from fastapi import FastAPI, UploadFile, File, HTTPException
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
Convert the provided SketchUp screenshot into a premium,
high-end photorealistic architectural visualization.

ABSOLUTE PRIORITY — PRESERVE THE SOURCE IMAGE:

Keep exactly the same:
- camera position
- camera angle
- perspective and field of view
- room dimensions
- architectural geometry
- walls
- ceiling
- floor
- doors and openings
- windows
- columns and partitions
- furniture positions
- furniture dimensions and proportions
- tables
- chairs
- cabinets
- shelves
- all visible objects
- complete spatial composition

The source image must remain clearly recognizable
as exactly the same architectural project.

DO NOT:
- redesign the interior
- change the architecture
- change the layout
- move furniture
- replace furniture
- add furniture
- remove furniture
- add architectural elements
- remove architectural elements
- change camera perspective
- distort walls or proportions
- crop important parts of the original composition

ONLY transform the visual quality and materials.

RENDER QUALITY:

Create a highly realistic professional architectural render
with physically believable PBR materials.

Use:
- detailed natural wood grain
- realistic painted plaster walls
- realistic stone and ceramic surfaces
- realistic flooring
- realistic metal
- physically accurate glass reflections
- realistic upholstery and fabrics
- subtle surface imperfections
- fine material micro-texture
- realistic roughness and reflections
- accurate contact shadows
- ambient occlusion

LIGHTING:

Use premium architectural photography lighting:
- soft natural daylight
- physically realistic global illumination
- realistic indirect bounced light
- soft natural shadows
- balanced highlights
- controlled contrast
- realistic exposure
- neutral white balance
- no blown highlights
- no excessive darkness
- natural interior atmosphere

IMAGE QUALITY:

Ultra photorealistic.
High-end architectural visualization.
Professional interior photography.
Extremely detailed materials.
Clean sharp edges.
Fine realistic textures.
Natural depth.
Realistic reflections.
Realistic shadows.
High dynamic range.
Crisp professional image quality.

The final result should look like a photograph of the
original SketchUp project after professional construction,
NOT like a redesigned AI-generated room.
"""


app = FastAPI(title="ArchRender AI")


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
async def render(image: UploadFile = File(...)):

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

        data = {
            "prompt": PROMPT,
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