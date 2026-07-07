import csv
import html
import io
import smtplib
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from app import config
from app.db import get_cursor

SA_TZ = ZoneInfo("Africa/Johannesburg")


def today_sa():
    return datetime.now(SA_TZ).date()


def previous_month_report_date(today=None):
    today = today or today_sa()
    return today.replace(day=1) - timedelta(days=1)


def parse_report_date(value):
    if not value:
        return today_sa()

    if isinstance(value, date):
        return value

    return datetime.strptime(value, "%Y-%m-%d").date()


def month_start(value):
    return value.replace(day=1)


def year_start(value):
    return value.replace(month=1, day=1)


def fetch_attendance_rows(report_date=None):
    report_date = parse_report_date(report_date)

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT
                a.member_id,
                a.event_date,
                a.source,
                a.created_at AS checked_in_at,
                m.phone,
                m.first_name,
                m.last_name,
                COALESCE(m.participation_type, 'UNKNOWN') AS participation_type,
                EXISTS (
                    SELECT 1
                    FROM submissions s
                    WHERE s.member_id = a.member_id
                      AND s.activity = 'TT'
                      AND s.status = 'COMPLETE'
                      AND s.event_date = a.event_date
                ) AS submitted_result,
                EXISTS (
                    SELECT 1
                    FROM submissions s
                    WHERE s.member_id = a.member_id
                      AND s.activity = 'TT'
                      AND s.status = 'PENDING'
                      AND s.tt_code_verified = TRUE
                      AND s.event_date = a.event_date
                ) AS pending_result
            FROM attendance a
            JOIN members m ON m.id = a.member_id
            WHERE a.event = 'TT'
              AND a.event_date BETWEEN %s AND %s
            ORDER BY a.event_date ASC, m.first_name ASC, m.last_name ASC
            """,
            (year_start(report_date), report_date),
        )
        return cur.fetchall()


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value


def _full_name(row):
    return f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip() or "Unknown member"


def _period_rows(rows, start_date, end_date):
    return [
        dict(row)
        for row in rows
        if start_date <= _as_date(row["event_date"]) <= end_date
    ]


def _period_metrics(rows, start_date, end_date):
    period_rows = _period_rows(rows, start_date, end_date)
    total_checkins = len(period_rows)
    event_dates = sorted({_as_date(row["event_date"]) for row in period_rows})
    unique_members = {row["member_id"] for row in period_rows}
    submitted = sum(1 for row in period_rows if row.get("submitted_result"))
    pending = sum(1 for row in period_rows if row.get("pending_result"))
    by_type = Counter((row.get("participation_type") or "UNKNOWN").upper() for row in period_rows)

    member_counts = defaultdict(lambda: {"checkins": 0, "last_checkin": None, "name": "", "phone": ""})
    for row in period_rows:
        key = row["member_id"]
        event_date = _as_date(row["event_date"])
        member_counts[key]["checkins"] += 1
        member_counts[key]["last_checkin"] = max(
            member_counts[key]["last_checkin"] or event_date,
            event_date,
        )
        member_counts[key]["name"] = _full_name(row)
        member_counts[key]["phone"] = row.get("phone") or ""

    top_members = sorted(
        member_counts.values(),
        key=lambda item: (-item["checkins"], item["name"]),
    )[:10]

    events = defaultdict(lambda: {"event_date": None, "checkins": 0, "submitted": 0})
    for row in period_rows:
        event_date = _as_date(row["event_date"])
        events[event_date]["event_date"] = event_date
        events[event_date]["checkins"] += 1
        if row.get("submitted_result"):
            events[event_date]["submitted"] += 1

    event_trend = [events[event_date] for event_date in sorted(events)]
    completion_rate = submitted / total_checkins if total_checkins else 0
    avg_attendance = total_checkins / len(event_dates) if event_dates else 0

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_checkins": total_checkins,
        "unique_members": len(unique_members),
        "events": len(event_dates),
        "avg_attendance": avg_attendance,
        "submitted_results": submitted,
        "missing_results": total_checkins - submitted,
        "pending_results": pending,
        "completion_rate": completion_rate,
        "by_type": {
            "RUNNER": by_type.get("RUNNER", 0),
            "WALKER": by_type.get("WALKER", 0),
            "BOTH": by_type.get("BOTH", 0),
            "UNKNOWN": by_type.get("UNKNOWN", 0),
        },
        "top_members": top_members,
        "event_trend": event_trend,
    }


def build_attendance_report(report_date=None, rows=None):
    report_date = parse_report_date(report_date)
    rows = list(fetch_attendance_rows(report_date) if rows is None else rows)

    return {
        "report_date": report_date,
        "mtd_start": month_start(report_date),
        "ytd_start": year_start(report_date),
        "mtd": _period_metrics(rows, month_start(report_date), report_date),
        "ytd": _period_metrics(rows, year_start(report_date), report_date),
        "rows": rows,
    }


def _format_date(value):
    return _as_date(value).strftime("%d %b %Y")


def _format_percent(value):
    return f"{value * 100:.0f}%"


def _format_number(value):
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _metric_table(metrics):
    split = metrics["by_type"]
    return f"""
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
      <tr><td>Total check-ins</td><td align="right"><strong>{metrics['total_checkins']}</strong></td></tr>
      <tr><td>Unique members</td><td align="right"><strong>{metrics['unique_members']}</strong></td></tr>
      <tr><td>TT events</td><td align="right"><strong>{metrics['events']}</strong></td></tr>
      <tr><td>Avg attendance / TT</td><td align="right"><strong>{_format_number(metrics['avg_attendance'])}</strong></td></tr>
      <tr><td>Result completion</td><td align="right"><strong>{_format_percent(metrics['completion_rate'])}</strong></td></tr>
      <tr><td>Missing results</td><td align="right"><strong>{metrics['missing_results']}</strong></td></tr>
      <tr><td>Runner / Walker / Both</td><td align="right"><strong>{split['RUNNER']} / {split['WALKER']} / {split['BOTH']}</strong></td></tr>
    </table>
    """


def _top_members_table(top_members):
    if not top_members:
        return "<p style=\"margin:0;color:#64748b;\">No TT check-ins for this period.</p>"

    rows = []
    for member in top_members:
        rows.append(
            "<tr>"
            f"<td>{html.escape(member['name'])}</td>"
            f"<td align=\"right\">{member['checkins']}</td>"
            f"<td align=\"right\">{_format_date(member['last_checkin'])}</td>"
            "</tr>"
        )
    return (
        "<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;\">"
        "<tr><th align=\"left\">Member</th><th align=\"right\">Check-ins</th><th align=\"right\">Last</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _event_trend_table(event_trend):
    if not event_trend:
        return "<p style=\"margin:0;color:#64748b;\">No TT events for this period.</p>"

    rows = []
    for event in event_trend[-8:]:
        rows.append(
            "<tr>"
            f"<td>{_format_date(event['event_date'])}</td>"
            f"<td align=\"right\">{event['checkins']}</td>"
            f"<td align=\"right\">{event['submitted']}</td>"
            "</tr>"
        )
    return (
        "<table width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;\">"
        "<tr><th align=\"left\">TT date</th><th align=\"right\">Check-ins</th><th align=\"right\">Results</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def build_attendance_report_html(report):
    mtd = report["mtd"]
    ytd = report["ytd"]
    report_date = report["report_date"]

    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#f6f7f9;font-family:Arial,sans-serif;color:#111827;">
    <div style="max-width:860px;margin:0 auto;padding:24px;">
      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:24px;">
        <p style="margin:0 0 6px;color:#64748b;font-size:13px;letter-spacing:.04em;text-transform:uppercase;">Irene Athletics Club</p>
        <h1 style="margin:0;font-size:26px;line-height:1.25;">TT Attendance Dashboard</h1>
        <p style="margin:8px 0 0;color:#475569;">Report date: {_format_date(report_date)}</p>
      </div>

      <div style="display:block;margin-top:16px;">
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin-bottom:16px;">
          <h2 style="margin:0 0 12px;font-size:18px;">Month to date ({_format_date(report['mtd_start'])} - {_format_date(report_date)})</h2>
          {_metric_table(mtd)}
        </div>
        <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin-bottom:16px;">
          <h2 style="margin:0 0 12px;font-size:18px;">Year to date ({_format_date(report['ytd_start'])} - {_format_date(report_date)})</h2>
          {_metric_table(ytd)}
        </div>
      </div>

      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:20px;margin-bottom:16px;">
        <h2 style="margin:0 0 12px;font-size:18px;">YTD top attendees</h2>
        {_top_members_table(ytd['top_members'])}
      </div>

      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:20px;">
        <h2 style="margin:0 0 12px;font-size:18px;">Recent TT attendance trend</h2>
        {_event_trend_table(ytd['event_trend'])}
      </div>

      <p style="color:#64748b;font-size:13px;">The attached CSV contains the member-level YTD attendance export.</p>
    </div>
  </body>
</html>"""


