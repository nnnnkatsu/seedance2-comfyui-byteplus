"""
BytePlus ModelArk Seedance 2.0 ComfyUI Nodes
==================================
Focused nodes for Seedance 2.0 video generation via BytePlus ModelArk.

  Seedance2TextToVideo        - ModelArk video generation task
  Seedance2ImageToVideo       - ModelArk video generation task
  Seedance2Extend             - Re-submit using source video as reference_video
  Seedance2RetrieveTask       - Retrieve a recent ModelArk task result
  Seedance2Omni               - ModelArk multimodal reference task
  Seedance2Character          - Not supported by direct BytePlus video API
  Seedance2ConsistentVideo    - ModelArk reference_image task

Reference image workflow:
  LoadImage → Seedance2ConsistentVideo

Auth:     Authorization: Bearer header
Create:   POST /api/v3/contents/generations/tasks
Polling:  GET /api/v3/contents/generations/tasks/{id}
"""

import base64
import hashlib
import io
import json
import os
import re
import time
from datetime import datetime

import numpy as np
import requests
import torch
from PIL import Image

try:
    import folder_paths
except ImportError:
    class folder_paths:
        @staticmethod
        def get_output_directory():
            return os.path.join(os.path.expanduser("~"), "comfyui_output")

DEFAULT_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_MODEL = ""
POLL_INTERVAL = 10
MAX_WAIT = 900
CONFIG_PATHS = (
    "~/.byteplus/seedance2-comfyui.json",
    "~/.byteplus/modelark.json",
    "~/.ark/config.json",
)
API_KEY_ENV_VARS = ("ARK_API_KEY", "BYTEPLUS_ARK_API_KEY", "BYTEPLUS_API_KEY")
ENDPOINT_ENV_VARS = (
    "SEEDANCE2_ENDPOINT",
    "BYTEPLUS_SEEDANCE_ENDPOINT",
    "ARK_ENDPOINT",
    "SEEDANCE2_MODEL",
    "BYTEPLUS_SEEDANCE_MODEL",
    "ARK_MODEL",
)
BASE_URL_ENV_VARS = ("BYTEPLUS_ARK_BASE_URL", "ARK_BASE_URL")
RESOLUTION_OPTIONS = ["480p", "720p", "1080p"]
DEFAULT_RESOLUTION = "480p"
VIDEO_REF_TYPE = "SEEDANCE2_VIDEO_REF"
QUALITY_TO_RESOLUTION = {
    "basic": "480p",
    "high": "720p",
}

VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
AUDIO_EXTS = (".mp3", ".wav")
_NONE_CHOICE = "(none)"
_MANUAL_TASK_CHOICE = "(manual task_id)"
TASK_HISTORY_PATH = "~/.byteplus/seedance2-comfyui-tasks.json"
TASK_HISTORY_LIMIT = 50

def _list_input_files(extensions):
    """Return sorted list of files in ComfyUI/input/ matching the given extensions."""
    try:
        import folder_paths
        input_dir = folder_paths.get_input_directory()
        files = [
            f for f in os.listdir(input_dir)
            if os.path.isfile(os.path.join(input_dir, f))
            and f.lower().endswith(extensions)
        ]
        return [_NONE_CHOICE] + sorted(files)
    except Exception:
        return [_NONE_CHOICE]


def _task_history_path():
    return os.path.expanduser(TASK_HISTORY_PATH)


def _load_task_history():
    path = _task_history_path()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[Seedance2] Failed to read task history: {e}")
        return []


def _save_task_history(history):
    try:
        path = _task_history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history[:TASK_HISTORY_LIMIT], f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Seedance2] Failed to write task history: {e}")


def _record_task(task_id, payload_or_result):
    if not task_id:
        return
    data = payload_or_result if isinstance(payload_or_result, dict) else {}
    record = {
        "id": task_id,
        "recorded_at": int(time.time()),
        "model": str(data.get("model", "")),
        "status": str(data.get("status", "")),
        "resolution": str(data.get("resolution", "")),
        "ratio": str(data.get("ratio", "")),
        "duration": data.get("duration", ""),
        "generate_audio": data.get("generate_audio", ""),
    }
    history = [item for item in _load_task_history() if item.get("id") != task_id]
    history.insert(0, record)
    _save_task_history(history)


def _parse_json_object(value, label):
    if not value or not str(value).strip():
        return {}
    try:
        data = json.loads(str(value))
    except Exception as e:
        raise ValueError(f"Invalid {label}: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return data


def _video_ref_data(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"url": text}


def _video_ref_url_and_s3(value):
    data = _video_ref_data(value)
    url = str(data.get("url") or data.get("video_url") or "").strip()
    s3 = data.get("s3") or data.get("s3_reference") or {}
    return url, s3 if isinstance(s3, dict) else {}


def _delete_s3_video_refs(video_refs, delete_enabled):
    if not delete_enabled:
        return
    refs = [
        _video_ref_url_and_s3(value)[1]
        for value in video_refs
        if value
    ]
    refs = [ref for ref in refs if ref.get("key")]
    if not refs:
        print("[Seedance2 Omni] S3 delete requested, but no deletable S3 video_ref inputs were provided.")
        return

    try:
        import boto3
    except ImportError as e:
        raise RuntimeError(
            "boto3 is required to delete S3 reference videos after generation. "
            "Install project requirements in the ComfyUI Python environment."
        ) from e

    seen = set()
    for ref in refs:
        region = str(ref.get("region") or os.environ.get("SEEDANCE2_S3_REGION")
                     or os.environ.get("AWS_DEFAULT_REGION") or "ap-northeast-1").strip()
        bucket = str(ref.get("bucket") or os.environ.get("SEEDANCE2_S3_BUCKET") or "").strip()
        key = str(ref.get("key") or "").strip()
        if not bucket or not key:
            print("[Seedance2 Omni] Skipping S3 delete because bucket or key is missing.")
            continue
        dedupe_key = (region, bucket, key)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        access_key = (
            ref.get("aws_access_key_id")
            or ref.get("access_key_id")
            or os.environ.get("SEEDANCE2_S3_ACCESS_KEY_ID")
            or os.environ.get("AWS_ACCESS_KEY_ID")
            or ""
        )
        secret_key = (
            ref.get("aws_secret_access_key")
            or ref.get("secret_access_key")
            or os.environ.get("SEEDANCE2_S3_SECRET_ACCESS_KEY")
            or os.environ.get("AWS_SECRET_ACCESS_KEY")
            or ""
        )

        client_args = {"region_name": region}
        if access_key or secret_key:
            client_args["aws_access_key_id"] = str(access_key).strip()
            client_args["aws_secret_access_key"] = str(secret_key).strip()
        s3 = boto3.client("s3", **client_args)
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            print(f"[Seedance2 Omni] Deleted S3 reference s3://{bucket}/{key}")
        except Exception as e:
            print(f"[Seedance2 Omni] Failed to delete S3 reference s3://{bucket}/{key}: {e}")


def _recent_task_choices():
    choices = [_MANUAL_TASK_CHOICE]
    for item in _load_task_history():
        task_id = str(item.get("id", "")).strip()
        if not task_id:
            continue
        timestamp = item.get("recorded_at") or 0
        try:
            created = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(timestamp)))
        except Exception:
            created = "unknown time"
        details = " ".join(
            str(value) for value in (
                item.get("status", ""),
                item.get("resolution", ""),
                item.get("ratio", ""),
                f"{item.get('duration')}s" if item.get("duration") else "",
            ) if value
        )
        choices.append(f"{task_id} | {created} | {details}".strip())
    return choices


