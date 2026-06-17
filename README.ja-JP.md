# Seedance 2.0 ComfyUI Nodes for BytePlus ModelArk

言語: [English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja-JP.md)

これは [Anil-matcha/seedance2-comfyui](https://github.com/Anil-matcha/seedance2-comfyui) のカスタム fork です。元の muapi.ai 連携を、BytePlus ModelArk 公式 API への直接呼び出しに置き換えています。さらに、非公開のローカル参照動画を扱うための AWS S3 補助ノードを追加しています。

BytePlus ModelArk の API Key と `ep-...` endpoint ID を持っているユーザー向けです。

## この fork の変更点

- BytePlus ModelArk API を直接呼び出します。
- UI の `endpoint` に BytePlus の `ep-...` endpoint ID を入力します。API リクエストでは公式フィールド `model` に渡します。
- `resolution`: `480p`, `720p`, `1080p` を選択できます。
- `seed` を設定できます。
- `watermark` は常に `false` です。
- S3 アップロード、ブラウズ、プレビュー、削除用の補助ノードを追加しています。
- 参照動画は `video_ref` で接続します。URL と S3 cleanup 情報を一緒に渡せます。
- BytePlus の生成履歴を一覧表示するノードを追加しています。

## ノード一覧

| ノード | 説明 |
|--------|------|
| `Seedance 2.0 BytePlus Config` | 最初に追加する推奨ノード。BytePlus `api_key` と `endpoint` をまとめて設定します。 |
| `Seedance 2.0 Text-to-Video` | テキストから動画を生成します。 |
| `Seedance 2.0 Image-to-Video` | 最大 9 枚の画像参照から動画を生成します。 |
| `Seedance 2.0 First/Last Frame-to-Video` | first frame と任意の last frame から動画を生成します。通常の参照画像、参照動画、参照音声とは混在できません。 |
| `Seedance 2.0 Omni Reference` | テキスト、画像、動画、音声を参照して動画を生成します。 |
| `Seedance 2.0 Consistent Character Video` | メイン参照画像または `sheet_url` で一貫したキャラクター動画を生成します。 |
| `Seedance 2.0 Extend` | 完了済み動画を延長します。 |
| `Seedance 2.0 Retrieve Task Result` | `cgt-...` task ID から近期タスクを取得します。 |
| `Seedance 2.0 Generation History Browser` | BytePlus の近期生成タスクを一覧表示し、選択したタスクの `video_url` と `video_ref` を出力します。 |
| `Seedance 2.0 Video Reference URL` | 公開 URL、S3 署名付き URL、`asset://` を `video_ref` に変換します。 |
| `Seedance 2.0 Preview Video Reference` | 終端の確認用ノードです。URL と S3 key をノード内に表示し、出力ポートはありません。 |
| `Seedance 2.0 Preview Video URL` | `video_url` をダウンロードして ComfyUI で動画プレビューします。 |
| `Seedance 2.0 Save Video` | 動画を保存し、IMAGE frames を出力します。 |
| `Seedance 2.0 S3 Config` | S3 region、bucket、prefix、アクセスキーをまとめて設定します。 |
| `Seedance 2.0 S3 Upload Reference Video` | ローカル参照動画を S3 にアップロードし、`video_ref` を出力します。`Load Video` に対応しています。 |
| `Seedance 2.0 S3 Browse Reference Videos` | S3 の参照動画を一覧し、プレビュー表示し、選択した `video_ref` を出力します。選択中の object 削除もできます。 |
| `Seedance 2.0 Consistent Character` | 廃止済みです。元の muapi 専用機能です。 |

## インストール

### ComfyUI Manager

1. ComfyUI Manager を開きます。
2. **Install via Git URL** を選びます。
3. 次を貼り付けます。

```text
https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
```

4. ComfyUI を再起動します。

### 手動インストール

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/nnnnkatsu/seedance2-comfyui-byteplus
pip install -r seedance2-comfyui-byteplus/requirements.txt
```

`boto3` は S3 補助ノードを使う場合だけ必要です。

## 基本的な使い方

1. `Seedance 2.0 BytePlus Config` を追加します。
2. `api_key` に BytePlus ModelArk API Key を入力します。
3. `endpoint` に `ep-...` endpoint ID を入力します。
4. `Text-to-Video` などの生成ノードを追加します。
5. `api_key` と `endpoint` を接続します。
6. prompt を入力して実行します。

## Omni の動画参照

BytePlus の生成 API は、PC 上の非公開ローカル動画を直接読み込めません。ローカル動画は先に S3 にアップロードし、生成された `video_ref` を Omni に渡します。

新しい参照動画をアップロードする場合:

```text
S3 Config s3_config_json -> S3 Upload Reference Video s3_config_json
Load Video video -> S3 Upload Reference Video video
S3 Upload Reference Video video_ref -> Omni Reference video_ref_1
Omni Reference delete_s3_references_after_generation = true
```

S3 にある参照動画を再利用する場合:

```text
S3 Config s3_config_json -> S3 Browse Reference Videos s3_config_json
S3 Browse Reference Videos video_ref -> Omni Reference video_ref_1
```

`video_ref` には次が含まれます。

- BytePlus が読む動画 URL
- S3 bucket/key/region などの cleanup 情報
- 必要な場合、Omni が生成成功後に S3 object を削除するための情報

`Preview Video Reference` は確認用です。`video_ref` の URL と `s3_key` だけを表示し、動画のダウンロードやプレビューは行いません。

## S3 設定

S3 API には `region` と `bucket` が必要ですが、`S3 Config` に一度入力すれば十分です。

環境変数も使えます。

```bash
SEEDANCE2_S3_REGION=ap-northeast-1
SEEDANCE2_S3_BUCKET=your-private-reference-video-bucket
SEEDANCE2_S3_PREFIX=video-refs
SEEDANCE2_S3_ACCESS_KEY_ID=your_s3_access_key_id
SEEDANCE2_S3_SECRET_ACCESS_KEY=your_s3_secret_access_key
```

IAM 権限:

- アップロード: `s3:PutObject`
- ブラウズ/プレビュー: `s3:ListBucket`, `s3:GetObject`
- 削除: `s3:DeleteObject`

参照動画用 bucket/prefix だけに権限を絞った IAM ユーザーを使うことを推奨します。

## First/Last Frame 生成

`Seedance 2.0 First/Last Frame-to-Video` は独立ノードです。BytePlus では first/last frame 生成が通常の参照素材付き生成とは別モードとして扱われるためです。

対応内容:

- 必須 first frame
- 任意 last frame
- prompt
- resolution、duration、seed、audio generation

通常の参照画像、参照動画、参照音声とは同じリクエストで混在できません。キャラクター、背景、物体、動画、音声などの追加参照が必要な場合は `Image-to-Video` または `Omni Reference` を使ってください。

## 生成履歴

`Seedance 2.0 Generation History Browser` は BytePlus の近期タスクを一覧表示します。

```text
Generation History Browser video_ref -> Omni Reference video_ref_1
Generation History Browser video_url -> Save Video video_url
Generation History Browser video_url -> Preview Video URL video_url
```

一度実行してリストを取得し、行をクリックして、もう一度実行すると選択タスクを再取得してプレビューを更新します。BytePlus の task list API を先に試し、失敗した場合はこのノードパックがローカルに記録した task ID にフォールバックします。

BytePlus のタスク結果と出力 URL は短期間しか保持されません。通常は約 24 時間です。長期保存する場合は `Save Video` を使ってください。

## 音声参照

`Omni Reference` はローカル音声ファイルと音声 URL に対応しています。

- `audio_file_1` から `audio_file_3`: ComfyUI input 内の `mp3` または `wav`。
- `audio_url_1` から `audio_url_3`: 公開 URL、`asset://...`、既存の `data:audio/...`、ローカル `mp3` / `wav` パス。
- BytePlus 制限: 1 clip は 2-15 秒、最大 3 clip、合計 15 秒以内、各ファイル 15 MB 以内。

## セキュリティ

- API Key や AWS Secret を Git にコミットしないでください。
- この README には実際の認証情報は含めていません。
- ComfyUI workflow は widget 値を保存する場合があります。権限を絞った IAM ユーザーを使ってください。
