# Echoes

**Your words. Your voice. Your memories.**

A small Streamlit voice journal using Sarvam for editable first-person memoirs,
preset narration, and consent-based own-voice narration. English and Hindi supported.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Create `.env` using `.env.example` and enter your Sarvam key and a private demo
passcode. Then load it without printing its contents:

```bash
set -a
source .env
set +a
.venv/bin/python -m streamlit run app.py
```

Open http://localhost:8501 and enter the passcode stored in `.env`.

To make just the first small API call:

```bash
set -a
source .env
set +a
.venv/bin/python first_call.py
```

It saves `first_memory.wav` and prints only its size and duration. This makes one
billable request and disables SDK retries. The key is read from the environment.

## A 60-second demo

1. Open **Journal** and choose **Load sample journal** in the sidebar. The sample memories are fictional.
2. Open **Memoir**, select their month/year and language, and click **Create my recap**.
3. Read and edit the script. Keep it within 900 characters.
4. Choose the **Sarvam narrator**, or go to **Voice** to record a 10–15-second sample of your own voice, give consent, save the sample, and select **My own voice**.
5. Return to **Memoir**, click **Narrate my memory**, listen, and download the WAV.

Individual entries can be sent to the script editor from Journal. A typed script
can be narrated directly without paying for a recap.

## Credits and data

- Recaps use `sarvam-105b`; preset narration uses `bulbul:v4-flash`.
- Own-voice narration uses `/voices/clone` with an inline reference WAV. It creates no saved voice library; beta account access is required.
- Paid requests happen only on **Create my recap** and **Narrate my memory**. Matching results are reused within the current session; no automatic retries or silent paid fallback.
- Audio estimates use ₹1/1,000 characters for Bulbul v4 Flash and ₹2/1,000 for cloning, before tax. Recap token charges are separate. Estimates are not an account balance or hard spending limit. See [Sarvam pricing](https://docs.sarvam.ai/api/getting-started/pricing).
- Each session holds up to 100 entries, with up to 5,000 characters each. Recap source is limited to 20,000 characters; a draft may need shortening if the model exceeds its requested length.
- Journal, reference clip, drafts, and generated audio are held in server session memory. They may be lost on refresh, disconnect, restart, or redeploy. Export JSON and download WAV files to keep them.
- JSON export contains entries, not the voice sample or audio. Import replaces entries after you check the confirmation box.
- Narration sends text, and own-voice narration also sends the sample, to Sarvam. Recaps send the selected journal entries. Sarvam's data policies apply.
- The passcode is a demo gate, not individual accounts or durable private storage. **Clear session & lock** removes the session's data. **Forget my voice** removes the active sample and generated audio from the session.
- `.env`, `.streamlit/secrets.toml`, the virtual environment, and generated audio are ignored. Do not upload them to GitHub.

## Deploy to Streamlit Community Cloud

1. Put the source in a GitHub repository, excluding ignored files. A short path through the web UI is to upload `app.py`, `echoes.py`, `requirements.txt`, and `.streamlit/config.toml`.
2. At [share.streamlit.io](https://share.streamlit.io/), create an app, select that repository, and set the entrypoint to `app.py` with Python 3.12.
3. In **Advanced settings → Secrets**, enter:

```toml
SARVAM_API_KEY = "your-sarvam-key"
DEMO_PASSCODE = "your-private-demo-passcode"
```

4. Deploy and open the app. No external database or system packages are needed.

The first-call WAV is intentionally excluded from publication. Generate your
first memoir in the deployed app to demonstrate live narration.

See [Streamlit deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app)
and [secret settings](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).

## Verify without spending credits

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover period filtering, JSON validation, request boundaries, session audio
reuse, voice sample validation, and Streamlit flows using mocked Sarvam calls.
No test needs a live API key.