def _task_id_from_choice(choice):
    match = re.search(r"\bcgt-[^\s|]+", str(choice or ""))
    return match.group(0) if match else ""


def _blank_image():
    return torch.zeros(1, 64, 64, 3)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_config():
    for config_path in CONFIG_PATHS:
        path = os.path.expanduser(config_path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"[Seedance2] Failed to read {path}: {e}")
    return {}


def _first_value(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _load_api_key(api_key_input):
    """Load a BytePlus ModelArk API key from node input, env, or config file."""
    cfg = _read_config()
    key = _first_value(
        api_key_input,
        *(os.environ.get(name, "") for name in API_KEY_ENV_VARS),
        cfg.get("api_key", ""),
        cfg.get("ark_api_key", ""),
    )
    if key:
        return key
    raise RuntimeError(
        "No BytePlus API key found. Paste it into api_key, set ARK_API_KEY, "
        "or create ~/.byteplus/seedance2-comfyui.json with api_key."
    )


def _load_endpoint(endpoint_input):
    cfg = _read_config()
    endpoint = _first_value(
        endpoint_input,
        *(os.environ.get(name, "") for name in ENDPOINT_ENV_VARS),
        cfg.get("endpoint", ""),
        cfg.get("endpoint_id", ""),
        cfg.get("model", ""),
    )
    if endpoint:
        return endpoint
    raise RuntimeError(
        "No BytePlus endpoint configured. Paste your endpoint ID into the "
        "endpoint field, wire the endpoint output from Seedance2BytePlusConfig, "
        "set SEEDANCE2_ENDPOINT, or add endpoint to ~/.byteplus/seedance2-comfyui.json."
    )


def _base_url():
    cfg = _read_config()
    return _first_value(
        *(os.environ.get(name, "") for name in BASE_URL_ENV_VARS),
        cfg.get("base_url", ""),
        DEFAULT_BASE_URL,
    ).rstrip("/")


def _json_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _auth_headers(api_key):
    return {"Authorization": f"Bearer {api_key}"}

def _normalize_prompt_references(prompt):
    """Keep old @image1 syntax working with BytePlus' [Image 1] wording."""
    prompt = prompt or ""

    def repl(match):
        label = match.group(1).capitalize()
        number = match.group(2)
        return f"[{label} {number}]"

    return re.sub(r"@(image|video|audio)([1-9])\b", repl, prompt, flags=re.IGNORECASE)


def _normalize_resolution(resolution):
    value = str(resolution or "").strip().lower()
    return QUALITY_TO_RESOLUTION.get(value, value if value else DEFAULT_RESOLUTION)


def _image_tensor_to_data_url(image_tensor):
    if image_tensor.dim() == 4:
        image_tensor = image_tensor[0]
    arr = np.clip(image_tensor.cpu().numpy(), 0.0, 1.0)
    arr = (arr * 255).astype("uint8")
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    if arr.shape[-1] > 3:
        arr = arr[..., :3]
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=95)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _upload_image(api_key, image_tensor):
    # BytePlus content generation accepts image data URLs directly.
    return _image_tensor_to_data_url(image_tensor)

# Resolve a user-supplied media reference to a URL.
# Rules:
#   - empty / whitespace   → None
#   - starts with http(s)  → returned as-is (already a URL)
#   - local audio file     -> converted to data URL
#   - local video file     -> error; use public URL or asset:// ID
def _path_from_input(ref):
    path = ref
    if os.path.isfile(path):
        return path
    try:
        import folder_paths
        candidate = os.path.join(folder_paths.get_input_directory(), ref)
        if os.path.isfile(candidate):
            return candidate
    except Exception:
        pass
    return None


def _file_to_data_url(path, fallback_mime):
    import mimetypes
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = fallback_mime
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _resolve_media_ref(api_key, ref, kind):
    if not ref or not ref.strip():
        return None
    ref = ref.strip().strip('"').strip("'")
    lower_ref = ref.lower()
    if kind == "video":
        if lower_ref.startswith(("http://", "https://", "asset://")):
            return ref
        if lower_ref.startswith("data:"):
            raise RuntimeError(
                "[Seedance2 Omni] BytePlus reference videos must be public URLs, "
                "S3 pre-signed URLs, or asset:// IDs. data:video inputs are not supported."
            )
    elif kind == "audio":
        if lower_ref.startswith(("http://", "https://", "asset://", "data:audio/")):
            return ref
    path = _path_from_input(ref)
    if not path:
        raise RuntimeError(
            f"[Seedance2 Omni] {kind} reference not found: {ref!r}. "
            "Use a public URL, asset:// ID, data URL, or a file in ComfyUI/input."
        )
    if kind == "video":
        raise RuntimeError(
            "[Seedance2 Omni] BytePlus video generation requires reference videos "
            "to be public URLs or asset:// IDs. Local video upload no longer maps "
            "to a usable generation URL."
        )
    if kind == "audio":
        if not path.lower().endswith(AUDIO_EXTS):
            raise RuntimeError(
                "[Seedance2 Omni] BytePlus reference audio supports only mp3 or wav files."
            )
        return _file_to_data_url(path, "audio/mpeg")
    raise RuntimeError(f"Unsupported media kind: {kind}")

def _url(data):
    u = data.get("url") or data.get("file_url") or data.get("output")
    if not u: raise RuntimeError(f"Upload missing URL: {data}")
    return str(u)

def _content_text(prompt):
    return {"type": "text", "text": _normalize_prompt_references(prompt).strip()}


def _content_image(url, role="reference_image"):
    item = {"type": "image_url", "image_url": {"url": url}}
    if role:
        item["role"] = role
    return item


def _content_video(url, role="reference_video"):
    item = {"type": "video_url", "video_url": {"url": url}}
    if role:
        item["role"] = role
    return item


def _content_audio(url, role="reference_audio"):
    item = {"type": "audio_url", "audio_url": {"url": url}}
    if role:
        item["role"] = role
    return item


SEED_MIN = -1
SEED_MAX = 4294967295


