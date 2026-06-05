import argparse
import csv
import unicodedata
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

PARENT_DIR = Path("private") / "attendance"
DEFAULT_ZOOM_CSV = PARENT_DIR / "zoom_csv" / "zoom_report.csv"
DEFAULT_ROSTER_CSV = PARENT_DIR / "roster.csv"
DEFAULT_ALIASES_CSV = PARENT_DIR / "aliases.csv"
DEFAULT_OUTPUT_CSV = PARENT_DIR / "output" / "attendance_output.csv"

AUTO_MATCH_THRESHOLD = 87
REVIEW_THRESHOLD = 70


ZoomAttendee = dict[str, Any]
MatchResult = dict[str, Any]


def normalize_name(name: str) -> str:
    """
    名前比較用に文字列を正規化する。
    """
    if name is None:
        return ""

    name = unicodedata.normalize("NFKC", name)
    name = name.lower()
    name = name.replace(",", " ")
    name = name.replace(".", " ")
    name = " ".join(name.split())
    return name


def parse_duration(value: str) -> float:
    """
    Zoom CSVの Total duration (minutes) を数値に変換する。
    空欄や不正な値は 0 とみなす。
    """
    try:
        return float(value)
    except TypeError, ValueError:
        return 0.0


def name_candidates(first: str, family: str) -> list[str]:
    """
    スプレッドシート側の First / Family から照合候補を作る。
    """
    first = first.strip()
    family = family.strip()

    if not first and not family:
        return []

    candidates = [
        f"{first} {family}",
        f"{family} {first}",
        f"{first}{family}",
        f"{family}{first}",
    ]

    normalized_candidates = []
    for candidate in candidates:
        normalized = normalize_name(candidate)
        if normalized and normalized not in normalized_candidates:
            normalized_candidates.append(normalized)

    return normalized_candidates


def read_aliases(path: str | Path) -> dict[str, list[str]]:
    """
    aliases.csvを読む。

    形式:
        spreadsheet_name,zoom_name

    例:
        Taro Yamada,山田 太郎
        Taro Yamada,Yamada Taro
        Taro Yamada,T. Yamada

    1つの spreadsheet_name に対して複数の zoom_name を書ける。
    """
    aliases: dict[str, list[str]] = {}

    if not Path(path).exists():
        return aliases

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            spreadsheet_name = normalize_name(row.get("spreadsheet_name", ""))
            zoom_name = normalize_name(row.get("zoom_name", ""))

            if not spreadsheet_name or not zoom_name:
                continue

            aliases.setdefault(spreadsheet_name, [])

            if zoom_name not in aliases[spreadsheet_name]:
                aliases[spreadsheet_name].append(zoom_name)

    return aliases


def make_zoom_key(normalized_name: str, occurrence_index: int) -> str:
    """
    Zoom参加者を一意に識別するための内部キーを作る。

    同じ表示名で複数回入室した行があっても上書きされないように、
    normalized_name と出現番号を組み合わせる。
    """
    return f"{normalized_name}#{occurrence_index}"


def read_zoom_attendees(path: str | Path) -> dict[str, ZoomAttendee]:
    """
    ZoomのCSVを読み込む。
    最初の3行はメタ情報なので無視する。

    戻り値は internal_key -> attendee_info の辞書。
    normalized_name が同じ行が複数あっても、別々の参加記録として保持する。
    """
    attendees: dict[str, ZoomAttendee] = {}
    occurrence_counts: dict[str, int] = {}

    with open(path, newline="", encoding="utf-8-sig") as f:
        for _ in range(3):
            next(f)

        reader = csv.DictReader(f)

        for row in reader:
            original_name = row.get("Name (original name)", "").strip()
            email = row.get("Email", "").strip()
            duration_raw = row.get("Total duration (minutes)", "").strip()
            guest = row.get("Guest", "").strip()

            if not original_name:
                continue

            normalized = normalize_name(original_name)
            duration = parse_duration(duration_raw)

            occurrence_index = occurrence_counts.get(normalized, 0) + 1
            occurrence_counts[normalized] = occurrence_index
            zoom_key = make_zoom_key(normalized, occurrence_index)

            attendees[zoom_key] = {
                "zoom_key": zoom_key,
                "normalized_name": normalized,
                "original_name": original_name,
                "email": email,
                "duration": duration,
                "guest": guest,
            }

    return attendees


def read_roster(path: str | Path) -> list[dict[str, str]]:
    """
    スプレッドシートをCSVとして保存したものを読む。
    B列 First name, C列 Family Name を使う。

    CSV上では:
        A列: row[0]
        B列: row[1]
        C列: row[2]
    """
    rows = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)

        for row in reader:
            first = row[1].strip() if len(row) > 1 else ""
            family = row[2].strip() if len(row) > 2 else ""

            rows.append(
                {
                    "first": first,
                    "family": family,
                }
            )

    return rows


