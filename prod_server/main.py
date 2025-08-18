import json
import ephem
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, date, timedelta
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.requests import Request
from pathlib import Path
import random
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ---------------------------------------------------------------------------
# Try several fallback locations so the app works in both dev (file in /static)
# and prod (file copied next to main.py).
# ---------------------------------------------------------------------------
DATA_PATH_CANDIDATES = [
    os.path.join(BASE_DIR, "calendar_data.json"),
    os.path.join(BASE_DIR, "static", "calendar_data.json"),
    os.path.join(BASE_DIR, "..", "static", "calendar_data.json"),
]

def _find_data_file() -> str:
    for path in DATA_PATH_CANDIDATES:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "calendar_data.json not found in any of: "
        + ", ".join(DATA_PATH_CANDIDATES)
    )

DATA_FILE = _find_data_file()


moon_descriptions = {
    "New Moon": "The start of a new lunar cycle, symbolising new beginnings and intentions.",
    "First Quarter": "A time for taking action on your goals as the moon waxes.",
    "Last Quarter": "A reflective phase as the moon wanes, encouraging release and gratitude."
}

app = FastAPI()

# CORS
raw = os.environ.get("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in raw.split(",") if o.strip()] or [
    "http://localhost:5173"  # dev default
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    max_age=600,
)

# Mount the directory containing static files
# app.mount("/celtic_wheel", StaticFiles(directory="celtic_wheel"), name="celtic_wheel")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    print(f"⚠️ Static dir {STATIC_DIR} not found; skipping mount.")


# Serve the "assets", "css", "js" directories as static files
# app.mount("/assets", StaticFiles(directory="assets"), name="assets")
# app.mount("/css", StaticFiles(directory="css"), name="css")
# app.mount("/js", StaticFiles(directory="js"), name="js")

@app.get("/")
async def root():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"ok": True, "service": "lunar-almanac-backend", "static": False}


# Force browser to load fresh page
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

# Health endpoint
@app.get("/health", include_in_schema=False)
@app.head("/health", include_in_schema=False)
async def health() -> Response:
    return Response(content="ok", media_type="text/plain", headers={"Cache-Control": "no-store"})

# Display all 13 months
@app.get("/calendar")
def get_calendar():
    return calendar_data

# Display a single month
@app.get("/calendar/month/{month_name}")
def get_month(month_name: str):
    # Search for the month in the calendar data
    for month in calendar_data["months"]:
        if month["name"].lower() == month_name.lower():  # Case-insensitive search
            return {"month": month}
    # If not found, return an error message
    return {"error": f"Month '{month_name}' not found in the Celtic Calendar"}


# Check if the year is a leap year
def is_leap_year(year):
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


# Show Moon phases: dynamic with safe fallback
@app.get("/lunar-phases")
def get_lunar_phases(start_date: str | None = None, end_date: str | None = None):
    """If start_date & end_date are provided (YYYY-MM-DD), compute dynamically; otherwise fall back to named full moons."""
    if start_date and end_date:
        try:
            s = datetime.fromisoformat(start_date).date()
            e = datetime.fromisoformat(end_date).date()
            return calculate_lunar_phases(s, e)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid dates: {exc}")
    return [
        {
            "date": fm["date"],
            "phase": "Full Moon",
            "phaseName": fm.get("name", "Full Moon"),
            "description": fm.get("description", ""),
            "poem": fm.get("poem", ""),
            "graphic": "🌕",
        }
        for fm in calendar_data.get("full_moons", [])
    ]