def _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, seed, content_tail=None):
    content = []
    if prompt and prompt.strip():
        content.append(_content_text(prompt))
    if content_tail:
        content.extend(content_tail)
    return {
        "model": _load_endpoint(endpoint),
        "content": content,
        "resolution": _normalize_resolution(resolution),
        "ratio": aspect_ratio or "adaptive",
        "duration": int(duration),
        "seed": int(seed),
        "generate_audio": bool(generate_audio),
        "watermark": False,
    }


def _submit(api_key, endpoint, payload):
    payload = dict(payload)
    payload["model"] = _load_endpoint(endpoint or payload.get("model", ""))
    resp = requests.post(
        f"{_base_url()}/contents/generations/tasks",
        headers=_json_headers(api_key),
        json=payload,
        timeout=60,
    )
    _check(resp)
    data = resp.json()
    task_id = data.get("id") or data.get("task_id") or data.get("request_id")
    if not task_id:
        raise RuntimeError(f"No task id in response: {data}")
    _record_task(task_id, payload)
    return task_id


def _retrieve_task(api_key, task_id):
    resp = requests.get(
        f"{_base_url()}/contents/generations/tasks/{task_id}",
        headers=_auth_headers(api_key),
        timeout=30,
    )
    _check(resp)
    return resp.json()


def _poll(api_key, request_id):
    deadline = time.time() + MAX_WAIT
    while time.time() < deadline:
        data = _retrieve_task(api_key, request_id)
        status = data.get("status")
        print(f"[Seedance2] {status}  {request_id}")
        if status == "succeeded":
            return data
        if status in ("failed", "expired", "cancelled"):
            error = data.get("error") or {}
            raise RuntimeError(f"Failed: {error or status}")
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"Timeout: {request_id}")

def _output_url(result):
    content = result.get("content") or {}
    if isinstance(content, dict) and content.get("video_url"):
        return str(content["video_url"])
    out = result.get("outputs") or result.get("output") or []
    if isinstance(out, list) and out: return str(out[0])
    if isinstance(out, str): return out
    for k in ("video_url", "url"):
        if result.get(k): return str(result[k])
    raise RuntimeError(f"No output video URL: {result}")

def _image_url(result):
    """Extract image URL from a character sheet result."""
    content = result.get("content") or {}
    if isinstance(content, dict) and content.get("last_frame_url"):
        return str(content["last_frame_url"])
    out = result.get("outputs") or result.get("output") or []
    if isinstance(out, list) and out: return str(out[0])
    if isinstance(out, str): return out
    for k in ("image_url", "sheet_url", "url"):
        if result.get(k): return str(result[k])
    raise RuntimeError(f"No image URL in result: {result}")

def _download_image(url):
    """Download a remote image and return a ComfyUI IMAGE tensor (1,H,W,3)."""
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGB")
    arr = np.array(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)

def _check_legacy_unused(resp):
    if resp.status_code == 401: raise RuntimeError("Auth failed — check API key.")
    if resp.status_code == 402: raise RuntimeError("Insufficient credits — top up at muapi.ai")
    if resp.status_code == 429: raise RuntimeError("Rate limited — retry later.")
    if not resp.ok:
        print(f"[Seedance2] API ERROR {resp.status_code}: {resp.text[:500]}")
        try:
            err = resp.json()
            raise RuntimeError(f"API {resp.status_code}: {err}")
        except Exception:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:300]}")

def _check(resp):
    if resp.status_code == 401:
        raise RuntimeError("BytePlus auth failed; check API key.")
    if resp.status_code == 402:
        raise RuntimeError("BytePlus quota or billing error; check ModelArk balance/contract.")
    if resp.status_code == 429:
        raise RuntimeError("BytePlus rate limited; retry later.")
    if not resp.ok:
        print(f"[Seedance2] API ERROR {resp.status_code}: {resp.text[:500]}")
        try:
            err = resp.json()
            raise RuntimeError(f"API {resp.status_code}: {err}")
        except Exception:
            raise RuntimeError(f"API {resp.status_code}: {resp.text[:300]}")


def _first_frame(video_url):
    try:
        import tempfile, cv2
        r = requests.get(video_url, timeout=180, stream=True)
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            for chunk in r.iter_content(8192):
                if chunk: tmp.write(chunk)
            path = tmp.name
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release(); os.remove(path)
        if not ret: raise RuntimeError("no frame")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        return torch.from_numpy(rgb).unsqueeze(0)
    except Exception as e:
        print(f"[Seedance2] first frame failed: {e}")
        return torch.zeros(1, 64, 64, 3)


def _video_preview_ui(filename, subfolder, folder_type="output"):
    return {
        "images": [{
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }],
        "animated": (True,),
    }


def _safe_filename(filename):
    base = os.path.basename(str(filename or "video.mp4"))
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "video.mp4"


def _download_task_preview(video_url, task_id):
    subfolder = "seedance2_task_history_previews"
    out_dir = os.path.join(folder_paths.get_output_directory(), subfolder)
    os.makedirs(out_dir, exist_ok=True)
    digest = hashlib.sha1(f"{task_id}|{video_url}".encode("utf-8")).hexdigest()[:12]
    filename = f"task_{_safe_filename(task_id)}_{digest}.mp4"
    target = os.path.join(out_dir, filename)
    if not os.path.exists(target) or os.path.getsize(target) <= 0:
        r = requests.get(video_url, stream=True, timeout=300)
        r.raise_for_status()
        with open(target, "wb") as fh:
            for chunk in r.iter_content(8192):
                if chunk:
                    fh.write(chunk)
    return filename, subfolder


def _timestamp_from_value(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number = number / 1000
        return int(number)
    text = str(value).strip()
    if not text:
        return 0
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return _timestamp_from_value(float(text))
    normalized = text.replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(normalized).timestamp())
    except Exception:
        return 0


def _format_task_time(record):
    timestamp = int(record.get("created_ts") or record.get("recorded_at") or 0)
    if timestamp:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except Exception:
            pass
    return str(record.get("created_at") or record.get("created") or "")


def _task_id_from_record(record):
    if not isinstance(record, dict):
        return str(record or "").strip()
    for key in ("id", "task_id", "request_id"):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_task_video_url(record):
    if not isinstance(record, dict):
        return ""
    try:
        return _output_url(record)
    except Exception:
        return ""


def _task_prompt_summary(record):
    if not isinstance(record, dict):
        return ""
    content = record.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                return str(item.get("text") or "").replace("\n", " ").strip()
    if isinstance(content, dict):
        text = content.get("text") or content.get("prompt")
        if text:
            return str(text).replace("\n", " ").strip()
    for key in ("prompt", "text"):
        if record.get(key):
            return str(record.get(key)).replace("\n", " ").strip()
    return ""


