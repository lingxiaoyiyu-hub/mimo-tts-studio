import base64
import json
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_BASE_URL = "https://token-plan-sgp.xiaomimimo.com/v1"
TTS_MODELS = {
    "mimo-v2.5-tts",
    "mimo-v2.5-tts-voicedesign",
    "mimo-v2.5-tts-voiceclone",
}

app = FastAPI(title="MMTTS Studio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")


class AssistRequest(BaseModel):
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    kind: str
    text: str = ""
    model: str = "mimo-v2.5-pro"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/assist")
def assist(req: AssistRequest):
    if not req.api_key:
        return {"ok": False, "message": "请先填写 API Key"}

    prompts = {
        "style": (
            "你是专业配音导演。请根据用户的播报文本，生成一句适合 TTS 的语音风格指令。"
            "要求：30字以内；包含语气、语速、情绪或场景；不要解释；不要输出引号。"
        ),
        "voice": "根据用户的用途，生成一段 80 字以内的音色描述，包含年龄、性别、音质、语气、场景，只输出描述本身。",
        "text": "把用户的播报文本优化成更适合 TTS 朗读的版本，保持原意，只输出优化后的文本。",
    }
    system = prompts.get(req.kind, prompts["style"])
    payload = {
        "model": req.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": req.text or "自然、清晰、适合短视频旁白"},
        ],
    }
    data = _post_json(req.base_url, req.api_key, "/chat/completions", payload)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"ok": True, "text": content.strip()}


@app.post("/api/tts")
async def generate_tts(
    api_key: str = Form(...),
    base_url: str = Form(DEFAULT_BASE_URL),
    model: str = Form(...),
    voice: str = Form("冰糖"),
    style_prompt: str = Form(""),
    voice_description: str = Form(""),
    text: str = Form(...),
    output_format: str = Form("wav"),
    voice_file: Optional[UploadFile] = File(None),
):
    if model not in TTS_MODELS:
        return {"ok": False, "message": f"不支持的模型：{model}"}
    if not api_key:
        return {"ok": False, "message": "请先填写 API Key"}
    if not text.strip():
        return {"ok": False, "message": "请输入播报文本"}

    audio = {"format": output_format}
    messages = []

    if model == "mimo-v2.5-tts-voiceclone":
        if voice_file is None:
            return {"ok": False, "message": "语音克隆需要上传参考音频"}
        content = await voice_file.read()
        mime_type = _audio_mime_type(voice_file.filename or "", voice_file.content_type)
        encoded = base64.b64encode(content).decode("utf-8")
        if len(encoded) > 10 * 1024 * 1024:
            return {"ok": False, "message": "参考音频 Base64 后不能超过 10MB"}
        audio["voice"] = f"data:{mime_type};base64,{encoded}"
        if style_prompt.strip():
            messages.append({"role": "user", "content": style_prompt.strip()})
        messages.append({"role": "assistant", "content": text.strip()})

    elif model == "mimo-v2.5-tts-voicedesign":
        if not voice_description.strip():
            return {"ok": False, "message": "音色设计需要填写音色描述"}
        messages.append({"role": "user", "content": voice_description.strip()})
        messages.append({"role": "assistant", "content": text.strip()})

    else:
        audio["voice"] = voice.strip() or "冰糖"
        if style_prompt.strip():
            messages.append({"role": "user", "content": style_prompt.strip()})
        messages.append({"role": "assistant", "content": text.strip()})

    payload = {
        "model": model,
        "messages": messages,
        "audio": audio,
    }

    try:
        data = _post_json(base_url, api_key, "/chat/completions", payload, timeout=180)
        audio_data = data.get("choices", [{}])[0].get("message", {}).get("audio", {}).get("data")
        if not audio_data:
            return {"ok": False, "message": "接口没有返回音频", "raw": data}
        audio_bytes = base64.b64decode(audio_data)
        suffix = "mp3" if output_format == "mp3" else "wav"
        file_id = f"{uuid.uuid4().hex}.{suffix}"
        out_path = OUTPUT_DIR / file_id
        out_path.write_bytes(audio_bytes)
        return {
            "ok": True,
            "url": f"/outputs/{file_id}",
            "filename": file_id,
            "size": len(audio_bytes),
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def _post_json(base_url: str, api_key: str, path: str, payload: dict, timeout: int = 60) -> dict:
    url = base_url.rstrip("/") + path
    resp = requests.post(
        url,
        headers={
            "api-key": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=timeout,
    )
    if resp.status_code != 200:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(f"MiMo API 返回错误 {resp.status_code}: {detail}")
    return resp.json()


def _audio_mime_type(filename: str, content_type: Optional[str]) -> str:
    ext = Path(filename).suffix.lower()
    guessed, _ = mimetypes.guess_type(filename)
    mime_type = content_type or guessed
    if ext == ".mp3":
        return "audio/mpeg"
    if ext == ".wav":
        return "audio/wav"
    if mime_type in {"audio/mpeg", "audio/mp3", "audio/wav", "audio/wave", "audio/x-wav"}:
        return "audio/wav" if "wav" in mime_type else "audio/mpeg"
    raise RuntimeError("参考音频只支持 mp3 或 wav")
