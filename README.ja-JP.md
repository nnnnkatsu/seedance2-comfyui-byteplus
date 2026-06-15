# Seedance 2.0 ComfyUI ノード for BytePlus ModelArk

言語: [English](README.md) | [中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

これは ComfyUI 用の Seedance 2.0 カスタムノードです。この fork は、元の muapi.ai 経由ではなく、BytePlus ModelArk API を直接呼び出すように変更されています。

元プロジェクト: [Anil-matcha/seedance2-comfyui](https://github.com/Anil-matcha/seedance2-comfyui)

---

## 必要なもの

- BytePlus ModelArk API Key。通常は `ark-...` の形式
- BytePlus endpoint ID。通常は `ep-...` の形式
- 非公開のローカル動画を参照素材として使う場合は、AWS S3 bucket とアクセスキー

注意：ComfyUI 側では `endpoint` と表示していますが、BytePlus 公式 API のリクエスト字段名は `model` です。このノード内部で `endpoint` を公式 API の `model` 字段へ入れています。

---

## インストール

### ComfyUI Manager からインストール

1. **ComfyUI Manager** -> **Install via Git URL** を開く
2. 次の URL を入力:

```text
https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
```

3. ComfyUI を再起動

### 手動インストール

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
pip install -r seedance2-comfyui-byteplus/requirements.txt
```

通常の生成ノードだけなら既存環境の依存で足りることが多いです。S3 補助ノードを使う場合は `boto3` が必要です。

---

## 基本的な使い方

1. `Seedance 2.0 BytePlus Config` を追加
2. `api_key` に BytePlus API Key を入力
3. `endpoint` に BytePlus endpoint ID、つまり `ep-...` を入力
4. `Seedance 2.0 Text-to-Video` などの生成ノードを追加
5. Config ノードの `api_key` と `endpoint` を生成ノードへ接続
6. prompt を書いて workflow を実行

---

## ノード一覧

| ノード | 用途 |
|--------|------|
| `Seedance 2.0 BytePlus Config` | 最初に置く推奨ノード。`api_key` と `endpoint` をまとめて設定します。 |
| `Seedance 2.0 API Key` | 旧 workflow 互換用。通常は BytePlus Config を推奨します。 |
| `Seedance 2.0 Text-to-Video` | テキストから動画を生成します。 |
| `Seedance 2.0 Image-to-Video` | 最大 9 枚の ComfyUI 画像を参照して動画を生成します。 |
| `Seedance 2.0 Omni Reference` | テキスト、画像、動画、音声を参照して動画を生成します。 |
| `Seedance 2.0 Consistent Character Video` | キャラクター画像や参照画像を使って一貫性のあるキャラクター動画を生成します。 |
| `Seedance 2.0 Extend` | 生成済み動画の続きを生成します。 |
| `Seedance 2.0 Retrieve Task Result` | `cgt-...` の task ID から、約 24 時間以内の生成結果を取得します。 |
| `Seedance 2.0 Preview Video URL` | `video_url` をダウンロードし、ComfyUI 内で動画プレビューします。 |
| `Seedance 2.0 Save Video` | `video_url` をローカル保存し、IMAGE フレームも出力します。 |
| `Seedance 2.0 S3 Config` | S3 の key、region、bucket、prefix をまとめて設定します。 |
| `Seedance 2.0 S3 Upload Reference Video` | ローカル参照動画を S3 にアップロードし、短時間有効な署名付き URL を出力します。 |
| `Seedance 2.0 S3 Browse Reference Videos` | S3 内の参照動画を一覧し、プレビュー表示して、選択した署名付き URL を出力します。 |
| `Seedance 2.0 S3 Delete Reference Video` | 高度/手動クリーンアップ用ノードです。通常 workflow では `Omni Reference` から自動削除できます。 |
| `Seedance 2.0 Consistent Character` | 非推奨ノード。古い workflow に明確なエラーを出すために残しています。 |

---

## 設定方法

### 推奨：Config ノード

```text
[Seedance 2.0 BytePlus Config]
  api_key  -> 生成ノード api_key
  endpoint -> 生成ノード endpoint
```

### 環境変数

ノードのフィールドを空欄にして、環境変数で指定することもできます。

```bash
ARK_API_KEY=your_byteplus_api_key
SEEDANCE2_ENDPOINT=your_endpoint_id
BYTEPLUS_ARK_BASE_URL=https://ark.ap-southeast.bytepluses.com/api/v3
```

旧名称との互換：

```bash
SEEDANCE2_MODEL=your_endpoint_id
BYTEPLUS_SEEDANCE_MODEL=your_endpoint_id
ARK_MODEL=your_endpoint_id
```

### ローカル設定ファイル

`~/.byteplus/seedance2-comfyui.json` を作成することもできます。

```json
{
  "api_key": "your_byteplus_api_key",
  "endpoint": "your_endpoint_id",
  "base_url": "https://ark.ap-southeast.bytepluses.com/api/v3"
}
```

互換フィールドとして `endpoint_id` と `model` も endpoint として使えます。

---

## 解像度

生成ノードでは `resolution` を使います。選択肢：

- `480p`
- `720p`
- `1080p`

古い `quality` は主要設定ではありません。BytePlus 公式 API では解像度を指定します。Seedance 2.0 Fast endpoint では `1080p` が使えない場合があります。

---

## Omni Reference の動画参照

BytePlus の生成 API は、PC 上のローカル動画ファイルを直接読むことはできません。参照動画は以下のいずれかが必要です。

- 外部からアクセス可能な `https://...` URL
- BytePlus の `asset://...` ID
- このプロジェクトの S3 補助ノードでアップロードして作った pre-signed URL

非公開動画の推奨 workflow：

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
Load Video video -> S3 Upload Reference Video video
S3 Upload Reference Video video_url -> Omni Reference video_url_1
S3 Upload Reference Video s3_reference_json -> Omni Reference s3_reference_json_1
S3 Config s3_config_json -> Omni Reference s3_config_json
Omni Reference delete_s3_references_after_generation = true
```

説明：

- `Load Video` は `S3 Upload Reference Video` の `video` 入力へそのまま接続できます。
- アップロードノードは元の動画ファイルを S3 にアップロードします。フレームへ分解して再エンコードする処理ではありません。
- `video_url` は署名付き URL で、初期値では `300` 秒だけ有効です。
- `s3_reference_json` は `Omni Reference` の自動クリーンアップ用の任意情報です。生成後に S3 オブジェクトを削除したい場合だけ接続します。
- `Omni Reference` の `delete_s3_references_after_generation` を有効にすると、BytePlus 生成成功後に Omni が接続された S3 オブジェクトを自動削除します。
- 生成が失敗した場合は削除されないため、S3 側の 24 時間ライフサイクル削除も併用するのが安全です。
- `S3 Delete Reference Video` は手動削除や高度なクリーンアップ用として残しています。通常の Upload -> Omni workflow では不要です。
- `S3 Browse Reference Videos` は現在の `selected_index` の動画だけをプレビューし、その同じ S3 object の署名付き URL を再発行します。別の参照動画を使う場合は、`selected_index` を変えてノードを再実行してください。

---

## Omni Reference の音声参照

音声は動画と異なり、BytePlus API へ Base64 data URL として直接渡せます。

- `audio_file_1` から `audio_file_3` は残しています。ComfyUI input 内のローカル `mp3` / `wav` を選択します。
- `audio_url_1` から `audio_url_3` には、公開 `https://...` URL、`asset://...` ID、既存の `data:audio/...` URL、またはローカル `mp3` / `wav` の絶対パスを入力できます。
- 1 つの音声は 2 秒から 15 秒です。
- 参照音声は最大 3 本、合計長は 15 秒以内です。
- 1 ファイルは 15 MB 以内です。
- request body は 64 MB 以内です。大きいファイルは Base64 ではなく、公開 URL または S3 pre-signed URL を使う方が安全です。

---

## S3 の region と bucket

S3 API には `region` と `bucket` が必要です。ただし、アップロード、ブラウズ、削除ノードに毎回表示して入力する必要はありません。

推奨：

- `S3 Config` に AWS access key、secret key、`region`、`bucket`、`prefix` を一度だけ入力
- `S3 Config` の 1 本の `s3_config_json` を S3 補助ノードへ接続
- アップロード/ブラウズノードの `prefix` が空欄なら、`S3 Config` の prefix が使われます
- 一時的に保存先だけ変えたい場合だけ、アップロード/ブラウズノード側の `prefix` を入力します

ComfyUI マシンに `~/.byteplus/seedance2-s3.json` を置くこともできます。

```json
{
  "aws_access_key_id": "your_s3_access_key_id",
  "aws_secret_access_key": "your_s3_secret_access_key",
  "region": "ap-northeast-1",
  "bucket": "your-private-reference-video-bucket",
  "prefix": "video-refs"
}
```

環境変数も使えます。

```bash
SEEDANCE2_S3_REGION=ap-northeast-1
SEEDANCE2_S3_BUCKET=your-private-reference-video-bucket
SEEDANCE2_S3_PREFIX=video-refs
SEEDANCE2_S3_ACCESS_KEY_ID=your_s3_access_key_id
SEEDANCE2_S3_SECRET_ACCESS_KEY=your_s3_secret_access_key
```

IAM 権限：

- アップロードには対象 bucket/prefix への `s3:PutObject` が必要です。
- ブラウズとプレビューには `s3:ListBucket` と `s3:GetObject` が必要です。
- 削除には `s3:DeleteObject` が必要です。
- アップロード時に `AccessDenied` が出る場合は、IAM policy がより狭い prefix だけを許可していないか確認してください。ノードの実際のアップロード先は `S3 Config` の `prefix` で決まるため、この prefix と IAM の許可リソースパスが一致している必要があります。

---

## 履歴タスクと動画プレビュー

`Seedance 2.0 Retrieve Task Result` は `cgt-...` の task ID から履歴タスクを取得します。BytePlus 側の保持期間は通常約 24 時間なので、長期保存したい場合は `Save Video` を使ってください。

`Seedance 2.0 Preview Video URL` は `video_url` を ComfyUI output にダウンロードし、mp4 プレイヤーで表示します。動画全体を IMAGE フレームにデコードしないため、`Save Video` より軽いです。

---

## サンプル workflow

ComfyUI の **File -> Load** から読み込みます。

| ファイル | 説明 |
|----------|------|
| `Seedance2_T2V_Example.json` | BytePlus Config -> Text-to-Video -> Save Video |
| `Seedance2_ConsistentCharacter_Example.json` | Load Image -> Consistent Character Video -> Save Video |

どちらも自分の `api_key` と `endpoint` を入力する必要があります。

---

## 注意点

- API Key や AWS Secret Key をノードへ直接入力すると、workflow JSON に保存される可能性があります。
- GitHub へ自分の API Key、endpoint、AWS Key、実 bucket 名をコミットしないでください。
- BytePlus の過去 task と出力 URL は約 24 時間で使えなくなります。長期保存する場合は `Save Video` を使ってください。
- `Seedance 2.0 Consistent Character` は古い workflow 用の非推奨ノードです。BytePlus 直接 API でキャラクターシートを生成するノードではありません。
- 古い muapi CLI 設定 `~/.muapi/config.json` はこの fork では使いません。

---

## 依存関係

- Python >= 3.8
- `requests` >= 2.28
- `Pillow` >= 9.0
- `numpy` >= 1.23
- `torch` >= 2.0
- `opencv-python` >= 4.7
- `boto3` >= 1.34。S3 補助ノードを使う場合だけ必要です。

---

## License

MIT