def _task_record_from_raw(raw, source="api"):
    if isinstance(raw, str):
        raw = {"id": raw}
    if not isinstance(raw, dict):
        return None
    task_id = _task_id_from_record(raw)
    if not task_id:
        return None
    created_ts = 0
    created_at = ""
    for key in ("created_at", "created", "created_time", "create_time", "createdAt", "createTime", "updated_at", "recorded_at"):
        value = raw.get(key)
        ts = _timestamp_from_value(value)
        if ts:
            created_ts = ts
            created_at = str(value)
            break
    if not created_ts:
        created_ts = int(raw.get("recorded_at") or 0)
    return {
        "id": task_id,
        "source": source,
        "status": str(raw.get("status") or raw.get("state") or ""),
        "model": str(raw.get("model") or raw.get("endpoint") or ""),
        "resolution": str(raw.get("resolution") or ""),
        "ratio": str(raw.get("ratio") or raw.get("aspect_ratio") or ""),
        "duration": raw.get("duration", ""),
        "created_at": created_at,
        "created_ts": created_ts,
        "prompt": _task_prompt_summary(raw),
        "video_url": _extract_task_video_url(raw),
        "raw": raw,
    }


def _extract_task_list(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("items", "tasks", "data", "list", "results"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_task_list(value)
            if nested:
                return nested
    return []


def _list_tasks_from_api(api_key, max_items):
    url = f"{_base_url()}/contents/generations/tasks"
    attempts = (
        {"limit": int(max_items)},
        {"page_size": int(max_items)},
        None,
    )
    last_response = None
    for params in attempts:
        resp = requests.get(url, headers=_auth_headers(api_key), params=params, timeout=30)
        if resp.ok:
            data = resp.json()
            return [_task_record_from_raw(item, "api") for item in _extract_task_list(data)]
        last_response = resp
        if resp.status_code not in (400, 404, 422):
            _check(resp)
    if last_response is not None:
        _check(last_response)
    return []


def _list_tasks_from_local(max_items):
    return [
        _task_record_from_raw(item, "local")
        for item in _load_task_history()[:int(max_items)]
    ]


def _combined_task_records(api_key, source, max_items):
    records = []
    errors = []
    if source in ("api_then_local", "api"):
        try:
            records.extend(item for item in _list_tasks_from_api(api_key, max_items) if item)
        except Exception as e:
            errors.append(f"BytePlus list API failed: {e}")
            if source == "api":
                raise
    if source in ("api_then_local", "local") or errors:
        records.extend(item for item in _list_tasks_from_local(max_items) if item)

    deduped = []
    seen = set()
    for record in records:
        task_id = record.get("id")
        if not task_id or task_id in seen:
            continue
        seen.add(task_id)
        deduped.append(record)
    deduped.sort(key=lambda item: int(item.get("created_ts") or 0), reverse=True)
    return deduped[:int(max_items)], errors


def _task_browser_item(record, index, selected=False):
    details = " ".join(str(value) for value in (
        record.get("status", ""),
        record.get("resolution", ""),
        record.get("ratio", ""),
        f"{record.get('duration')}s" if record.get("duration") else "",
    ) if value)
    prompt = str(record.get("prompt") or "").strip()
    if prompt:
        details = f"{details} {prompt}".strip()
    return {
        "index": index,
        "task_id": record.get("id", ""),
        "status": record.get("status", ""),
        "created_at": _format_task_time(record),
        "details": details,
        "source": record.get("source", ""),
        "selected": bool(selected),
    }

# ── Nodes ──────────────────────────────────────────────────────────────────────

class Seedance2TextToVideo:
    """
    Seedance 2.0 Text-to-Video
    ---------------------------
    Generate video purely from a text prompt.
    Resolutions: 480p | 720p | 1080p
    Aspect ratios: 16:9 | 9:16 | 4:3 | 3:4
    Duration: 5 | 10 | 15 seconds
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True,
                "default": "A cinematic aerial shot of a futuristic city at dusk, volumetric lighting, 4K"}),
            "aspect_ratio": (["16:9", "9:16", "4:3", "3:4"], {"default": "16:9"}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ([5, 10, 15], {"default": 5}),
            "seed": ("INT", {"default": -1, "min": SEED_MIN, "max": SEED_MAX, "control_after_generate": True}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, prompt, aspect_ratio, resolution, duration, seed, api_key="", endpoint="", generate_audio=True):
        api_key = _load_api_key(api_key)
        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, seed)
        print("[Seedance2 T2V] Submitting...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 T2V] Done → {url}")
        return (url, _first_frame(url), rid)


class Seedance2ImageToVideo:
    """
    Seedance 2.0 Image-to-Video
    ----------------------------
    Connect up to 9 reference images. Reference them in the prompt
    using @image1 … @image9.

    Example: "The cat in @image1 walks through a sunlit garden."
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True,
                "default": "The character in @image1 walks through a beautiful garden, cinematic motion"}),
            "aspect_ratio": (["16:9", "9:16", "4:3", "3:4"], {"default": "16:9"}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ([5, 10, 15], {"default": 5}),
            "seed": ("INT", {"default": -1, "min": SEED_MIN, "max": SEED_MAX, "control_after_generate": True}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
            "image_1": ("IMAGE",), "image_2": ("IMAGE",), "image_3": ("IMAGE",),
            "image_4": ("IMAGE",), "image_5": ("IMAGE",), "image_6": ("IMAGE",),
            "image_7": ("IMAGE",), "image_8": ("IMAGE",), "image_9": ("IMAGE",),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, prompt, aspect_ratio, resolution, duration, seed, api_key="", endpoint="", generate_audio=True,
            image_1=None, image_2=None, image_3=None, image_4=None, image_5=None,
            image_6=None, image_7=None, image_8=None, image_9=None):
        api_key = _load_api_key(api_key)
        tensors = [image_1, image_2, image_3, image_4, image_5,
                   image_6, image_7, image_8, image_9]
        images_list = []
        for i, img in enumerate(tensors, 1):
            if img is not None:
                print(f"[Seedance2 I2V] Encoding image {i}...")
                images_list.append(_upload_image(api_key, img))
        if not images_list:
            raise ValueError("At least one image required.")
        content_tail = [_content_image(url, "reference_image") for url in images_list]
        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, seed, content_tail)
        print(f"[Seedance2 I2V] Submitting ({len(images_list)} image(s))...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 I2V] Done → {url}")
        return (url, _first_frame(url), rid)


