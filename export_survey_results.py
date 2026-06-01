import re
from io import StringIO
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from pathlib import Path
import textwrap



def load_survey_csv(csv_path: str, poll_details_start_line: int) -> pd.DataFrame:
    """
    Load the exported Zoom survey/poll CSV.

    Adjust encoding if needed:
    - "utf-8-sig" often works well for CSV files exported from web apps.
    - Try "shift_jis" or "cp932" if your CSV contains Japanese text and fails to load.
    """
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        lines = f.readlines()

    # Start from the Poll Details table header line
    lines = lines[poll_details_start_line - 1:]

    # Remove trailing commas at the end of each line
    cleaned_lines = [
        re.sub(r",+\s*$", "\n", line)
        for line in lines
    ]

    cleaned_csv = "".join(cleaned_lines)

    df = pd.read_csv(StringIO(cleaned_csv))

    df = df.dropna(how="all")

    return df


def find_question_columns(df: pd.DataFrame) -> list[str]:
    """
    Identify survey question columns.

    Zoom exports often include metadata columns such as participant name,
    email, submitted time, etc. Exclude those and keep the actual question columns.

    You may need to customize this list depending on your CSV structure.
    """

    metadata_columns = [
        "#",
        "User Name",
        "Email Address",
        "Submitted Date and Time",
        "Collected from",
        "Topic/Name",
        "Meeting/Webinar ID"
    ]

    question_columns = []

    for col in df.columns:
        if col not in metadata_columns:
            question_columns.append(col)

    return question_columns


def wrap_text(text: str, width: int = 50) -> str:
    """
    Insert line breaks into long text for nicer chart labels.
    """
    return "\n".join(textwrap.wrap(str(text), width=width))


def count_answers(series: pd.Series) -> pd.Series:
    """
    Count answers for single-choice or multi-choice responses.

    This assumes multiple answers are separated by semicolons.
    Change the separator if your CSV uses commas, pipes, or newlines.
    """
    cleaned = series.dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned != ""]

    split_answers = cleaned.str.split(";").explode()
    split_answers = split_answers.astype(str).str.strip()
    split_answers = split_answers[split_answers != ""]

    return split_answers.value_counts().sort_values(ascending=False)


def create_bar_chart(
    question: str,
    counts: pd.Series,
    pdf: PdfPages,
    answered_count: int,
    total_count: int,    
    ) -> None:
    """
    Create a horizontal bar chart and save it as one page in the PDF.
    Long questions and answer options are wrapped for consistent formatting.
    """
    wrapped_question = wrap_text(question, width=70)
    response_summary = f"({answered_count}/{total_count} answered)"

    wrapped_labels = [
        wrap_text(label, width=30)
        for label in counts.index
    ]

    fig_height = max(4, 0.6 * len(counts))
    fig, ax = plt.subplots(figsize=(10, fig_height))

    # ax.barh(wrapped_labels, counts.values)
    cmap = plt.get_cmap("tab10")
    colors = [cmap(i % 10) for i in range(len(counts))]
    ax.barh(wrapped_labels, counts.values, color=colors)
    ax.invert_yaxis()

    ax.set_title(
        f"{wrapped_question}\n{response_summary}",
        fontsize=13,
        pad=16,
    )
    ax.set_xlabel("Number of responses")
    ax.set_ylabel("Answer")

    for i, value in enumerate(counts.values):
        ax.text(value, i, f" {value}", va="center")

    # plt.tight_layout()
    fig.subplots_adjust(
        left=0.27,  # fixed label area
        right=0.95,
        top=0.75,
        bottom=0.14,
    )

    pdf.savefig(fig)
    plt.close(fig)


def export_survey_charts_to_pdf(
    csv_path: str,
    output_pdf_path: str,
    question_columns: list[str] | None = None,
) -> None:
    """
    Load survey results from CSV and export all question charts to one PDF.
    """
    df = load_survey_csv(csv_path, poll_details_start_line=10)

    if question_columns is None:
        question_columns = find_question_columns(df)
    print(f"Found question columns: {question_columns}")

    if not question_columns:
        raise ValueError("No survey question columns were found.")

    with PdfPages(output_pdf_path) as pdf:
        total_count = len(df)

        for question in question_columns:
            series = df[question]

            answered_count = (
                series
                .dropna()
                .astype(str)
                .str.strip()
                .ne("")
                .sum()
            )

            counts = count_answers(series)

            if counts.empty:
                continue

            create_bar_chart(
                question=question,
                counts=counts,
                pdf=pdf,
                answered_count=answered_count,
                total_count=total_count,
            )

    print(f"Saved PDF to: {output_pdf_path}")


if __name__ == "__main__":
    csv_file = "private/report_poll.csv"
    output_pdf = "private/report_poll.pdf"

    export_survey_charts_to_pdf(csv_file, output_pdf)