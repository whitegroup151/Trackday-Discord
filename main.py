
from flask import Flask
import requests
import datetime
import re
from zoneinfo import ZoneInfo

app = Flask(__name__)

### --- SMSP and PI EVENTS CONFIG & FUNCTIONS ---

EVENTS_URLS = {
    "SMSP": "https://www.smsprd.com/json/events/events/getEventsForSelect?filters%5Bpublic%5D=true&filters%5BexcludeId%5D=101293",
    "PI": "https://www.phillipislandridedays.com.au/json/events/events/getEventsForSelect?filters%5Bpublic%5D=true&filters%5BexcludeId%5D=101276"
}

HEADERS_SMSP_PI = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Cookie": "PHPSESSID=9u0u0g8f1suparah2si7uaqm35; selmasuPublicToken=IH0OJCUtfK25ad3Dtb2uCHeyjTvXgMOA; _ga=GA1.3.1658598946.1747809112; _gid=GA1.3.1158673676.1747809112; _fbp=fb.2.1747821472993.219493874915532452; _ga_CDKJPXNRQF=GS2.3.s1747883817$o3$g1$t1747883833$j0$l0$h0; selmasuToken=hgSQb9rWmc7wcShhDBAT; _gat=1"
}

def extract_date_from_name(name):
    match = re.search(r'(\d{1,2})(?:st|nd|rd|th)? (\w+) (\d{4})', name)
    if not match:
        return None
    day, month_str, year = match.groups()
    month_map = {
        'january':1, 'february':2, 'march':3, 'april':4,
        'may':5, 'june':6, 'july':7, 'august':8,
        'september':9, 'october':10, 'november':11, 'december':12
    }
    month = month_map.get(month_str.lower())
    if not month:
        return None
    return datetime.date(int(year), month, int(day))

def get_events(url):
    response = requests.get(url, headers=HEADERS_SMSP_PI)
    response.raise_for_status()
    return response.json()

def format_sms_pi_date(date_str):
    date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    day_suffix = lambda d: 'th' if 11<=d<=13 else {1:'st',2:'nd',3:'rd'}.get(d%10, 'th')
    day = date.day
    suffix = day_suffix(day)
    return date.strftime(f"%a {day}{suffix} %B %Y")

### --- PHEASANT WOOD EVENTS CONFIG & FUNCTIONS ---

PW_API_URL = "https://94qrm2we1l.execute-api.us-east-1.amazonaws.com/production/storefront/calendar"
PW_SHOP = "pheasant-wood.myshopify.com"

def fetch_pheasant_wood_events():
    today = datetime.date.today()
    start_date = today.strftime("%Y-%m-%d")
    end_date = (today + datetime.timedelta(weeks=8)).strftime("%Y-%m-%d")
    params = {
        "shop": PW_SHOP,
        "startDate": start_date,
        "endDate": end_date,
        "currentDate": start_date
    }
    response = requests.get(PW_API_URL, params=params)
    response.raise_for_status()
    data = response.json()
    events = data.get("events", [])
    filtered = []
    keywords = ["social ride day", "125cc", "150cc"]
    for event in events:
        title = event.get("title", "").lower()
        if any(kw in title for kw in keywords):
            start_at = event.get("start_at") or event.get("start")
            if not start_at:
                continue
            try:
                event_date = datetime.datetime.fromisoformat(start_at.replace("Z", "+00:00")).date()
            except Exception:
                continue
            if event_date >= today:
                tickets_available = 0
                for ticket in event.get("ticket_types", []):
                    inventory = ticket.get("inventory")
                    if isinstance(inventory, int):
                        tickets_available += inventory
                filtered.append((event_date.strftime("%Y-%m-%d"), event.get("title", "No title"), tickets_available))
    filtered.sort()
    return filtered