# Filter lunar phase by phase, phaseName and date
@app.get("/lunar-phases/filter")
def filter_lunar_phases(phase: str = None, phaseName: str = None, start_date: str = None, end_date: str = None):
    if start_date and end_date:
        try:
            s = datetime.fromisoformat(start_date).date()
            e = datetime.fromisoformat(end_date).date()
            base = calculate_lunar_phases(s, e)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid dates: {exc}")
    else:
        base = [
            {
                "date": fm["date"],
                "phase": "Full Moon",
                "phaseName": fm.get("name", "Full Moon"),
                "description": fm.get("description", ""),
                "poem": fm.get("poem", ""),
                "graphic": "🌕",
            }
            for fm in calendar_data.get("full_moons", [])
        ]
    result = base
    if phase:
        result = [p for p in result if p.get("phase", "").lower() == phase.lower()]
    if phaseName:
        result = [p for p in result if p.get("phaseName", "").lower() == phaseName.lower()]
    if start_date or end_date:
        s = datetime.fromisoformat(start_date).date() if start_date else date.min
        e = datetime.fromisoformat(end_date).date() if end_date else date.max
        result = [p for p in result if s <= datetime.fromisoformat(p["date"]).date() <= e]
    return result


# Display list of festivals, filtered by name or month
@app.get("/festivals")
def get_festivals(name: str = None, month: str = None, festival_type: str = None):
    festivals = calendar_data["special_days"]

    # Filter by name
    if name:
        festivals = [f for f in festivals if f["name"].lower() == name.lower()]

    # Filter by month
    if month:
        festivals = [
            f for f in festivals
            if datetime.fromisoformat(f["date"]).strftime("%B").lower() == month.lower()
        ]

    # Filter by type
    if festival_type:
        festivals = [f for f in festivals if f["type"].lower() == festival_type.lower()]

    return festivals


# Retrieve festivals that align with lunar phases
@app.get("/festivals/lunar-phases")
def get_festivals_linked_to_phases(phase: str = None, moon_name: str = None):
    festivals = calendar_data["special_days"]
    linked_festivals = []

    # Normalize input for case-insensitive matching
    moon_name_lower = moon_name.lower() if moon_name else None
    phase_lower = phase.lower() if phase else None

    for festival in festivals:
        # Match linked moon
        if moon_name_lower and "linked_moon" in festival:
            if festival["linked_moon"].lower() == moon_name_lower:
                linked_festivals.append(festival)
        # Match linked phase
        elif phase_lower and "linked_phase" in festival:
            if festival["linked_phase"].lower() == phase_lower:
                linked_festivals.append(festival)

    if linked_festivals:
        return {"phase": moon_name or phase, "festivals": linked_festivals}
    return {"message": f"No festivals linked to the phase '{moon_name or phase}'."}


# Display phases of the moon (Dynamic)
@app.get("/dynamic-moon-phases")
def dynamic_moon_phases(start_date: date, end_date: date):
    phases = get_moon_phases(start_date, end_date) or []   # ← never None
    print("★ dynamic_moon_phases →", phases)   # <-- add
    return phases

#  Extend the /lunar-phases endpoint to include the poem field.
@app.get("/lunar-phases/poetry")
def get_lunar_phase_poetry(phase_name: str):
    for phase in calendar_data["lunar_phases"]:
        if phase.get("phaseName", "").lower() == phase_name.lower():
            return {
                "phase": phase["phase"],
                "phaseName": phase["phaseName"],
                "description": phase["description"],
                "poem": phase.get("poem", "No poem available."),
                "date": phase["date"]
            }
    return {"message": f"No poetry found for the phase '{phase_name}'."}


# Convert today's date into our Celtic Calendar equivalent
def get_celtic_year_start(year):
    # Winter Solstice is December 21
    solstice = datetime(year - 1, 12, 21)
    print(f"Winter Solstice: {solstice.date()} (weekday: {solstice.weekday()})")

    # Find the next Monday
    days_until_monday = (7 - solstice.weekday()) % 7
    celtic_year_start = solstice + timedelta(days=days_until_monday)
    print(f"Celtic Year Start: {celtic_year_start.date()} (weekday: {celtic_year_start.weekday()})")

    return celtic_year_start

