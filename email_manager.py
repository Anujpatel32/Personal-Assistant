# -*- coding: utf-8 -*-
"""
email_manager.py — Email Dispatch & Drafting for MEOW (Phase 7)
================================================================
Sends emails via standard SMTP (Gmail, Outlook, custom SMTP)
or drafts emails to disk/clipboard when SMTP is unconfigured.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional

logger = logging.getLogger("meow.core")


def send_email(to_address: str, subject: str, body: str) -> Dict[str, Any]:
    """Send an email using SMTP credentials from environment or settings."""
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_EMAIL", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_pass:
        # SMTP not configured — fall back to creating a draft
        return draft_email(to_address, subject, body, reason="SMTP credentials not configured in environment")

    try:
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_address], msg.as_string())

        logger.info("Sent email to %s with subject: %s", to_address, subject)
        return {"success": True, "message": f"Email successfully sent to {to_address}."}
    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_address, e)
        # On error, also save draft so user doesn't lose work
        draft_email(to_address, subject, body, reason=f"SMTP error: {e}")
        return {"success": False, "error": str(e), "message": f"Email sending failed ({e}), but draft was saved."}


def draft_email(to_address: str, subject: str, body: str, reason: str = "") -> Dict[str, Any]:
    """Create an email draft, copy to clipboard, and save as draft file."""
    draft_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "drafts")
    os.makedirs(draft_dir, exist_ok=True)

    filename = f"draft_{subject[:20].replace(' ', '_')}.txt"
    filepath = os.path.join(draft_dir, filename)

    draft_text = f"To: {to_address}\nSubject: {subject}\n\n{body}"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(draft_text)

    try:
        import pyperclip
        pyperclip.copy(draft_text)
        copied = True
    except Exception:
        copied = False

    msg = f"Draft saved to {filepath}."
    if copied:
        msg += " Email draft also copied to your clipboard!"
    if reason:
        msg += f" Note: {reason}"

    return {"success": True, "filepath": filepath, "copied": copied, "message": msg}


# ── Register Tools ────────────────────────────────────────────────────
try:
    import tool_registry

    @tool_registry.register_tool(
        "send_email",
        "Send an email to a recipient with subject and body text (uses SMTP or saves draft)",
        ["to_address", "subject", "body"]
    )
    def _tool_send_email(to_address: str, subject: str, body: str):
        res = send_email(to_address, subject, body)
        return res.get("message", "Done")

    @tool_registry.register_tool(
        "draft_email",
        "Draft an email without sending: copies content to clipboard and saves locally",
        ["to_address", "subject", "body"]
    )
    def _tool_draft_email(to_address: str, subject: str, body: str):
        res = draft_email(to_address, subject, body)
        return res.get("message", "Draft saved.")

except Exception as _tr_err:
    logger.warning("Could not register email tools: %s", _tr_err)

