from workflow.workflow_datatypes import NodeConfig, FieldType
from workflow.workflow_executor import Node
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import traceback
from jinja2 import Template, TemplateSyntaxError


class mailtrap_email_node:

    default_setup: NodeConfig = {
        "id": "MailtrapEmail",
        "name": "Send Email (Mailtrap)",
        "description": "Send emails using Mailtrap SMTP",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [],            # user can add custom pins here
            "output_pins": [{"name": "Response"}],
            "next_pins": [{"name": "Next"}],
        },
        "fields": [
            {
                "id": "Mode",
                "label": "Mode",
                "type": FieldType.SINGLE_SELECT,
                "options": ["Sandbox", "Production"],
                "width": "50%"
            },
            {
                "id": "Username",
                "label": "SMTP Username",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "Password",
                "label": "SMTP Password",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },

            # Email fields
            {
                "id": "FromEmail",
                "label": "From Email",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "FromName",
                "label": "From Name",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "To",
                "label": "To Emails (comma separated)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Cc",
                "label": "CC Emails (comma separated)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Bcc",
                "label": "BCC Emails (comma separated)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Subject",
                "label": "Subject",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "Body",
                "label": "Body (HTML allowed)",
                "type": FieldType.TEXT,
                "width": "100%"
            }
        ],
    }

    def __init__(self, node: Node):
        self.node = node
        cfg = node.data.get("configuration") or {}

        self.smtp_host = "sandbox.smtp.mailtrap.io"
        self.smtp_port = 2525

        self.mode = cfg.get("Mode")
        self.username = cfg.get("Username")
        self.password = cfg.get("Password")

        self.from_email = cfg.get("FromEmail")
        self.from_name = cfg.get("FromName")
        self.to = cfg.get("To") or ""
        self.cc = cfg.get("Cc") or ""
        self.bcc = cfg.get("Bcc") or ""
        self.subject = cfg.get("Subject")
        self.body = cfg.get("Body")

    def render_template(self, value, data):
        """Render Jinja template safely"""
        if not value:
            return value
        try:
            template = Template(value)
            return template.render(**data)
        except TemplateSyntaxError as e:
            raise Exception(f"Template error in field: {value} // {str(e)}")

    def Run(self, connection, data):
        response_data = {}

        try:
            # REQUIRED fields
            if not self.username or not self.password:
                raise Exception("SMTP username & password required")

            if not self.from_email:
                raise Exception("From Email is required")

            if not self.to:
                raise Exception("To is required")

            # 🔥 TEMPLATE RENDERING (MOST IMPORTANT PART)
            rendered_subject = self.render_template(self.subject, data)
            rendered_body = self.render_template(self.body, data)
            rendered_to = self.render_template(self.to, data)
            rendered_cc = self.render_template(self.cc, data)
            rendered_bcc = self.render_template(self.bcc, data)

            # Split recipients
            to_list = [x.strip() for x in rendered_to.split(",") if x.strip()]
            cc_list = [x.strip() for x in rendered_cc.split(",") if x.strip()]
            bcc_list = [x.strip() for x in rendered_bcc.split(",") if x.strip()]

            sender = (
                f"{self.from_name} <{self.from_email}>"
                if self.from_name else self.from_email
            )

            msg = MIMEMultipart()
            msg["From"] = sender
            msg["To"] = ", ".join(to_list)
            msg["Subject"] = rendered_subject or ""

            if cc_list:
                msg["Cc"] = ", ".join(cc_list)

            msg.attach(MIMEText(rendered_body or "", "html"))

            all_recipients = to_list + cc_list + bcc_list

            # SEND MAIL
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.from_email, all_recipients, msg.as_string())
            server.quit()

            response_data = {
                "status": "success",
                "sent_to": all_recipients
            }

            self.node.SetTargetPinData("Response", response_data)

        except Exception as e:
            error_data = {
                "error": str(e),
                "traceback": traceback.format_exc()
            }
            self.node.SetTargetPinData("Response", error_data)

        return self.node.TriggerAll()