def format_pheasant_wood_message():
    events = fetch_pheasant_wood_events()
    if not events:
        return "❌ No matching upcoming Pheasant Wood events found."

    groups = {
        "Ride days": [],
        "125cc Enduro": [],
        "150cc Enduro": []
    }

    for date, title, inventory in events:
        lower_title = title.lower()
        if "social ride day" in lower_title:
            groups["Ride days"].append((date, inventory))
        elif "125cc" in lower_title:
            groups["125cc Enduro"].append((date, inventory))
        elif "150cc" in lower_title:
            groups["150cc Enduro"].append((date, inventory))

    msg = "\n**PW**"
    for group_name, group_events in groups.items():
        if not group_events:
            continue
        msg += f"\n**{group_name}**\n"
        for date, inventory in sorted(group_events):
            date_str = format_sms_pi_date(date)
            msg += f"{date_str} (Remaining: {inventory})\n"

    return msg

def format_sms_pi_message():
    today = datetime.date.today()
    grouped_events = {}

    for location, url in EVENTS_URLS.items():
        events = get_events(url)
        upcoming = []
        for e in events:
            name = e.get("name", "")
            date = extract_date_from_name(name)
            tickets = e.get("totalAvailable", "N/A")
            if date and date >= today:
                upcoming.append((date, name, tickets))
        upcoming.sort()
        grouped_events[location] = upcoming[:5]

    msg = "**📅 Upcoming Events:**\n"
    for location in ["SMSP", "PI"]:
        msg += f"\n**{location}**\n"
        for date, name, tickets in grouped_events.get(location, []):
            msg += f"{date.strftime('%a %d %B %Y')} (Remaining: {tickets})\n"

    return msg

### --- FLICKET / MOTOSCHOOL EVENTS CONFIG & FUNCTIONS ---

GRAPHQL_URL = "https://api.flicket.io/graphql"
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1375796481491075163/fMbKEld79LKNBIXSNjX-DArtkjgyJDpVGYOQFv2Q7wil-p_7b785j4vyFGsog9bG7eHg"

HEADERS_FLICKET = {
    "Content-Type": "application/json",
    "flicket-org-id": "081be583-fa0f-4af0-9a05-0c46b15ceed4"
}

event_list_payload = {
    "operationName": "Events",
    "variables": {
        "first": 50,
        "after": None
    },
    "query": """
    query Events($first: Int!, $after: String) {
      events(first: $first, after: $after) {
        edges {
          node {
            id
            title
            startDate
          }
        }
        pageInfo {
          endCursor
          hasNextPage
        }
      }
    }
    """
}

def fetch_flicket_events():
    events = []
    after_cursor = None
    while True:
        event_list_payload["variables"]["after"] = after_cursor
        response = requests.post(GRAPHQL_URL, headers=HEADERS_FLICKET, json=event_list_payload)
        if response.status_code != 200:
            print(f"Error fetching Flicket events: {response.status_code} - {response.text}")
            break

        data = response.json()
        edges = data.get("data", {}).get("events", {}).get("edges", [])
        for edge in edges:
            node = edge["node"]
            events.append(node)

        page_info = data.get("data", {}).get("events", {}).get("pageInfo", {})
        if page_info.get("hasNextPage"):
            after_cursor = page_info.get("endCursor")
        else:
            break
    return events

def filter_upcoming_flicket_events(events):
    today = datetime.datetime.now(ZoneInfo("Australia/Sydney")).date()
    filtered = []
    for event in events:
        start_str = event.get("startDate")
        if start_str:
            try:
                event_dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(ZoneInfo("Australia/Sydney"))
                if event_dt.date() >= today:
                    filtered.append(event)
            except Exception as e:
                print(f"Error parsing Flicket event date '{start_str}': {e}")
    return filtered

def fetch_event_ticket_types(event_id):
    payload = {
        "operationName": "EventDetails",
        "variables": {"eventId": event_id},
        "query": """
        query EventDetails($eventId: String!) {
          event(id: $eventId) {
            ticketTypes {
              id
              name
              quantity
            }
          }
        }
        """
    }
    response = requests.post(GRAPHQL_URL, headers=HEADERS_FLICKET, json=payload)
    if response.status_code != 200:
        print(f"Error fetching Flicket event details for {event_id}: {response.status_code} - {response.text}")
        return []
    data = response.json()
    return data.get("data", {}).get("event", {}).get("ticketTypes", [])