#Display today's date in the Celtic Calendar
def celtic_date_for_gregorian(gregorian_date):
    year = gregorian_date.year
    celtic_year_start = get_celtic_year_start(year)

    # Adjust the Celtic year if the Gregorian date is past December 21
    if gregorian_date >= datetime(year, 12, 21).date():
        celtic_year_start = get_celtic_year_start(year + 1)

    # Calculate the number of days since the Celtic year started
    days_since_start = (gregorian_date - celtic_year_start.date()).days

    # Define Celtic months (13 months, each with 28 days)
    celtic_months = [
        "Yule", "Janus", "Brigid", "Flora", "Maya", "Juno",
        "Solis", "Terra", "Lugh", "Pomona", "Autumma", "Frost", "Aether"
    ]

    # Handle leap year special days (if applicable)
    if is_leap_year(year) and days_since_start == 8:
        return {"month": "Leap Day", "day": 1}

    if days_since_start == 364:
        return {"month": "Floating Day", "day": 1}

    month_index = days_since_start // 28
    day = (days_since_start % 28) + 1

    # Fallback for overflow (if any)
    if month_index >= len(celtic_months):
        return {"month": "Invalid Date", "day": None}

    month = celtic_months[month_index]
    return {"month": month, "day": day}

    

# Display today's date in the Celtic Calendar
@app.get("/celtic-today")
def celtic_today():
    today = datetime.now().date()
    celtic_date = celtic_date_for_gregorian(today)
    return {
        "gregorian_date": today.isoformat(),
        "celtic_month": celtic_date["month"],
        "celtic_day": celtic_date["day"]
    }


# Calculate lunar phases for a range of dates:
def calculate_lunar_phases(start_date, end_date):
    lunar_phases = []

    # Updated moon phase categorisation by age (in days)
    phase_mapping = [
        (0, 1.5, "New Moon", "🌑"),
        (1.5, 7.5, "Waxing Crescent", "🌒"),
        (7.5, 10.5, "First Quarter", "🌓"),
        (10.5, 13.5, "Waxing Gibbous", "🌔"),
        (13.5, 16.5, "Full Moon", "🌕"),  # Expanded Full Moon range
        (16.5, 21.5, "Waning Gibbous", "🌖"),
        (21.5, 24.5, "Last Quarter", "🌗"),
        (24.5, 29.53, "Waning Crescent", "🌘"),
        (29.53, 30.5, "New Moon", "🌑")  # For rounding
    ]

    current_date = start_date
    while current_date <= end_date:
        # Get ephem Moon object
        moon = ephem.Moon(current_date)

        # Calculate Moon Age
        prev_new_moon = ephem.previous_new_moon(current_date)
        moon_age = (current_date - prev_new_moon.datetime().date()).days % 29.53  # Days since last new moon

        # Determine the phase name and graphic
        phase_name, graphic = "Unknown Phase", "❓"
        for start, end, name, icon in phase_mapping:
            if start <= moon_age < end:
                phase_name, graphic = name, icon
                break

        # Debugging information
        illumination = moon.phase  # Illumination percentage
        print(f"DEBUG: Date = {current_date}, Illumination = {illumination:.2f}, Moon Age = {moon_age:.2f}, Phase Name = {phase_name}")

        # Append to results
        lunar_phases.append({
            "date": current_date.isoformat(),
            "phase": phase_name,
            "graphic": graphic,
            "description": f"{phase_name} phase with {illumination:.2f}% illumination.",
        })

        # Increment date
        current_date += timedelta(days=1)

    return lunar_phases


# ---------------------------------------------------------------------------
# Helper wrapper – keeps earlier code that calls get_moon_phases() working
# by simply delegating to calculate_lunar_phases().
# ---------------------------------------------------------------------------
def get_moon_phases(start_date: date, end_date: date):
    """
    Thin wrapper around `calculate_lunar_phases` for backwards‑compat.
    """
    return calculate_lunar_phases(start_date, end_date)


