"""Seedance 2.0 Video Saver — downloads a video URL, saves to disk, returns frames."""

import os
import json
import re
import numpy as np
import requests
import torch

try:
    from comfy.cli_args import args as comfy_args
except Exception:
    class comfy_args:
        disable_metadata = False

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


GENERATION_NODE_TYPES = {
    "Seedance2TextToVideo",
    "Seedance2ImageToVideo",
    "Seedance2FirstLastFrameToVideo",
    "Seedance2Extend",
    "Seedance2Omni",
    "Seedance2ConsistentVideo",
}
SECRET_FIELD_RE = re.compile(r"(api[_-]?key|secret|access[_-]?key|password|token)", re.IGNORECASE)
ARK_KEY_RE = re.compile(r"ark-[A-Za-z0-9-]+")
AWS_ACCESS_KEY_RE = re.compile(r"\b(?:AKIA|ASIA|AIDA|AGPA|AIPA|ANPA|AROA)[A-Z0-9]{16}\b")


def _is_secret_field(name):
    return bool(SECRET_FIELD_RE.search(str(name or "")))


def _redact_text(value):
    text = str(value)
    text = ARK_KEY_RE.sub("ark-***", text)
    text = AWS_ACCESS_KEY_RE.sub("***AWS_ACCESS_KEY***", text)
    return text


def _sanitize_value(value, key=""):
    if _is_secret_field(key):
        return ""
    if isinstance(value, dict):
        return {k: _sanitize_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v, key) for v in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.dumps(_sanitize_value(json.loads(stripped), key), ensure_ascii=False)
            except Exception:
                pass
        return _redact_text(value)
    return value


def _deepcopy_json(value):
    return json.loads(json.dumps(value))


def _prompt_node(prompt, node_id):
    if not isinstance(prompt, dict):
        return None
    return prompt.get(str(node_id)) or prompt.get(node_id)


def _node_type(node):
    if not isinstance(node, dict):
        return ""
    return str(node.get("class_type") or node.get("type") or "")


