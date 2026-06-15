# Seedance 2.0 ComfyUI Nodes for BytePlus ModelArk

Languages: [English](README.md) | [中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

> **⚠️ BytePlus Direct API Version** — This is a custom fork with direct BytePlus API integration. If you're using the original muapi.ai service, please use [Anil-matcha/seedance2-comfyui](https://github.com/nnnnkatsu/seedance2-comfyui-byteplus) instead.

> **ComfyUI custom nodes for Seedance 2.0** — the state-of-the-art video generation model by ByteDance.
> Generate stunning AI videos directly inside ComfyUI using the [muapi.ai](https://muapi.ai) API.
> If you wish to check the api documentation check this [Seedance 2.0 api](https://github.com/Anil-matcha/Seedance-2.0-API)

This fork changes the original muapi.ai-based node pack to call BytePlus directly:

- Uses `Authorization: Bearer <ARK_API_KEY>`.
- Creates video tasks with `POST /api/v3/contents/generations/tasks`.
- Polls task status with `GET /api/v3/contents/generations/tasks/{id}`.
- Uses a visible `endpoint` field in ComfyUI for your BytePlus `ep-...` endpoint ID.

The original project is [Anil-matcha/seedance2-comfyui](https://github.com/Anil-matcha/seedance2-comfyui).

---

## Nodes

| Node | Description |
|------|-------------|
| `Seedance 2.0 BytePlus Config` | Recommended first node. Set BytePlus `api_key` and `endpoint`, then wire both outputs to generation nodes. |
| `Seedance 2.0 API Key` | Legacy-compatible key-only node. Useful only if endpoint is supplied in each generation node or by environment/config. |
| `Seedance 2.0 Text-to-Video` | Generate video from a text prompt. |
| `Seedance 2.0 Image-to-Video` | Generate video from up to 9 ComfyUI image references. |
| `Seedance 2.0 Omni Reference` | Generate video using text plus image, video, and audio references. |
| `Seedance 2.0 Consistent Character Video` | Generate a reference-image-guided video using `sheet_image` or `sheet_url`. |
| `Seedance 2.0 Extend` | Continue from a completed BytePlus task ID, public video URL, or `asset://...` video reference. |
| `Seedance 2.0 Retrieve Task Result` | Retrieve a recent BytePlus task by `cgt-...` ID and output its `video_url`, first frame, status, and JSON. |
| `Seedance 2.0 Preview Video URL` | Download a generated video URL to ComfyUI output and show an mp4 player preview. |
| `Seedance 2.0 Save Video` | Download a generated video URL to disk and return ComfyUI IMAGE frames. |
| `Seedance 2.0 S3 Config` | Store AWS S3 access settings once and wire them to S3 helper nodes. |
| `Seedance 2.0 S3 Upload Reference Video` | Upload a local reference video, including ComfyUI `Load Video` output, to S3 and output a short-lived pre-signed URL. |
| `Seedance 2.0 S3 Browse Reference Videos` | List S3 reference videos, show mp4 previews, and output the selected pre-signed URL. |
| `Seedance 2.0 S3 Delete Reference Video` | Advanced/manual cleanup node for deleting a known S3 reference object. Normal workflows can delete from `Omni Reference`. |
| `Seedance 2.0 Consistent Character` | Deprecated for this BytePlus direct fork. The original node was a muapi-only character-sheet helper. |

---

## Installation

### Via ComfyUI Manager (recommended)
1. Open **ComfyUI Manager** → **Install via Git URL**
2. Paste: `https://github.com/nnnnkatsu/seedance2-comfyui-byteplus`
3. Restart ComfyUI

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
pip install -r seedance2-comfyui-byteplus/requirements.txt
```

---

## Quick Start

1. Add `Seedance 2.0 BytePlus Config`.
2. Paste your BytePlus ModelArk API key into `api_key`.
3. Paste your BytePlus endpoint ID into `endpoint`.
   - Endpoint IDs usually look like `ep-...`.
4. Add a generation node, for example `Seedance 2.0 Text-to-Video`.
5. Wire `api_key` and `endpoint` from the config node into the generation node.
6. Write a prompt and queue the workflow.

The ComfyUI UI says `endpoint` because direct BytePlus users normally receive an `ep-...` endpoint ID. Internally, the BytePlus API request field is still named `model`; the node maps `endpoint` to that official API field.

---

## Configuration

### Config Node

Use this for most workflows:

```text
[Seedance 2.0 BytePlus Config]
  api_key  -> generation node api_key
  endpoint -> generation node endpoint
```

### Environment Variables

You can leave node fields blank and configure values with environment variables:

```bash
ARK_API_KEY=your_byteplus_api_key
SEEDANCE2_ENDPOINT=your_endpoint_id
BYTEPLUS_ARK_BASE_URL=https://ark.ap-southeast.bytepluses.com/api/v3
```

Backward-compatible endpoint variables are also accepted:

```bash
SEEDANCE2_MODEL=your_endpoint_id
BYTEPLUS_SEEDANCE_MODEL=your_endpoint_id
ARK_MODEL=your_endpoint_id
```

### Config File

You can also create `~/.byteplus/seedance2-comfyui.json`:

```json
{
  "api_key": "your_byteplus_api_key",
  "endpoint": "your_endpoint_id",
  "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3"
}
```

For compatibility, `endpoint_id` and `model` are also accepted as endpoint keys in this config file.

---

## Node Reference

### Seedance 2.0 BytePlus Config

| Field | Description |
|-------|-------------|
| `api_key` | BytePlus ModelArk API key. |
| `endpoint` | BytePlus ModelArk endpoint ID, usually `ep-...`. |

Outputs: `api_key`, `endpoint`

---

### Seedance 2.0 Text-to-Video

Generate a video from a text prompt.

| Field | Values | Default |
|-------|--------|---------|
| `prompt` | Text prompt | Example cinematic prompt |
| `aspect_ratio` | `16:9`, `9:16`, `4:3`, `3:4` | `16:9` |
| `resolution` | `480p`, `720p`, `1080p` | `480p` |
| `duration` | `5`, `10`, `15` seconds | `5` |
| `api_key` | Optional if supplied by config/env/file | empty |
| `endpoint` | Optional if supplied by config/env/file | empty |
| `generate_audio` | Whether BytePlus should generate audio | `true` |

Outputs: `video_url`, `first_frame`, `request_id`

`resolution` is sent directly to the BytePlus API. The old `quality` widget from earlier versions was only a local compatibility mapping: `basic` meant `480p`, and `high` meant `720p`. BytePlus documents `1080p` for Seedance 2.0, but not for Seedance 2.0 Fast endpoints.

---

### Seedance 2.0 Image-to-Video

Generate a video from a prompt and up to 9 ComfyUI images.

Reference connected images in your prompt with `@image1`, `@image2`, and so on. The node converts this legacy syntax to BytePlus-style references internally.

```text
The character in @image1 walks through a sunlit garden.
```

Image tensors are sent as base64 data URLs.

---

### Seedance 2.0 Omni Reference

Generate video using text plus optional image, video, and audio references.

Supported prompt references:

```text
@image1 ... @image9
@video1 ... @video3
@audio1 ... @audio3
```

Reference handling:

- ComfyUI image tensors are sent as base64 image data URLs.
- Local audio files are sent as base64 `data:audio/...` URLs.
- `audio_file_1` ... `audio_file_3` accept local `mp3`/`wav` files from ComfyUI input.
- `audio_url_1` ... `audio_url_3` accept public `https://...` URLs, `asset://...` IDs, existing `data:audio/...` URLs, or absolute local `mp3`/`wav` paths.
- BytePlus audio reference limits: 2-15 seconds per clip, up to 3 clips, total audio duration <= 15 seconds, each audio file <= 15 MB. Avoid Base64 for large files.
- Reference videos must be public `https://...` URLs, S3 pre-signed URLs, or `asset://...` IDs.
- Local video files are not sent directly to BytePlus. Use the S3 helper nodes to upload local videos and pass a pre-signed URL.

---

### S3 Reference Video Workflow

Use this when your reference video cannot be published as a normal public URL.

New local reference video:

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
Load Video video -> S3 Upload Reference Video video
S3 Upload Reference Video video_url -> Omni Reference video_url_1
S3 Upload Reference Video s3_reference_json -> Omni Reference s3_reference_json_1
S3 Config s3_config_json -> Omni Reference s3_config_json
Omni Reference delete_s3_references_after_generation = true
```

The upload node stores the video in S3 and returns a pre-signed `video_url`, usually valid for 5 minutes. You can feed it a ComfyUI `Load Video` output through the optional `video` input; when the source is a loaded file, the node uploads the original video file instead of decoded frames. The `local_video_file` and `local_video_path` widgets remain as fallbacks.

`S3 Upload Reference Video` has two outputs:

- `video_url`: connect this to `Omni Reference video_url_1`, `video_url_2`, or `video_url_3`.
- `s3_reference_json`: optional metadata for `Omni Reference` cleanup. Connect it only when you want Omni to delete the uploaded object after generation.

If `delete_s3_references_after_generation` is enabled on `Omni Reference`, Omni deletes the connected S3 reference objects after the BytePlus generation succeeds. If generation fails before completion, deletion is not attempted, so your S3 lifecycle rule is still the fallback cleanup.

`S3 Delete Reference Video` remains available for manual cleanup, but it is no longer needed in the normal Upload -> Omni workflow.

Reuse a reference video already in S3:

```text
S3 Browse Reference Videos video_url -> Omni Reference video_url_1
```

`S3 Browse Reference Videos` lists recent objects under the configured prefix. It previews only the current `selected_index` item and outputs a newly signed URL for that same item. To choose another reference, change `selected_index` and run the node again.

S3 location settings:

- S3 itself requires both `region` and `bucket`, but the upload/browse/delete nodes do not need those fields repeated.
- Recommended: connect `S3 Config` once. It outputs one `s3_config_json`, which carries AWS access key, secret key, `region`, `bucket`, and `prefix` to the S3 helper nodes.
- The `prefix` widget on upload/browse nodes is only an override. Leave it blank to use the prefix from `S3 Config`, environment variables, local JSON config, or the built-in `video-refs` default.
- For shared workstations where users should not edit bucket settings, create `~/.byteplus/seedance2-s3.json` on the ComfyUI machine:

```json
{
  "aws_access_key_id": "your_s3_access_key_id",
  "aws_secret_access_key": "your_s3_secret_access_key",
  "region": "ap-northeast-1",
  "bucket": "your-private-reference-video-bucket",
  "prefix": "video-refs"
}
```

- Environment variables are also supported: `SEEDANCE2_S3_REGION`, `SEEDANCE2_S3_BUCKET`, and `SEEDANCE2_S3_PREFIX`.
- AWS credential environment variables are also supported: `SEEDANCE2_S3_ACCESS_KEY_ID`, `SEEDANCE2_S3_SECRET_ACCESS_KEY`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY`.

IAM permissions:

- Upload needs `s3:PutObject` on the target bucket/prefix.
- Browse and preview need `s3:ListBucket` and `s3:GetObject`.
- Delete needs `s3:DeleteObject`.
- If you get `AccessDenied` during upload, check whether the IAM policy only allows a narrower prefix. The node uploads under the configured `prefix`; that prefix must match the allowed S3 resource path.

Security notes:

- Pre-signed URLs are time-limited but can be used by anyone who has the full URL until they expire.
- AWS keys entered into ComfyUI node widgets can be stored in saved workflows. Use a limited IAM user scoped to the reference-video bucket/prefix.
- `expires_in=300` is the default. Increase it if BytePlus queueing causes the URL to expire before the generation service fetches the reference video.

---

### Seedance 2.0 Consistent Character Video

This node now works as a reference-image-guided video node.

Use one of:

- `sheet_image`: a ComfyUI IMAGE tensor, such as a loaded character/reference image.
- `sheet_url`: a public image URL or BytePlus `asset://...` image reference.

If the prompt does not contain `@image1` or `[Image 1]`, the node prepends `@image1` automatically so the reference image anchors the generation.

---

### Seedance 2.0 Extend

Continue from a source video.

`request_id` accepts:

- A completed BytePlus task ID from this node pack.
- A public `https://...` video URL.
- A BytePlus `asset://...` video reference.

The node retrieves the source task if needed, then submits a new task using the source video as `reference_video`.

---

### Seedance 2.0 Retrieve Task Result

Retrieve a historical BytePlus video generation task by `task_id`.

Use this when you want to reuse a generated video as new reference material:

```text
Retrieve Task Result video_url -> Omni Reference video_url_1
Retrieve Task Result video_url -> Save Video video_url
Retrieve Task Result video_url -> Preview Video URL video_url
Retrieve Task Result first_frame -> Preview Image
```

Inputs:

- `task_id`: a `cgt-...` request ID returned by a generation node.
- `recent_task`: optional local dropdown of recent task IDs created by this node pack on this machine.
- `wait_for_completion`: poll until the task finishes instead of reading the current status once.
- `download_first_frame`: decode the first frame for ComfyUI preview.

Outputs: `video_url`, `first_frame`, `request_id`, `status`, `task_json`

BytePlus only retains generated task data and output video URLs for about 24 hours, so save videos locally if you need to keep them.

---

### Seedance 2.0 Preview Video URL

Download a `video_url` to ComfyUI's output folder and display it with ComfyUI's mp4 preview UI.

This is lighter than `Seedance 2.0 Save Video` because it does not decode all frames into an IMAGE batch. Use it when you only want playback preview.

Outputs: `filepath`

---

### Seedance 2.0 Consistent Character

This node is kept only so old workflows fail with a clear message.

The original `Seedance2Character` node depended on muapi.ai-specific character-sheet behavior. BytePlus ModelArk's direct Seedance video generation API does not expose the same character-sheet generation endpoint through this node pack.

This deprecated node intentionally has no `endpoint` field because there is no BytePlus direct endpoint for that character-sheet operation.

Use `Seedance 2.0 Consistent Character Video` with an existing reference image, public sheet URL, or BytePlus `asset://...` digital character/image reference instead.

---

## Example Workflows

Load these JSON files from ComfyUI with **File -> Load**:

| File | Description |
|------|-------------|
| `Seedance2_T2V_Example.json` | BytePlus Config -> Text-to-Video -> Save Video |
| `Seedance2_ConsistentCharacter_Example.json` | Load Image -> Consistent Character Video -> Save Video |

Both examples use `Seedance 2.0 BytePlus Config` and require your own `api_key` and `endpoint`.

---

## API Details

This fork uses BytePlus ModelArk directly:

| Action | Endpoint |
|--------|----------|
| Create task | `POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks` |
| Poll task | `GET https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks/{id}` |
| Retrieve task | `GET https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks/{id}` |

Authentication:

```text
Authorization: Bearer <ARK_API_KEY>
```

Important naming note:

- ComfyUI field: `endpoint`
- BytePlus request body field: `model`
- Value to paste: your BytePlus `ep-...` endpoint ID

---

## Limitations

- `Seedance2Character` is not implemented for direct BytePlus API usage.
- Local video reference upload is supported through the S3 helper nodes. The generation API still receives a URL, not local file bytes.
- BytePlus task data and signed output URLs expire; save generated videos locally if you need to keep them.
- The old muapi CLI config `~/.muapi/config.json` is not used by this fork.

---

## Requirements

- Python >= 3.8
- `requests` >= 2.28
- `Pillow` >= 9.0
- `numpy` >= 1.23
- `torch` >= 2.0
- `opencv-python` >= 4.7
- `boto3` >= 1.34, only required for S3 helper nodes

---

## License

MIT © 2026
