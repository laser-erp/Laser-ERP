#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path

CFG = Path.home() / "AppData/Local/Happ/config.json"
DB = Path.home() / "AppData/Local/Happ/subs.db"


def main() -> None:
    data = json.loads(CFG.read_text(encoding="utf-8"))
    changed = False
    for rule in data.get("route", {}).get("rules", []):
        names = rule.get("process_name")
        if not names:
            continue
        cursorish = [n for n in names if "cursor" in n.lower()]
        if cursorish:
            print("FOUND_DIRECT_BYPASS:", cursorish)
            rule["process_name"] = [n for n in names if "cursor" not in n.lower()]
            if not rule["process_name"]:
                # leave empty list cleaned later
                pass
            changed = True
    # drop empty process rules
    rules = data.get("route", {}).get("rules", [])
    data["route"]["rules"] = [
        r for r in rules if not (("process_name" in r) and not r.get("process_name"))
    ]
    if changed:
        CFG.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
        print("UPDATED", CFG)
    else:
        print("NO_CURSOR_BYPASS_OR_ALREADY_CLEAN")

    if DB.exists():
        con = sqlite3.connect(str(DB))
        cur = con.cursor()
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        print("TABLES:", tables)
        for t in tables:
            cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
            print(f"COLS {t}:", cols)
            try:
                rows = cur.execute(f"SELECT * FROM {t} LIMIT 3").fetchall()
                print(f"SAMPLE {t}:", rows[:1])
            except Exception as e:
                print("ERR", t, e)
        # try find netherlands-like names
        for t in tables:
            cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]
            text_cols = [c for c in cols if c.lower() in {"name", "title", "remark", "host", "server", "tag", "country", "country_code"}]
            if not text_cols:
                text_cols = [c for c in cols if "name" in c.lower() or "remark" in c.lower() or "title" in c.lower()]
            for col in text_cols:
                try:
                    q = f"SELECT {col} FROM {t} WHERE lower(cast({col} as text)) LIKE '%nether%' OR cast({col} as text) LIKE '%Нидерл%' OR cast({col} as text) LIKE '%NL%' OR cast({col} as text) LIKE '%Holland%' LIMIT 20"
                    hits = cur.execute(q).fetchall()
                    if hits:
                        print(f"NL_HITS {t}.{col}:", hits[:20])
                except Exception as e:
                    print("QERR", t, col, e)
        con.close()


if __name__ == "__main__":
    main()
