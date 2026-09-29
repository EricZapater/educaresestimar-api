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

