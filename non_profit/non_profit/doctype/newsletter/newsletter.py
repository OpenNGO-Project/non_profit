import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


class Newsletter(Document):
    def validate(self):
        self.validate_email_group()
        self.update_recipient_count()

        if self.email_template and not self.content and not self.html_content:
            self.load_from_template()

    def validate_email_group(self):
        if not frappe.db.exists("Email Group", self.email_group):
            frappe.throw(_("Email Group {0} does not exist").format(self.email_group))

    def update_recipient_count(self):
        self.total_recipients = frappe.db.count(
            "Email Group Member",
            filters={"email_group": self.email_group, "unsubscribed": 0},
        )

    def load_from_template(self):
        template = frappe.get_doc("Email Template", self.email_template)
        self.subject = template.subject
        if template.use_html:
            self.use_html = 1
            self.html_content = template.response_html or template.response_
        else:
            self.use_html = 0
            self.content = template.response_

    def onload(self):
        self.load_email_accounts()

    def load_email_accounts(self):
        email_accounts = frappe.get_all(
            "Email Account",
            filters={"enable_outgoing": 1},
            fields=["name", "email_id"],
        )
        self.set_onload("email_accounts", [acc.email_id for acc in email_accounts])

    @frappe.whitelist()
    def send_now(self):
        if self.status not in ["Draft", "Failed"]:
            frappe.throw(_("Newsletter can only be sent from Draft or Failed status"))

        if self.total_recipients == 0:
            frappe.throw(_("No recipients found in the Email Group"))

        self.db_set("status", "Queued")
        frappe.enqueue(
            send_newsletter_emails,
            newsletter_name=self.name,
            queue="long",
            timeout=3600,
        )
        frappe.msgprint(_("Newsletter queued for sending"))

    @frappe.whitelist()
    def schedule(self):
        if not self.send_after:
            frappe.throw(_("Please set the Send After date and time"))

        if get_datetime(self.send_after) < now_datetime():
            frappe.throw(_("Send After time must be in the future"))

        self.db_set("status", "Queued")
        frappe.msgprint(_("Newsletter scheduled for {0}").format(self.send_after))


def send_newsletter_emails(newsletter_name):
    newsletter = frappe.get_doc("Newsletter", newsletter_name)
    newsletter.db_set("status", "Sending")

    recipients = frappe.get_all(
        "Email Group Member",
        filters={"email_group": newsletter.email_group, "unsubscribed": 0},
        fields=["email", "first_name", "last_name"],
    )

    sent_count = 0
    failed_count = 0

    for recipient in recipients:
        try:
            send_single_email(newsletter, recipient)
            sent_count += 1
        except Exception:
            failed_count += 1
            frappe.log_error(
                f"Failed to send newsletter {newsletter_name} to {recipient.email}",
                "Newsletter Send Error",
            )

        if sent_count % 10 == 0:
            newsletter.db_set("sent_count", sent_count)
            newsletter.db_set("failed_count", failed_count)

    newsletter.db_set("sent_count", sent_count)
    newsletter.db_set("failed_count", failed_count)

    if failed_count == 0:
        newsletter.db_set("status", "Sent")
    elif sent_count == 0:
        newsletter.db_set("status", "Failed")
    else:
        newsletter.db_set("status", "Partially Sent")


def send_single_email(newsletter, recipient):
    context = {
        "email": recipient.email,
        "first_name": recipient.first_name or "",
        "last_name": recipient.last_name or "",
        "full_name": f"{recipient.first_name or ''} {recipient.last_name or ''}".strip(),
        "email_group": newsletter.email_group,
    }

    if newsletter.use_html:
        content = frappe.render_template(newsletter.html_content, context)
    else:
        content = frappe.render_template(newsletter.content, context)

    subject = frappe.render_template(newsletter.subject, context)

    attachments = get_attachments(newsletter)

    frappe.sendmail(
        recipients=[recipient.email],
        sender=newsletter.sender,
        subject=subject,
        message=content,
        reference_doctype="Newsletter",
        reference_name=newsletter.name,
        add_unsubscribe_link=newsletter.add_unsubscribe_link,
        unsubscribe_message=_("Unsubscribe from this newsletter"),
        attachments=attachments,
        queue_separately=True,
        delayed=True,
        raw_html=newsletter.use_html,
    )


def get_attachments(newsletter):
    attachments = []
    for attachment in newsletter.attachments:
        file_doc = frappe.get_doc("File", attachment.file)
        attachments.append(
            {
                "fname": file_doc.file_name,
                "fcontent": frappe.get_doc("File", attachment.file).get_content(),
            }
        )
    return attachments


def process_scheduled_newsletters():
    newsletters = frappe.get_all(
        "Newsletter",
        filters={"status": "Queued", "schedule_send": 1},
        fields=["name", "send_after"],
    )

    for nl in newsletters:
        if nl.send_after and get_datetime(nl.send_after) <= now_datetime():
            frappe.enqueue(
                send_newsletter_emails,
                newsletter_name=nl.name,
                queue="long",
                timeout=3600,
            )


@frappe.whitelist()
def get_email_accounts():
    email_accounts = frappe.get_all(
        "Email Account",
        filters={"enable_outgoing": 1},
        pluck="email_id",
    )
    return email_accounts


@frappe.whitelist()
def get_recipient_count(email_group):
    return frappe.db.count(
        "Email Group Member",
        filters={"email_group": email_group, "unsubscribed": 0},
    )


@frappe.whitelist()
def get_template_content(template_name):
    template = frappe.get_doc("Email Template", template_name)
    return {
        "subject": template.subject,
        "content": template.response_ if not template.use_html else "",
        "html_content": template.response_html or template.response_
        if template.use_html
        else "",
        "use_html": template.use_html,
    }
