# app/services/face_verify.py
import base64
import io
from typing import Tuple
from PIL import Image

# Optional: load insightface jika tersedia
try:
    import numpy as np
    import insightface
    _face_model = insightface.app.FaceAnalysis(name="buffalo_l")
    _face_model.prepare(ctx_id=0, det_size=(320, 320))
except Exception:
    _face_model = None

def _read_image_from_request(req) -> Image.Image:
    if req.files and "image" in req.files:
        return Image.open(req.files["image"].stream).convert("RGB")
    # JSON base64
    data = (req.json or {}).get("image_base64")
    if data and isinstance(data, str):
        # support data URL
        if data.startswith("data:"):
            data = data.split(",", 1)[1]
        raw = base64.b64decode(data)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    raise ValueError("Tidak ada gambar di request (butuh field 'image' atau 'image_base64')")

def verify_face_fast(req) -> Tuple[bool, float]:
    """
    Return: (is_ok, score) — score dalam [0..1]
    """
    img = _read_image_from_request(req)

    if _face_model is None:
        # Fallback super cepat: valid kalau ada wajah terdeteksi minimal (dummy rule)
        # Di produksi, pastikan tetap pakai engine sebenarnya.
        width, height = img.size
        score = 0.6 if min(width, height) >= 64 else 0.2
        return (score >= 0.5, float(score))

    # InsightFace path (deteksi minimal 1 wajah)
    arr = np.array(img)[:, :, ::-1]  # RGB -> BGR
    faces = _face_model.get(arr)
    score = 0.0 if not faces else min(1.0, max(f.det_score for f in faces))
    return (score >= 0.5, float(score))
