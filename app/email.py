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

def _get_from_header() -> str:
    if not SMTP_FROM_EMAIL:
        return ""
    if "<" in SMTP_FROM_EMAIL:
        return SMTP_FROM_EMAIL
    return f"Educar és Estimar <{SMTP_FROM_EMAIL}>"


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
    msg["Subject"] = f"Nova sol·licitud de reserva · {client_name} · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = SMTP_FROM_EMAIL
    msg["Bcc"] = ", ".join(admin_emails)

    slot_info = "Pendent de programar"
    if slot_start:
        slot_info = slot_start.strftime("%d/%m/%Y a les %H:%M")

    safe_message = message if message else "-"

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Nova sol·licitud de reserva</title>
      </head>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border: 1px solid #e2e8f0; margin: 0 auto;">
          <tr>
            <td style="padding: 24px 32px; text-align: center; border-bottom: 1px solid #edf2f7; background-color: #ffffff;">
              <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 56px; max-height: 56px; width: auto; display: block; margin: 0 auto 8px;" />
              <h1 style="font-family: Georgia, serif; font-size: 20px; color: #2d3748; margin: 0; font-weight: normal;">Educar és Estimar</h1>
              <p style="font-size: 12px; color: #718096; margin: 2px 0 0 0;">Panell d'Administració</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px;">
              <div style="display: inline-block; background-color: #ebf8ff; color: #2b6cb0; font-weight: bold; font-size: 12px; padding: 4px 12px; border-radius: 16px; margin-bottom: 16px;">
                📩 Nova sol·licitud rebuda
              </div>
              <h2 style="font-family: Georgia, serif; color: #1a202c; font-size: 18px; margin-top: 0; margin-bottom: 12px; font-weight: normal;">S'ha registrat una nova sol·licitud de reserva</h2>
              <p style="font-size: 14px; color: #4a5568; margin-top: 0; margin-bottom: 20px;">
                Revisa els detalls del client i accedeix a l'agenda per validar o gestionar l'assignació:
              </p>
              
              <table style="width: 100%; border-collapse: collapse; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 24px;">
                <tr>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096; width: 140px;"><b>Client</b></td>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c; font-weight: 600;">{client_name}</td>
                </tr>
                <tr>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096;"><b>Email</b></td>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c;"><a href="mailto:{client_email}" style="color: #2b6cb0; text-decoration: none;">{client_email}</a></td>
                </tr>
                <tr>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096;"><b>Telèfon</b></td>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c;"><a href="tel:{client_phone}" style="color: #2b6cb0; text-decoration: none;">{client_phone}</a></td>
                </tr>
                <tr>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096;"><b>Sessió</b></td>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c; font-weight: 600;">{session_title}</td>
                </tr>
                <tr>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096;"><b>Franja sol·licitada</b></td>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c;">{slot_info}</td>
                </tr>
                <tr>
                  <td style="padding: 10px 16px; font-size: 13px; color: #718096; vertical-align: top;"><b>Missatge</b></td>
                  <td style="padding: 10px 16px; font-size: 14px; color: #4a5568; white-space: pre-line;">{safe_message}</td>
                </tr>
              </table>
              
              <div style="text-align: center; margin-top: 24px;">
                <a href="https://educaresestimar.cat/agenda" target="_blank" style="display: inline-block; background-color: #2d3748; color: #ffffff; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 500;">
                  Obrir l'Agenda d'Educar és Estimar
                </a>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding: 20px 32px; background-color: #f8fafc; border-top: 1px solid #edf2f7; text-align: center;">
              <p style="font-size: 12px; color: #a0aec0; margin: 0;">Notificació interna del sistema · Educar és Estimar</p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    msg.set_content(f"S'ha creat una nova sol·licitud de reserva al sistema per part de {client_name} ({client_phone}, {client_email}) per a la sessió {session_title}. Franja: {slot_info}. Missatge: {safe_message}")
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

