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
import io
import json
import os
import re
import time

import numpy as np
import requests
import torch
from PIL import Image

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
QUALITY_TO_RESOLUTION = {
    "basic": "480p",
    "high": "720p",
}

VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus")
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
    if ref.lower().startswith(("http://", "https://", "asset://", "data:")):
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


def _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, content_tail=None):
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

    def run(self, prompt, aspect_ratio, resolution, duration, api_key="", endpoint="", generate_audio=True):
        api_key = _load_api_key(api_key)
        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio)
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

    def run(self, prompt, aspect_ratio, resolution, duration, api_key="", endpoint="", generate_audio=True,
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
        if not images_list: raise ValueError("At least one image required.")
        content_tail = [_content_image(url, "reference_image") for url in images_list]
        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, content_tail)
        print(f"[Seedance2 I2V] Submitting ({len(images_list)} image(s))...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 I2V] Done → {url}")
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

    def run(self, request_id, resolution, duration, api_key="", endpoint="", generate_audio=True, prompt=""):
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
        payload = _build_payload(endpoint, extend_prompt, "adaptive", resolution, duration, generate_audio, content_tail)
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


class Seedance2Omni:
    """
    Seedance 2.0 Omni Reference
    ----------------------------
    Multi-modal generation: combine images, video clips, and audio clips
    as reference material alongside a text prompt.

    Reference media in the prompt using:
      @image1 … @image9   — uploaded image tensors
      @video1 … @video3   — video clip (local file path OR http/https URL)
      @audio1 … @audio3   — audio clip (local file path OR http/https URL)

    The video_* / audio_* fields accept any of:
      - an absolute path to a local file (e.g. D:\\clips\\a.mp4)
      - a filename inside ComfyUI/input/ (e.g. my_clip.mp4)
      - an http(s) URL (passed through unchanged)
    Local files are auto-uploaded to the API before submission.

    Example:
      "A person @image1 walking on the beach at sunset, cinematic lighting"

    Resolutions: 480p | 720p | 1080p
    Aspect ratios: 21:9 | 16:9 | 4:3 | 1:1 | 3:4 | 9:16
    Duration: 4 – 15 seconds
    """
    @classmethod
    def INPUT_TYPES(cls):
        video_files = _list_input_files(VIDEO_EXTS)
        audio_files = _list_input_files(AUDIO_EXTS)
        video_tip = ("Pick a video file from ComfyUI/input/. "
                     "Leave as (none) to use the URL/path override field instead.")
        audio_tip = ("Pick an audio file from ComfyUI/input/. "
                     "Leave as (none) to use the URL/path override field instead.")
        override_tip = ("Optional override: http(s) URL or absolute local path. "
                        "Used only if the dropdown above is (none).")
        return {"required": {
            "prompt": ("STRING", {"multiline": True,
                "default": "A person @image1 walking on the beach at sunset, cinematic lighting"}),
            "aspect_ratio": (["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"], {"default": "16:9"}),
            "resolution": (RESOLUTION_OPTIONS, {"default": DEFAULT_RESOLUTION,
                "tooltip": "BytePlus output resolution. 1080p is not supported by Seedance 2.0 Fast endpoints."}),
            "duration": ("INT", {"default": 5, "min": 4, "max": 15, "step": 1}),
        }, "optional": {
            "api_key":      ("STRING", {"multiline": False, "default": ""}),
            "endpoint": ("STRING", {"multiline": False, "default": DEFAULT_MODEL,
                "tooltip": "BytePlus ModelArk endpoint ID, for example ep-..."}),
            "generate_audio": ("BOOLEAN", {"default": True}),
            "character_id": ("STRING", {"multiline": False, "default": "",
                "tooltip": "BytePlus asset:// ID or asset ID for a digital character"}),
            # Reference images (uploaded from ComfyUI tensors)
            "image_1": ("IMAGE",), "image_2": ("IMAGE",), "image_3": ("IMAGE",),
            "image_4": ("IMAGE",), "image_5": ("IMAGE",), "image_6": ("IMAGE",),
            "image_7": ("IMAGE",), "image_8": ("IMAGE",), "image_9": ("IMAGE",),
            # Reference videos (@video1 … @video3): dropdown + override string
            "video_file_1": (video_files, {"default": _NONE_CHOICE, "tooltip": video_tip}),
            "video_url_1":  ("STRING", {"multiline": False, "default": "", "tooltip": override_tip}),
            "video_file_2": (video_files, {"default": _NONE_CHOICE, "tooltip": video_tip}),
            "video_url_2":  ("STRING", {"multiline": False, "default": "", "tooltip": override_tip}),
            "video_file_3": (video_files, {"default": _NONE_CHOICE, "tooltip": video_tip}),
            "video_url_3":  ("STRING", {"multiline": False, "default": "", "tooltip": override_tip}),
            # Reference audio (@audio1 … @audio3): dropdown + override string
            "audio_file_1": (audio_files, {"default": _NONE_CHOICE, "tooltip": audio_tip}),
            "audio_url_1":  ("STRING", {"multiline": False, "default": "", "tooltip": override_tip}),
            "audio_file_2": (audio_files, {"default": _NONE_CHOICE, "tooltip": audio_tip}),
            "audio_url_2":  ("STRING", {"multiline": False, "default": "", "tooltip": override_tip}),
            "audio_file_3": (audio_files, {"default": _NONE_CHOICE, "tooltip": audio_tip}),
            "audio_url_3":  ("STRING", {"multiline": False, "default": "", "tooltip": override_tip}),
        }}
    RETURN_TYPES = ("STRING", "IMAGE", "STRING")
    RETURN_NAMES = ("video_url", "first_frame", "request_id")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"

    def run(self, prompt, aspect_ratio, resolution, duration, api_key="", endpoint="", generate_audio=True,
            character_id="",
            image_1=None, image_2=None, image_3=None, image_4=None, image_5=None,
            image_6=None, image_7=None, image_8=None, image_9=None,
            video_file_1=_NONE_CHOICE, video_url_1="",
            video_file_2=_NONE_CHOICE, video_url_2="",
            video_file_3=_NONE_CHOICE, video_url_3="",
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

        # For each slot, prefer the dropdown selection; fall back to the URL/path override.
        def _pick(dropdown, url):
            if dropdown and dropdown != _NONE_CHOICE:
                return dropdown  # filename inside ComfyUI/input/ — _resolve_media_ref handles it
            return url

        video_refs = [
            _pick(video_file_1, video_url_1),
            _pick(video_file_2, video_url_2),
            _pick(video_file_3, video_url_3),
        ]
        audio_refs = [
            _pick(audio_file_1, audio_url_1),
            _pick(audio_file_2, audio_url_2),
            _pick(audio_file_3, audio_url_3),
        ]

        # Resolve references (local path → upload, URL → passthrough)
        video_files = []
        for u in video_refs:
            resolved = _resolve_media_ref(api_key, u, "video")
            if resolved:
                video_files.append(resolved)

        audio_files = []
        for u in audio_refs:
            resolved = _resolve_media_ref(api_key, u, "audio")
            if resolved:
                audio_files.append(resolved)

        content_tail = []
        if character_id and character_id.strip():
            asset_ref = character_id.strip()
            if not asset_ref.startswith("asset://"):
                asset_ref = f"asset://{asset_ref}"
            content_tail.append(_content_image(asset_ref, "reference_image"))
        content_tail.extend(_content_image(url, "reference_image") for url in images_list)
        content_tail.extend(_content_video(url, "reference_video") for url in video_files)
        content_tail.extend(_content_audio(url, "reference_audio") for url in audio_files)

        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, content_tail)

        print(f"[Seedance2 Omni] PAYLOAD: {payload}")
        print(f"[Seedance2 Omni] Submitting "
              f"({len(images_list)} image(s), {len(video_files)} video(s), {len(audio_files)} audio(s))...")
        rid = _submit(api_key, endpoint, payload)
        result = _poll(api_key, rid)
        url = _output_url(result)
        print(f"[Seedance2 Omni] Done → {url}")
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

    def run(self, prompt, aspect_ratio, resolution, duration, api_key="", endpoint="", generate_audio=True,
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
        payload = _build_payload(endpoint, prompt, aspect_ratio, resolution, duration, generate_audio, content_tail)

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
    "Seedance2TextToVideo":       Seedance2TextToVideo,
    "Seedance2ImageToVideo":      Seedance2ImageToVideo,
    "Seedance2Extend":            Seedance2Extend,
    "Seedance2Omni":              Seedance2Omni,
    "Seedance2Character":         Seedance2Character,
    "Seedance2ConsistentVideo":   Seedance2ConsistentVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance2ApiKey":            "🔑 Seedance 2.0 API Key",
    "Seedance2BytePlusConfig":    "🌱 Seedance2BytePlusConfig",  
    "Seedance2RetrieveTask":      "🌱 Seedance 2.0 Retrieve Task Result",
    "Seedance2TextToVideo":       "🌱 Seedance 2.0 Text-to-Video",
    "Seedance2ImageToVideo":      "🌱 Seedance 2.0 Image-to-Video",
    "Seedance2Extend":            "🌱 Seedance 2.0 Extend",
    "Seedance2Omni":              "🌱 Seedance 2.0 Omni Reference",
    "Seedance2Character":         "Deprecated - MuAPI-only Character Sheet (Unsupported)",
    "Seedance2ConsistentVideo":   "🌱 Seedance 2.0 Consistent Character Video",
}
NODE_DISPLAY_NAME_MAPPINGS["Seedance2BytePlusConfig"] = "🌱 Seedance 2.0 BytePlus Config"
