"""Run with: streamlit run app.py"""

import calendar
from dataclasses import asdict
from datetime import date, datetime
import hashlib
import hmac
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

from echoes import (
    LANGUAGES, MAX_ENTRIES, MAX_SCRIPT, SarvamGateway, cached_narration,
    export_journal, fingerprint, friendly_error, import_journal, make_entry,
    sample_entries, select_entries, validate_reference, wav_duration,
)

st.set_page_config(page_title="Echoes · Your audio journal", page_icon="🎧", layout="centered")


def setting(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        return str(st.secrets.get(name, "")).strip()
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return ""


def require_access() -> None:
    passcode = setting("DEMO_PASSCODE")
    if not passcode:
        st.warning("Set DEMO_PASSCODE in the server environment or Streamlit secrets to open this demo.")
        st.stop()
    if st.session_state.get("authenticated"):
        return
    st.markdown("## A quiet place for your memories.")
    st.info("Public hackathon demo — for demonstration only. Judges and visitors can copy the passcode below to try Echoes.")
    st.caption("Demo passcode · use the copy button on the right")
    st.code(passcode, language=None)
    with st.form("access"):
        entered = st.text_input("Demo passcode", type="password", placeholder="Paste the demo passcode shown above")
        submitted = st.form_submit_button("Open my journal", type="primary")
    if submitted:
        if hmac.compare_digest(entered.encode(), passcode.encode()):
            st.session_state.authenticated = True
            st.rerun()
        st.error("That passcode doesn't match.")
    st.stop()


def reset_session() -> None:
    for key in list(st.session_state):
        del st.session_state[key]


def initialize() -> None:
    for key, value in {
        "entries": [], "audio_cache": {}, "summary_cache": {},
        "script_draft": "", "draft_label": "Your audio memory",
        "draft_source": "", "reference": None, "voice_consent": False,
        "voice_mode": "Sarvam narrator", "voice_revision": 0,
        "summary_calls": 0, "narration_calls": 0,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = value


def set_draft(text: str, label: str, source: str = "") -> None:
    st.session_state.script_draft = text
    st.session_state.draft_label = label
    st.session_state.draft_source = source


def render_journal(today: date) -> None:
    st.markdown("### The little things are the big things.")
    st.caption("Write it as you remember it. A moment, a conversation, a feeling.")
    with st.form("new_entry"):
        left, right = st.columns([2, 1])
        title = left.text_input("Memory title", placeholder="Something I want to remember", max_chars=120)
        day = right.date_input("Date", value=today)
        text = st.text_area("Your words", placeholder="Today, I…", height=160, max_chars=5000)
        save = st.form_submit_button("Save this memory", type="primary")
    if save:
        try:
            if len(st.session_state.entries) >= MAX_ENTRIES:
                raise ValueError("This demo holds up to 100 entries. Export your journal before starting a new one.")
            entry = make_entry(day, title, text)
            if any((item.date, item.title, item.text) == (entry.date, entry.title, entry.text)
                   for item in st.session_state.entries):
                raise ValueError("This memory is already saved. Change the words or date to add a new one.")
            st.session_state.entries.append(entry)
            st.success("Memory saved.")
        except ValueError as exc:
            st.error(str(exc))

    if not st.session_state.entries:
        st.info("Your first memory starts here. Or load the sample journal from the sidebar.")
        return
    st.markdown("#### Your pages")
    for entry in sorted(st.session_state.entries, key=lambda item: (item.date, item.id), reverse=True):
        with st.expander(f"{date.fromisoformat(entry.date).strftime('%d %b %Y')} · {entry.title}"):
            st.text(entry.text)
            if st.button("Use as narration script", key=f"read_{entry.id}"):
                set_draft(entry.text, entry.title)
                st.success("Your words are in the Memoir tab. Review them, then choose Narrate.")
            with st.form(f"edit_{entry.id}"):
                edited_title = st.text_input("Title", entry.title, max_chars=120)
                edited_date = st.date_input("Memory date", date.fromisoformat(entry.date))
                edited_text = st.text_area("Entry", entry.text, max_chars=5000)
                if st.form_submit_button("Save changes"):
                    try:
                        updated = make_entry(edited_date, edited_title, edited_text, entry.id)
                        st.session_state.entries = [updated if item.id == entry.id else item for item in st.session_state.entries]
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            confirm = st.checkbox("I want to delete this entry", key=f"confirm_{entry.id}")
            if st.button("Delete memory", key=f"delete_{entry.id}", disabled=not confirm):
                st.session_state.entries = [item for item in st.session_state.entries if item.id != entry.id]
                st.rerun()


def render_memoir(today: date, api_key: str) -> None:
    st.markdown("### Turn a chapter of your life into a keepsake.")
    st.caption("Choose a period, shape your story, then hear it aloud.")
    col1, col2, col3 = st.columns([1, 1, 1.4])
    period_kind = col1.selectbox("Chapter", ["Monthly", "Yearly"])
    years = sorted({today.year} | {date.fromisoformat(entry.date).year for entry in st.session_state.entries}, reverse=True)
    year = col2.selectbox("Year", years)
    language = col3.selectbox("Narration language", list(LANGUAGES))
    month = None
    if period_kind == "Monthly":
        month = st.selectbox("Month", list(range(1, 13)), index=today.month - 1,
                             format_func=lambda number: calendar.month_name[number])
    period = f"{calendar.month_name[month]} {year}" if month else str(year)
    selected = select_entries(st.session_state.entries, year, month)
    source = fingerprint([asdict(entry) for entry in selected], period, language)
    st.caption(f"{len(selected)} {'memory' if len(selected) == 1 else 'memories'} in {period} · English and Hindi supported")
    with st.expander("See the entries included"):
        if not selected:
            st.write("No entries in this period yet.")
        for entry in selected:
            st.text(f"{entry.date} · {entry.title}\n{entry.text}")

    if st.button("✦ Create my recap", type="primary", disabled=not selected or not api_key):
        try:
            if source in st.session_state.summary_cache:
                recap = st.session_state.summary_cache[source]
                st.info("Restored this recap from your session. No new API call.")
            else:
                with st.spinner("Finding the thread between your memories…"):
                    recap = SarvamGateway(api_key).summarize(selected, period, language)
                if len(st.session_state.summary_cache) >= 10:
                    del st.session_state.summary_cache[next(iter(st.session_state.summary_cache))]
                st.session_state.summary_cache[source] = recap
                st.session_state.summary_calls += 1
            set_draft(recap, f"My {period}", source)
        except Exception as exc:
            st.error(friendly_error(exc))

    st.divider()
    st.markdown("#### Make it sound like you.")
    st.caption("Review every word. You can also paste your own script here without generating a recap.")
    if st.session_state.draft_source and source != st.session_state.draft_source:
        st.info("This draft comes from an earlier selection. Create a recap to use the current entries and language, or keep editing this draft.")
    script = st.text_area("Narration script", key="script_draft", height=210,
                          placeholder="Your story will appear here. Or write your own…")
    text = script.strip()
    count = len(text)
    own_voice = st.session_state.voice_mode == "My own voice"
    reference = st.session_state.reference if own_voice else None
    voice_ready = not own_voice or (reference is not None and st.session_state.voice_consent)
    rate = 2 if own_voice else 1
    st.caption(f"{count} / {MAX_SCRIPT} characters · Audio estimate: ₹{count * rate / 1000:.2f} before tax · {st.session_state.voice_mode}")
    if count > MAX_SCRIPT:
        st.warning(f"Shorten your script by {count - MAX_SCRIPT} characters before narrating.")
    if not voice_ready:
        st.info("Set up your sample and voice consent in the Voice tab, or choose the Sarvam narrator there.")
    if text and not own_voice:
        st.caption("The preset narrator speaks these words as written. Create a recap in your selected language to translate the story.")

    if st.button("▶ Narrate my memory", type="primary",
                 disabled=not api_key or not text or count > MAX_SCRIPT or not voice_ready):
        try:
            with st.spinner("Giving your memory a voice…"):
                audio, reused = cached_narration(SarvamGateway(api_key), st.session_state.audio_cache,
                                                 text, LANGUAGES[language], reference)
            if not reused:
                st.session_state.narration_calls += 1
            st.session_state.last_audio = {
                "bytes": audio, "label": st.session_state.draft_label,
                "fingerprint": fingerprint(text, LANGUAGES[language], st.session_state.voice_mode,
                                           hashlib.sha256(reference).hexdigest() if reference else ""),
                "language": LANGUAGES[language], "voice": st.session_state.voice_mode,
            }
            st.success("Ready to keep." if not reused else "Reused your audio. No new API call.")
        except Exception as exc:
            st.error(friendly_error(exc, cloning=own_voice))
            if own_voice:
                st.info("To use the fallback, choose Sarvam narrator in Voice and click Narrate again.")

    if "last_audio" in st.session_state:
        memory = st.session_state.last_audio
        current = fingerprint(text, LANGUAGES[language], st.session_state.voice_mode,
                              hashlib.sha256(reference).hexdigest() if reference else "")
        with st.container(border=True):
            st.markdown("#### Your audio keepsake")
            st.text(memory["label"])
            if current != memory["fingerprint"]:
                st.caption("This is your previous recording. Narrate again to apply the latest words or voice settings.")
            st.caption(f"{memory['voice']} · {memory['language']} · {wav_duration(memory['bytes']):.0f} seconds")
            st.audio(memory["bytes"], format="audio/wav")
            st.download_button("↓ Download WAV", memory["bytes"], file_name="echoes-memory.wav", mime="audio/wav")
    else:
        preview = Path(__file__).parent / "first_memory.wav"
        if preview.exists():
            with st.expander("Hear the first working Sarvam call"):
                st.caption("Preset narrator · demo sentence · playback uses no API credits")
                st.audio(preview.read_bytes(), format="audio/wav")


def clear_voice() -> None:
    st.session_state.reference = None
    st.session_state.voice_consent = False
    st.session_state.voice_mode = "Sarvam narrator"
    st.session_state.audio_cache = {}
    st.session_state.pop("last_audio", None)
    st.session_state.voice_revision += 1


def render_voice() -> None:
    st.markdown("### A familiar voice makes it a memory.")
    st.radio("Narrator", ["Sarvam narrator", "My own voice"], key="voice_mode", horizontal=True)
    if st.session_state.voice_mode == "Sarvam narrator":
        st.info("Using a Sarvam preset narrator. This is not a clone of your voice.")
        st.caption("You can listen to any journal entry or recap immediately with this option.")
    st.markdown("#### Your voice sample")
    st.write("Record 10–15 seconds in a quiet room, with only your voice and no background music.")
    st.caption("Try reading: “These are the moments I want to remember. The small joys, the people I love, and the things I am learning. This is my story, in my own words.”")
    revision = st.session_state.voice_revision
    recording = st.audio_input("Record your voice", key=f"recording_{revision}")
    upload = st.file_uploader("Or upload a 10–15-second WAV", type=["wav"], key=f"voice_upload_{revision}")
    source = st.radio("Sample source", ["Microphone", "WAV upload"], horizontal=True)
    sample = recording if source == "Microphone" else upload
    consent = st.checkbox(
        "This is my voice, and I consent to Sarvam processing and cloning it for this narration.",
        key="voice_consent",
    )
    if st.button("Use this voice sample", disabled=sample is None or not consent):
        try:
            audio = sample.getvalue()
            duration = validate_reference(audio)
            st.session_state.reference = audio
            st.success(f"Voice sample ready ({duration:.1f} seconds). Choose My own voice above, then narrate in Memoir.")
        except ValueError as exc:
            st.error(str(exc))
    if st.session_state.reference is not None:
        st.caption("Active sample · stored only in this session")
        st.audio(st.session_state.reference, format="audio/wav")
    st.button("Forget my voice and generated audio", on_click=clear_voice)
    st.caption("Only narrating sends your sample to Sarvam. Echoes keeps no saved voice library or permanent journal database. Sarvam's own data policies apply to submitted content.")


def main() -> None:
    st.markdown("""
    <style>
      .stApp { background: #faf7f0; color: #352c27; }
      .block-container { max-width: 1040px; padding-top: 2.6rem; }
      h1, h2, h3 { font-family: Georgia, 'Times New Roman', serif; letter-spacing: -.035em; }
      h1 { font-size: clamp(3rem, 8vw, 5rem) !important; line-height: 1.05 !important; }
      [data-testid="stSidebar"] { background: #f1ece1; }
      [data-testid="stForm"], [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 14px; }
      .eyebrow { font-size: .72rem; letter-spacing: .22em; color: #92765b; font-weight: 600; }
      .intro { font-family: Georgia, serif; font-size: 1.25rem; color: #796657; max-width: 580px; }
      .stButton > button, .stDownloadButton > button { border-radius: 9px; }
      button[kind="primary"] { background: #954b35; border-color: #954b35; }
    </style>
    <div class="eyebrow">A PERSONAL AUDIO JOURNAL · POWERED BY SARVAM</div>
    <h1>Echoes<span style="color:#b66c47">.</span></h1>
    <p class="intro">Your words. Your voice. Your memories.</p>
    """, unsafe_allow_html=True)
    require_access()
    initialize()
    api_key = setting("SARVAM_API_KEY")
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    if not api_key:
        st.warning("Add SARVAM_API_KEY to the server environment or Streamlit secrets to enable generation. Your journal still works.")

    with st.sidebar:
        st.markdown("### A life, in little moments.")
        st.caption("Save a few lines today. Hear the story they become.")
        st.metric("Memories collected", len(st.session_state.entries))
        if st.button("Load sample journal", disabled=bool(st.session_state.entries)):
            st.session_state.entries = sample_entries(today)
            st.rerun()
        st.caption("Samples are fictional. Loading them uses no credits.")
        st.divider()
        st.download_button("↓ Export journal", export_journal(st.session_state.entries),
                           file_name="echoes-journal.json", mime="application/json")
        upload = st.file_uploader("Import journal JSON", type=["json"])
        replace = st.checkbox("Replace my current entries with this import")
        if st.button("Import journal", disabled=upload is None or not replace):
            try:
                st.session_state.entries = import_journal(upload.getvalue())
                st.session_state.summary_cache = {}
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        st.divider()
        st.caption(f"This session: {st.session_state.summary_calls} recaps · {st.session_state.narration_calls} narrations")
        st.caption("Credits are spent only when you create a recap or narrate. Repeated identical results are reused within this session.")
        st.caption("Refresh or disconnect may clear your session. Export your journal and download audio to keep them.")
        if st.checkbox("I have exported what I want to keep"):
            st.button("Clear session & lock", on_click=reset_session)

    journal, memoir, voice = st.tabs(["✍  Journal", "♫  Memoir", "◉  Voice"])
    with journal:
        render_journal(today)
    with memoir:
        render_memoir(today, api_key)
    with voice:
        render_voice()
    st.divider()
    st.caption("Public hackathon demo · For demonstration only. Session data is temporary. · Powered by Sarvam")


if __name__ == "__main__":
    main()