def _linked_node_id(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        source_id = value[0]
        if isinstance(source_id, (str, int)):
            return str(source_id)
    return None


def _walk_upstream_prompt(prompt, node_id, visited=None):
    if visited is None:
        visited = set()
    node_id = str(node_id)
    if node_id in visited:
        return set()
    node = _prompt_node(prompt, node_id)
    if not isinstance(node, dict):
        return set()

    visited.add(node_id)
    ids = {node_id}
    inputs = node.get("inputs") or {}
    if isinstance(inputs, dict):
        for value in inputs.values():
            source_id = _linked_node_id(value)
            if source_id is not None:
                ids.update(_walk_upstream_prompt(prompt, source_id, visited))
    return ids


def _generation_ids_in(ids, prompt):
    return {
        str(node_id)
        for node_id in ids
        if _node_type(_prompt_node(prompt, node_id)) in GENERATION_NODE_TYPES
    }


def _sanitize_prompt_subset(prompt, node_ids):
    subset = {}
    for node_id in sorted(node_ids, key=lambda x: str(x)):
        node = _prompt_node(prompt, node_id)
        if not isinstance(node, dict):
            continue
        copied = _deepcopy_json(node)
        inputs = copied.get("inputs")
        if isinstance(inputs, dict):
            for key, value in list(inputs.items()):
                inputs[key] = _sanitize_value(value, key)
        subset[str(node_id)] = copied
    return subset


SECRET_WIDGET_INDEXES = {
    "Seedance2ApiKey": {0},
    "Seedance2BytePlusConfig": {0},
    "Seedance2S3Config": {0, 1},
    "Seedance2TextToVideo": {6},
    "Seedance2ImageToVideo": {6},
    "Seedance2FirstLastFrameToVideo": {6},
    "Seedance2Extend": {5},
    "Seedance2Omni": {6},
    "Seedance2ConsistentVideo": {6},
}


def _sanitize_workflow_node(node):
    copied = _deepcopy_json(node)
    node_type = str(copied.get("type") or copied.get("class_type") or "")
    widgets = copied.get("widgets_values")
    if isinstance(widgets, list):
        for idx in SECRET_WIDGET_INDEXES.get(node_type, set()):
            if 0 <= idx < len(widgets):
                widgets[idx] = ""
        for i, value in enumerate(widgets):
            widgets[i] = _sanitize_value(value)
    elif isinstance(widgets, dict):
        for key, value in list(widgets.items()):
            widgets[key] = _sanitize_value(value, key)
    return copied


def _workflow_node_id(node):
    if not isinstance(node, dict):
        return None
    node_id = node.get("id")
    if node_id is None:
        return None
    return str(node_id)


def _workflow_link_endpoints(link):
    if isinstance(link, list) and len(link) >= 5:
        return str(link[1]), str(link[3])
    if isinstance(link, dict):
        origin = link.get("origin_id") or link.get("source_id") or link.get("from_node_id")
        target = link.get("target_id") or link.get("to_node_id")
        if origin is not None and target is not None:
            return str(origin), str(target)
    return None, None


def _workflow_link_id(link):
    if isinstance(link, list) and link:
        return link[0]
    if isinstance(link, dict):
        return link.get("id")
    return None


def _filter_node_links(node, kept_link_ids):
    for slot in node.get("inputs") or []:
        if isinstance(slot, dict) and slot.get("link") not in kept_link_ids:
            slot["link"] = None
    for slot in node.get("outputs") or []:
        if isinstance(slot, dict) and isinstance(slot.get("links"), list):
            slot["links"] = [link_id for link_id in slot["links"] if link_id in kept_link_ids]


def _prune_workflow(workflow, node_ids):
    if not isinstance(workflow, dict):
        return None
    node_ids = {str(x) for x in node_ids}
    pruned = _deepcopy_json(workflow)
    nodes = []
    for node in pruned.get("nodes") or []:
        node_id = _workflow_node_id(node)
        if node_id in node_ids:
            nodes.append(_sanitize_workflow_node(node))
    pruned["nodes"] = nodes

    kept_links = []
    kept_link_ids = set()
    raw_links = pruned.get("links") or []
    if isinstance(raw_links, list):
        for link in raw_links:
            origin, target = _workflow_link_endpoints(link)
            if origin in node_ids and target in node_ids:
                kept_links.append(link)
                kept_link_ids.add(_workflow_link_id(link))
        pruned["links"] = kept_links
    elif isinstance(raw_links, dict):
        for key, link in raw_links.items():
            origin, target = _workflow_link_endpoints(link)
            if origin in node_ids and target in node_ids:
                kept_links.append((key, link))
                kept_link_ids.add(_workflow_link_id(link) or key)
        pruned["links"] = {key: link for key, link in kept_links}

    kept_link_ids.discard(None)
    for node in pruned["nodes"]:
        _filter_node_links(node, kept_link_ids)
    return pruned


def _plain_input(inputs, key):
    value = inputs.get(key)
    return "" if _linked_node_id(value) is not None else value


def _seedance_summary(prompt, generation_ids):
    items = []
    for node_id in sorted(generation_ids, key=lambda x: str(x)):
        node = _prompt_node(prompt, node_id)
        inputs = node.get("inputs") or {}
        media_inputs = sorted(
            key for key, value in inputs.items()
            if _linked_node_id(value) is not None
            and (
                key.startswith("image_")
                or key.startswith("video_ref_")
                or key.startswith("audio_")
                or key in {"first_frame_image", "last_frame_image", "sheet_image", "scene_image_2", "scene_image_3"}
            )
        )
        items.append({
            "node_id": str(node_id),
            "node_type": _node_type(node),
            "prompt": _plain_input(inputs, "prompt"),
            "seed": _plain_input(inputs, "seed"),
            "resolution": _plain_input(inputs, "resolution"),
            "aspect_ratio": _plain_input(inputs, "aspect_ratio"),
            "duration": _plain_input(inputs, "duration"),
            "batch_count": _plain_input(inputs, "batch_count"),
            "media_inputs": media_inputs,
        })
    return {
        "type": "seedance2-comfyui-byteplus",
        "note": "Pruned metadata for the Seedance generation chain saved by Seedance 2.0 Save Video.",
        "generation_nodes": items,
    }


def _seedance_video_metadata(prompt, extra_pnginfo, unique_id):
    if not prompt or unique_id is None:
        return None
    save_node = _prompt_node(prompt, unique_id)
    if not isinstance(save_node, dict):
        return None
    video_source_id = _linked_node_id((save_node.get("inputs") or {}).get("video_url"))
    if video_source_id is None:
        return None

    upstream_ids = _walk_upstream_prompt(prompt, video_source_id)
    generation_ids = _generation_ids_in(upstream_ids, prompt)
    if not generation_ids:
        return None

    node_ids = set(upstream_ids)
    node_ids.add(str(unique_id))
    metadata = {
        "prompt": _sanitize_prompt_subset(prompt, node_ids),
        "seedance2_generation": _seedance_summary(prompt, generation_ids),
    }
    workflow = None
    if isinstance(extra_pnginfo, dict):
        workflow = _prune_workflow(extra_pnginfo.get("workflow"), node_ids)
    if workflow:
        metadata["workflow"] = workflow
    return metadata


def _comfy_metadata(prompt, extra_pnginfo, unique_id):
    if getattr(comfy_args, "disable_metadata", False):
        return None
    return _seedance_video_metadata(prompt, extra_pnginfo, unique_id)


def _json_metadata_value(value):
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _embed_video_metadata(path, metadata):
    if not metadata:
        return False

    tmp_path = f"{os.path.splitext(path)[0]}.metadata.tmp.mp4"
    try:
        import av
        from av.subtitles.stream import SubtitleStream

        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        with av.open(path, mode="r") as source:
            with av.open(tmp_path, mode="w", options={"movflags": "use_metadata_tags"}) as output:
                for key, value in source.metadata.items():
                    if key not in metadata:
                        output.metadata[key] = value
                for key, value in metadata.items():
                    output.metadata[key] = _json_metadata_value(value)

                stream_map = {}
                for stream in source.streams:
                    if isinstance(stream, (av.VideoStream, av.AudioStream, SubtitleStream)):
                        stream_map[stream] = output.add_stream_from_template(template=stream, opaque=True)

                for packet in source.demux():
                    if packet.stream in stream_map and packet.dts is not None:
                        packet.stream = stream_map[packet.stream]
                        output.mux(packet)

        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        print(f"[Seedance2 Saver] metadata embed skipped: {exc}")
        return False


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
            "frame_load_cap": ("INT", {"default": 1, "min": 0, "max": 9999,
                "tooltip": "When load_frames is enabled, 0 loads all frames; otherwise cap the number of frames."}),
            "skip_first_frames": ("INT", {"default": 0, "min": 0, "max": 500}),
            "select_every_nth": ("INT", {"default": 1, "min": 1, "max": 30}),
            "load_frames": ("BOOLEAN", {"default": False,
                "tooltip": "Load saved video frames into the IMAGE output. Off is safer for 1080p/4k videos."}),
        }, "hidden": {
            "prompt": "PROMPT",
            "extra_pnginfo": "EXTRA_PNGINFO",
            "unique_id": "UNIQUE_ID",
        }}
    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("frames", "filepath", "frame_count")
    FUNCTION = "run"
    CATEGORY = "🌱 Seedance 2.0"
    OUTPUT_NODE = True

    def run(self, video_url, save_subfolder, filename_prefix,
            frame_load_cap=1, skip_first_frames=0, select_every_nth=1, load_frames=False,
            prompt=None, extra_pnginfo=None, unique_id=None):
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
            metadata = _comfy_metadata(prompt, extra_pnginfo, unique_id)
            embedded = _embed_video_metadata(fp, metadata)
            if load_frames:
                frames, count = self._load(fp, frame_load_cap, skip_first_frames, select_every_nth)
            else:
                frames, count = __import__("torch").zeros(1, 64, 64, 3), 0
            fname = os.path.basename(fp)
            metadata_note = " with metadata" if embedded else ""
            print(f"[Seedance2 Saver] Saved {fname}{metadata_note} — {count} frames")
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