# Display lunar phases for a specific Celtic month
@app.get("/calendar/lunar-phases")
def get_lunar_phases_for_celtic_month(month_name: str = None):
    # Get the start and end dates of the Celtic month
    for month in calendar_data["months"]:
        if month["name"].lower() == month_name.lower():
            start_date = datetime.fromisoformat(month["start_date"]).date()
            end_date = datetime.fromisoformat(month["end_date"]).date()

            # Calculate lunar phases for this range
            lunar_phases = calculate_lunar_phases(start_date, end_date)
            return {"month": month["name"], "lunar_phases": lunar_phases}

    return {"error": f"Month '{month_name}' not found in the Celtic Calendar"}



def load_calendar_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"⚠️  DATA_FILE not found even after search: {DATA_FILE}")
        return {}

def save_calendar_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)

# Load data initially
calendar_data = load_calendar_data()

@app.get("/api/custom-events")
async def get_custom_events():
    data = load_calendar_data()
    return data.get("custom_events", [])

# ✅ Add a New Custom Event
@app.post("/api/custom-events")
def add_custom_event(custom_event: dict):
    required_fields = ["title", "date"]
    
    # Ensure required fields are present
    if not all(field in custom_event for field in required_fields):
        raise HTTPException(status_code=400, detail="Missing required fields: title, date")

    # Default optional fields if missing
    custom_event.setdefault("type", "General")
    custom_event.setdefault("notes", "")

    calendar_data.setdefault("custom_events", []).append(custom_event)
    save_calendar_data(calendar_data)

    return {
        "message": "Custom event added successfully!",
        "event": custom_event
    }

# ✅ Delete a Custom Event
@app.delete("/api/custom-events/{id}")
def delete_custom_event(id: str):
    global calendar_data
    custom_events = calendar_data.get("custom_events", [])
    updated_events = [e for e in custom_events if e.get("id") != id]
    if len(updated_events) < len(custom_events):
        calendar_data["custom_events"] = updated_events
        save_calendar_data(calendar_data)
        calendar_data = load_calendar_data()
        return {"message": f"Custom event {id} deleted successfully!"}
    raise HTTPException(status_code=404, detail=f"No custom event found with id {id}.")


# ✅ Edit an Existing Custom Event
@app.put("/api/custom-events/{id}")
def edit_custom_event(id: str, updated_data: dict):
    custom_events = calendar_data.get("custom_events", [])

    for event in custom_events:
        if event["id"] == id:
            event.update(updated_data)
            save_calendar_data(calendar_data)
            return {"message": f"Custom event on {id} updated successfully!", "event": event}
    
    raise HTTPException(status_code=404, detail=f"No custom event found on {id}.")


# Retrieve the Celtic Zodiac sign for a specific date
@app.get("/zodiac")
def get_zodiac_by_date(date: str):
    from datetime import datetime

    # Parse the query date
    query_date = datetime.fromisoformat(date).date()
    query_month_day = (query_date.month, query_date.day)  # Extract month and day
    print(f"Query Date: {query_date}, Month-Day: {query_month_day}")

    for sign in calendar_data["zodiac"]:
        # Extract month and day from start and end dates
        start = datetime.fromisoformat(sign["start_date"]).date()
        end = datetime.fromisoformat(sign["end_date"]).date()
        start_month_day = (start.month, start.day)
        end_month_day = (end.month, end.day)

        print(f"Checking Zodiac: {sign['name']}")
        print(f"Start Month-Day: {start_month_day}, End Month-Day: {end_month_day}")

        # Check for "normal" ranges (start and end in the same year)
        if start_month_day <= end_month_day:
            if start_month_day <= query_month_day <= end_month_day:
                print(f"Match Found: {sign['name']} (Normal Range)")
                return {
                    "date": date,
                    "zodiac_sign": sign["name"],
                    "symbolism": sign["symbolism"],
                    "animal": sign["animal"],
                    "mythical_creature": sign["mythical_creature"]
                }

        # Check for "wrapped" ranges (e.g., Dec 24 - Jan 20)
        else:
            if query_month_day >= start_month_day or query_month_day <= end_month_day:
                print(f"Match Found: {sign['name']} (Wrapped Range)")
                return {
                    "date": date,
                    "zodiac_sign": sign["name"],
                    "symbolism": sign["symbolism"],
                    "animal": sign["animal"],
                    "mythical_creature": sign["mythical_creature"]
                }

    # No match found
    print("No match found.")