def fetch_max_purchase_quantities(event_id):
    query = """
    query getEventAndReleaseForCustomer($input: EventsWithAccessControlInput!) {
      getEventAndReleaseForCustomer(input: $input) {
        release {
          releaseZones {
            ticketTypes {
              ticketTypeId
              maxPurchaseQuantity
            }
          }
        }
      }
    }
    """
    payload = {
        "operationName": "getEventAndReleaseForCustomer",
        "variables": {"input": {"eventId": event_id}},
        "query": query
    }
    response = requests.post(GRAPHQL_URL, headers=HEADERS_FLICKET, json=payload)
    if response.status_code != 200:
        print(f"Error fetching maxPurchaseQuantity for {event_id}: {response.status_code} - {response.text}")
        return []
    data = response.json()
    release = data.get("data", {}).get("getEventAndReleaseForCustomer", {}).get("release")
    if not release:
        return []
    ticket_types = []
    for zone in release.get("releaseZones", []):
        for tt in zone.get("ticketTypes", []):
            ticket_types.append(tt)
    return ticket_types

def ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th')}"

def format_date(dt):
    day_name = dt.strftime("%a")
    day = ordinal(dt.day)
    month = dt.strftime("%b")
    return f"{day_name}, {day} {month}"

def strip_brackets(text):
    return re.sub(r"\s*\([^)]*\)", "", text).strip()

def format_flicket_message():
    all_events = fetch_flicket_events()
    upcoming_events = filter_upcoming_flicket_events(all_events)

    if not upcoming_events:
        return "No upcoming MotoSchool events found."

    upcoming_events.sort(key=lambda e: datetime.datetime.fromisoformat(e['startDate'].replace("Z", "+00:00")).astimezone(ZoneInfo("Australia/Sydney")))

    message_lines = []
    for event in upcoming_events:
        start_dt = datetime.datetime.fromisoformat(event['startDate'].replace("Z", "+00:00")).astimezone(ZoneInfo("Australia/Sydney"))
        message_lines.append(f"**{event['title']} — {format_date(start_dt)}**")

        ticket_types = fetch_event_ticket_types(event["id"])
        max_purchase_data = fetch_max_purchase_quantities(event["id"])
        max_map = {t['ticketTypeId']: t['maxPurchaseQuantity'] for t in max_purchase_data}

        for ticket in ticket_types:
            name = strip_brackets(ticket.get("name", "Unnamed"))
            max_per_user = max_map.get(ticket.get("id"), 0)
            remaining_display = ">10" if max_per_user >= 10 else str(max_per_user)
            message_lines.append(f"{name} (Remaining: {remaining_display})")

        message_lines.append("")

    return "\n".join(message_lines)

### --- COMBINED MESSAGE & FLASK ROUTE ---

def format_combined_message():
    sms_pi_msg = format_sms_pi_message()
    pw_msg = format_pheasant_wood_message()
    flicket_msg = format_flicket_message()
    return f"{sms_pi_msg}\n{pw_msg}\n\n**MotoSchool Events:**\n{flicket_msg}"

def post_to_discord(message):
    payload = {
        "content": message[:2000]  # Discord limit per message
    }
    try:
        resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        if resp.status_code in (200, 204):
            print("✅ Message posted to Discord.")
        else:
            print(f"❌ Discord post failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"❌ Exception posting to Discord: {e}")

@app.route("/")
def trigger():
    combined_message = format_combined_message()
    post_to_discord(combined_message)
    return "✅ Message sent to Discord."

if __name__ == "__main__":
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    def scheduled_job():
        with app.app_context():
            print("Running scheduled job at 6:10 PM")
            combined_message = format_combined_message()
            post_to_discord(combined_message)

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        scheduled_job,
        CronTrigger(hour=88, minute=10, timezone="Australia/Sydney")  # Adjust timezone as needed
    )
    scheduler.start()
    app.run(debug=True, host="0.0.0.0", port=5000)
