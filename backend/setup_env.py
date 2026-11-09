from base64 import urlsafe_b64encode
from pathlib import Path
from secrets import token_bytes, token_urlsafe

root = Path(__file__).resolve().parent.parent
template = (root / ".env.example").read_text()
values = {
    "APP_SECRET_KEY": token_urlsafe(48),
    "ENCRYPTION_KEY": urlsafe_b64encode(token_bytes(32)).decode(),
}
try:
    with (root / ".env").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(
            f"{line.split('=')[0]}={values[line.split('=')[0]]}"
            if line.split("=")[0] in values else line
            for line in template.splitlines()
        ) + "\n")
except FileExistsError:
    print(".env already exists")
else:
    print("Created .env with unique encryption and application keys")
