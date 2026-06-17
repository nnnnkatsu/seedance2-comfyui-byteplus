## 🚀 Enhanced Fork - BytePlus + AWS S3 Support

> **This is an optimized fork** with direct BytePlus API integration and AWS S3 reference video support.
> > If you need BytePlus support instead of muapi.ai, this is the version for you!
> >
> > > >> > ># Seedance 2.0 ComfyUI Nodes for BytePlus ModelArk

Languages: [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

This is a custom fork of [Anil-matcha/seedance2-comfyui](https://github.com/Anil-matcha/seedance2-comfyui). It replaces the original muapi.ai integration with direct BytePlus ModelArk API calls and adds AWS S3 helper nodes for private reference-video workflows.

The node pack is designed for users who have a BytePlus ModelArk API key and an endpoint ID such as `ep-...`.

## What This Fork Changes

- Calls BytePlus ModelArk directly with `Authorization: Bearer <ARK_API_KEY>`.
- Creates Seedance video tasks with `POST /api/v3/contents/generations/tasks`.
- Polls task status with `GET /api/v3/contents/generations/tasks/{id}`.
- Uses an `endpoint` UI field for your BytePlus `ep-...` endpoint ID. Internally this is sent to the official API field named `model`.
- Adds output `resolution` controls: `480p`, `720p`, `1080p`.
- Adds `seed` controls to generation nodes.
- Keeps `watermark` fixed to `false`.
- Adds AWS S3 upload, browse, preview, and cleanup helper nodes for private local reference videos.
- Uses a structured `video_ref` connection for reference videos so S3 cleanup metadata travels with the URL.
- Adds a BytePlus generation history browser.

## Nodes

| Node | Description |
|------|-------------|
| `Seedance 2.0 BytePlus Config` | Recommended first node. Set BytePlus `api_key` and `endpoint`, then wire both outputs to generation nodes. |
| `Seedance 2.0 API Key` | Legacy key-only node. Useful when endpoint is supplied elsewhere. |
| `Seedance 2.0 Text-to-Video` | Generate video from text. |
| `Seedance 2.0 Image-to-Video` | Generate video from up to 9 ComfyUI image references. |
| `Seedance 2.0 First/Last Frame-to-Video` | Generate from a first frame and optional last frame. This mode cannot be mixed with normal reference images, reference videos, or reference audio. |
| `Seedance 2.0 Omni Reference` | Generate using text plus image, video, and audio references. |
| `Seedance 2.0 Consistent Character Video` | Generate using a main reference image or `sheet_url`. |
| `Seedance 2.0 Extend` | Continue from a completed task ID, public video URL, or `asset://...` reference. |
| `Seedance 2.0 Retrieve Task Result` | Retrieve a recent task by `cgt-...` ID. |
| `Seedance 2.0 Generation History Browser` | Browse recent BytePlus tasks in a list, select one, preview it, and output `video_url` plus `video_ref`. |
| `Seedance 2.0 Video Reference URL` | Convert a public/S3/`asset://` video URL into `video_ref`. |
| `Seedance 2.0 Preview Video Reference` | Terminal inspector. Displays a `video_ref` URL and S3 key in the node; it has no output ports. |
| `Seedance 2.0 Preview Video URL` | Download a video URL to ComfyUI output and show an mp4 player preview. |
| `Seedance 2.0 Save Video` | Download a video URL and return frames as a ComfyUI IMAGE batch. |
| `Seedance 2.0 S3 Config` | Store AWS S3 access settings once. |
| `Seedance 2.0 S3 Upload Reference Video` | Upload a local reference video to S3 and output `video_ref`. Supports ComfyUI `Load Video`. |
| `Seedance 2.0 S3 Browse Reference Videos` | List S3 reference videos, show previews, output selected `video_ref`, and optionally delete selected S3 objects. |
| `Seedance 2.0 Consistent Character` | Deprecated muapi-only helper. Kept only to show a clear error in old workflows. |

## Installation

### ComfyUI Manager

1. Open ComfyUI Manager.
2. Use **Install via Git URL**.
3. Paste:

```text
https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
```

4. Restart ComfyUI.

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
pip install -r seedance2-comfyui-byteplus/requirements.txt
```

`boto3` is only required for the S3 helper nodes.

## Quick Start

1. Add `Seedance 2.0 BytePlus Config`.
2. Paste your BytePlus ModelArk API key into `api_key`.
3. Paste your BytePlus endpoint ID into `endpoint`.
4. Add a generation node, for example `Seedance 2.0 Text-to-Video`.
5. Connect `api_key` and `endpoint`.
6. Write a prompt and queue the workflow.

## Configuration

You can leave node fields blank and configure values through environment variables:

```bash
ARK_API_KEY=your_byteplus_api_key
SEEDANCE2_ENDPOINT=your_endpoint_id
BYTEPLUS_ARK_BASE_URL=https://ark.ap-southeast.bytepluses.com/api/v3
```

Local config file is also supported:

```json
{
  "api_key": "your_byteplus_api_key",
  "endpoint": "your_endpoint_id",
  "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3"
}
```

Save it as `~/.byteplus/seedance2-comfyui.json`.

## Omni Reference Video Workflow

BytePlus does not accept private local video files directly in generation requests. For local reference videos, upload them to S3 first and pass the resulting `video_ref`.

New local reference video:

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
Load Video video -> S3 Upload Reference Video video
S3 Upload Reference Video video_ref -> Omni Reference video_ref_1
Omni Reference delete_s3_references_after_generation = true
```

Reuse a reference video already in S3:

```text
S3 Config s3_config_json -> S3 Browse Reference Videos s3_config_json
S3 Browse Reference Videos video_ref -> Omni Reference video_ref_1
```

`video_ref` contains:

- The short-lived pre-signed URL used by BytePlus.
- Optional S3 metadata such as bucket/key/region.
- Optional S3 credentials copied from S3 Config, used only when `Omni Reference` deletes the uploaded reference after a successful generation.

Use `Preview Video Reference` to inspect a `video_ref`. It displays only the URL and `s3_key`; it does not download or preview the video.

## S3 Settings

Recommended workflow:

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
S3 Config s3_config_json -> S3 Browse Reference Videos s3_config_json
```

`region` and `bucket` are required by AWS S3, but you only need to enter them once in `S3 Config`.

You can also use environment variables:

```bash
SEEDANCE2_S3_REGION=ap-northeast-1
SEEDANCE2_S3_BUCKET=your-private-reference-video-bucket
SEEDANCE2_S3_PREFIX=video-refs
SEEDANCE2_S3_ACCESS_KEY_ID=your_s3_access_key_id
SEEDANCE2_S3_SECRET_ACCESS_KEY=your_s3_secret_access_key
```

IAM permissions:

- Upload: `s3:PutObject`
- Browse/preview: `s3:ListBucket`, `s3:GetObject`
- Delete: `s3:DeleteObject`

Use a limited IAM user scoped to the reference-video bucket/prefix. Pre-signed URLs are time-limited, but anyone who has the full URL can access the file until it expires.

## First/Last Frame Mode

`Seedance 2.0 First/Last Frame-to-Video` is separate because BytePlus treats first/last-frame generation as a separate mode.

It supports:

- Required first frame image
- Optional last frame image
- Prompt
- Resolution, duration, seed, audio generation

It cannot be mixed with normal reference images, reference videos, reference audio, or draft tasks in the same request. Use `Image-to-Video` or `Omni Reference` when you need additional references.

## Generation History

`Seedance 2.0 Generation History Browser` lists recent BytePlus tasks.

Workflow:

```text
Generation History Browser video_ref -> Omni Reference video_ref_1
Generation History Browser video_url -> Save Video video_url
Generation History Browser video_url -> Preview Video URL video_url
```

Run it once to load recent tasks, click a row, then run it again to retrieve that task and refresh the preview. The node tries BytePlus task listing first and falls back to local task IDs recorded by this node pack.

BytePlus task data and output URLs are short-lived, usually around 24 hours. Use `Save Video` for anything you need to keep.

## Audio References

`Omni Reference` supports local audio files and audio URLs.

- `audio_file_1` to `audio_file_3`: choose local `mp3` or `wav` files from ComfyUI input.
- `audio_url_1` to `audio_url_3`: public URL, `asset://...`, existing `data:audio/...`, or local `mp3`/`wav` path.
- BytePlus limits: 2-15 seconds per audio clip, max 3 clips, total duration <= 15 seconds, each file <= 15 MB.

## Security

- Do not commit API keys or AWS secrets.
- This README intentionally contains no real credentials.
- Saved ComfyUI workflows may include widget values, so prefer limited IAM credentials and rotate keys when needed.

## API Reference

| Action | Endpoint |
|--------|----------|
| Create task | `POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks` |
| Retrieve task | `GET https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks/{id}` |
| List tasks | `GET https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks` |