class Seedance2FirstLastFrameToVideo:
    """
    Seedance 2.0 First/Last Frame-to-Video
    ---------------------------------------
    Generate video from a first frame and an optional last frame.
    BytePlus does not allow first/last frame inputs to be mixed with
    reference images, reference videos, reference audio, or draft tasks.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "first_frame_image": ("IMAGE",),
            "prompt": ("STRING", {"multiline": True,
                "default": "Generate a smooth cinematic video starting from the first frame."}),
            "aspect_ratio": (["adaptive", "16:9", "9:16", "4:3", "3:4", "1:1", "21:9"], {"default": "adaptive",
                "tooltip": "Use adaptive to follow the first frame aspect ratio."}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ("INT", {"default": 5, "min": 4, "max": 15, "step": 1}),
            "seed": ("INT", {"default": -1, "min": SEED_MIN, "max": SEED_MAX, "control_after_generate": True}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
            "last_frame_image": ("IMAGE",),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, first_frame_image, prompt, aspect_ratio, resolution, duration, seed,
            api_key="", endpoint="", generate_audio=True, last_frame_image=None):
        api_key = _load_api_key(api_key)
        print("[Seedance2 Frame] Encoding first frame...")
        content_tail = [_content_image(_upload_image(api_key, first_frame_image), "first_frame")]
        if last_frame_image is not None:
            print("[Seedance2 Frame] Encoding last frame...")
            content_tail.append(_content_image(_upload_image(api_key, last_frame_image), "last_frame"))

        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, seed, content_tail)
        print(f"[Seedance2 Frame] Submitting ({len(content_tail)} frame image(s))...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 Frame] Done → {url}")
        return (url, _first_frame(url), rid)


class Seedance2Extend:
    """
    Seedance 2.0 Extend Video
    --------------------------
    Extend a previously generated Seedance 2.0 video.
    Pass the request_id from a completed generation.
    Optionally provide a prompt to guide the continuation.
    Duration: 5 | 10 | 15 seconds added to the original.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "request_id": ("STRING", {"multiline": False, "default": "",
                "tooltip": "request_id from a completed Seedance 2.0 generation"}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ([5, 10, 15], {"default": 5}),
            "seed": ("INT", {"default": -1, "min": SEED_MIN, "max": SEED_MAX, "control_after_generate": True}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
            "prompt": ("STRING", {"multiline": True, "default": "",
                "tooltip": "Optional continuation prompt"}),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "new_request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, request_id, resolution, duration, seed, api_key="", endpoint="", generate_audio=True, prompt=""):
        api_key = _load_api_key(api_key)
        if not request_id.strip(): raise ValueError("request_id required.")
        source = request_id.strip()
        if source.lower().startswith(("http://", "https://", "asset://")):
            source_url = source
        else:
            print(f"[Seedance2 Extend] Retrieving source task {source}...")
            source_result = _retrieve_task(api_key, source)
            if source_result.get("status") != "succeeded":
                source_result = _poll(api_key, source)
            source_url = _output_url(source_result)
        extend_prompt = prompt.strip() or "Continue the reference video naturally."
        content_tail = [_content_video(source_url, "reference_video")]
        payload = _build_payload(endpoint, extend_prompt, "adaptive", resolution, duration, generate_audio, seed, content_tail)
        print(f"[Seedance2 Extend] Submitting extension from {source}...")
        new_id = _submit(api_key, endpoint, payload)
        result = _poll(api_key, new_id)
        url = _output_url(result)
        print(f"[Seedance2 Extend] Done → {url}")
        return (url, _first_frame(url), new_id)


class Seedance2ApiKey:
    """
    Store your BytePlus ModelArk API key once and wire it to any Seedance 2.0 node.
    Leave all node api_key fields empty — they auto-read from this node
    Blank api_key fields can also read ARK_API_KEY or ~/.byteplus/seedance2-comfyui.json.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "api_key": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Your BytePlus ModelArk API key"}),
        }}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("api_key",)
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, api_key):
        return (_load_api_key(api_key),)


class Seedance2BytePlusConfig:
    """
    Store BytePlus API key and endpoint ID once and wire both outputs.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "api_key": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Your BytePlus ModelArk API key"}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
        }}
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("api_key", "endpoint")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, api_key, endpoint):
        return (_load_api_key(api_key), _load_endpoint(endpoint))


