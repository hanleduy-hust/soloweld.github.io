"""
Send a SoloWeld AI news draft for review using Gmail SMTP.
Uses the same resilient SMTP strategy as the personal blog: SSL/465, then STARTTLS/587.
"""
import html
import json
import os
import re
import smtplib
import ssl
import sys
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

DRAFT_DIR = Path(os.environ.get("DRAFT_DIR", ".draft"))
SITE = "https://hanleduy-hust.github.io/soloweld.github.io"


def esc(value):
    return html.escape(str(value or ""))


def render_refs(refs):
    items = []
    for ref in refs:
        authors = ", ".join(ref.get("authors", []))
        if ref.get("more_authors"):
            authors += " et al."
        doi_link = ref.get("url") or ("https://doi.org/" + ref["doi"] if ref.get("doi") else "")
        doi = f'<a href="{esc(doi_link)}">doi:{esc(ref.get("doi", ""))}</a>' if doi_link else ""
        license_name = f" · {esc(ref['license']).upper()}" if ref.get("license") else ""
        items.append(
            f'<li style="margin-bottom:8px">{esc(authors)} ({esc(str(ref.get("date", ""))[:4])}). '
            f'{esc(ref.get("title"))}. <em>{esc(ref.get("journal"))}</em>. {doi}{license_name}</li>'
        )
    return '<ol style="font-size:13px;color:#475569;padding-left:20px">' + "".join(items) + "</ol>"


def email_body(content):
    content = re.sub(
        r'src="images/news/[^"]+/fig(\d+)\.jpg"',
        r'src="cid:fig\1" style="max-width:100%;height:auto;border-radius:8px"',
        content or "",
    )
    content = content.replace('<figure class="post-figure', '<div style="margin:20px 0;text-align:center" data-figure="')
    content = content.replace("</figure>", "</div>")
    content = re.sub(r'<figcaption[^>]*>', '<div style="font-size:13px;color:#64748b;text-align:left;margin-top:6px">', content)
    content = content.replace("</figcaption>", "</div>")
    content = content.replace('<p class="lead">', '<p style="font-size:16px;color:#0f172a;font-weight:500">')
    content = content.replace("<h3>", '<h3 style="color:#1d4ed8;margin-top:24px">')
    return content


