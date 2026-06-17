"""Seedance 2.0 Video Saver — downloads a video URL, saves to disk, returns frames."""

import os
import json
import numpy as np
import requests
import torch

try:
    import folder_paths
except ImportError:
    class folder_paths:
        @staticmethod
        def get_output_directory():
            return os.path.join(os.path.expanduser("~"), "comfyui_output")


def _video_preview_ui(filename, subfolder, folder_type="output"):
    return {
        "images": [{
            "filename": filename,
            "subfolder": subfolder,
            "type": folder_type,
        }],
        "animated": (True,),
    }


VIDEO_REF_TYPE = "SEEDANCE2_VIDEO_REF"


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


def _video_ref_summary(data):
    url = str(data.get("url") or data.get("video_url") or "").strip()
    s3 = data.get("s3") or data.get("s3_reference") or {}
    lines = [
        "Seedance 2.0 video_ref",
        f"url: {url or '(empty)'}",
        f"url_type: {'asset' if url.startswith('asset://') else 'http' if url.startswith(('http://', 'https://')) else 'unknown'}",
    ]
    if isinstance(s3, dict) and s3:
        lines.extend([
            f"s3_uri: {s3.get('s3_uri') or '(none)'}",
            f"bucket: {s3.get('bucket') or '(none)'}",
            f"key: {s3.get('key') or '(none)'}",
            f"region: {s3.get('region') or '(none)'}",
            f"deletable: {'yes' if s3.get('bucket') and s3.get('key') else 'no'}",
        ])
    else:
        lines.append("deletable: no S3 metadata")
    return "\n".join(lines)


class Seedance2VideoSaver:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video_url": ("STRING", {"multiline": False, "default": ""}),
            "save_subfolder": ("STRING", {"default": "seedance2"}),
            "filename_prefix": ("STRING", {"default": "seedance2"}),
        }, "optional": {
            "frame_load_cap": ("INT", {"default": 0, "min": 0, "max": 9999}),
            "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": 500}),
            "select_every_nth": ("INT", {"default": 1, "min": 1, "max": 30}),
        }}
    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("frames", "filepath", "frame_count")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"
    OUTPUT_NODE = True

    def run(self, video_url, save_subfolder, filename_prefix,
            frame_load_cap=0, skip_first_frames=0, select_every_nth=1):
        if not video_url or not video_url.strip().startswith("http"):
            return self._err("Invalid URL")
        out_dir = os.path.join(folder_paths.get_output_directory(), save_subfolder)
        os.makedirs(out_dir, exist_ok=True)
        n = 1
        fp = os.path.join(out_dir, f"{filename_prefix}_{n:05d}.mp4")
        while os.path.exists(fp):
            n += 1
            fp = os.path.join(out_dir, f"{filename_prefix}_{n:05d}.mp4")
        try:
            print(f"[Seedance2 Saver] Downloading {video_url[:80]}...")
            r = requests.get(video_url, stream=True, timeout=300)
            r.raise_for_status()
            with open(fp, "wb") as fh:
                for chunk in r.iter_content(8192):
                    if chunk: fh.write(chunk)
            frames, count = self._load(fp, frame_load_cap, skip_first_frames, select_every_nth)
            fname = os.path.basename(fp)
            print(f"[Seedance2 Saver] Saved {fname} — {count} frames")
            return {"ui": _video_preview_ui(fname, save_subfolder), "result": (frames, fp, count)}
        except Exception as e:
            return self._err(str(e))

    def _load(self, path, cap, skip, nth):
        try:
            import cv2
            frames, raw, loaded = [], 0, 0
            vc = cv2.VideoCapture(path)
            while True:
                ret, frame = vc.read()
                if not ret: break
                if raw < skip: raw += 1; continue
                if (raw - skip) % nth == 0:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                    frames.append(rgb); loaded += 1
                    if cap > 0 and loaded >= cap: break
                raw += 1
            vc.release()
            if not frames: raise RuntimeError("No frames")
            return __import__("torch").from_numpy(__import__("numpy").stack(frames)), len(frames)
        except Exception as e:
            print(f"[Seedance2 Saver] frame load error: {e}")
            return __import__("torch").zeros(1, 64, 64, 3), 1

    def _err(self, msg):
        print(f"[Seedance2 Saver] ERROR: {msg}")
        return {"ui": {"text": [msg]}, "result": (__import__("torch").zeros(1, 64, 64, 3), "ERROR", 0)}


class Seedance2VideoPreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video_url": ("STRING", {"multiline": False, "default": ""}),
            "save_subfolder": ("STRING", {"default": "seedance2_preview"}),
            "filename_prefix": ("STRING", {"default": "seedance2_preview"}),
        }}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"
    OUTPUT_NODE = True

    def run(self, video_url, save_subfolder, filename_prefix):
        if not video_url or not video_url.strip().startswith("http"):
            return self._err("Invalid URL")
        out_dir = os.path.join(folder_paths.get_output_directory(), save_subfolder)
        os.makedirs(out_dir, exist_ok=True)
        n = 1
        fp = os.path.join(out_dir, f"{filename_prefix}_{n:05d}.mp4")
        while os.path.exists(fp):
            n += 1
            fp = os.path.join(out_dir, f"{filename_prefix}_{n:05d}.mp4")
        try:
            print(f"[Seedance2 Preview] Downloading {video_url[:80]}...")
            r = requests.get(video_url, stream=True, timeout=300)
            r.raise_for_status()
            with open(fp, "wb") as fh:
                for chunk in r.iter_content(8192):
                    if chunk:
                        fh.write(chunk)
            fname = os.path.basename(fp)
            print(f"[Seedance2 Preview] Saved {fname}")
            return {"ui": _video_preview_ui(fname, save_subfolder), "result": (fp,)}
        except Exception as e:
            return self._err(str(e))

    def _err(self, msg):
        print(f"[Seedance2 Preview] ERROR: {msg}")
        return {"ui": {"text": [msg]}, "result": ("ERROR",)}


class Seedance2VideoReferencePreview:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "video_ref": (VIDEO_REF_TYPE,),
            "video_url": ("STRING", {"multiline": True, "default": ""}),
            "s3_key": ("STRING", {"multiline": False, "default": ""}),
        }}
    RETURN_TYPES = ()
    RETURN_NAMES = ()
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"
    OUTPUT_NODE = True

    def run(self, video_ref, video_url="", s3_key=""):
        data = _video_ref_data(video_ref)
        url = str(data.get("url") or data.get("video_url") or "").strip()
        s3 = data.get("s3") or data.get("s3_reference") or {}
        key = str(s3.get("key") or "") if isinstance(s3, dict) else ""
        return {
            "ui": {
                "video_url": [url],
                "s3_key": [key],
            },
            "result": (),
        }


NODE_CLASS_MAPPINGS = {
    "Seedance2VideoSaver": Seedance2VideoSaver,
    "Seedance2VideoPreview": Seedance2VideoPreview,
    "Seedance2VideoReferencePreview": Seedance2VideoReferencePreview,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "Seedance2VideoSaver": "🌱 Seedance 2.0 Save Video",
    "Seedance2VideoPreview": "🌱 Seedance 2.0 Preview Video URL",
    "Seedance2VideoReferencePreview": "🌱 Seedance 2.0 Preview Video Reference",
}
