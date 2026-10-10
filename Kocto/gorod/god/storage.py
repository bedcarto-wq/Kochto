"""Bounded JSON compression shared by disk and network. No pickle/code loading."""
import base64,json,zlib
from ..engine import DataError
LIMIT=20_000_000

def encode(value):
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    if len(raw)>LIMIT:raise DataError('Мир превышает ограничение 20 МБ')
    return base64.b64encode(zlib.compress(raw,6)).decode()

def decode(value):
    try:
        if not isinstance(value,str) or len(value)>5_000_000:raise DataError('Слишком большой сжатый снимок')
        compressed=base64.b64decode(value,validate=True);dec=zlib.decompressobj();raw=dec.decompress(compressed,LIMIT+1)
        if len(raw)>LIMIT or not dec.eof or dec.unused_data:raise DataError('Неверный размер сжатого снимка')
        return json.loads(raw)
    except (TypeError,ValueError,zlib.error) as exc:raise DataError('Повреждённые сжатые данные: '+str(exc)) from exc