def main():
    user = os.environ.get("MAIL_USERNAME", "").strip().strip('"\'')
    password = re.sub(r"[\s\u00a0\u200b\"']", "", os.environ.get("MAIL_APP_PASSWORD", ""))
    recipients = [addr.strip() for addr in (os.environ.get("MAIL_TO") or user).split(",") if addr.strip()]
    pr_url = os.environ.get("PR_URL", "").strip()
    if not user or not password:
        sys.exit("Missing MAIL_USERNAME or MAIL_APP_PASSWORD Actions secret.")
    if not recipients:
        sys.exit("Missing MAIL_TO Actions secret and sender address.")
    if "@" not in user:
        sys.exit(f"MAIL_USERNAME must be a full Gmail address (received {len(user)} characters, no @).")
    if not re.fullmatch(r"[a-zA-Z]{16}", password):
        print(f"Warning: Gmail App Password normally has 16 letters; received {len(password)} characters.")

    post = json.loads((DRAFT_DIR / "post.json").read_text(encoding="utf-8"))
    title = post["title_vi"]
    title_en = post.get("title_en", "")
    summary = post.get("summary_vi", "")
    paper_count = post.get("paper_count", len(post.get("references", [])))
    figure_count = post.get("figure_count", 0)
    button_style = "display:inline-block;padding:12px 22px;border-radius:10px;font-weight:600;text-decoration:none;font-size:14px;margin:4px 6px 4px 0;"
    refs = render_refs(post.get("references", []))
    body = f"""<!doctype html><html><body style="margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#334155">
<div style="max-width:760px;margin:0 auto;background:#fff;padding:28px">
<p style="font-size:13px;color:#64748b;margin:0">📝 DRAFT FOR REVIEW · SoloWeld News · {esc(post.get('date'))}</p>
<h1 style="font-size:22px;color:#0f172a;margin:8px 0">{esc(title)}</h1>
<p style="font-size:14px;color:#64748b"><em>{esc(title_en)}</em></p>
<p style="font-size:14px">{esc(summary)}</p>
<p style="font-size:13px;color:#64748b">{paper_count} research papers · {figure_count} figures</p>
<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:12px;padding:16px;margin:16px 0">
<p style="margin:0 0 10px;font-size:14px"><strong>Review and publish:</strong> open the pull request below.</p>
<a href="{esc(pr_url)}" style="{button_style}background:#15803d;color:#fff">✅ Review and merge</a>
<a href="{esc(pr_url)}" style="{button_style}background:#e2e8f0;color:#334155">Close pull request to discard</a>
<p style="font-size:12px;color:#64748b">After merging, the article will appear on the SoloWeld News &amp; Insights page after GitHub Pages deploys.</p>
</div>
<hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
<h2 style="font-size:18px;color:#0f172a">🇻🇳 Bản tiếng Việt</h2>
<div style="font-size:15px;line-height:1.65">{email_body(post.get('content_vi', ''))}</div>
<h3>Tài liệu tham khảo</h3>{refs}
<hr style="border:none;border-top:1px solid #e2e8f0;margin:24px 0">
<h2 style="font-size:18px;color:#0f172a">🇬🇧 English version</h2>
<h3>{esc(title_en)}</h3>
<div style="font-size:15px;line-height:1.65">{email_body(post.get('content_en', ''))}</div>
<h3>References</h3>{refs}
<p style="font-size:12px;color:#94a3b8;margin-top:32px">Automated review email from {SITE}. AI-generated draft; please review before publication.</p>
</div></body></html>"""

    msg = MIMEMultipart("related")
    msg["Subject"] = f"[SoloWeld – Duyệt bản tin] {title}"
    msg["From"] = f"SoloWeld News <{user}>"
    msg["To"] = ", ".join(recipients)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(f"{title}\n\n{summary}\n\nDuyệt bài tại: {pr_url}\n", "plain", "utf-8"))
    alt.attach(MIMEText(body, "html", "utf-8"))
    msg.attach(alt)

    expected = sorted(set(re.findall(r'src="(images/news/[^"]+/fig\d+\.jpg)"', post.get("content_vi", "") + post.get("content_en", ""))))
    resolved = []
    for relative in expected:
        image_path = DRAFT_DIR / relative
        if not image_path.is_file():
            sys.exit(f"Missing image for review email: {relative}; email was not sent.")
        resolved.append(image_path)
    for image_path in resolved:
        part = MIMEImage(image_path.read_bytes(), _subtype="jpeg")
        part.add_header("Content-ID", f"<{image_path.stem}>")
        part.add_header("Content-Disposition", "inline", filename=image_path.name)
        msg.attach(part)

    errors = []
    for port in (465, 587):
        try:
            if port == 465:
                smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60)
            else:
                smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=60)
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            with smtp:
                smtp.login(user, password)
                smtp.sendmail(user, recipients, msg.as_string())
            print(f"SoloWeld review email sent to {', '.join(recipients)} via port {port}.")
            return
        except smtplib.SMTPAuthenticationError as exc:
            detail = exc.smtp_error.decode(errors="replace") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
            errors.append(f"port {port}: Gmail rejected authentication ({exc.smtp_code}): {detail[:200]}")
            break
        except Exception as exc:
            errors.append(f"port {port}: {type(exc).__name__}: {exc}")
    print("\n".join(errors))
    sys.exit("Could not send review email. Check that MAIL_USERNAME is the full Gmail address and MAIL_APP_PASSWORD is the 16-letter Google App Password. Draft PR: " + pr_url)


if __name__ == "__main__":
    main()