@app.get("/zodiac/by-name")
def get_zodiac_by_name(name: str):
    for sign in calendar_data["zodiac"]:
        if sign["name"].lower() == name.lower():
            return sign
    raise HTTPException(status_code=404, detail=f"Zodiac sign '{name}' not found.")

# Display all Zodiac signs with their dates and symbolism
@app.get("/zodiac/all")
def list_all_zodiac_signs():
    return calendar_data["zodiac"]


# Lists all Zodiac signs, their meanings, and symbols
@app.get("/zodiac/insights")
def zodiac_insights():
    formatted_zodiac = []
    for sign in calendar_data["zodiac"]:
        formatted_sign = {
            "name": sign["name"],
            "dates": f"{datetime.fromisoformat(sign['start_date']).strftime('%d %B')} to {datetime.fromisoformat(sign['end_date']).strftime('%d %B')}",
            "symbolism": sign["symbolism"],
            "animal": sign["animal"],
            "mythical_creature": sign["mythical_creature"]
        }
        formatted_zodiac.append(formatted_sign)
    return formatted_zodiac

# Allows users to query a specific sign by name for deeper insights
@app.get("/zodiac/insights/{sign_name}")
def get_zodiac_sign_details(sign_name: str):
    for sign in calendar_data["zodiac"]:
        if sign["name"].lower() == sign_name.lower():
            return sign
    return {"message": f"Zodiac sign '{sign_name}' not found."}


# let users stay attuned to the rhythm of the calendar and their magical practices
@app.get("/notifications")
def get_upcoming_events(days_ahead: int = 3):
    today = datetime.now().date()
    window_end = today + timedelta(days=days_ahead)
    upcoming = []
    for ev in calendar_data.get("special_days", []):
        d = datetime.fromisoformat(ev["date"]).date()
        if today < d <= window_end:
            upcoming.append({
                "name": ev.get("name", "Special Day"),
                "type": "Festival",
                "description": ev.get("description", ""),
                "date": d.isoformat(),
                "days_until": (d - today).days,
            })
    for ev in calendar_data.get("custom_events", []):
        d = datetime.fromisoformat(ev["date"]).date()
        if today < d <= window_end:
            upcoming.append({
                "name": ev.get("title", "Custom Event"),
                "type": ev.get("type", "Custom Event"),
                "description": ev.get("notes", ""),
                "date": d.isoformat(),
                "days_until": (d - today).days,
            })
    for fm in calendar_data.get("full_moons", []):
        d = datetime.fromisoformat(fm["date"]).date()
        if today < d <= window_end:
            upcoming.append({
                "name": fm.get("name", "Full Moon"),
                "type": "Lunar Phase",
                "description": fm.get("description", ""),
                "date": d.isoformat(),
                "days_until": (d - today).days,
            })
    try:
        for p in calculate_lunar_phases(today, window_end):
            if p.get("phase") in {"New Moon", "Full Moon"}:
                d = datetime.fromisoformat(p["date"]).date()
                if today < d <= window_end:
                    upcoming.append({
                        "name": p.get("phase"),
                        "type": "Lunar Phase",
                        "description": p.get("description", ""),
                        "date": d.isoformat(),
                        "days_until": (d - today).days,
                    })
    except Exception:
        pass
    if upcoming:
        upcoming.sort(key=lambda x: x["date"]) 
        return {"upcoming_events": upcoming}
    return {"message": "No events in the next few days."}


