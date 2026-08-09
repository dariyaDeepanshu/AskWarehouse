"""Headless functional test of the Streamlit app using AppTest -- runs the
actual script, simulates a real chat question, and checks for exceptions,
since curling the page only fetches the static shell (the script only runs
per-session over websocket)."""
import os
from streamlit.testing.v1 import AppTest

app_path = os.path.join(os.path.dirname(__file__), "..", "src", "askwarehouse", "ui", "streamlit_app.py")
at = AppTest.from_file(app_path, default_timeout=180)
at.run()

print("initial run exceptions:", at.exception)
assert not at.exception, "app crashed on initial load"
print("sidebar checkboxes:", [c.label for c in at.sidebar.checkbox])

at.chat_input[0].set_value("How many completed orders were there in California in 2025?").run()
print("after question exceptions:", at.exception)
assert not at.exception, "app crashed after asking a question"

print("chat messages rendered:", len(at.chat_message))
for m in at.chat_message:
    texts = [md.value for md in m.markdown]
    print(" role:", m.type, "| text preview:", (texts[0][:200] if texts else None))

print("metrics rendered:", [(m.label, m.value) for m in at.metric])
print("images rendered:", len(at.get("imgs")) if at.get("imgs") else 0)

print("\nOK: streamlit app ran a full question end-to-end with no exceptions")