class Seedance2RetrieveTask:
    """
    Retrieve a historical BytePlus video generation task result.

    Use the request_id returned by any generation node. BytePlus retains task
    status and output video URLs for about 24 hours, so save the video locally
    if you need to keep it.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "task_id": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Historical BytePlus video generation task ID, for example cgt-..."}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
            "recent_task": (_recent_task_choices(), {"default": _MANUAL_TASK_CHOICE,
                "tooltip": "Recent task IDs created by this node pack on this machine. Leave task_id blank to use this selection."}),
            "wait_for_completion": ("BOOLEAN", {"default": False,
                "tooltip": "Poll until the task succeeds, fails, expires, or times out."}),
            "download_first_frame": ("BOOLEAN", {"default": True,
                "tooltip": "Download the generated video URL and decode its first frame for preview."}),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id", "status", "task_json")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, task_id, api_key="", recent_task=_MANUAL_TASK_CHOICE,
            wait_for_completion=False, download_first_frame=True):
        api_key = _load_api_key(api_key)
        resolved_id = task_id.strip() or _task_id_from_choice(recent_task)
        if not resolved_id:
            raise ValueError("task_id is required. Paste a cgt-... ID or select a recent task.")

        print(f"[Seedance2 RetrieveTask] Retrieving {resolved_id}...")
        result = _poll(api_key, resolved_id) if wait_for_completion else _retrieve_task(api_key, resolved_id)
        status = str(result.get("status", ""))
        _record_task(resolved_id, result)

        video_url = ""
        if status == "succeeded":
            try:
                video_url = _output_url(result)
            except Exception as e:
                print(f"[Seedance2 RetrieveTask] No video URL found: {e}")

        first_frame = _first_frame(video_url) if (download_first_frame and video_url) else _blank_image()
        task_json = json.dumps(result, ensure_ascii=False, indent=2)
        return (video_url, first_frame, resolved_id, status, task_json)


class Seedance2TaskHistoryBrowser:
    """
    Browse recent BytePlus video generation tasks.

    The node tries the BytePlus list-task API first, then falls back to the
    local task IDs recorded by this node pack. Selecting a row retrieves that
    task again so the video URL can be previewed and reused as video_ref.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source": (["api_then_local", "api", "local"], {"default": "api_then_local",
                "tooltip": "api_then_local tries BytePlus list tasks first, then falls back to this node pack's local task history."}),
            "selected_index": ("INT", {"default": 1, "min": 1, "max": 999, "step": 1}),
            "max_items": ("INT", {"default": 20, "min": 1, "max": 200, "step": 1}),
            "selected_task_id": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Stable task ID selected by the browser list. If set, it is used before selected_index."}),
            "download_preview": ("BOOLEAN", {"default": True,
                "tooltip": "Download the selected task video for inline preview when a video URL is available."}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
        }}

    RETURN_TYPES = ("STRING", VIDEO_REF_TYPE, "IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "video_ref", "first_frame", "request_id", "status", "task_json")
    FUNCTION = "run"
    CATEGORY = "験 Seedance 2.0"
    OUTPUT_NODE = True

    def run(self, source, selected_index, max_items, selected_task_id, download_preview, api_key=""):
        api_key = _load_api_key(api_key)
        records, errors = _combined_task_records(api_key, source, max_items)
        if not records:
            text = "No BytePlus generation tasks found."
            if errors:
                text += "\n\n" + "\n".join(errors)
            return {
                "ui": {
                    "text": [text],
                    "task_items_json": ["[]"],
                    "selected_task_id": [""],
                    "selected_index": [""],
                },
                "result": ("", {}, _blank_image(), "", "", "{}"),
            }

        selected_id = str(selected_task_id or "").strip()
        selected_pos = None
        if selected_id:
            for pos, record in enumerate(records):
                if record.get("id") == selected_id:
                    selected_pos = pos
                    break
        if selected_pos is None:
            selected_pos = max(1, min(int(selected_index), len(records))) - 1
        selected = records[selected_pos]
        selected_id = selected.get("id") or ""

        task_result = {}
        retrieve_error = ""
        if selected_id:
            try:
                print(f"[Seedance2 TaskHistory] Retrieving {selected_id}...")
                task_result = _retrieve_task(api_key, selected_id)
                _record_task(selected_id, task_result)
            except Exception as e:
                retrieve_error = f"Retrieve selected task failed: {e}"
                print(f"[Seedance2 TaskHistory] {retrieve_error}")
                task_result = selected.get("raw") if isinstance(selected.get("raw"), dict) else {}

        status = str(task_result.get("status") or selected.get("status") or "")
        video_url = _extract_task_video_url(task_result) or str(selected.get("video_url") or "")
        video_ref = {"url": video_url} if video_url else {}
        first_frame = _first_frame(video_url) if (download_preview and video_url.startswith(("http://", "https://"))) else _blank_image()
        task_json = json.dumps(task_result or selected.get("raw") or selected, ensure_ascii=False, indent=2)

        selected["status"] = status or selected.get("status", "")
        selected["video_url"] = video_url
        items = [
            _task_browser_item(record, index, index - 1 == selected_pos)
            for index, record in enumerate(records, 1)
        ]

        lines = []
        for item in items:
            marker = "*" if item["selected"] else " "
            lines.append(
                f"{marker}{item['index']:02d} {item['task_id']}  "
                f"{item['status'] or '(unknown)'}  {item['created_at']}  {item['details']}"
            )
        selected_line = (
            f"Selected {selected_pos + 1:02d}: {selected_id}  "
            f"{status or '(unknown)'}  {_format_task_time(selected)}"
        )
        text_parts = [selected_line]
        if errors:
            text_parts.extend(errors)
        if retrieve_error:
            text_parts.append(retrieve_error)
        if video_url:
            text_parts.append(f"video_url: {video_url}")
        else:
            text_parts.append("video_url: (none; task may still be running, failed, or expired)")
        text_parts.append("\n".join(lines))

        ui = {
            "text": ["\n\n".join(part for part in text_parts if part)],
            "task_items_json": [json.dumps(items, ensure_ascii=False)],
            "selected_task_id": [selected_id],
            "selected_index": [str(selected_pos + 1)],
        }
        if download_preview and video_url.startswith(("http://", "https://")):
            try:
                filename, subfolder = _download_task_preview(video_url, selected_id)
                ui.update(_video_preview_ui(filename, subfolder))
            except Exception as e:
                ui["text"] = [ui["text"][0] + f"\n\nPreview download failed: {e}"]

        return {
            "ui": ui,
            "result": (video_url, video_ref, first_frame, selected_id, status, task_json),
        }


class Seedance2VideoReference:
    """
    Convert a public video URL, S3 pre-signed URL, or asset:// ID into the
    structured reference type consumed by Omni.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video_url": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Reference video URL, S3 pre-signed URL, or asset:// ID."}),
        }}
    RETURN_TYPES = (VIDEO_REF_TYPE,)
    RETURN_NAMES = ("video_ref",)
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, video_url):
        url = str(video_url or "").strip()
        if not url:
            raise ValueError("video_url is required.")
        return ({"url": url},)


class Seedance2Omni:
    """
    Seedance 2.0 Omni Reference
    ----------------------------
    Multi-modal generation: combine images, video clips, and audio clips
    as reference material alongside a text prompt.

    Reference media in the prompt using:
      @image1 … @image9   — uploaded image tensors
      @video1 … @video3   — SEEDANCE2_VIDEO_REF from S3 nodes or Video Reference URL
      @audio1 … @audio3   — audio URL, asset:// ID, data URL, or local audio file

    BytePlus does not accept local video files in this request. Upload private
    videos through the S3 helper nodes and pass the generated video_ref.
    Local audio files in ComfyUI/input/ are encoded as data:audio URLs.

    Example:
      "A person @image1 walking on the beach at sunset, cinematic lighting"

    Resolutions: 480p | 720p | 1080p
    Aspect ratios: 21:9 | 16:9 | 4:3 | 1:1 | 3:4 | 9:16
    Duration: 4 – 15 seconds
    """
    @classmethod
    def INPUT_TYPES(cls):
        audio_files = _list_input_files(AUDIO_EXTS)
        video_ref_tip = ("Reference video object from S3 Upload/Browse or Video Reference URL. "
                         "S3 refs can be deleted after generation when cleanup is enabled.")
        audio_tip = ("Pick an mp3 or wav file from ComfyUI/input/. BytePlus audio refs: "
                     "2-15s each, max 3 clips, total <=15s, each file <=15 MB.")
        audio_url_tip = ("Reference audio. Use a public http(s) URL, asset:// ID, data:audio URL, "
                         "or an absolute local mp3/wav path that will be encoded as Base64.")
        return {"required": {
            "prompt": ("STRING", {"multiline": True,
                "default": "A person @image1 walking on the beach at sunset, cinematic lighting"}),
            "aspect_ratio": (["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"], {"default": "16:9"}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ("INT", {"default": 5, "min": 4, "max": 15, "step": 1}),
            "seed": ("INT", {"default": -1, "min": SEED_MIN, "max": SEED_MAX, "control_after_generate": True}),
        }, "optional": {
            "api_key":      ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
            # Reference images (uploaded from ComfyUI tensors)
            "image_1": ("IMAGE",), "image_2": ("IMAGE",), "image_3": ("IMAGE",),
            "image_4": ("IMAGE",), "image_5": ("IMAGE",), "image_6": ("IMAGE",),
            "image_7": ("IMAGE",), "image_8": ("IMAGE",), "image_9": ("IMAGE",),
            # Reference videos (@video1 … @video3): structured video refs
            "video_ref_1": (VIDEO_REF_TYPE, {"tooltip": video_ref_tip}),
            "video_ref_2": (VIDEO_REF_TYPE, {"tooltip": video_ref_tip}),
            "video_ref_3": (VIDEO_REF_TYPE, {"tooltip": video_ref_tip}),
            "delete_s3_references_after_generation": ("BOOLEAN", {"default": False,
                "tooltip": "Delete connected S3 video_ref objects after this Omni generation succeeds."}),
            # Reference audio (@audio1 … @audio3): dropdown + override string
            "audio_file_1": (audio_files, {"default": _NONE_CHOICE, "tooltip": audio_tip}),
            "audio_url_1":  ("STRING", {"multiline": False, "default": "", "tooltip": audio_url_tip}),
            "audio_file_2": (audio_files, {"default": _NONE_CHOICE, "tooltip": audio_tip}),
            "audio_url_2":  ("STRING", {"multiline": False, "default": "", "tooltip": audio_url_tip}),
            "audio_file_3": (audio_files, {"default": _NONE_CHOICE, "tooltip": audio_tip}),
            "audio_url_3":  ("STRING", {"multiline": False, "default": "", "tooltip": audio_url_tip}),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, prompt, aspect_ratio, resolution, duration, seed, api_key="", endpoint="", generate_audio=True,
            character_id="",
            image_1=None, image_2=None, image_3=None, image_4=None, image_5=None,
            image_6=None, image_7=None, image_8=None, image_9=None,
            video_ref_1=None, video_ref_2=None, video_ref_3=None,
            video_file_1=_NONE_CHOICE, video_url_1="",
            video_file_2=_NONE_CHOICE, video_url_2="",
            video_file_3=_NONE_CHOICE, video_url_3="",
            s3_config_json="", s3_reference_json_1="", s3_reference_json_2="", s3_reference_json_3="",
            delete_s3_references_after_generation=False,
            audio_file_1=_NONE_CHOICE, audio_url_1="",
            audio_file_2=_NONE_CHOICE, audio_url_2="",
            audio_file_3=_NONE_CHOICE, audio_url_3=""):
        api_key = _load_api_key(api_key)

        # Upload image tensors
        image_tensors = [image_1, image_2, image_3, image_4, image_5,
                         image_6, image_7, image_8, image_9]
        images_list = []
        for i, img in enumerate(image_tensors, 1):
            if img is not None:
                print(f"[Seedance2 Omni] Encoding image {i}...")
                images_list.append(_upload_image(api_key, img))

        # Legacy workflows may still contain removed local video widgets.
        legacy_video_files = [video_file_1, video_file_2, video_file_3]
        if any(v and v != _NONE_CHOICE for v in legacy_video_files):
            raise RuntimeError(
                "[Seedance2 Omni] Local video_file inputs were removed because BytePlus "
                "requires reference videos to be URLs or asset:// IDs. Upload local videos "
                "with S3 Upload Reference Video, then connect its video_ref to Omni."
            )

        # For audio slots, prefer the dropdown selection; fall back to the URL/path override.
        def _pick(dropdown, url):
            if dropdown and dropdown != _NONE_CHOICE:
                return dropdown  # filename inside ComfyUI/input/ — _resolve_media_ref handles it
            return url

        legacy_s3_config = _parse_json_object(s3_config_json, "s3_config_json") if s3_config_json else {}

        def _legacy_video_ref(url, s3_json, index):
            data = {"url": str(url).strip()}
            if s3_json and str(s3_json).strip():
                s3_data = _parse_json_object(s3_json, f"s3_reference_json_{index}")
                for key in ("aws_access_key_id", "aws_secret_access_key", "access_key_id", "secret_access_key"):
                    if legacy_s3_config.get(key) and not s3_data.get(key):
                        s3_data[key] = legacy_s3_config[key]
                if legacy_s3_config.get("region") and not s3_data.get("region"):
                    s3_data["region"] = legacy_s3_config["region"]
                if legacy_s3_config.get("bucket") and not s3_data.get("bucket"):
                    s3_data["bucket"] = legacy_s3_config["bucket"]
                data["s3"] = s3_data
            return data

        video_refs = []
        for index, (ref, legacy_url, legacy_s3_json) in enumerate((
            (video_ref_1, video_url_1, s3_reference_json_1),
            (video_ref_2, video_url_2, s3_reference_json_2),
            (video_ref_3, video_url_3, s3_reference_json_3),
        ), 1):
            if ref:
                video_refs.append(ref)
            elif legacy_url and str(legacy_url).strip():
                video_refs.append(_legacy_video_ref(legacy_url, legacy_s3_json, index))
        audio_refs = [
            _pick(audio_file_1, audio_url_1),
            _pick(audio_file_2, audio_url_2),
            _pick(audio_file_3, audio_url_3),
        ]

        # Resolve references (local path → upload, URL → passthrough)
        video_files = []
        for ref in video_refs:
            url, _ = _video_ref_url_and_s3(ref)
            resolved = _resolve_media_ref(api_key, url, "video")
            if resolved:
                video_files.append(resolved)

        audio_files = []
        for u in audio_refs:
            resolved = _resolve_media_ref(api_key, u, "audio")
            if resolved:
                audio_files.append(resolved)

        content_tail = []
        content_tail.extend(_content_image(url, "reference_image") for url in images_list)
        content_tail.extend(_content_video(url, "reference_video") for url in video_files)
        content_tail.extend(_content_audio(url, "reference_audio") for url in audio_files)

        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, seed, content_tail)

        print(f"[Seedance2 Omni] PAYLOAD: {payload}")
        print(f"[Seedance2 Omni] Submitting "
              f"({len(images_list)} image(s), {len(video_files)} video(s), {len(audio_files)} audio(s))...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 Omni] Done → {url}")
        _delete_s3_video_refs(video_refs, delete_s3_references_after_generation)
        return (url, _first_frame(url), rid)


class Seedance2Character:
    """
    Seedance 2.0 Consistent Character
    -----------------------------------
    Deprecated muapi-only character-sheet helper.
    BytePlus direct Seedance video generation does not expose this operation.

    Use:
      LoadImage → Seedance2ConsistentVideo
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "outfit_description": ("STRING", {"multiline": True,
                "default": "cyberpunk jacket with neon accents, glowing visor",
                "tooltip": "Describe the desired outfit/style for the character sheet"}),
        }, "optional": {
            "api_key": ("STRING", {"multiline": False, "default": ""}),
            # Up to 3 reference photos (server hard-cap)
            "image_1": ("IMAGE",), "image_2": ("IMAGE",), "image_3": ("IMAGE",),
        }}
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("sheet_image", "sheet_url", "character_id")
    FUNCTION = "run"
    CATEGORY = "Seedance 2.0/Deprecated"

    def run(self, outfit_description, api_key="",
            image_1=None, image_2=None, image_3=None):
        raise RuntimeError(
            "Seedance2Character was a MuAPI-only helper. BytePlus ModelArk does "
            "not expose a direct character-sheet generation endpoint through the "
            "Seedance video generation API, so this deprecated node intentionally "
            "has no endpoint field. Use Seedance2ConsistentVideo with an existing "
            "reference image, public sheet_url, or BytePlus asset:// reference instead."
        )
        api_key = _load_api_key(api_key)
        tensors = [image_1, image_2, image_3]
        images_list = []
        for i, img in enumerate(tensors, 1):
            if img is not None:
                print(f"[Seedance2 Character] Uploading reference image {i}...")
                images_list.append(_upload_image(api_key, img))
        if not images_list:
            raise ValueError("At least one reference image is required to create a character.")

        payload = {
            "images_list": images_list,
            "prompt": outfit_description.strip(),
        }

        print(f"[Seedance2 Character] Creating character sheet from {len(images_list)} image(s)...")
        rid = _submit(api_key, "seedance-2-character", payload)
        result = _poll(api_key, rid)

        # seedance-2-character returns only a character_id (UUID), not an image URL.
        # Try to get a real URL; fall back to blank placeholder if not available.
        try:
            sheet_url = _image_url(result)
            if not sheet_url.startswith("http"):
                raise ValueError("Not a URL")
            print(f"[Seedance2 Character] Sheet ready → {sheet_url}")
            sheet_image = _download_image(sheet_url)
        except Exception as e:
            print(f"[Seedance2 Character] No sheet image ({e}), using placeholder.")
            sheet_url = ""
            sheet_image = torch.zeros(1, 64, 64, 3)

        print(f"[Seedance2 Character] character_id = {rid}")
        return (sheet_image, sheet_url, rid)