#generate the lunar calendar visuals. This function integrates lunar phase calculations and Celtic date conversions.
@app.get("/calendar/lunar-visuals")
def get_lunar_visuals(month_name: str = None, start_date: str = None, end_date: str = None):
    from datetime import datetime, timedelta
    
    # Define the date range
    if month_name:
        # Retrieve the start and end dates for the given Celtic month
        for month in calendar_data["months"]:
            if month["name"].lower() == month_name.lower():
                start_date = datetime.fromisoformat(month["start_date"]).date()
                end_date = datetime.fromisoformat(month["end_date"]).date()
                break
        else:
            return {"error": f"Month '{month_name}' not found in the Celtic Calendar"}
    elif start_date and end_date:
        start_date = datetime.fromisoformat(start_date).date()
        end_date = datetime.fromisoformat(end_date).date()
    else:
        return {"error": "You must provide either a 'month_name' or 'start_date' and 'end_date'."}

    # Generate lunar phases
    lunar_phases = calculate_lunar_phases(start_date, end_date)

    # Integrate Celtic dates
    visuals = []
    for phase in lunar_phases:
        gregorian_date = datetime.fromisoformat(phase["date"]).date()
        celtic_date = celtic_date_for_gregorian(gregorian_date)
        visuals.append({
            "date": phase["date"],
            "celtic_date": celtic_date,
            "phase": phase["phase"],
            "graphic": phase["graphic"],
            "description": phase["description"]
        })

    return {
        "month": month_name if month_name else "Custom Range",
        "days": visuals
    }

# Fetch the moon poem or display a default moon poem

# List of mystical moon poems
moon_poems = [
    "<h3>The Moon’s Gentle Whisper</h3><p>A sliver of light, a quiet song,<br />Guiding the night as dreams drift along.<br />Not yet whole, but softly bright,<br />The moon still weaves her silver light.</p>",
    
    "<h3>Silver Secrets</h3><p>She drifts in shadows, silver-bright,<br />A lantern glowing in the night.<br />Whisper your dreams, let wishes rise,<br />The moon will answer from the skies.</p>",

    "<h3>Moonlit Veil</h3><p>Between the stars and midnight’s hush,<br />She weaves a veil, so soft and lush.<br />Step through the silver, lose your way,<br />And dance where spirits come to play.</p>",

    "<h3>Celestial Tide</h3><p>Moonlight pulls the ocean’s breath,<br />A rhythm old as life and death.<br />Under her glow, the tide obeys,<br />As time drifts on in silver waves.</p>",

    "<h3>Enchanted Glow</h3><p>She watches from her skybound throne,<br />A queen of dreams, forever known.<br />Beneath her glow, all shadows fade,<br />As magic stirs in silver shade.</p>",

    "<h3>Night’s Guardian</h3><p>She keeps the secrets of the night,<br />A guardian bathed in silver light.<br />She hums in silence, soft and low,<br />A melody the dreamers know.</p>"
]

# Fetch a **random** moon poem when the user loads the home screen
@app.get("/api/lunar-phase-poem")
def get_random_moon_poem():
    return {"poem": random.choice(moon_poems)}

@app.get("/api/celtic-date")
def get_celtic_date_api():
    celtic_calendar = load_calendar_data()
    if not celtic_calendar:
        raise HTTPException(status_code=500, detail="calendar_data.json not found")

    current_date   = datetime.now().date()
    weekday        = current_date.strftime("%A")
    gregorian_date = current_date.strftime("%B %d")

    for month in celtic_calendar.get("months", []):
        start_date = datetime.strptime(month["start_date"], "%Y-%m-%d").date()
        end_date   = datetime.strptime(month["end_date"],   "%Y-%m-%d").date()
        if start_date <= current_date <= end_date:
            celtic_day   = (current_date - start_date).days + 1
            celtic_month = month["name"]
            return {
                "day":            weekday,
                "celtic_day":     celtic_day,
                "month":          celtic_month,
                "gregorian_date": gregorian_date
            }

    raise HTTPException(status_code=404, detail="Celtic date not found in current range")


