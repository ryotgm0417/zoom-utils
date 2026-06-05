# zoom-utils

ZoomからエクスポートしたCSVを扱うための小さなユーティリティ集です。

このプロジェクトには、主に次の2つのプログラムがあります。

- `generate_attendance_csv.py`: Zoom meetingの出席レポートCSVから、スプレッドシートへ転記しやすい出席CSVを作成する
- `export_survey_results.py`: Zoomのアンケート結果CSVを読み込み、回答数のグラフをPDFとして出力する

## セットアップ

`uv`を使って環境構築できます。

```bash
uv sync
```

## 1. 出席転記用CSVの作成

### 目的

`generate_attendance_csv.py` は、Zoom meetingの出席レポートCSVと、スプレッドシートからエクスポートした名簿CSVを照合し、スプレッドシートに貼り付けやすい出席CSVを作成します。

スプレッドシート側は、次の列構成を想定しています。

- B列: First name
- C列: Family Name
- I列以降: 各回の出席欄

Zoom出席レポートCSVは、最初の3行がmeetingのメタ情報で、4行目に次のヘッダーがある形式を想定しています。

```csv
Name (original name),Email,Total duration (minutes),Guest
```

### デフォルトのファイル配置

```text
private/attendance/
├── roster.csv
├── aliases.csv
├── zoom_csv/
│   └── zoom_report.csv
└── output/
    └── attendance_output.csv
```

### 基本的な実行方法

```bash
python generate_attendance_csv.py
```

この場合、デフォルトでは次のファイルを使います。

- 入力Zoom CSV: `private/attendance/zoom_csv/zoom_report.csv`
- 入力名簿CSV: `private/attendance/roster.csv`
- alias対応表: `private/attendance/aliases.csv`
- 出力CSV: `private/attendance/output/attendance_output.csv`

### ファイル名や条件を指定して実行する例

```bash
python generate_attendance_csv.py \
  --zoom-csv private/attendance/zoom_csv/zoom_report.csv \
  --roster-csv private/attendance/roster.csv \
  --aliases-csv private/attendance/aliases.csv \
  --output-csv private/attendance/output/attendance_output.csv \
  --duration-thresh 10 \
  --duration-mode sum
```

### 主なオプション

| オプション | 意味 | デフォルト |
|---|---|---|
| `--zoom-csv` | Zoom出席レポートCSV | `private/attendance/zoom_csv/zoom_report.csv` |
| `--roster-csv` | スプレッドシートから出力した名簿CSV | `private/attendance/roster.csv` |
| `--aliases-csv` | 名前表記ゆれの手動対応表 | `private/attendance/aliases.csv` |
| `--output-csv` | 出力CSV | `private/attendance/output/attendance_output.csv` |
| `--duration-thresh` | 出席とみなす最低参加時間、単位は分 | `1` |
| `--duration-mode` | 複数Zoom名が同一人物に対応した場合の参加時間集約方法。`sum` または `max` | `sum` |

### `aliases.csv` の書き方

Zoom上の名前と名簿上の名前が大きく異なる場合は、`aliases.csv` に対応を書きます。

```csv
spreadsheet_name,zoom_name
Taro Yamada,山田 太郎
Taro Yamada,Yamada Taro
Taro Yamada,T. Yamada
Hiroshi Ito,伊藤 博
```

同じ `spreadsheet_name` に対して複数の `zoom_name` を書けます。

複数のZoom名が同じ人物に対応し、Zoom CSV内にも複数見つかった場合は、`--duration-mode` に従って参加時間を集約します。

- `sum`: 参加時間を合算する
- `max`: 最も長い参加時間を使う

出力CSVの `Matched Zoom Name` には、対応したZoom名が複数表示されます。

### 出力CSV

出力CSVには、スプレッドシート側の名簿と同じ順番で行が並びます。空行も保持されるため、`Attendance` 列をコピーしてスプレッドシートの該当回の列に貼り付けられます。

出力例:

```csv
First Name,Family Name,Attendance,Matched Zoom Name,Duration,Score,Note
Taro,Yamada,✅,Yamada Taro (20 min); T. Yamada (35 min),55.0,alias,
Hiroshi,Ito,,Hiroshi I. (0.5 min),0.5,alias,short duration
,,,
Koichi,Masuda,✅,Koichi Masuda (45 min),45.0,96.0,
```

実行後、名簿の誰にも対応しなかったZoom参加者はターミナルに表示されます。名簿漏れや表記ゆれの確認に使えます。

## 2. アンケート結果PDFの作成

### 目的

`export_survey_results.py` は、Zoomのアンケート結果CSVを読み込み、各質問の回答数を横棒グラフにして、1つのPDFにまとめます。

### デフォルトの入出力

スクリプト末尾では、次のファイルを使う設定になっています。

```python
csv_file = "private/report_poll.csv"
output_pdf = "private/report_poll.pdf"
```

### 基本的な実行方法

```bash
python export_survey_results.py
```

実行すると、`private/report_poll.csv` を読み込み、`private/report_poll.pdf` を出力します。

### CSV形式について

ZoomのCSVのうち、Poll Detailsの表が10行目から始まる想定です。

```python
df = load_survey_csv(csv_path, poll_details_start_line=10)
```

CSVの形式が異なる場合は、`poll_details_start_line` の値を調整してください。

### 質問列の検出

以下のようなメタデータ列を除外し、それ以外の列をアンケート質問列として扱います。

```text
#
User Name
Email Address
Submitted Date and Time
Collected from
Topic/Name
Meeting/Webinar ID
```

必要に応じて、`find_question_columns()` 内の `metadata_columns` を編集してください。

### 複数回答について

複数回答は、セミコロン `;` 区切りとして集計されます。

例:

```text
Option A; Option C
```

Zoom CSV側の区切り文字が異なる場合は、`count_answers()` 内の次の部分を変更してください。

```python
split_answers = cleaned.str.split(";").explode()
```

## 注意

- CSVに日本語が含まれる場合、基本的には `utf-8-sig` で読み込みます。
- 文字化けする場合は、対象スクリプト内の `encoding` を `shift_jis` や `cp932` に変更してください。
- 出席処理は名前の曖昧一致を含むため、初回運用時は `Matched Zoom Name`, `Score`, `Note` を確認してください。