def make_match_result(
    *,
    attendance: str,
    matched_zoom_keys: list[str],
    matched_zoom_name: str,
    duration: float | str,
    score: float | str,
    note: str,
) -> MatchResult:
    return {
        "attendance": attendance,
        "matched_zoom_keys": matched_zoom_keys,
        "matched_zoom_name": matched_zoom_name,
        "duration": duration,
        "score": score,
        "note": note,
    }


def aggregate_duration(attendees: list[ZoomAttendee], duration_mode: str) -> float:
    """
    複数のZoom参加記録を1人分として集約する。

    duration_mode:
        sum: durationを合算する
        max: 最長durationを使う
    """
    durations = [attendee["duration"] for attendee in attendees]

    if not durations:
        return 0.0

    if duration_mode == "max":
        return max(durations)

    return sum(durations)


def format_matched_zoom_names(attendees: list[ZoomAttendee]) -> str:
    """
    出力CSVの Matched Zoom Name に入れる文字列を作る。
    複数候補がある場合は ; で連結する。
    """
    parts = []
    for attendee in attendees:
        name = attendee["original_name"]
        duration = attendee["duration"]
        parts.append(f"{name} ({duration:g} min)")
    return "; ".join(parts)


def judge_attendance_for_matches(
    *,
    matched_zoom_keys: list[str],
    zoom_attendees: dict[str, ZoomAttendee],
    duration_thresh: float,
    duration_mode: str,
    score: float | str,
    note_if_present: str = "",
) -> MatchResult:
    """
    対応するZoom参加記録が1件以上見つかったあと、
    durationを集約して出席を判定する。
    """
    attendees = [zoom_attendees[key] for key in matched_zoom_keys]
    duration = aggregate_duration(attendees, duration_mode)
    matched_zoom_name = format_matched_zoom_names(attendees)

    if duration >= duration_thresh:
        attendance = "✅"
        note = note_if_present
    else:
        attendance = ""
        note = "short duration"

    return make_match_result(
        attendance=attendance,
        matched_zoom_keys=matched_zoom_keys,
        matched_zoom_name=matched_zoom_name,
        duration=duration,
        score=score,
        note=note,
    )


def find_zoom_keys_by_normalized_name(
    zoom_attendees: dict[str, ZoomAttendee],
    normalized_name: str,
) -> list[str]:
    """
    normalized_name に一致するZoom参加記録をすべて返す。
    同じ表示名で複数回入室していた場合も全部返す。
    """
    return [
        key
        for key, attendee in zoom_attendees.items()
        if attendee["normalized_name"] == normalized_name
    ]


def collect_alias_matches(
    *,
    candidates: list[str],
    aliases: dict[str, list[str]],
    zoom_attendees: dict[str, ZoomAttendee],
) -> list[str]:
    """
    spreadsheet側の候補名に対応する alias の zoom_name をすべて集める。
    見つかったZoom参加記録は重複を除いてすべて返す。
    """
    matched_keys: list[str] = []

    for candidate in candidates:
        for alias_zoom_name in aliases.get(candidate, []):
            for zoom_key in find_zoom_keys_by_normalized_name(
                zoom_attendees, alias_zoom_name
            ):
                if zoom_key not in matched_keys:
                    matched_keys.append(zoom_key)

    return matched_keys


def build_zoom_name_index(zoom_attendees: dict[str, ZoomAttendee]) -> list[str]:
    """
    fuzzy matching用に、重複を除いた normalized_name の一覧を作る。
    """
    names: list[str] = []
    for attendee in zoom_attendees.values():
        normalized_name = attendee["normalized_name"]
        if normalized_name not in names:
            names.append(normalized_name)
    return names


