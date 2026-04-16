import logging
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = os.getenv("SMTP_PORT", "587")
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")

def send_reservation_notification(
    client_name: str,
    client_email: str,
    client_phone: str,
    message: str | None,
    session_title: str,
    slot_start: datetime | None,
    admin_emails: list[str]
):
    """
    Envia un correu electrònic sincrònicament als administradors 
    sobre una nova reserva. Aquesta funció ha de ser executada amb BackgroundTasks.
    """
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("SMTP configuration not fully set. Skipping email notification.")
        return

    if not admin_emails:
        logger.info("No admin emails to notify.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"Nova Reserva de {client_name}"
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = SMTP_FROM_EMAIL
    msg["Bcc"] = ", ".join(admin_emails)

    slot_info = "Pendent de programar"
    if slot_start:
        slot_info = slot_start.strftime("%d/%m/%Y a les %H:%M")

    safe_message = message if message else "-"

    body_html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #2c3e50;">Nova Reserva Rebuda</h2>
        <p>S'ha creat una nova reserva al sistema. A continuació en tens els detalls:</p>
        
        <table style="width: 100%; max-width: 600px; border-collapse: collapse; margin-top: 20px;">
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; width: 150px; background-color: #f9f9f9;">Client</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{client_name}</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; background-color: #f9f9f9;">Email</td>
            <td style="padding: 8px; border: 1px solid #ddd;"><a href="mailto:{client_email}">{client_email}</a></td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; background-color: #f9f9f9;">Telèfon</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{client_phone}</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; background-color: #f9f9f9;">Sessió sol·licitada</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{session_title}</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; background-color: #f9f9f9;">Franja horària</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{slot_info}</td>
          </tr>
          <tr>
            <td style="padding: 8px; border: 1px solid #ddd; font-weight: bold; background-color: #f9f9f9;">Missatge</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{safe_message}</td>
          </tr>
        </table>
        
        <p style="margin-top: 30px; font-size: 0.9em; color: #7f8c8d;">Aquest és un missatge automàtic de l'API de reserves.</p>
      </body>
    </html>
    """

    msg.set_content(f"S'ha creat una nova reserva al sistema del client {client_name}. Revisa l'administració per més detalls.")
    msg.add_alternative(body_html, subtype='html')

    try:
        # TLS vs SSL depending on port
        port = int(SMTP_PORT)
        if port == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, port) as server:
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, port) as server:
                server.starttls()
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        logger.info(f"Notification email sent to {len(admin_emails)} admins.")
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