def build_attendance_report_text(report):
    mtd = report["mtd"]
    ytd = report["ytd"]

    return (
        "Irene AC TT Attendance Dashboard\n\n"
        f"Report date: {_format_date(report['report_date'])}\n\n"
        "Month to date\n"
        f"- Check-ins: {mtd['total_checkins']}\n"
        f"- Unique members: {mtd['unique_members']}\n"
        f"- TT events: {mtd['events']}\n"
        f"- Result completion: {_format_percent(mtd['completion_rate'])}\n\n"
        "Year to date\n"
        f"- Check-ins: {ytd['total_checkins']}\n"
        f"- Unique members: {ytd['unique_members']}\n"
        f"- TT events: {ytd['events']}\n"
        f"- Avg attendance / TT: {_format_number(ytd['avg_attendance'])}\n"
        f"- Result completion: {_format_percent(ytd['completion_rate'])}\n\n"
        "The attached CSV contains the member-level YTD attendance export."
    )


def build_attendance_csv(report):
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "event_date",
            "in_month_to_date",
            "member_name",
            "phone",
            "participation_type",
            "submitted_result",
            "pending_result",
            "source",
            "checked_in_at",
        ],
    )
    writer.writeheader()

    for row in report["rows"]:
        event_date = _as_date(row["event_date"])
        checked_in_at = row.get("checked_in_at")
        if isinstance(checked_in_at, datetime):
            checked_in_at = checked_in_at.isoformat()

        writer.writerow(
            {
                "event_date": event_date.isoformat(),
                "in_month_to_date": "yes" if event_date >= report["mtd_start"] else "no",
                "member_name": _full_name(row),
                "phone": row.get("phone") or "",
                "participation_type": row.get("participation_type") or "",
                "submitted_result": "yes" if row.get("submitted_result") else "no",
                "pending_result": "yes" if row.get("pending_result") else "no",
                "source": row.get("source") or "",
                "checked_in_at": checked_in_at or "",
            }
        )

    return output.getvalue()


