"""Local runtime configuration. Secrets never live in a project or source export."""
from __future__ import annotations
import os
from pathlib import Path
import secrets

class Config:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or os.environ.get('FRAMEVA_DATA_DIR') or Path.home() / '.frameva').expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.assets_dir = self.data_dir / 'assets'
        self.assets_dir.mkdir(exist_ok=True, mode=0o700)
        self.db_path = self.data_dir / 'frameva.sqlite3'
        self.token_path = self.data_dir / 'token'
        override = os.environ.get('FRAMEVA_TOKEN')
        if override:
            if not 32 <= len(override) <= 512 or any(ord(c)<33 or ord(c)>126 for c in override):
                raise ValueError('FRAMEVA_TOKEN must contain 32–512 visible ASCII characters without spaces.')
            self.token = override
        else:
            try:
                self.token = self.token_path.read_text(encoding='utf-8').strip()
            except FileNotFoundError:
                token = secrets.token_urlsafe(48)
                try:
                    fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'w', encoding='utf-8') as file:
                        file.write(token + '\n')
                    self.token = token
                except FileExistsError:
                    self.token = self.token_path.read_text(encoding='utf-8').strip()
            if not 32 <= len(self.token) <= 512 or any(ord(c)<33 or ord(c)>126 for c in self.token):
                raise ValueError('The local Frameva token is invalid; remove the token file to regenerate it.')
        self.comfy_url = os.environ.get('FRAMEVA_COMFY_URL', 'http://127.0.0.1:8188')
        self.allowed_hosts = ['127.0.0.1', 'localhost', '[::1]', '::1']
        self.max_upload_bytes = 256 * 1024 * 1024
        self.max_source_bytes = 64 * 1024 * 1024