def match_person(
    first: str,
    family: str,
    zoom_attendees: dict[str, ZoomAttendee],
    aliases: dict[str, list[str]],
    duration_thresh: float,
    duration_mode: str,
) -> MatchResult:
    """
    スプレッドシートの1人について、Zoom参加者の中から対応する人を探す。
    """
    candidates = name_candidates(first, family)

    if not candidates:
        return make_match_result(
            attendance="",
            matched_zoom_keys=[],
            matched_zoom_name="",
            duration="",
            score="",
            note="blank row",
        )

    # 1. まず手動aliasを試す。
    #    同じ spreadsheet_name に複数の zoom_name がある場合、見つかったものを全部採用する。
    alias_matched_keys = collect_alias_matches(
        candidates=candidates,
        aliases=aliases,
        zoom_attendees=zoom_attendees,
    )

    if alias_matched_keys:
        return judge_attendance_for_matches(
            matched_zoom_keys=alias_matched_keys,
            zoom_attendees=zoom_attendees,
            duration_thresh=duration_thresh,
            duration_mode=duration_mode,
            score="alias",
        )

    # 2. aliasで見つからなければ fuzzy matching。
    #    fuzzy matchingでは最も近い normalized_name を1つ選び、
    #    その normalized_name に対応するZoom参加記録が複数あれば全部採用する。
    zoom_names = build_zoom_name_index(zoom_attendees)
    best_match = None

    for candidate in candidates:
        result = process.extractOne(
            candidate,
            zoom_names,
            scorer=fuzz.WRatio,
        )

        if result is None:
            continue

        matched_name, score, _ = result

        if best_match is None or score > best_match[1]:
            best_match = (matched_name, score)

    if best_match is None:
        return make_match_result(
            attendance="",
            matched_zoom_keys=[],
            matched_zoom_name="",
            duration="",
            score="",
            note="no match",
        )

    matched_name, score = best_match
    matched_keys = find_zoom_keys_by_normalized_name(zoom_attendees, matched_name)

    if score >= AUTO_MATCH_THRESHOLD:
        return judge_attendance_for_matches(
            matched_zoom_keys=matched_keys,
            zoom_attendees=zoom_attendees,
            duration_thresh=duration_thresh,
            duration_mode=duration_mode,
            score=round(score, 1),
        )

    attendees = [zoom_attendees[key] for key in matched_keys]
    matched_zoom_name = format_matched_zoom_names(attendees)
    duration = aggregate_duration(attendees, duration_mode)

    if score >= REVIEW_THRESHOLD:
        return make_match_result(
            attendance="",
            matched_zoom_keys=matched_keys,
            matched_zoom_name=matched_zoom_name,
            duration=duration,
            score=round(score, 1),
            note="review",
        )

    return make_match_result(
        attendance="",
        matched_zoom_keys=matched_keys,
        matched_zoom_name=matched_zoom_name,
        duration=duration,
        score=round(score, 1),
        note="low score",
    )


def print_unused_zoom_attendees(
    zoom_attendees: dict[str, ZoomAttendee],
    used_zoom_keys: set[str],
) -> None:
    """
    名簿の誰にも対応しなかったZoom参加者をターミナルに表示する。
    """
    unused_keys = [key for key in zoom_attendees.keys() if key not in used_zoom_keys]

    if not unused_keys:
        print("\nUnused Zoom attendees: none")
        return

    print("\nUnused Zoom attendees:")
    print("----------------------")

    for key in unused_keys:
        attendee = zoom_attendees[key]
        print(
            f"- {attendee['original_name']}"
            f" | duration={attendee['duration']}"
            f" | email={attendee['email']}"
            f" | guest={attendee['guest']}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an attendance CSV from a Zoom report and a roster CSV."
    )

    parser.add_argument(
        "--zoom-csv",
        default=DEFAULT_ZOOM_CSV,
        help=f"Zoom attendance report CSV. Default: {DEFAULT_ZOOM_CSV}",
    )

    parser.add_argument(
        "--roster-csv",
        default=DEFAULT_ROSTER_CSV,
        help=f"Roster CSV exported from the spreadsheet. Default: {DEFAULT_ROSTER_CSV}",
    )

    parser.add_argument(
        "--aliases-csv",
        default=DEFAULT_ALIASES_CSV,
        help=f"Alias mapping CSV. Default: {DEFAULT_ALIASES_CSV}",
    )

    parser.add_argument(
        "--output-csv",
        default=DEFAULT_OUTPUT_CSV,
        help=f"Output CSV. Default: {DEFAULT_OUTPUT_CSV}",
    )

    parser.add_argument(
        "--duration-thresh",
        type=float,
        default=1.0,
        help="Minimum Zoom duration in minutes required for attendance. Default: 1",
    )

    parser.add_argument(
        "--duration-mode",
        choices=["sum", "max"],
        default="sum",
        help="How to aggregate durations when multiple Zoom rows match one person. Default: sum",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    zoom_attendees = read_zoom_attendees(args.zoom_csv)
    roster_rows = read_roster(args.roster_csv)
    aliases = read_aliases(args.aliases_csv)

    output_rows = []
    used_zoom_keys: set[str] = set()

    for person in roster_rows:
        first = person["first"]
        family = person["family"]

        match = match_person(
            first=first,
            family=family,
            zoom_attendees=zoom_attendees,
            aliases=aliases,
            duration_thresh=args.duration_thresh,
            duration_mode=args.duration_mode,
        )

        used_zoom_keys.update(match["matched_zoom_keys"])

        output_rows.append(
            {
                "First Name": first,
                "Family Name": family,
                "Attendance": match["attendance"],
                "Matched Zoom Name": match["matched_zoom_name"],
                "Duration": match["duration"],
                "Score": match["score"],
                "Note": match["note"],
            }
        )

    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "First Name",
            "Family Name",
            "Attendance",
            "Matched Zoom Name",
            "Duration",
            "Score",
            "Note",
        ]

        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nOutput written to: {output_path}")
    print_unused_zoom_attendees(zoom_attendees, used_zoom_keys)


if __name__ == "__main__":
    main()
