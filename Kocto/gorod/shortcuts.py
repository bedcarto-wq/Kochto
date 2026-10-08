"""Local named phrase shortcuts. No executable code or gameplay effects in settings."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import uuid
from .engine import DataError, RuleError

LIMIT = 20
NAME_LIMIT = 32


def normalize_clipboard(text, limit=2000):
    if not isinstance(text,str): raise RuleError('В буфере нет текста')
    if '\x00' in text: raise RuleError('Буфер содержит недопустимый символ')
    text = text.replace('\r\n','\n').replace('\r','\n')
    # Each non-empty clipboard line becomes an explicit plan clause.
    lines = [re.sub(r'[\t\v\f ]+',' ',line).strip() for line in text.split('\n')]
    result = '; '.join(line.rstrip(';') for line in lines if line)
    if not result: raise RuleError('Буфер обмена пуст')
    if len(result)>limit: raise RuleError('Текст слишком длинный: максимум '+str(limit)+' символов')
    return result


class ShortcutStore:
    def __init__(self,path,max_text=2000):
        self.path=Path(path)
        self.max_text=max_text
        self.items=[]
        self.load_error=None
        self.load()

    def validate(self,items):
        if not isinstance(items,list) or len(items)>LIMIT: raise DataError('Мои действия: максимум '+str(LIMIT))
        seen=set();names=set()
        for item in items:
            if not isinstance(item,dict) or set(item)!={'id','name','text'}: raise DataError('Мои действия: неверная запись')
            key,name,text=item['id'],item['name'],item['text']
            if not isinstance(key,str) or not re.fullmatch(r'[0-9a-f]{32}',key) or key in seen: raise DataError('Мои действия: неверный id')
            if not isinstance(name,str) or not name.strip() or len(name)>NAME_LIMIT or name.casefold() in names or any(ord(c)<32 for c in name): raise DataError('Мои действия: имя от 1 до 32 символов, без повторов')
            if not isinstance(text,str) or not text.strip() or len(text)>self.max_text or '\x00' in text: raise DataError('Мои действия: неверный текст')
            seen.add(key);names.add(name.casefold())

    def load(self):
        if not self.path.exists(): return
        try:
            if self.path.stat().st_size>250000: raise DataError('Мои действия: слишком большой файл')
            obj=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(obj,dict) or set(obj)!={'schema','items'} or type(obj['schema']) is not int or obj['schema']!=1: raise DataError('Мои действия: неизвестная версия')
            self.validate(obj['items']);self.items=obj['items']
        except (OSError,ValueError,DataError) as exc:
            self.load_error='Не удалось загрузить мои действия: '+str(exc)+'. Файл сохранён, не перезаписываю его.'

    def commit(self,items):
        if self.load_error: raise DataError(self.load_error)
        self.validate(items)
        temp=self.path.with_name(self.path.name+'.tmp-'+uuid.uuid4().hex)
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with temp.open('w',encoding='utf-8') as fh:
                json.dump({'schema':1,'items':items},fh,ensure_ascii=False,indent=2)
                fh.flush();os.fsync(fh.fileno())
            os.replace(temp,self.path)
        except OSError as exc:
            raise DataError('Не удалось сохранить мои действия: '+str(exc)) from exc
        finally:
            try:
                if temp.exists(): temp.unlink()
            except OSError:
                pass  # original write error is reported; never mask it with cleanup
        self.items=items

    def put(self,name,text,key=None):
        if not isinstance(name,str) or not isinstance(text,str): raise DataError('Мои действия: имя и текст должны быть строками')
        name=name.strip();text=text.strip()
        if key is not None and not any(x['id']==key for x in self.items): raise DataError('Моё действие уже удалено')
        item={'id':key or uuid.uuid4().hex,'name':name,'text':text}
        items=[item if x['id']==key else dict(x) for x in self.items] if key else [dict(x) for x in self.items]+[item]
        self.commit(items)
        return item

    def delete(self,key):
        if not any(x['id']==key for x in self.items): raise DataError('Моё действие уже удалено')
        self.commit([dict(x) for x in self.items if x['id']!=key])
