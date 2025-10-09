import io
import time
import numpy as np
import cv2

from ..extensions import get_face_engine
from .storage.supabase_storage import upload_bytes, signed_url, download, list_objects
from ..celery_utils import celery # <-- 1. Impor instance Celery

# Fungsi helper seperti _now_ts, _normalize, _cosine, dll. tetap sama
# ...
def _now_ts() -> int:
    return int(time.time())

def _today_str() -> str:
    import datetime as _dt
    return _dt.datetime.utcnow().strftime("%Y%m%d")

def _normalize(x: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = np.linalg.norm(x) + eps
    return x / n

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = _normalize(a)
    b = _normalize(b)
    return float(np.dot(a, b))

def _l2(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(a - b))

def _score(a: np.ndarray, b: np.ndarray, metric: str) -> float:
    return _cosine(a, b) if metric == "cosine" else _l2(a, b)

def _is_match(score: float, metric: str, threshold: float) -> bool:
    return score >= threshold if metric == "cosine" else score <= threshold

def decode_image(file_storage):
    # Disesuaikan agar bisa menerima bytes atau objek FileStorage
    if isinstance(file_storage, bytes):
        data = file_storage
    else:
        data = file_storage.read()
    
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Invalid image")
    return img

def get_embedding(img_bgr):
    engine = get_face_engine()
    faces = engine.get(img_bgr)
    if not faces:
        return None
    return faces[0].embedding

def _user_root(user_id: str) -> str:
    user_id = (user_id or "").strip()
    if not user_id:
        raise ValueError("user_id kosong")
    return f"face_detection/{user_id}"
# ...

# -------- public services --------

@celery.task(name='tasks.enroll_user_task')
def enroll_user_task(user_id: str, images_data: list[bytes]):
    """
    Versi 'enroll_user' yang berjalan sebagai background task.
    Menerima data gambar dalam bentuk bytes.
    """
    try:
        embeddings = []
        uploaded = []

        for idx, img_bytes in enumerate(images_data, 1):
            img = decode_image(img_bytes)
            emb = get_embedding(img)
            if emb is None:
                print(f"Wajah tidak terdeteksi pada gambar #{idx} untuk user {user_id}")
                continue
            
            emb = _normalize(emb.astype(np.float32))

            _, buf = cv2.imencode(".jpg", img)
            ts = _now_ts()
            key = f"{_user_root(user_id)}/baseline_{ts}_{idx}.jpg"
            upload_bytes(key, buf.tobytes(), "image/jpeg")
            uploaded.append({"path": key, "signed_url": signed_url(key)})
            embeddings.append(emb)

        if not embeddings:
            # Gagal memproses semua gambar
            # Di sini Anda bisa menambahkan logika notifikasi kegagalan
            return {"status": "error", "message": "Tidak ada wajah yang terdeteksi di semua gambar."}

        mean_emb = _normalize(np.stack(embeddings, axis=0).mean(axis=0))
        emb_io = io.BytesIO()
        np.save(emb_io, mean_emb)
        emb_key = f"{_user_root(user_id)}/embedding.npy"
        upload_bytes(emb_key, emb_io.getvalue(), "application/octet-stream")
        
        # Di sini Anda dapat memicu notifikasi keberhasilan
        # Contoh: memanggil task lain untuk mengirim notifikasi
        # from .notification_service import send_notification_task
        # send_notification_task.delay(...)

        return {
            "status": "success",
            "user_id": user_id,
            "images_count": len(uploaded),
            "embedding_path": emb_key,
        }
    except Exception as e:
        print(f"Error dalam enroll_user_task untuk user {user_id}: {e}")
        return {"status": "error", "message": str(e)}

# Fungsi verify_user tetap sama karena harus sinkron (memberi respons langsung)
def verify_user(
    user_id: str,
    probe_file,
    metric: str = "cosine",
    threshold: float = 0.45,
):
    # ... (kode verify_user tidak berubah)
    probe_img = decode_image(probe_file)
    probe_emb = get_embedding(probe_img)
    if probe_emb is None:
        raise ValueError("Wajah tidak terdeteksi pada probe")
    probe_n = _normalize(probe_emb.astype(np.float32))

    emb_key = f"{_user_root(user_id)}/embedding.npy"
    ref = None
    try:
        emb_bytes = download(emb_key)
        ref = np.load(io.BytesIO(emb_bytes))
    except Exception:
        ref = None

    if ref is None:
        prefix = f"{_user_root(user_id)}"
        items = list_objects(prefix)
        baselines = [it for it in items if it.get("name", "").startswith("baseline_")]
        if not baselines:
            raise FileNotFoundError("Embedding & baseline user belum ada di storage")
        embs = []
        for it in baselines[:3]:
            key = f"{prefix}/{it['name']}"
            img_bytes = download(key)
            img_arr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
            e = get_embedding(img)
            if e is not None:
                embs.append(_normalize(e.astype(np.float32)))
        if not embs:
            raise RuntimeError("Gagal hitung embedding baseline")
        ref = np.stack(embs, axis=0).mean(axis=0)

    ref_n = _normalize(ref.astype(np.float32))
    score = _score(ref_n, probe_n, metric)
    match = _is_match(score, metric, threshold)

    return {
        "user_id": user_id,
        "metric": metric,
        "threshold": threshold,
        "score": float(score),
        "match": bool(match),
    }