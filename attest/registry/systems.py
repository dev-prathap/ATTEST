"""Known systems: canonical ids, aliases, and API hostnames. Seeded from DO `registry.py` SYSTEM_LABELS
and TEMPLATE_APPS. Unknown stays `unknown` (with a best-effort hostname-derived id when a URL is available)."""
from __future__ import annotations

SYSTEM_LABELS: dict[str, str] = {
    "gmail": "Gmail", "calendar": "Google Calendar", "drive": "Google Drive", "contacts": "Google Contacts",
    "docs": "Google Docs", "sheets": "Google Sheets", "slides": "Google Slides",
    "slack": "Slack", "hubspot": "HubSpot", "notion": "Notion", "linear": "Linear",
    "outlook": "Outlook", "teams": "Microsoft Teams", "onedrive": "OneDrive", "sharepoint": "SharePoint",
    "zoho_crm": "Zoho CRM", "zoho_books": "Zoho Books", "zoho_people": "Zoho People",
    "jira": "Jira", "confluence": "Confluence", "github": "GitHub", "gitlab": "GitLab", "zoom": "Zoom",
    "fireflies": "Fireflies", "salesforce": "Salesforce", "freshdesk": "Freshdesk", "intercom": "Intercom",
    "stripe": "Stripe", "razorpay": "Razorpay", "quickbooks": "QuickBooks", "xero": "Xero", "asana": "Asana",
    "clickup": "ClickUp", "monday": "monday.com", "zendesk": "Zendesk", "calendly": "Calendly",
    "docusign": "DocuSign", "dropbox": "Dropbox", "box": "Box", "airtable": "Airtable", "trello": "Trello",
    "twilio": "Twilio", "sendgrid": "SendGrid", "resend": "Resend", "mailchimp": "Mailchimp",
    "discord": "Discord", "telegram": "Telegram", "whatsapp": "WhatsApp", "shopify": "Shopify",
    "aws": "AWS", "gcp": "Google Cloud", "azure": "Azure", "postgres": "Postgres", "filesystem": "Filesystem",
    "unknown": "Unknown",
}

# alias (as it appears in tool names, SDK paths, Nango integration keys) → canonical system id
SYSTEM_ALIASES: dict[str, str] = {
    "google_mail": "gmail", "googlemail": "gmail", "mail": "gmail",
    "google_calendar": "calendar", "gcal": "calendar",
    "google_drive": "drive", "gdrive": "drive",
    "google_docs": "docs", "google_sheet": "sheets", "google_sheets": "sheets", "google_slides": "slides",
    "google_contacts": "contacts", "people": "contacts",
    "microsoft_teams": "teams", "msteams": "teams", "ms_teams": "teams",
    "one_drive": "onedrive", "sharepoint_online": "sharepoint", "microsoft_outlook": "outlook", "office365": "outlook",
    "zoho": "zoho_crm", "zohocrm": "zoho_crm", "zohobooks": "zoho_books",
    "hubspot_crm": "hubspot", "hs": "hubspot",
    "gh": "github", "fs": "filesystem", "file": "filesystem", "files": "filesystem",
    "pg": "postgres", "postgresql": "postgres", "sql": "postgres",
    "s3": "aws", "ses": "aws", "lambda": "aws",
}