def send_client_confirmation_email(
    client_name: str,
    client_email: str,
    session_title: str,
    date_str: str,
    start_time: str,
    end_time: str
):
    """
    Envia un correu electrònic al client confirmant la reserva i indicant els detalls de temps.
    """
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("SMTP configuration not fully set. Skipping client email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "Confirmació de Reserva · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = client_email

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Confirmació de Reserva · Educar és Estimar</title>
      </head>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border: 1px solid #e2e8f0; margin: 0 auto;">
          <!-- Header amb Logo -->
          <tr>
            <td style="padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid #edf2f7; background-color: #ffffff;">
              <a href="https://educaresestimar.cat" target="_blank" style="text-decoration: none; display: inline-block;">
                <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 68px; max-height: 68px; width: auto; display: block; margin: 0 auto 12px;" />
                <h1 style="font-family: Georgia, serif; font-size: 22px; color: #2d3748; margin: 0; font-weight: normal; letter-spacing: -0.5px;">Educar és Estimar</h1>
                <p style="font-size: 13px; color: #718096; margin: 4px 0 0 0;">Educació Canina Amable</p>
              </a>
            </td>
          </tr>
          <!-- Cos del missatge -->
          <tr>
            <td style="padding: 32px;">
              <div style="display: inline-block; background-color: #e6f4ea; color: #137333; font-weight: bold; font-size: 12px; padding: 4px 12px; border-radius: 16px; margin-bottom: 16px;">
                ✓ Reserva confirmada
              </div>
              <h2 style="font-family: Georgia, serif; color: #1a202c; font-size: 20px; margin-top: 0; margin-bottom: 16px; font-weight: normal;">Hola {client_name},</h2>
              <p style="font-size: 15px; color: #4a5568; margin-top: 0; margin-bottom: 20px;">
                Des d'<strong>Educar és Estimar</strong> ens complau confirmar-te que la teva reserva ha estat acceptada i programada a l'agenda:
              </p>
              
              <!-- Detalls de la reserva -->
              <table style="width: 100%; border-collapse: collapse; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 24px;">
                <tr>
                  <td style="padding: 12px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096; width: 140px;"><b>Sessió</b></td>
                  <td style="padding: 12px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c; font-weight: 600;">{session_title}</td>
                </tr>
                <tr>
                  <td style="padding: 12px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096;"><b>Data</b></td>
                  <td style="padding: 12px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c;">{date_str}</td>
                </tr>
                <tr>
                  <td style="padding: 12px 16px; font-size: 13px; color: #718096;"><b>Horari</b></td>
                  <td style="padding: 12px 16px; font-size: 14px; color: #137333; font-weight: 600;">{start_time} - {end_time}</td>
                </tr>
              </table>
              
              <p style="font-size: 14px; color: #4a5568; margin-bottom: 12px;">
                T'hi esperem puntualment per gaudir al màxim de la sessió.
              </p>
              <p style="font-size: 14px; color: #4a5568; margin-bottom: 0;">
                Si necessites fer qualsevol consulta o canvi d'horari, no dubtis a respondre directament a aquest correu.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding: 24px 32px; background-color: #f8fafc; border-top: 1px solid #edf2f7; text-align: center;">
              <p style="font-size: 13px; color: #718096; margin: 0 0 6px 0; font-weight: 500;">
                Educar és Estimar
              </p>
              <p style="font-size: 12px; color: #a0aec0; margin: 0;">
                <a href="https://educaresestimar.cat" target="_blank" style="color: #4a5568; text-decoration: underline;">www.educaresestimar.cat</a>
              </p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    msg.set_content(f"Hola {client_name}, des d'Educar és Estimar et confirmem la teva reserva per a la sessió {session_title} el dia {date_str} de {start_time} a {end_time}. T'hi esperem!")
    msg.add_alternative(body_html, subtype='html')

    try:
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
        logger.info(f"Confirmation email sent to client {client_email}.")
    except Exception as e:
        logger.error(f"Failed to send confirmation email to client: {str(e)}")

def send_client_cancellation_email(
    client_name: str,
    client_email: str,
    session_title: str,
    date_str: str | None = None,
    start_time: str | None = None,
):
    """
    Envia un correu electrònic al client notificant que la seva sol·licitud/reserva no ha pogut ser acceptada o ha estat cancel·lada.
    """
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("SMTP configuration not fully set. Skipping client cancellation email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "Estat de la teva sol·licitud de reserva · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = client_email

    time_rows = f"""
      <tr>
        <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #718096; width: 140px;"><b>Sessió</b></td>
        <td style="padding: 10px 16px; border-bottom: 1px solid #edf2f7; font-size: 14px; color: #1a202c; font-weight: 600;">{session_title}</td>
      </tr>
    """
    if date_str and start_time:
        time_rows += f"""
        <tr>
          <td style="padding: 10px 16px; font-size: 13px; color: #718096;"><b>Data i hora sol·licitada</b></td>
          <td style="padding: 10px 16px; font-size: 14px; color: #1a202c;">{date_str} a les {start_time}</td>
        </tr>
        """

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Estat de la teva sol·licitud · Educar és Estimar</title>
      </head>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border: 1px solid #e2e8f0; margin: 0 auto;">
          <!-- Header amb Logo -->
          <tr>
            <td style="padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid #edf2f7; background-color: #ffffff;">
              <a href="https://educaresestimar.cat" target="_blank" style="text-decoration: none; display: inline-block;">
                <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 68px; max-height: 68px; width: auto; display: block; margin: 0 auto 12px;" />
                <h1 style="font-family: Georgia, serif; font-size: 22px; color: #2d3748; margin: 0; font-weight: normal; letter-spacing: -0.5px;">Educar és Estimar</h1>
                <p style="font-size: 13px; color: #718096; margin: 4px 0 0 0;">Educació Canina Amable</p>
              </a>
            </td>
          </tr>
          <!-- Cos del missatge -->
          <tr>
            <td style="padding: 32px;">
              <h2 style="font-family: Georgia, serif; color: #1a202c; font-size: 20px; margin-top: 0; margin-bottom: 16px; font-weight: normal;">Hola {client_name},</h2>
              <p style="font-size: 15px; color: #4a5568; margin-top: 0; margin-bottom: 20px;">
                Des d'<strong>Educar és Estimar</strong> t'informem que, per motius de disponibilitat d'agenda, no ha estat possible confirmar la teva sol·licitud per a la classe sol·licitada:
              </p>
              
              <table style="width: 100%; border-collapse: collapse; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 24px;">
                {time_rows}
              </table>
              
              <p style="font-size: 14px; color: #4a5568; margin-bottom: 16px;">
                Pots accedir de nou al nostre calendari a <a href="https://educaresestimar.cat/reserva" target="_blank" style="color: #2b6cb0; text-decoration: underline;">educaresestimar.cat/reserva</a> per seleccionar una altra data o franja horària que et vagi bé.
              </p>
              
              <p style="font-size: 14px; color: #4a5568; margin-bottom: 0;">
                Disculpa les molèsties i moltes gràcies pel teu interès i confiança!
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding: 24px 32px; background-color: #f8fafc; border-top: 1px solid #edf2f7; text-align: center;">
              <p style="font-size: 13px; color: #718096; margin: 0 0 6px 0; font-weight: 500;">
                Educar és Estimar
              </p>
              <p style="font-size: 12px; color: #a0aec0; margin: 0;">
                <a href="https://educaresestimar.cat" target="_blank" style="color: #4a5568; text-decoration: underline;">www.educaresestimar.cat</a>
              </p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    msg.set_content(f"Hola {client_name}, des d'Educar és Estimar t'informem que per motius d'agenda no ha estat possible acceptar la teva sol·licitud per a la sessió {session_title}. Pots tornar a consultar el nostre calendari a https://educaresestimar.cat/reserva per escollir una altra franja disponible.")
    msg.add_alternative(body_html, subtype='html')

    try:
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
        logger.info(f"Cancellation email sent to client {client_email}.")
    except Exception as e:
        logger.error(f"Failed to send cancellation email to client: {str(e)}")


def send_daily_agenda_email(
    date_formatted: str,
    confirmed_items: list[dict],
    pending_items: list[dict],
    blocked_items: list[dict],
    admin_emails: list[str],
):
    """
    Envia un correu matinal (08:00h) amb el resum de l'agenda del dia a l'educador i als administradors (en CCO).
    """
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("SMTP configuration not fully set. Skipping daily agenda email.")
        return

    if not admin_emails:
        logger.info("No admin emails to notify for daily agenda.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"📅 Agenda del dia ({date_formatted}) · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = SMTP_FROM_EMAIL
    msg["Bcc"] = ", ".join(admin_emails)

    # Construir secció de sessions confirmades
    if confirmed_items:
        rows_html = ""
        for item in confirmed_items:
            badge_html = (
                f'<span style="display:inline-block;background:#f3e8ff;color:#6b21a8;font-size:11px;padding:2px 8px;border-radius:10px;font-weight:600;margin-left:6px;">👥 Grup</span>'
                if item.get("is_shared")
                else ""
            )
            notes_html = (
                f'<div style="font-size:12px;color:#718096;margin-top:4px;font-style:italic;">💬 "{item["message"]}"</div>'
                if item.get("message")
                else ""
            )
            rows_html += f"""
            <tr>
              <td style="padding: 12px 14px; border-bottom: 1px solid #edf2f7; font-size: 13px; font-weight: 700; color: #137333; white-space: nowrap; vertical-align: top; width: 110px;">
                {item["time_range"]}
              </td>
              <td style="padding: 12px 14px; border-bottom: 1px solid #edf2f7; font-size: 13px; color: #1a202c; vertical-align: top;">
                <div style="font-weight: 600;">{item["client_name"]} <span style="font-weight:normal;color:#4a5568;">({item["client_phone"]})</span></div>
                <div style="font-size: 12px; color: #4a5568; margin-top: 2px;">{item["session_title"]}{badge_html}</div>
                {notes_html}
              </td>
            </tr>
            """
        confirmed_section_html = f"""
        <h3 style="font-size: 15px; color: #1a202c; margin: 20px 0 10px; font-weight: 600;">
          ✅ Sessions confirmades per avui ({len(confirmed_items)})
        </h3>
        <table style="width: 100%; border-collapse: collapse; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 20px;">
          {rows_html}
        </table>
        """
    else:
        confirmed_section_html = """
        <div style="padding: 16px; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 20px; text-align: center; color: #718096; font-size: 14px;">
          Avui no hi ha cap sessió confirmada programada a l'agenda.
        </div>
        """

    # Construir secció de bloquejos personals
    blocked_section_html = ""
    if blocked_items:
        b_rows = ""
        for b in blocked_items:
            b_rows += f"""
            <tr>
              <td style="padding: 10px 14px; border-bottom: 1px solid #fed7d7; font-size: 13px; font-weight: 700; color: #c53030; white-space: nowrap; width: 110px;">
                {b["time_range"]}
              </td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #fed7d7; font-size: 13px; color: #742a2a;">
                🔒 {b["reason"]}
              </td>
            </tr>
            """
        blocked_section_html = f"""
        <h3 style="font-size: 15px; color: #9b2c2c; margin: 20px 0 10px; font-weight: 600;">
          🔒 Franges bloquejades avui ({len(blocked_items)})
        </h3>
        <table style="width: 100%; border-collapse: collapse; background-color: #fff5f5; border-radius: 8px; border: 1px solid #feb2b2; margin-bottom: 20px;">
          {b_rows}
        </table>
        """

    # Construir secció de sol·licituds pendents
    pending_section_html = ""
    if pending_items:
        p_rows = ""
        for p in pending_items:
            p_rows += f"""
            <tr>
              <td style="padding: 10px 14px; border-bottom: 1px solid #feebc8; font-size: 12px; font-weight: 600; color: #b7791f;">
                {p["client_name"]} ({p["client_phone"]}) · {p["session_title"]}
              </td>
              <td style="padding: 10px 14px; border-bottom: 1px solid #feebc8; font-size: 12px; color: #744210; text-align: right;">
                {p["slot_info"]}
              </td>
            </tr>
            """
        pending_section_html = f"""
        <h3 style="font-size: 15px; color: #b7791f; margin: 20px 0 10px; font-weight: 600;">
          ⏳ Sol·licituds pendents de validar ({len(pending_items)})
        </h3>
        <table style="width: 100%; border-collapse: collapse; background-color: #fffff0; border-radius: 8px; border: 1px solid #fbd38d; margin-bottom: 20px;">
          {p_rows}
        </table>
        """

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Agenda del dia · Educar és Estimar</title>
      </head>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); border: 1px solid #e2e8f0; margin: 0 auto;">
          <tr>
            <td style="padding: 28px 32px 20px; text-align: center; border-bottom: 1px solid #edf2f7; background-color: #ffffff;">
              <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 60px; max-height: 60px; width: auto; display: block; margin: 0 auto 10px;" />
              <h1 style="font-family: Georgia, serif; font-size: 21px; color: #2d3748; margin: 0; font-weight: normal;">Educar és Estimar</h1>
              <p style="font-size: 12px; color: #718096; margin: 4px 0 0 0;">Resum diari d'Agenda · {date_formatted}</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px 32px;">
              <h2 style="font-family: Georgia, serif; color: #1a202c; font-size: 19px; margin-top: 0; margin-bottom: 8px; font-weight: normal;">Bon dia! 🐾</h2>
              <p style="font-size: 14px; color: #4a5568; margin-top: 0; margin-bottom: 20px;">
                Aquí tens la planificació de l'agenda d'avui (<strong>{date_formatted}</strong>):
              </p>

              {confirmed_section_html}
              {blocked_section_html}
              {pending_section_html}

              <div style="text-align: center; margin-top: 28px;">
                <a href="https://educaresestimar.cat/agenda" target="_blank" style="display: inline-block; background-color: #2d3748; color: #ffffff; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 500;">
                  Obrir l'Agenda Completa
                </a>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding: 20px 32px; background-color: #f8fafc; border-top: 1px solid #edf2f7; text-align: center;">
              <p style="font-size: 12px; color: #a0aec0; margin: 0;">Enviament automàtic diari (08:00h) · Educar és Estimar</p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """

    msg.set_content(
        f"Bon dia! Agenda del dia {date_formatted} a Educar és Estimar: "
        f"{len(confirmed_items)} sessions confirmades, {len(blocked_items)} bloquejos i {len(pending_items)} sol·licituds pendents."
    )
    msg.add_alternative(body_html, subtype="html")

    try:
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
        logger.info(f"Daily agenda email sent to {len(admin_emails)} admins for {date_formatted}.")
    except Exception as e:
        logger.error(f"Failed to send daily agenda email: {str(e)}")


def _deliver_smtp_message(msg: EmailMessage, log_label: str) -> None:
    try:
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
        logger.info("Email sent (%s).", log_label)
    except Exception as e:
        logger.error("Failed to send email (%s): %s", log_label, str(e))


def send_password_reset_email(client_name: str, client_email: str, reset_url: str) -> None:
    """Envia l'enllaç per restablir la contrasenya al client registrat."""
    if not SMTP_HOST or not SMTP_FROM_EMAIL:
        logger.warning("SMTP configuration not fully set. Skipping password reset email.")
        return

    msg = EmailMessage()
    msg["Subject"] = "Restablir contrasenya · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = client_email

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Restablir contrasenya · Educar és Estimar</title>
      </head>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; margin: 0 auto;">
          <tr>
            <td style="padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid #edf2f7;">
              <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 64px; width: auto; display: block; margin: 0 auto 12px;" />
              <h1 style="font-family: Georgia, serif; font-size: 22px; color: #2d3748; margin: 0; font-weight: normal;">Educar és Estimar</h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px;">
              <h2 style="font-family: Georgia, serif; color: #1a202c; font-size: 20px; margin-top: 0; margin-bottom: 12px; font-weight: normal;">Hola {client_name},</h2>
              <p style="font-size: 14px; color: #4a5568;">Hem rebut una sol·licitud per restablir la contrasenya del teu compte a <strong>Educar és Estimar</strong>.</p>
              <div style="text-align: center; margin: 28px 0;">
                <a href="{reset_url}" target="_blank" style="display: inline-block; background-color: #2d3748; color: #ffffff; padding: 12px 28px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600;">
                  Crear nova contrasenya
                </a>
              </div>
              <p style="font-size: 12px; color: #718096; margin-bottom: 0;">Aquest enllaç caduca en 30 minuts. Si no has demanat aquest canvi, pots ignorar aquest correu amb total tranquil·litat.</p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    msg.set_content(f"Hola {client_name}, pots crear una nova contrasenya per al teu compte d'Educar és Estimar aquí: {reset_url}")
    msg.add_alternative(body_html, subtype="html")
    _deliver_smtp_message(msg, f"password_reset:{client_email}")


def send_client_self_cancellation_notification(
    client_name: str,
    client_email: str | None,
    client_phone: str,
    session_title: str,
    date_str: str,
    start_time: str,
    admin_emails: list[str],
) -> None:
    """Notifica a l'educador/admins que un client ha cancel·lat una sessió des de la seva àrea privada."""
    if not SMTP_HOST or not SMTP_FROM_EMAIL or not admin_emails:
        return

    msg = EmailMessage()
    msg["Subject"] = f"⚠️ Reserva cancel·lada pel client · {client_name} · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = SMTP_FROM_EMAIL
    msg["Bcc"] = ", ".join(admin_emails)

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; margin: 0 auto;">
          <tr>
            <td style="padding: 24px 32px; text-align: center; border-bottom: 1px solid #edf2f7;">
              <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 56px; width: auto; display: block; margin: 0 auto 8px;" />
              <h1 style="font-family: Georgia, serif; font-size: 20px; color: #2d3748; margin: 0; font-weight: normal;">Educar és Estimar</h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px 32px;">
              <div style="display: inline-block; background-color: #fff5f5; color: #c53030; font-weight: bold; font-size: 12px; padding: 4px 12px; border-radius: 16px; margin-bottom: 14px;">
                Cancel·lació amb +48h d'antelació
              </div>
              <p style="font-size: 14px; color: #4a5568; margin-top: 0;">El client <strong>{client_name}</strong> ({client_phone}{f' · {client_email}' if client_email else ''}) ha cancel·lat la següent sessió des de l'àrea de client, i la franja ha quedat novament alliberada:</p>
              <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 16px; font-size: 14px;">
                <div><strong>Sessió:</strong> {session_title}</div>
                <div><strong>Data i hora:</strong> {date_str} a les {start_time}</div>
              </div>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    msg.set_content(f"El client {client_name} ({client_phone}) ha cancel·lat la reserva de {session_title} del dia {date_str} a les {start_time}.")
    msg.add_alternative(body_html, subtype="html")
    _deliver_smtp_message(msg, f"self_cancel:{client_name}")


def send_series_admin_notification(
    client_name: str,
    client_email: str | None,
    client_phone: str,
    message: str | None,
    session_title: str,
    dates_list: list[str],
    admin_emails: list[str],
) -> None:
    """Envia un sol correu resum a l'educador quan un client sol·licita una sèrie periòdica."""
    if not SMTP_HOST or not SMTP_FROM_EMAIL or not admin_emails:
        return

    msg = EmailMessage()
    msg["Subject"] = f"🔁 Nova sèrie periòdica ({len(dates_list)} sessions) · {client_name} · Educar és Estimar"
    msg["From"] = _get_from_header()
    msg["To"] = SMTP_FROM_EMAIL
    msg["Bcc"] = ", ".join(admin_emails)

    items_html = "".join(f"<li style='margin: 4px 0;'>{d}</li>" for d in dates_list)
    safe_message = message if message else "-"

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; margin: 0 auto;">
          <tr>
            <td style="padding: 24px 32px; text-align: center; border-bottom: 1px solid #edf2f7;">
              <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 56px; width: auto; display: block; margin: 0 auto 8px;" />
              <h1 style="font-family: Georgia, serif; font-size: 20px; color: #2d3748; margin: 0; font-weight: normal;">Educar és Estimar</h1>
            </td>
          </tr>
          <tr>
            <td style="padding: 28px 32px;">
              <h2 style="font-family: Georgia, serif; font-size: 18px; margin-top: 0;">Nova sol·licitud de sèrie periòdica ({len(dates_list)} sessions)</h2>
              <p style="font-size: 14px; color: #4a5568;"><strong>Client:</strong> {client_name} ({client_phone}{f' · {client_email}' if client_email else ''})<br/><strong>Sessió:</strong> {session_title}<br/><strong>Missatge:</strong> {safe_message}</p>
              <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 20px; font-size: 13px;">
                <strong>Dates sol·licitades:</strong>
                <ul style="margin: 8px 0 0; padding-left: 18px;">{items_html}</ul>
              </div>
              <div style="text-align: center; margin-top: 24px;">
                <a href="https://educaresestimar.cat/agenda" target="_blank" style="display: inline-block; background-color: #2d3748; color: #ffffff; padding: 10px 24px; border-radius: 8px; text-decoration: none; font-size: 14px;">Obrir l'Agenda per validar la sèrie</a>
              </div>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    msg.set_content(f"Nova sèrie periòdica de {client_name} ({len(dates_list)} sessions de {session_title}): " + ", ".join(dates_list))
    msg.add_alternative(body_html, subtype="html")
    _deliver_smtp_message(msg, f"series_admin:{client_name}")


def send_series_client_status_email(
    client_name: str,
    client_email: str,
    session_title: str,
    dates_list: list[str],
    approved: bool,
) -> None:
    """Envia un sol correu resum al client quan l'educador aprova o rebutja una sèrie periòdica."""
    if not SMTP_HOST or not SMTP_FROM_EMAIL or not client_email:
        return

    msg = EmailMessage()
    msg["From"] = _get_from_header()
    msg["To"] = client_email

    items_html = "".join(f"<li style='margin: 5px 0;'>{d}</li>" for d in dates_list)

    if approved:
        msg["Subject"] = f"Confirmació de Sèrie de Reserves ({len(dates_list)} sessions) · Educar és Estimar"
        badge = '<div style="display:inline-block;background-color:#e6f4ea;color:#137333;font-weight:bold;font-size:12px;padding:4px 12px;border-radius:16px;margin-bottom:16px;">✓ Sèrie confirmada</div>'
        intro = f"Des d'<strong>Educar és Estimar</strong> ens complau confirmar-te les <strong>{len(dates_list)} sessions</strong> de <strong>{session_title}</strong>:"
        outro = "Pots consultar o gestionar les teves sessions en qualsevol moment des de la teva àrea de client a www.educaresestimar.cat."
    else:
        msg["Subject"] = "Estat de la teva sol·licitud de sèrie periòdica · Educar és Estimar"
        badge = ""
        intro = f"Des d'<strong>Educar és Estimar</strong> t'informem que, per motius de disponibilitat d'agenda, no ha estat possible confirmar la sèrie sol·licitada de <strong>{session_title}</strong>:"
        outro = "Pots accedir de nou a www.educaresestimar.cat/reserva per escollir un altre horari o posar-te en contacte amb nosaltres."

    body_html = f"""
    <!DOCTYPE html>
    <html lang="ca">
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #2d3748; background-color: #f7fafc; margin: 0; padding: 24px;">
        <table align="center" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 580px; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; margin: 0 auto;">
          <tr>
            <td style="padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid #edf2f7;">
              <img src="https://educaresestimar.cat/logo.png" alt="Educar és Estimar" style="height: 68px; width: auto; display: block; margin: 0 auto 12px;" />
              <h1 style="font-family: Georgia, serif; font-size: 22px; color: #2d3748; margin: 0; font-weight: normal;">Educar és Estimar</h1>
              <p style="font-size: 13px; color: #718096; margin: 4px 0 0 0;">Educació Canina Amable</p>
            </td>
          </tr>
          <tr>
            <td style="padding: 32px;">
              {badge}
              <h2 style="font-family: Georgia, serif; color: #1a202c; font-size: 20px; margin-top: 0;">Hola {client_name},</h2>
              <p style="font-size: 15px; color: #4a5568;">{intro}</p>
              <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 20px; font-size: 14px; margin-bottom: 20px;">
                <ul style="margin: 0; padding-left: 18px;">{items_html}</ul>
              </div>
              <p style="font-size: 14px; color: #4a5568; margin-bottom: 0;">{outro}</p>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """
    msg.set_content(f"Hola {client_name}, estat de la sèrie ({session_title}): " + ", ".join(dates_list))
    msg.add_alternative(body_html, subtype="html")
    _deliver_smtp_message(msg, f"series_client:{client_email}:{'approved' if approved else 'rejected'}")



