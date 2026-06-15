"""S3 helper nodes for private Seedance 2.0 reference videos."""

import json
import hashlib
import mimetypes
import os
import re
import shutil
import time
import uuid
from datetime import datetime

try:
    import folder_paths
except ImportError:
    class folder_paths:
        @staticmethod
        def get_input_directory():
            return os.path.join(os.path.expanduser("~"), "comfyui_input")

        @staticmethod
        def get_output_directory():
            return os.path.join(os.path.expanduser("~"), "comfyui_output")


VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v")
NONE_CHOICE = "(none)"
DEFAULT_REGION = "ap-northeast-1"
DEFAULT_PREFIX = "video-refs"
DEFAULT_EXPIRES_IN = 300
S3_CONFIG_PATHS = (
    "~/.byteplus/seedance2-s3.json",
    "~/.aws/seedance2-s3.json",
)


def _boto3():
    try:
        import boto3
        return boto3
    except ImportError as e:
        raise RuntimeError(
            "boto3 is required for S3 reference video nodes. Install it in the "
            "ComfyUI Python environment with: pip install boto3"
        ) from e


def _requests():
    try:
        import requests
        return requests
    except ImportError as e:
        raise RuntimeError(
            "requests is required for downloading S3 preview videos. Install the "
            "project requirements in the ComfyUI Python environment."
        ) from e


def _s3_client(settings):
    client_args = {"region_name": (settings.get("region") or DEFAULT_REGION).strip()}
    access_key = (settings.get("aws_access_key_id") or "").strip()
    secret_key = (settings.get("aws_secret_access_key") or "").strip()
    if access_key or secret_key:
        client_args["aws_access_key_id"] = access_key
        client_args["aws_secret_access_key"] = secret_key
    return _boto3().client("s3", **client_args)


def _read_s3_file_config():
    for config_path in S3_CONFIG_PATHS:
        path = os.path.expanduser(config_path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"[Seedance2 S3] Failed to read {path}: {e}")
    return {}