def build_attendance_email(report, recipients=None):
    recipients = tuple(recipients or config.ATTENDANCE_REPORT_RECIPIENTS)
    if not recipients:
        raise RuntimeError("ATTENDANCE_REPORT_RECIPIENTS is not configured")
    if not config.SMTP_FROM_EMAIL:
        raise RuntimeError("SMTP_FROM_EMAIL or SMTP_USERNAME must be configured")

    report_date = report["report_date"]
    message = EmailMessage()
    message["Subject"] = f"Irene AC TT Attendance Dashboard - {report_date.strftime('%B %Y')}"
    message["From"] = config.SMTP_FROM_EMAIL
    message["To"] = ", ".join(recipients)
    message.set_content(build_attendance_report_text(report))
    message.add_alternative(build_attendance_report_html(report), subtype="html")
    message.add_attachment(
        build_attendance_csv(report).encode("utf-8"),
        maintype="text",
        subtype="csv",
        filename=f"irene-ac-tt-attendance-ytd-{report_date.isoformat()}.csv",
    )
    return message


def _send_email(message):
    if not config.SMTP_HOST:
        raise RuntimeError("SMTP_HOST must be configured before sending attendance reports")

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
        if config.SMTP_USE_TLS:
            smtp.starttls()
        if config.SMTP_USERNAME and config.SMTP_PASSWORD:
            smtp.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        smtp.send_message(message)


def send_monthly_attendance_report(report_date=None, recipients=None):
    report = build_attendance_report(report_date)
    message = build_attendance_email(report, recipients)
    _send_email(message)

    return {
        "report_date": report["report_date"].isoformat(),
        "recipients": len(tuple(recipients or config.ATTENDANCE_REPORT_RECIPIENTS)),
        "mtd_checkins": report["mtd"]["total_checkins"],
        "ytd_checkins": report["ytd"]["total_checkins"],
        "ytd_unique_members": report["ytd"]["unique_members"],
    }