@app.get("/api/lunar-phase")
def get_dynamic_moon_phase(day: int, month: int, year: int = datetime.now().year):
    try:
        target = date(year, month, day)
        result = calculate_lunar_phases(target, target)
        # calculate_lunar_phases returns a list; for a single day we return the first item
        return result[0] if result else {"error": "No phase data for that date."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/zodiac")
def get_zodiac_sign(month: str, day: int):
    for sign in calendar_data["zodiac"]:
        if sign["month"] == month and sign["day"] == day:
            return sign
    return {"message": "No zodiac sign found."}

@app.get("/api/events")
def get_events(month: str, day: int):
    for event in calendar_data["events"]:
        if event["month"] == month and event["day"] == day:
            return event
    return {"message": "No events found."}



# Remove global custom_events and national_holidays and their try/except loaders.

@app.get("/api/national-holidays")
def get_national_holidays():
    data = load_calendar_data()
    return data.get("national_holidays", [])


# Load lunar and solar eclipses
def estimate_eclipses():
    now = ephem.now()

    # Find the next full moon (for lunar eclipses)
    next_full_moon = ephem.next_full_moon(now)
    next_full_moon_date = ephem.Date(next_full_moon).datetime()

    # Find the next new moon (for solar eclipses)
    next_new_moon = ephem.next_new_moon(now)
    next_new_moon_date = ephem.Date(next_new_moon).datetime()

    # Estimate Lunar Eclipse (assuming it happens near a full moon)
    lunar_eclipse_event = {
        "type": "lunar-eclipse",
        "title": "Lunar Eclipse",
        "description": "Shadow and light embrace in celestial dance, a moment between worlds.",
        "date": next_full_moon_date.strftime("%Y-%m-%d %H:%M:%S")
    }

    # Estimate Solar Eclipse (assuming it happens near a new moon)
    solar_eclipse_event = {
        "type": "solar-eclipse",
        "title": "Solar Eclipse",
        "description": "A rare solar eclipse is on the horizon.",
        "date": next_new_moon_date.strftime("%Y-%m-%d %H:%M:%S")
    }

    return [lunar_eclipse_event, solar_eclipse_event]



# -----------------------------
# Simple storage for custom events (file-backed)
# -----------------------------
from pydantic import BaseModel
from typing import Optional, List

CUSTOM_EVENTS_FILE = os.path.join(BASE_DIR, "custom_events.json")

class CustomEvent(BaseModel):
    id: str
    date: str            # "YYYY-MM-DD"
    title: str
    type: Optional[str] = None   # e.g. "🔥 Date"
    notes: Optional[str] = None
    recurring: bool = False

def _load_custom_events() -> List[dict]:
    try:
        with open(CUSTOM_EVENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

def _save_custom_events(events: List[dict]) -> None:
    with open(CUSTOM_EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)

@app.get("/custom-events")
def get_custom_events():
    return _load_custom_events()

@app.post("/custom-events")
def create_custom_event(evt: CustomEvent):
    events = _load_custom_events()
    # replace any existing with same id
    events = [e for e in events if e.get("id") != evt.id]
    events.append(evt.dict())
    _save_custom_events(events)
    return {"ok": True, "saved": evt.id}

@app.put("/custom-events/{date}")
def update_custom_event(date: str, evt: CustomEvent):
    events = _load_custom_events()
    updated = False
    for i, e in enumerate(events):
        # Prefer matching by id if present, else by date
        if (evt.id and e.get("id") == evt.id) or (e.get("date") == date):
            events[i] = evt.dict()
            updated = True
            break
    if not updated:
        events.append(evt.dict())
    _save_custom_events(events)
    return {"ok": True, "updated": updated}

@app.delete("/custom-events/{date}")
def delete_custom_event(date: str):
    events = _load_custom_events()
    before = len(events)
    # delete by exact date (and allow query ?id=... if you want to be stricter later)
    events = [e for e in events if e.get("date") != date]
    _save_custom_events(events)
    return {"ok": True, "deleted": before - len(events)}

# -----------------------------
# Holidays & Eclipse events (stubs)
# -----------------------------
HOLIDAYS_FILE = os.path.join(BASE_DIR, "national_holidays.json")
ECLIPSES_FILE = os.path.join(BASE_DIR, "eclipse_events.json")

def _load_json_or_empty(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

@app.get("/national-holidays")
def national_holidays():
    # Return contents if file present; else empty list
    return _load_json_or_empty(HOLIDAYS_FILE)

@app.get("/eclipse-events")
def eclipse_events():
    return _load_json_or_empty(ECLIPSES_FILE)




# API Endpoint for Eclipses
@app.get("/api/eclipse-events")
def eclipse_events():
    events = estimate_eclipses()
    return events



@app.get("/api/calendar-data")
def get_calendar_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        return JSONResponse(content=data)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

# Compatibility alias for dev proxy that may strip the `/api` prefix
@app.get("/calendar-data", include_in_schema=False)
def get_calendar_data_alias():
    return get_calendar_data()

from typing import Optional

def _is_leap_year(y: int) -> bool:
    return (y % 4 == 0) and (y % 100 != 0 or y % 400 == 0)

def _celtic_month_for(dt: date) -> tuple[str, int]:
    """
    Return (month_name, celtic_day) for a Gregorian date using
    the same boundaries you use in the frontend.
    """
    # "Cycle year" matches your JS: dates on/after Dec 23 advance the cycle.
    cycle = dt.year + 1 if dt >= date(dt.year, 12, 23) else dt.year

    ranges = [
        ("Nivis",   date(cycle-1, 12, 23), date(cycle,  1, 19)),
        ("Janus",   date(cycle,   1, 20),  date(cycle,  2, 16)),
        ("Brigid",  date(cycle,   2, 17),  date(cycle,  3, 16)),
        ("Flora",   date(cycle,   3, 17),  date(cycle,  4, 13)),
        ("Maia",    date(cycle,   4, 14),  date(cycle,  5, 11)),
        ("Juno",    date(cycle,   5, 12),  date(cycle,  6,  8)),
        ("Solis",   date(cycle,   6,  9),  date(cycle,  7,  6)),
        ("Terra",   date(cycle,   7,  8),  date(cycle,  8,  4)),
        ("Lugh",    date(cycle,   8,  4),  date(cycle,  8, 31)),
        ("Pomona",  date(cycle,   9,  1),  date(cycle,  9, 28)),
        ("Autumna", date(cycle,   9, 29),  date(cycle, 10, 26)),
        ("Eira",    date(cycle,  10, 27),  date(cycle, 11, 23)),
        ("Aether",  date(cycle,  11, 24),  date(cycle, 12, 21)),
    ]

    # Mirabilis: Dec 22; 2 days iff leap-year (of the cycle), else 1 day.
    mir_end = 23 if _is_leap_year(cycle) else 22
    ranges.append(("Mirabilis", date(cycle, 12, 22), date(cycle, 12, mir_end)))

    for name, start, end in ranges:
        if start <= dt <= end:
            return name, (dt - start).days + 1

    # Fallback — shouldn't happen with the ranges above.
    return "Nivis", 1

@app.get("/celtic-date")
def api_celtic_date(date_str: Optional[str] = None):
    """
    Return today's Celtic month/day, or for the supplied ?date=YYYY-MM-DD.
    """
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Bad date; use YYYY-MM-DD")

    month, celtic_day = _celtic_month_for(target)
    return {"month": month, "celtic_day": celtic_day}

# Simple initial version: returns a pleasant poem; you can wire this
# to ephem + phase classification later if you want phase-specific lines.
@app.get("/lunar-phase-poem")
def api_lunar_phase_poem(date_str: Optional[str] = None):
    _ = date_str  # reserved for future use
    poem = (
        "Moonlight pulls the ocean’s breath,\n"
        "A rhythm old as life and death.\n"
        "Under her glow, the tide obeys,\n"
        "As time drifts on in silver waves."
    )
    return {"poem": poem}