def _parse_config_json(s3_config_json):
    if not s3_config_json or not str(s3_config_json).strip():
        return {}
    try:
        data = json.loads(str(s3_config_json))
    except Exception as e:
        raise ValueError(f"Invalid s3_config_json: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("s3_config_json must be a JSON object.")
    return data


def _s3_settings(s3_config_json="", prefix_override=""):
    file_cfg = _read_s3_file_config()
    node_cfg = _parse_config_json(s3_config_json)
    prefix_override = str(prefix_override or "").strip()
    aws_access_key_id = (
        node_cfg.get("aws_access_key_id")
        or node_cfg.get("access_key_id")
        or os.environ.get("SEEDANCE2_S3_ACCESS_KEY_ID")
        or os.environ.get("AWS_ACCESS_KEY_ID")
        or file_cfg.get("aws_access_key_id")
        or file_cfg.get("access_key_id")
        or ""
    )
    aws_secret_access_key = (
        node_cfg.get("aws_secret_access_key")
        or node_cfg.get("secret_access_key")
        or os.environ.get("SEEDANCE2_S3_SECRET_ACCESS_KEY")
        or os.environ.get("AWS_SECRET_ACCESS_KEY")
        or file_cfg.get("aws_secret_access_key")
        or file_cfg.get("secret_access_key")
        or ""
    )
    region = (
        node_cfg.get("region")
        or os.environ.get("SEEDANCE2_S3_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or file_cfg.get("region")
        or DEFAULT_REGION
    )
    bucket = (
        node_cfg.get("bucket")
        or os.environ.get("SEEDANCE2_S3_BUCKET")
        or file_cfg.get("bucket")
        or ""
    )
    prefix = (
        prefix_override
        or node_cfg.get("prefix")
        or os.environ.get("SEEDANCE2_S3_PREFIX")
        or file_cfg.get("prefix")
        or DEFAULT_PREFIX
    )
    if not str(bucket).strip():
        raise ValueError(
            "S3 bucket is required. Connect S3 Config, set SEEDANCE2_S3_BUCKET, "
            "or create ~/.byteplus/seedance2-s3.json."
        )
    return {
        "aws_access_key_id": str(aws_access_key_id).strip(),
        "aws_secret_access_key": str(aws_secret_access_key).strip(),
        "region": str(region).strip() or DEFAULT_REGION,
        "bucket": str(bucket).strip(),
        "prefix": _clean_prefix(str(prefix)),
    }


def _list_input_videos():
    try:
        input_dir = folder_paths.get_input_directory()
        files = [
            name for name in os.listdir(input_dir)
            if os.path.isfile(os.path.join(input_dir, name))
            and name.lower().endswith(VIDEO_EXTS)
        ]
        return [NONE_CHOICE] + sorted(files)
    except Exception:
        return [NONE_CHOICE]


def _video_input_to_path(video):
    if video is None:
        return ""

    if isinstance(video, str) and os.path.isfile(video):
        return video

    if isinstance(video, dict):
        for key in ("path", "file", "filename"):
            value = video.get(key)
            if isinstance(value, str) and os.path.isfile(value):
                return value

    if hasattr(video, "get_stream_source"):
        source = video.get_stream_source()
        if isinstance(source, str) and os.path.isfile(source):
            return source
        if hasattr(source, "name") and isinstance(source.name, str) and os.path.isfile(source.name):
            return source.name

    if hasattr(video, "save_to"):
        out_subfolder = "seedance2_s3_video_inputs"
        out_dir = os.path.join(folder_paths.get_output_directory(), out_subfolder)
        os.makedirs(out_dir, exist_ok=True)
        target = os.path.join(out_dir, f"{int(time.time())}_{uuid.uuid4().hex[:8]}_video.mp4")
        video.save_to(target)
        if os.path.isfile(target):
            return target

    return ""


def _resolve_video_path(local_video_file, local_video_path, video=None):
    video_path = _video_input_to_path(video)
    if video_path:
        return video_path

    path = (local_video_path or "").strip().strip('"').strip("'")
    if path and os.path.isfile(path):
        return path
    if local_video_file and local_video_file != NONE_CHOICE:
        candidate = os.path.join(folder_paths.get_input_directory(), local_video_file)
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError("Select a video from ComfyUI/input or provide a valid local_video_path.")


def _clean_prefix(prefix):
    value = (prefix or DEFAULT_PREFIX).strip().strip("/")
    return value or DEFAULT_PREFIX


def _safe_filename(filename):
    base = os.path.basename(filename)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "reference.mp4"


def _s3_key(prefix, file_path):
    day = datetime.now().strftime("%Y%m%d")
    stamp = datetime.now().strftime("%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    filename = _safe_filename(file_path)
    return f"{_clean_prefix(prefix)}/{day}/{stamp}_{suffix}_{filename}"


def _presign_get(s3, bucket, key, expires_in):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket.strip(), "Key": key},
        ExpiresIn=int(expires_in),
    )


def _content_type(path):
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "video/mp4"


def _format_size(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


def _download_preview(url, subfolder, filename):
    out_dir = os.path.join(folder_paths.get_output_directory(), subfolder)
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, filename)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        return target
    r = _requests().get(url, stream=True, timeout=300)
    r.raise_for_status()
    with open(target, "wb") as fh:
        for chunk in r.iter_content(8192):
            if chunk:
                fh.write(chunk)
    return target


def _s3_preview_name(index, obj):
    key = obj["Key"]
    filename = key.rsplit("/", 1)[-1]
    modified = obj.get("LastModified")
    modified_text = modified.isoformat() if hasattr(modified, "isoformat") else str(modified or "")
    size_text = str(obj.get("Size", 0))
    digest = hashlib.sha1(f"{key}|{modified_text}|{size_text}".encode("utf-8")).hexdigest()[:12]
    return f"s3ref_selected_{index:02d}_{digest}_{_safe_filename(filename)}"


def _video_preview_ui(previews):
    if isinstance(previews, dict):
        previews = [previews]
    items = []
    for preview in previews:
        items.append({
            "filename": preview["filename"],
            "subfolder": preview.get("subfolder", ""),
            "type": preview.get("type", "output"),
        })
    return {"images": items, "animated": (True,)}


def _local_video_preview(file_path):
    abs_path = os.path.abspath(file_path)
    input_dir = os.path.abspath(folder_paths.get_input_directory())
    try:
        rel = os.path.relpath(abs_path, input_dir)
        if not rel.startswith("..") and not os.path.isabs(rel):
            subfolder = os.path.dirname(rel).replace("\\", "/")
            return {
                "filename": os.path.basename(rel),
                "subfolder": subfolder,
                "type": "input",
                "format": "video/mp4",
            }
    except Exception:
        pass

    out_subfolder = "seedance2_s3_local_previews"
    out_dir = os.path.join(folder_paths.get_output_directory(), out_subfolder)
    os.makedirs(out_dir, exist_ok=True)
    filename = f"{int(time.time())}_{_safe_filename(file_path)}"
    target = os.path.join(out_dir, filename)
    shutil.copy2(file_path, target)
    return {
        "filename": filename,
        "subfolder": out_subfolder,
        "type": "output",
        "format": "video/mp4",
    }


def _s3_reference_payload(settings, key):
    bucket = settings["bucket"].strip()
    return json.dumps(
        {
            "region": settings["region"].strip() or DEFAULT_REGION,
            "bucket": bucket,
            "key": key,
            "s3_uri": f"s3://{bucket}/{key}",
        },
        ensure_ascii=False,
    )


def _friendly_s3_error(action, error, bucket, key_or_prefix):
    text = str(error)
    if "AccessDenied" in text or "not authorized" in text:
        if action == "upload":
            permission = "s3:PutObject"
            target = f"arn:aws:s3:::{bucket}/{key_or_prefix}"
            hint = (
                "If your IAM policy is limited to a prefix such as "
                "`video-refs/project-a/*`, set the S3 Config prefix to that exact prefix."
            )
        elif action == "list":
            permission = "s3:ListBucket and s3:GetObject"
            target = f"bucket `{bucket}` with prefix `{key_or_prefix}`"
            hint = "Allow ListBucket on the bucket and GetObject on the reference-video prefix."
        else:
            permission = "s3:DeleteObject"
            target = f"arn:aws:s3:::{bucket}/{key_or_prefix}"
            hint = "Allow DeleteObject on the reference-video prefix, or disable deletion."
        raise RuntimeError(
            f"S3 {action} was denied by AWS IAM. Required permission: {permission}. "
            f"Target: {target}. {hint}"
        ) from error
    raise error


class Seedance2S3Config:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "aws_access_key_id": ("STRING", {"multiline": False, "default": ""}),
            "aws_secret_access_key": ("STRING", {"multiline": False, "default": "", "password": True}),
            "region": ("STRING", {"multiline": False, "default": DEFAULT_REGION,
                "tooltip": "AWS S3 region. Required unless provided by env vars or ~/.byteplus/seedance2-s3.json."}),
            "bucket": ("STRING", {"multiline": False, "default": "",
                "tooltip": "AWS S3 bucket name. Required unless provided by env vars or ~/.byteplus/seedance2-s3.json."}),
            "prefix": ("STRING", {"multiline": False, "default": DEFAULT_PREFIX,
                "tooltip": "Default S3 key prefix for reference videos."}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("s3_config_json",)
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0/S3"

    def run(self, aws_access_key_id, aws_secret_access_key, region, bucket, prefix):
        config = {
            "aws_access_key_id": aws_access_key_id.strip(),
            "aws_secret_access_key": aws_secret_access_key.strip(),
            "region": region.strip() or DEFAULT_REGION,
            "bucket": bucket.strip(),
            "prefix": _clean_prefix(prefix),
        }
        return (json.dumps(config, ensure_ascii=False),)


class Seedance2S3UploadReferenceVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "s3_config_json": ("STRING", {"forceInput": True}),
            "prefix": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Optional per-upload prefix override. Leave blank to use S3 Config, env vars, file config, or video-refs."}),
            "local_video_file": (_list_input_videos(), {"default": NONE_CHOICE}),
            "local_video_path": ("STRING", {"multiline": False, "default": ""}),
            "expires_in": ("INT", {"default": DEFAULT_EXPIRES_IN, "min": 60, "max": 86400, "step": 60}),
        }, "optional": {
            "video": ("VIDEO", {"tooltip": "Optional video from ComfyUI Load Video. This uses the original file path when available."}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_url", "s3_reference_json")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0/S3"
    OUTPUT_NODE = True

    def run(self, s3_config_json, prefix, local_video_file, local_video_path,
            expires_in, video=None):
        settings = _s3_settings(s3_config_json, prefix)
        file_path = _resolve_video_path(local_video_file, local_video_path, video)
        key = _s3_key(settings["prefix"], file_path)
        s3 = _s3_client(settings)
        print(f"[Seedance2 S3 Upload] Uploading {file_path} -> s3://{settings['bucket']}/{key}")
        try:
            s3.upload_file(
                file_path,
                settings["bucket"],
                key,
                ExtraArgs={"ContentType": _content_type(file_path)},
            )
        except Exception as e:
            _friendly_s3_error("upload", e, settings["bucket"], key)
        url = _presign_get(s3, settings["bucket"], key, expires_in)
        s3_reference_json = _s3_reference_payload(settings, key)
        preview = _local_video_preview(file_path)
        return {"ui": _video_preview_ui(preview), "result": (url, s3_reference_json)}


class Seedance2S3BrowseReferenceVideos:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "s3_config_json": ("STRING", {"forceInput": True}),
            "prefix": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Optional prefix override for browsing. Leave blank to use S3 Config, env vars, file config, or video-refs."}),
            "selected_index": ("INT", {"default": 1, "min": 1, "max": 999, "step": 1}),
            "max_items": ("INT", {"default": 20, "min": 1, "max": 200, "step": 1}),
            "expires_in": ("INT", {"default": DEFAULT_EXPIRES_IN, "min": 60, "max": 86400, "step": 60}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "s3_reference_json", "items_json")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0/S3"
    OUTPUT_NODE = True

    def run(self, s3_config_json, prefix, selected_index, max_items, expires_in, preview_count=0):
        settings = _s3_settings(s3_config_json, prefix)
        s3 = _s3_client(settings)
        try:
            response = s3.list_objects_v2(Bucket=settings["bucket"], Prefix=settings["prefix"] + "/")
        except Exception as e:
            _friendly_s3_error("list", e, settings["bucket"], settings["prefix"])
        objects = [
            obj for obj in response.get("Contents", [])
            if obj.get("Key") and obj.get("Size", 0) > 0 and obj["Key"].lower().endswith(VIDEO_EXTS)
        ]
        objects.sort(key=lambda obj: obj["LastModified"], reverse=True)
        objects = objects[:int(max_items)]
        if not objects:
            return {"ui": {"text": ["No S3 reference videos found."]}, "result": ("", "", "[]")}

        selected_pos = max(1, min(int(selected_index), len(objects))) - 1
        selected = objects[selected_pos]
        selected_url = _presign_get(s3, settings["bucket"], selected["Key"], expires_in)
        selected_reference_json = _s3_reference_payload(settings, selected["Key"])

        items = []
        lines = []
        for index, obj in enumerate(objects, 1):
            key = obj["Key"]
            filename = key.rsplit("/", 1)[-1]
            last_modified = obj["LastModified"].astimezone().strftime("%Y-%m-%d %H:%M:%S")
            size = int(obj.get("Size", 0))
            items.append({
                "index": index,
                "filename": filename,
                "s3_key": key,
                "last_modified": last_modified,
                "size": size,
                "size_label": _format_size(size),
            })
            marker = "*" if index - 1 == selected_pos else " "
            lines.append(f"{marker}{index:02d} {filename}  {last_modified}  {_format_size(size)}")

        selected_filename = selected["Key"].rsplit("/", 1)[-1]
        selected_modified = selected["LastModified"].astimezone().strftime("%Y-%m-%d %H:%M:%S")
        selected_line = (
            f"Selected {selected_pos + 1:02d}: {selected_filename}  "
            f"{selected_modified}  {_format_size(int(selected.get('Size', 0)))}"
        )
        preview_name = _s3_preview_name(selected_pos + 1, selected)
        _download_preview(selected_url, "seedance2_s3_previews", preview_name)
        preview = {
            "filename": preview_name,
            "subfolder": "seedance2_s3_previews",
            "type": "output",
        }

        ui = {"text": [selected_line + "\n\n" + "\n".join(lines)]}
        ui.update(_video_preview_ui(preview))
        return {
            "ui": ui,
            "result": (
                selected_url,
                selected_reference_json,
                json.dumps(items, ensure_ascii=False, indent=2),
            ),
        }


class Seedance2S3DeleteReferenceVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "s3_config_json": ("STRING", {"forceInput": True}),
            "s3_key": ("STRING", {"multiline": False, "default": ""}),
            "delete_enabled": ("BOOLEAN", {"default": False}),
        }, "optional": {
            "s3_reference_json": ("STRING", {"multiline": True, "default": ""}),
            "trigger": ("STRING", {"multiline": False, "default": "",
                "tooltip": "Connect a generation request_id here so deletion runs after generation completes."}),
        }}

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("deleted_key", "status")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0/S3"
    OUTPUT_NODE = True

    def run(self, s3_config_json, s3_key, delete_enabled, s3_reference_json="", trigger=""):
        payload = {}
        if s3_reference_json and s3_reference_json.strip():
            try:
                payload = json.loads(s3_reference_json)
            except Exception as e:
                raise ValueError(f"Invalid s3_reference_json: {e}") from e
        settings = _s3_settings(s3_config_json, "")
        final_region = str(payload.get("region") or settings["region"] or DEFAULT_REGION)
        final_bucket = str(payload.get("bucket") or settings["bucket"]).strip()
        final_key = str(payload.get("key") or s3_key).strip()
        enabled = bool(delete_enabled or payload.get("delete_after_generation"))
        if not enabled:
            return (final_key, "skipped")
        if not final_bucket or not final_key:
            raise ValueError("bucket and s3_key are required for deletion.")
        delete_settings = dict(settings)
        delete_settings["region"] = final_region
        s3 = _s3_client(delete_settings)
        try:
            s3.delete_object(Bucket=final_bucket, Key=final_key)
        except Exception as e:
            _friendly_s3_error("delete", e, final_bucket, final_key)
        print(f"[Seedance2 S3 Delete] Deleted s3://{final_bucket}/{final_key}")
        return (final_key, "deleted")


NODE_CLASS_MAPPINGS = {
    "Seedance2S3Config": Seedance2S3Config,
    "Seedance2S3UploadReferenceVideo": Seedance2S3UploadReferenceVideo,
    "Seedance2S3BrowseReferenceVideos": Seedance2S3BrowseReferenceVideos,
    "Seedance2S3DeleteReferenceVideo": Seedance2S3DeleteReferenceVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance2S3Config": "🌱 Seedance 2.0 S3 Config",
    "Seedance2S3UploadReferenceVideo": "🌱 Seedance 2.0 S3 Upload Reference Video",
    "Seedance2S3BrowseReferenceVideos": "🌱 Seedance 2.0 S3 Browse Reference Videos",
    "Seedance2S3DeleteReferenceVideo": "🌱 Seedance 2.0 S3 Delete Reference Video",
}