class Seedance2ConsistentVideo:
    """
    Seedance 2.0 Consistent Character Video
    -----------------------------------------
    Generate a video that maintains character identity from an existing
    reference image, public image URL, or BytePlus asset:// image reference.

    Wire a Load Image output to sheet_image, or paste sheet_url, then write
    your scene prompt. The reference image is automatically passed as the first
    reference image and referenced as @image1 in the prompt.

    You can also wire in up to 2 additional scene/background images
    (referenced as @image2, @image3 in your prompt).

    Example prompt:
        "@image1 rides a motorcycle through a neon-lit city at night, cinematic"
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "prompt": ("STRING", {"multiline": True,
                "default": "@image1 walks through a sunlit garden, cinematic motion, 4K"}),
            "aspect_ratio": (["16:9", "9:16", "4:3", "3:4"], {"default": "16:9"}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ([5, 10, 15], {"default": 5}),
            "seed": ("INT", {"default": -1, "min": SEED_MIN, "max": SEED_MAX, "control_after_generate": True}),
        }, "optional": {
            "api_key":         ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
            # Reference image, for example from ComfyUI Load Image.
            "sheet_image":     ("IMAGE",),
            # Fallback: paste the sheet_url string if you don't have the tensor
            "sheet_url":       ("STRING", {"multiline": False, "default": ""}),
            # Optional extra scene/background images (@image2, @image3)
            "scene_image_2":   ("IMAGE",),
            "scene_image_3":   ("IMAGE",),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, prompt, aspect_ratio, resolution, duration, seed, api_key="", endpoint="", generate_audio=True,
            sheet_image=None, sheet_url="", scene_image_2=None, scene_image_3=None):
        api_key = _load_api_key(api_key)

        images_list = []

        # Character sheet goes first — either from tensor or URL
        if sheet_image is not None:
            print("[Seedance2 ConsistentVideo] Encoding character sheet...")
            images_list.append(_upload_image(api_key, sheet_image))
        elif sheet_url and sheet_url.strip():
            images_list.append(sheet_url.strip())
        else:
            raise ValueError(
                "Connect sheet_image (from Seedance2Character) or paste sheet_url."
            )

        # Optional extra images
        for i, img in enumerate([scene_image_2, scene_image_3], 2):
            if img is not None:
                print(f"[Seedance2 ConsistentVideo] Encoding scene image {i}...")
                images_list.append(_upload_image(api_key, img))

        # Ensure @image1 is present so the reference image anchors the scene.
        if "@image1" not in prompt and "[Image 1]" not in prompt:
            prompt = f"@image1 {prompt.strip()}"

        content_tail = [_content_image(url, "reference_image") for url in images_list]
        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, seed, content_tail)

        print(f"[Seedance2 ConsistentVideo] Submitting with {len(images_list)} image(s)...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 ConsistentVideo] Done → {url}")
        return (url, _first_frame(url), rid)


NODE_CLASS_MAPPINGS = {
    "Seedance2ApiKey":            Seedance2ApiKey,
    "Seedance2BytePlusConfig":    Seedance2BytePlusConfig,
    "Seedance2RetrieveTask":      Seedance2RetrieveTask,
    "Seedance2TaskHistoryBrowser": Seedance2TaskHistoryBrowser,
    "Seedance2VideoReference":    Seedance2VideoReference,
    "Seedance2TextToVideo":       Seedance2TextToVideo,
    "Seedance2ImageToVideo":      Seedance2ImageToVideo,
    "Seedance2FirstLastFrameToVideo": Seedance2FirstLastFrameToVideo,
    "Seedance2Extend":            Seedance2Extend,
    "Seedance2Omni":              Seedance2Omni,
    "Seedance2Character":         Seedance2Character,
    "Seedance2ConsistentVideo":   Seedance2ConsistentVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance2TaskHistoryBrowser": "🌱 Seedance 2.0 Generation History Browser",
    "Seedance2ApiKey":            "🔑 Seedance 2.0 API Key",
    "Seedance2BytePlusConfig":    "🌱 Seedance2BytePlusConfig",  
    "Seedance2RetrieveTask":      "🌱 Seedance 2.0 Retrieve Task Result",
    "Seedance2VideoReference":    "🌱 Seedance 2.0 Video Reference URL",
    "Seedance2TextToVideo":       "🌱 Seedance 2.0 Text-to-Video",
    "Seedance2ImageToVideo":      "🌱 Seedance 2.0 Image-to-Video",
    "Seedance2FirstLastFrameToVideo": "🌱 Seedance 2.0 First/Last Frame-to-Video",
    "Seedance2Extend":            "🌱 Seedance 2.0 Extend",
    "Seedance2Omni":              "🌱 Seedance 2.0 Omni Reference",
    "Seedance2Character":         "Deprecated - MuAPI-only Character Sheet (Unsupported)",
    "Seedance2ConsistentVideo":   "🌱 Seedance 2.0 Consistent Character Video",
}
NODE_DISPLAY_NAME_MAPPINGS["Seedance2BytePlusConfig"] = "🌱 Seedance 2.0 BytePlus Config"
