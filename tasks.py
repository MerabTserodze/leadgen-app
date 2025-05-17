from celery_worker import celery
from app import extract_emails_from_url_async, is_valid_email, send_email
import asyncio

@celery.task
def collect_and_send_emails(user_email, urls, max_emails):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    all_emails = loop.run_until_complete(extract_emails_from_url_async(urls))
    valid = [e for e in all_emails if is_valid_email(e)]
    final_emails = valid[:max_emails]

    result_text = "\n".join(final_emails) if final_emails else "Keine gültigen E-Mails gefunden."
    send_email(user_email, "🎯 Deine LeadGen-Ergebnisse", result_text)
