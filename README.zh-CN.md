# Seedance 2.0 ComfyUI 节点 for BytePlus ModelArk

语言: [English](README.md) | [中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

这是一个给 ComfyUI 使用的 Seedance 2.0 节点包。这个 fork 已经从原版的 muapi.ai 调用方式改成了直接调用 BytePlus ModelArk API。

原项目: [Anil-matcha/seedance2-comfyui](https://github.com/Anil-matcha/seedance2-comfyui)

---

## 需要准备什么

- BytePlus ModelArk API Key，通常是 `ark-...`
- BytePlus endpoint ID，通常是 `ep-...`
- 如果要用私有本地视频作为参考素材，还需要 AWS S3 bucket 和访问密钥

注意：ComfyUI 里显示的是 `endpoint`，但 BytePlus 官方 API 的请求字段名仍然叫 `model`。节点内部会自动把 `endpoint` 填到官方的 `model` 字段里。

---

## 安装

### ComfyUI Manager 安装

1. 打开 **ComfyUI Manager** -> **Install via Git URL**
2. 输入:

```text
https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
```

3. 重启 ComfyUI

### 手动安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
pip install -r seedance2-comfyui-byteplus/requirements.txt
```

如果只使用普通生成节点，通常已有依赖就够了。使用 S3 辅助节点时需要 `boto3`。

---

## 基本使用

1. 添加 `Seedance 2.0 BytePlus Config`
2. 在 `api_key` 填入 BytePlus API Key
3. 在 `endpoint` 填入 BytePlus endpoint ID，也就是 `ep-...`
4. 添加生成节点，例如 `Seedance 2.0 Text-to-Video`
5. 把 Config 节点的 `api_key` 和 `endpoint` 连接到生成节点
6. 写 prompt 后运行工作流

---

## 节点列表

| 节点 | 用途 |
|------|------|
| `Seedance 2.0 BytePlus Config` | 推荐第一个添加。集中填写 `api_key` 和 `endpoint`。 |
| `Seedance 2.0 API Key` | 旧版兼容用。通常推荐使用 BytePlus Config。 |
| `Seedance 2.0 Text-to-Video` | 文本生成视频。 |
| `Seedance 2.0 Image-to-Video` | 使用最多 9 张 ComfyUI 图片作为参考生成视频。 |
| `Seedance 2.0 Omni Reference` | 使用文字、图片、视频、音频作为综合参考生成视频。 |
| `Seedance 2.0 Consistent Character Video` | 使用角色图或参考图生成一致角色视频。 |
| `Seedance 2.0 Extend` | 继续扩展已经生成过的视频。 |
| `Seedance 2.0 Retrieve Task Result` | 通过历史 `cgt-...` task ID 取回约 24 小时内的生成结果。 |
| `Seedance 2.0 Preview Video URL` | 从 `video_url` 下载并在 ComfyUI 里直接预览播放。 |
| `Seedance 2.0 Save Video` | 下载 `video_url` 并保存到本地，同时输出 IMAGE 帧。 |
| `Seedance 2.0 S3 Config` | 集中设置 S3 的 key、region、bucket、prefix。 |
| `Seedance 2.0 S3 Upload Reference Video` | 把本地参考视频上传到 S3，并输出短时间有效的签名 URL。 |
| `Seedance 2.0 S3 Browse Reference Videos` | 列出 S3 中已有参考视频，显示预览，输出选中的签名 URL，并可直接删除选中的 S3 对象。 |
| `Seedance 2.0 Consistent Character` | 废弃节点，只保留给旧工作流显示明确错误。 |

---

## 配置方式

### 推荐：Config 节点

```text
[Seedance 2.0 BytePlus Config]
  api_key  -> 生成节点 api_key
  endpoint -> 生成节点 endpoint
```

### 环境变量

也可以把节点字段留空，通过环境变量提供配置：

```bash
ARK_API_KEY=your_byteplus_api_key
SEEDANCE2_ENDPOINT=your_endpoint_id
BYTEPLUS_ARK_BASE_URL=https://ark.ap-southeast.bytepluses.com/api/v3
```

兼容旧命名：

```bash
SEEDANCE2_MODEL=your_endpoint_id
BYTEPLUS_SEEDANCE_MODEL=your_endpoint_id
ARK_MODEL=your_endpoint_id
```

### 本地配置文件

也可以创建 `~/.byteplus/seedance2-comfyui.json`：

```json
{
  "api_key": "your_byteplus_api_key",
  "endpoint": "your_endpoint_id",
  "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3"
}
```

兼容字段：`endpoint_id` 和 `model` 也可以作为 endpoint 使用。

---

## 分辨率

生成节点里使用 `resolution`，可选：

- `480p`
- `720p`
- `1080p`

旧版的 `quality` 不再作为主要设置使用。BytePlus 官方 API 使用的是分辨率。注意 Seedance 2.0 Fast endpoint 可能不支持 `1080p`。

---

## Omni Reference 的视频参考

BytePlus 生成接口不能直接读取你电脑上的本地视频文件。参考视频需要是：

- 公开可访问的 `https://...` URL
- BytePlus `asset://...` ID
- 使用本项目的 S3 辅助节点上传后得到的 pre-signed URL

私有视频推荐流程：

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
Load Video video -> S3 Upload Reference Video video
S3 Upload Reference Video video_url -> Omni Reference video_url_1
S3 Upload Reference Video s3_reference_json -> Omni Reference s3_reference_json_1
S3 Config s3_config_json -> Omni Reference s3_config_json
Omni Reference delete_s3_references_after_generation = true
```

说明：

- `Load Video` 可以直接连接到 `S3 Upload Reference Video` 的 `video` 输入。
- 上传节点会把原始视频文件上传到 S3，不会把视频拆成帧后重新编码。
- `video_url` 是签名 URL，默认有效期 `300` 秒。
- `s3_reference_json` 是给 `Omni Reference` 自动清理用的可选信息。只在需要生成后删除 S3 对象时连接。
- 如果打开 `Omni Reference` 里的 `delete_s3_references_after_generation`，BytePlus 生成成功后 Omni 会自动删除连接的 S3 对象。
- 如果生成失败，删除不会执行，所以建议 S3 侧也设置 24 小时生命周期清理规则。
- `S3 Browse Reference Videos` 先运行一次拉取列表，点击列表中的某一行选择参考视频，再运行一次即可刷新预览并输出该对象的新签名 URL。打开 `delete_selected` 后运行节点，会删除当前选中的 S3 对象；执行后 UI 会自动把开关关回去。

---

## Omni Reference 的音频参考

音频和视频不一样，BytePlus API 支持把本地音频转成 Base64 data URL 后直接提交。

- `audio_file_1` 到 `audio_file_3` 保留，用来选择 ComfyUI input 里的本地 `mp3` / `wav` 文件。
- `audio_url_1` 到 `audio_url_3` 保留，可填公开 `https://...` URL、`asset://...` ID、已有 `data:audio/...` URL，或本地 `mp3` / `wav` 绝对路径。
- 单个音频长度需要 2 到 15 秒。
- 最多 3 段参考音频，所有音频总时长不能超过 15 秒。
- 单个音频文件不能超过 15 MB。
- request body 不能超过 64 MB，大文件不要用 Base64，建议用公开 URL 或 S3 pre-signed URL。

---

## S3 的 region 和 bucket

S3 API 本身必须知道 `region` 和 `bucket`，但是不需要在上传、浏览节点里重复填写。

推荐做法：

- 在 `S3 Config` 填一次 AWS access key、secret key、`region`、`bucket`、`prefix`
- 把 `S3 Config` 的一条 `s3_config_json` 连接到上传、浏览节点
- 上传/浏览节点上的 `prefix` 为空时，会使用 `S3 Config` 里的 prefix
- 只有想临时换目录时，才在上传/浏览节点上填 `prefix`

也可以在 ComfyUI 机器上创建 `~/.byteplus/seedance2-s3.json`：

```json
{
  "aws_access_key_id": "your_s3_access_key_id",
  "aws_secret_access_key": "your_s3_secret_access_key",
  "region": "ap-northeast-1",
  "bucket": "your-private-reference-video-bucket",
  "prefix": "video-refs"
}
```

还支持环境变量：

```bash
SEEDANCE2_S3_REGION=ap-northeast-1
SEEDANCE2_S3_BUCKET=your-private-reference-video-bucket
SEEDANCE2_S3_PREFIX=video-refs
SEEDANCE2_S3_ACCESS_KEY_ID=your_s3_access_key_id
SEEDANCE2_S3_SECRET_ACCESS_KEY=your_s3_secret_access_key
```

IAM 权限：

- 上传需要目标 bucket/prefix 上的 `s3:PutObject`。
- 浏览和预览需要 `s3:ListBucket` 和 `s3:GetObject`。
- 在 Browse 节点里删除对象需要 `s3:DeleteObject`。
- 如果上传时报 `AccessDenied`，优先检查 IAM policy 是否只允许某个更窄的 prefix。节点实际上传路径由 `S3 Config` 的 `prefix` 决定，这个 prefix 必须和 IAM 允许的资源路径一致。

---

## 历史任务和视频预览

`Seedance 2.0 Retrieve Task Result` 可以通过 `cgt-...` task ID 取回历史任务结果。BytePlus 通常只保留约 24 小时，所以需要长期保存时请使用 `Save Video`。

`Seedance 2.0 Preview Video URL` 会把 `video_url` 下载到 ComfyUI output，并显示 mp4 播放预览。它比 `Save Video` 更轻，因为不会把视频全部解码成 IMAGE 帧。

---

## 示例工作流

ComfyUI 里用 **File -> Load** 加载：

| 文件 | 说明 |
|------|------|
| `Seedance2_T2V_Example.json` | BytePlus Config -> Text-to-Video -> Save Video |
| `Seedance2_ConsistentCharacter_Example.json` | Load Image -> Consistent Character Video -> Save Video |

两个示例都需要填入自己的 `api_key` 和 `endpoint`。

---

## 注意事项

- API Key 和 AWS Secret Key 如果直接填在节点里，可能会保存在工作流 JSON 中。
- GitHub 上不要提交自己的 API Key、endpoint、AWS Key 或真实 bucket 名。
- BytePlus 的历史 task 和输出 URL 大约只保留 24 小时，需要长期保存时请用 `Save Video`。
- `Seedance 2.0 Consistent Character` 是保留给旧工作流的废弃节点，不是直接 BytePlus API 可用的角色表生成节点。
- 旧 muapi CLI 配置 `~/.muapi/config.json` 不会被这个 fork 使用。

---

## 依赖

- Python >= 3.8
- `requests` >= 2.28
- `Pillow` >= 9.0
- `numpy` >= 1.23
- `torch` >= 2.0
- `opencv-python` >= 4.7
- `boto3` >= 1.34，只在使用 S3 辅助节点时需要

---

## License

MIT
