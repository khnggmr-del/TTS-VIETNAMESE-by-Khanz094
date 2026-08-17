import asyncio
import io
import json
import re
import threading
import time
import uuid
from pathlib import Path

import edge_tts
from flask import Flask, request, jsonify, send_file, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

VOICES = {
    "nam-minh": "vi-VN-NamMinhNeural",
    "hoai-my": "vi-VN-HoaiMyNeural",
}
VOICE_LABELS = {
    "nam-minh": "Nam Minh",
    "hoai-my": "Hoài My",
}

MAX_CHARS = 20000
CHUNK_SIZE = 2000
MAX_HISTORY = 50

JOBS = {}

HISTORY_DIR = Path("history")
HISTORY_DIR.mkdir(exist_ok=True)
HISTORY_INDEX = HISTORY_DIR / "index.json"


def load_history():
    if HISTORY_INDEX.exists():
        try:
            return json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_history(items):
    HISTORY_INDEX.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_history_entry(entry):
    items = load_history()
    items.insert(0, entry)
    if len(items) > MAX_HISTORY:
        for old in items[MAX_HISTORY:]:
            old_path = HISTORY_DIR / old["filename"]
            if old_path.exists():
                old_path.unlink()
        items = items[:MAX_HISTORY]
    save_history(items)


def sanitize_filename(name):
    name = (name or "").strip()
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    if name.lower().endswith(".mp3"):
        name = name[:-4]
    name = name.strip()[:100]
    return name or None


def split_text(text, max_len=CHUNK_SIZE):
    text = text.strip()
    if len(text) <= max_len:
        return [text]
    sentences = re.split(r"(?<=[.!?…\n])\s+", text)
    chunks = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_len:
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


async def synth_chunk(text, voice, rate, pitch, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            buf = io.BytesIO()
            async for msg in communicate.stream():
                if msg["type"] == "audio":
                    buf.write(msg["data"])
            data = buf.getvalue()
            if data:
                return data
        except Exception as e:
            last_err = e
        await asyncio.sleep(1.5 * (attempt + 1))
    if last_err:
        raise last_err
    return b""


async def synth_all_with_progress(job_id, chunks, voice, rate, pitch, concurrency=3):
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(idx, chunk):
        async with semaphore:
            data = await synth_chunk(chunk, voice, rate, pitch)
            JOBS[job_id]["completed"] += 1
            return idx, data

    tasks = [worker(i, c) for i, c in enumerate(chunks)]
    raw_results = await asyncio.gather(*tasks)
    raw_results.sort(key=lambda x: x[0])
    return [data for _, data in raw_results if data]


def run_job(job_id, chunks, voice_id, voice_key, rate, pitch, preview, custom_name):
    try:
        audio_bytes_list = asyncio.run(
            synth_all_with_progress(job_id, chunks, voice_id, rate, pitch)
        )
        if not audio_bytes_list:
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["error"] = "Không tạo được âm thanh, thử lại"
            return
        final_bytes = (
            audio_bytes_list[0] if len(audio_bytes_list) == 1 else b"".join(audio_bytes_list)
        )

        filename = f"{job_id}.mp3"
        (HISTORY_DIR / filename).write_bytes(final_bytes)
        add_history_entry(
            {
                "id": job_id,
                "filename": filename,
                "voice_key": voice_key,
                "voice_label": VOICE_LABELS.get(voice_key, voice_key),
                "preview": preview,
                "created_at": time.strftime("%d/%m/%Y %H:%M"),
                "custom_name": custom_name,
            }
        )

        JOBS[job_id]["status"] = "done"
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/tts/start", methods=["POST"])
def start_tts():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    voice_key = body.get("voice")
    rate = body.get("rate", "+0%")
    pitch = body.get("pitch", "+0Hz")
    custom_name = sanitize_filename(body.get("filename"))

    if not text:
        return jsonify({"detail": "Thiếu văn bản"}), 400
    if len(text) > MAX_CHARS:
        return jsonify({"detail": f"Văn bản vượt quá {MAX_CHARS} ký tự"}), 400
    if voice_key not in VOICES:
        return jsonify({"detail": "Giọng không hợp lệ"}), 400

    voice_id = VOICES[voice_key]
    chunks = split_text(text)
    job_id = uuid.uuid4().hex
    preview = text[:80] + ("…" if len(text) > 80 else "")

    JOBS[job_id] = {
        "total": len(chunks),
        "completed": 0,
        "status": "processing",
        "error": None,
        "custom_name": custom_name,
    }
    threading.Thread(
        target=run_job,
        args=(job_id, chunks, voice_id, voice_key, rate, pitch, preview, custom_name),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id, "total": len(chunks)})


@app.route("/api/tts/status/<job_id>")
def tts_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"detail": "Không tìm thấy job"}), 404
    return jsonify(
        {
            "status": job["status"],
            "completed": job["completed"],
            "total": job["total"],
            "error": job.get("error"),
            "custom_name": job.get("custom_name"),
        }
    )


@app.route("/api/tts/result/<job_id>")
def tts_result(job_id):
    path = HISTORY_DIR / f"{job_id}.mp3"
    if not path.exists():
        return jsonify({"detail": "Chưa sẵn sàng"}), 400
    job = JOBS.get(job_id, {})
    custom_name = job.get("custom_name")
    download_name = f"{custom_name}.mp3" if custom_name else path.name
    return send_file(path, mimetype="audio/mpeg", as_attachment=True, download_name=download_name)


@app.route("/api/history")
def get_history():
    return jsonify(load_history())


@app.route("/api/history/<entry_id>/audio")
def history_audio(entry_id):
    path = HISTORY_DIR / f"{entry_id}.mp3"
    if not path.exists():
        return jsonify({"detail": "Không tìm thấy file"}), 404
    return send_file(path, mimetype="audio/mpeg")


@app.route("/api/history/<entry_id>", methods=["DELETE"])
def delete_history(entry_id):
    items = load_history()
    items = [i for i in items if i["id"] != entry_id]
    save_history(items)
    path = HISTORY_DIR / f"{entry_id}.mp3"
    if path.exists():
        path.unlink()
    return jsonify({"status": "deleted"})


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, threaded=True)
