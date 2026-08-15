import asyncio
import io
import re
import uuid

import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydub import AudioSegment

app = FastAPI(title="VN TTS - Nam Minh & Hoài My")

VOICES = {
    "nam-minh": "vi-VN-NamMinhNeural",
    "hoai-my": "vi-VN-HoaiMyNeural",
}

MAX_CHARS = 20000
CHUNK_SIZE = 1800  # số ký tự an toàn cho mỗi lần gọi edge-tts


class TTSRequest(BaseModel):
    text: str
    voice: str  # "nam-minh" hoặc "hoai-my"
    rate: str = "+0%"   # ví dụ "+10%", "-10%"
    pitch: str = "+0Hz"


def split_text(text: str, max_len: int = CHUNK_SIZE) -> list[str]:
    """Chia văn bản thành các đoạn nhỏ, ưu tiên cắt ở cuối câu."""
    text = text.strip()
    if len(text) <= max_len:
        return [text]

    sentences = re.split(r"(?<=[.!?…\n])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(sentence) > max_len:
            # câu quá dài, cắt cứng theo dấu phẩy hoặc khoảng trắng
            words = sentence.split(" ")
            piece = ""
            for w in words:
                if len(piece) + len(w) + 1 > max_len:
                    if piece:
                        chunks.append(piece.strip())
                    piece = w
                else:
                    piece = f"{piece} {w}".strip()
            if piece:
                sentence = piece
            else:
                continue

        if len(current) + len(sentence) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()

    if current:
        chunks.append(current.strip())

    return [c for c in chunks if c]


async def synth_chunk(text: str, voice: str, rate: str, pitch: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    buf = io.BytesIO()
    async for msg in communicate.stream():
        if msg["type"] == "audio":
            buf.write(msg["data"])
    return buf.getvalue()


@app.post("/api/tts")
async def text_to_speech(req: TTSRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Thiếu văn bản")
    if len(text) > MAX_CHARS:
        raise HTTPException(400, f"Văn bản vượt quá {MAX_CHARS} ký tự")
    if req.voice not in VOICES:
        raise HTTPException(400, "Giọng không hợp lệ")

    voice_id = VOICES[req.voice]
    chunks = split_text(text)

    audio_bytes_list = []
    for chunk in chunks:
        data = await synth_chunk(chunk, voice_id, req.rate, req.pitch)
        if data:
            audio_bytes_list.append(data)

    if not audio_bytes_list:
        raise HTTPException(500, "Không tạo được âm thanh, thử lại")

    if len(audio_bytes_list) == 1:
        final_bytes = audio_bytes_list[0]
    else:
        combined = AudioSegment.empty()
        for b in audio_bytes_list:
            seg = AudioSegment.from_file(io.BytesIO(b), format="mp3")
            combined += seg
        out = io.BytesIO()
        combined.export(out, format="mp3", bitrate="128k")
        final_bytes = out.getvalue()

    filename = f"tts-{uuid.uuid4().hex[:8]}.mp3"
    return StreamingResponse(
        io.BytesIO(final_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
