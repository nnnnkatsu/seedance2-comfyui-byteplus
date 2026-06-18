# Seedance 2.0 ComfyUI 节点 for BytePlus ModelArk

语言: [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

这是 [Anil-matcha/seedance2-comfyui](https://github.com/Anil-matcha/seedance2-comfyui) 的自定义 fork。这个版本把原来的 muapi.ai 调用改成直接调用 BytePlus ModelArk 官方 API，并增加了 AWS S3 辅助节点，用来处理私有本地参考视频。

本项目适合已经签约 BytePlus ModelArk，并拥有 API Key 与 `ep-...` endpoint ID 的用户。

## 这个版本改了什么

- 直接使用 BytePlus ModelArk API。
- 使用 `endpoint` 字段填写 BytePlus 的 `ep-...` endpoint ID。API 请求里它会被写入官方字段 `model`。
- 增加 `resolution`: `480p`、`720p`、`1080p`。
- 增加 `seed`。
- `watermark` 固定为 `false`，不显示在 UI 里。
- 增加 S3 上传、浏览、预览、删除辅助节点。
- 使用统一的 `video_ref` 连接参考视频，URL 和 S3 清理信息会一起传递。
- 增加 BytePlus 生成历史浏览节点。

## 节点列表

| 节点 | 说明 |
|------|------|
| `Seedance 2.0 BytePlus Config` | 推荐首先添加。集中填写 BytePlus `api_key` 和 `endpoint`。 |
| `Seedance 2.0 Text-to-Video` | 文生视频。 |
| `Seedance 2.0 Image-to-Video` | 使用最多 9 张图片作为参考生成视频。 |
| `Seedance 2.0 First/Last Frame-to-Video` | 使用起始帧和可选结束帧生成视频。不能和普通参考图、视频、音频混用。 |
| `Seedance 2.0 Omni Reference` | 使用文本、图片、视频、音频综合参考生成视频。 |
| `Seedance 2.0 Consistent Character Video` | 使用主参考图或 `sheet_url` 生成一致角色视频。 |
| `Seedance 2.0 Extend` | 继续扩展已完成的视频。 |
| `Seedance 2.0 Retrieve Task Result` | 通过 `cgt-...` task ID 取回近期任务。 |
| `Seedance 2.0 Generation History Browser` | 以列表方式浏览近期 BytePlus 生成任务，选择后输出 `video_url` 和 `video_ref`。 |
| `Seedance 2.0 Video Reference URL` | 把公开视频 URL、S3 签名 URL 或 `asset://` 转成 `video_ref`。 |
| `Seedance 2.0 Preview Video Reference` | 终端检查节点。只在节点内显示 URL 和 S3 key，没有输出端口。 |
| `Seedance 2.0 Preview Video URL` | 下载 `video_url` 并在 ComfyUI 显示视频预览。 |
| `Seedance 2.0 Save Video` | 下载视频并输出 IMAGE 帧。 |
| `Seedance 2.0 S3 Config` | 集中保存 S3 region、bucket、prefix、访问密钥。 |
| `Seedance 2.0 S3 Upload Reference Video` | 上传本地参考视频到 S3，并输出 `video_ref`。支持 `Load Video`。 |
| `Seedance 2.0 S3 Browse Reference Videos` | 列出 S3 参考视频，显示预览，输出选中的 `video_ref`，也可以直接删除选中对象。 |
| `Seedance 2.0 Consistent Character` | 已废弃。原节点是 muapi 专用功能。 |

## 安装

### ComfyUI Manager

1. 打开 ComfyUI Manager。
2. 选择 **Install via Git URL**。
3. 输入:

```text
https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
```

4. 重启 ComfyUI。

### 手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
pip install -r seedance2-comfyui-byteplus/requirements.txt
```

只有使用 S3 辅助节点时才需要 `boto3`。

## 基本使用

1. 添加 `Seedance 2.0 BytePlus Config`。
2. 在 `api_key` 填 BytePlus ModelArk API Key。
3. 在 `endpoint` 填 `ep-...` endpoint ID。
4. 添加生成节点，例如 `Text-to-Video`。
5. 连接 `api_key` 和 `endpoint`。
6. 输入提示词并运行。

## Omni 的视频参考

BytePlus 生成 API 不能直接读取你电脑上的私有视频文件。本地视频需要先上传到 S3，然后把生成的 `video_ref` 交给 Omni。

新上传参考视频:

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
Load Video video -> S3 Upload Reference Video video
S3 Upload Reference Video video_ref -> Omni Reference video_ref_1
Omni Reference delete_s3_references_after_generation = true
```

复用已经上传到 S3 的参考视频:

```text
S3 Config s3_config_json -> S3 Browse Reference Videos s3_config_json
S3 Browse Reference Videos video_ref -> Omni Reference video_ref_1
```

`video_ref` 里包含:

- BytePlus 实际读取的视频 URL。
- S3 bucket/key/region 等清理信息。
- 如有需要，Omni 生成成功后可以根据这些信息删除 S3 对象。

`Preview Video Reference` 只是检查节点，用来显示 `video_ref` 里的 URL 和 `s3_key`，不会下载视频，也没有输出端口。

## S3 设置

S3 API 需要 `region` 和 `bucket`，但只需要在 `S3 Config` 里填一次。

也可以用环境变量:

```bash
SEEDANCE2_S3_REGION=ap-northeast-1
SEEDANCE2_S3_BUCKET=your-private-reference-video-bucket
SEEDANCE2_S3_PREFIX=video-refs
SEEDANCE2_S3_ACCESS_KEY_ID=your_s3_access_key_id
SEEDANCE2_S3_SECRET_ACCESS_KEY=your_s3_secret_access_key
```

IAM 权限:

- 上传: `s3:PutObject`
- 浏览/预览: `s3:ListBucket`, `s3:GetObject`
- 删除: `s3:DeleteObject`

建议使用只允许访问参考视频 bucket/prefix 的受限 IAM 用户。

## 首尾帧生成

`Seedance 2.0 First/Last Frame-to-Video` 是独立节点，因为 BytePlus 把首尾帧生成视为独立模式。

它支持:

- 必填起始帧
- 可选结束帧
- 提示词
- 分辨率、时长、seed、是否生成音频

它不能和普通参考图、参考视频、参考音频混在同一个请求里。如果需要人物、背景、物体、视频或音频参考，请使用 `Image-to-Video` 或 `Omni Reference`。

## 生成历史

`Seedance 2.0 Generation History Browser` 可以浏览近期 BytePlus 任务。

```text
Generation History Browser video_ref -> Omni Reference video_ref_1
Generation History Browser video_url -> Save Video video_url
Generation History Browser video_url -> Preview Video URL video_url
```

先运行一次拉取列表，点击一行，再运行一次即可重新取得该任务结果并刷新预览。节点会优先尝试 BytePlus 的 task list API，失败时回退到本节点包本机记录过的 task ID。

BytePlus 的任务结果和输出 URL 通常只短期保留，大约 24 小时。需要长期保存请用 `Save Video`。

已过期任务会以红色显示。选择已过期任务时，节点不会输出 `video_url`、`video_ref` 或 `task_json`，预览区域会显示过期标记。

## 音频参考

`Omni Reference` 支持本地音频文件和音频 URL。

- `audio_file_1` 到 `audio_file_3`: 从 ComfyUI input 里选择 `mp3` 或 `wav`。
- `audio_url_1` 到 `audio_url_3`: 公开视频 URL、`asset://...`、已有 `data:audio/...` 或本地 `mp3` / `wav` 路径。
- BytePlus 限制: 单段 2-15 秒，最多 3 段，总时长不超过 15 秒，单文件不超过 15 MB。

## 安全注意

- 不要把 API Key 或 AWS Secret 提交到 Git。
- 本 README 不包含任何真实密钥。
- ComfyUI workflow 可能保存节点输入值，建议使用权限受限的 IAM 用户。
