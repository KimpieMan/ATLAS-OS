"""Start the dashboard after the service is ready, in the logged-in graphical session."""
import shutil
import subprocess
import time
from urllib.request import urlopen

URL = 'http://127.0.0.1:8080'
for attempt in range(60):
    try:
        with urlopen(URL + '/api/system', timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('ATLAS start niet. Controleer: systemctl status atlas-os')
browser = shutil.which('chromium') or shutil.which('chromium-browser')
if not browser:
    raise SystemExit('Chromium is niet geïnstalleerd')
subprocess.run([browser, '--kiosk', '--no-first-run', '--no-default-browser-check', URL], check=False)