# API hostname (suffix match) → (system, optional path-prefix → system refinements)
HOST_SYSTEMS: list[tuple[str, str, dict[str, str]]] = [
    ("gmail.googleapis.com", "gmail", {}),
    ("people.googleapis.com", "contacts", {}),
    ("sheets.googleapis.com", "sheets", {}),
    ("docs.googleapis.com", "docs", {}),
    ("slides.googleapis.com", "slides", {}),
    ("www.googleapis.com", "unknown", {"/gmail/": "gmail", "/calendar/": "calendar", "/drive/": "drive",
                                       "/upload/drive/": "drive", "/people/": "contacts"}),
    ("googleapis.com", "gcp", {}),
    ("slack.com", "slack", {}),
    ("api.hubapi.com", "hubspot", {}),
    ("hubapi.com", "hubspot", {}),
    ("api.notion.com", "notion", {}),
    ("api.linear.app", "linear", {}),
    ("graph.microsoft.com", "unknown", {"/me/messages": "outlook", "/users/": "outlook", "/me/events": "outlook",
                                        "/me/calendars": "outlook", "/me/mailFolders": "outlook",
                                        "/teams/": "teams", "/chats/": "teams", "/me/drive": "onedrive",
                                        "/drives/": "onedrive", "/sites/": "sharepoint"}),
    ("zohoapis.com", "unknown", {"/crm/": "zoho_crm", "/books/": "zoho_books", "/people/": "zoho_people"}),
    ("zohoapis.in", "unknown", {"/crm/": "zoho_crm", "/books/": "zoho_books", "/people/": "zoho_people"}),
    ("atlassian.net", "unknown", {"/rest/api/": "jira", "/wiki/": "confluence"}),
    ("api.atlassian.com", "unknown", {"/jira/": "jira", "/confluence/": "confluence"}),
    ("api.github.com", "github", {}),
    ("gitlab.com", "gitlab", {}),
    ("api.zoom.us", "zoom", {}),
    ("salesforce.com", "salesforce", {}),
    ("freshdesk.com", "freshdesk", {}),
    ("api.intercom.io", "intercom", {}),
    ("api.stripe.com", "stripe", {}),
    ("api.razorpay.com", "razorpay", {}),
    ("quickbooks.api.intuit.com", "quickbooks", {}),
    ("api.xero.com", "xero", {}),
    ("app.asana.com", "asana", {}),
    ("api.clickup.com", "clickup", {}),
    ("api.monday.com", "monday", {}),
    ("zendesk.com", "zendesk", {}),
    ("api.calendly.com", "calendly", {}),
    ("docusign.net", "docusign", {}),
    ("api.dropboxapi.com", "dropbox", {}),
    ("api.box.com", "box", {}),
    ("api.airtable.com", "airtable", {}),
    ("api.trello.com", "trello", {}),
    ("api.twilio.com", "twilio", {}),
    ("api.sendgrid.com", "sendgrid", {}),
    ("api.resend.com", "resend", {}),
    ("api.mailchimp.com", "mailchimp", {}),
    ("discord.com", "discord", {}),
    ("api.telegram.org", "telegram", {}),
    ("myshopify.com", "shopify", {}),
    ("amazonaws.com", "aws", {}),
]

_SECOND_LEVEL_SUFFIXES = {"co.uk", "com.au", "co.in", "co.jp", "com.br", "co.nz", "org.uk", "ac.uk", "com.mx",
                          "co.za", "com.sg", "gov.uk", "net.au", "org.au"}


def registered_domain(host: str) -> str:
    """`api.someweirdcrm.io` → `someweirdcrm.io`; `foo.bar.co.uk` → `bar.co.uk`. No network, no dep."""
    host = (host or "").lower().strip(".").split(":")[0]
    parts = host.split(".")
    if len(parts) < 2:
        return host
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def canonical_system(name: str | None) -> str | None:
    if not name:
        return None
    key = name.lower().replace("-", "_").replace(" ", "_").replace(".", "_")
    if key in SYSTEM_LABELS:
        return key
    return SYSTEM_ALIASES.get(key)


def system_for_host(host: str, path: str = "") -> str:
    host = (host or "").lower()
    for suffix, system, refinements in HOST_SYSTEMS:
        if host == suffix or host.endswith("." + suffix):
            for prefix, refined in refinements.items():
                if prefix in path:
                    return refined
            return system
    reg = registered_domain(host)
    label = reg.split(".")[0] if reg else ""
    return label.replace("-", "_") or "unknown"
