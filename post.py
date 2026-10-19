"""Threads 幣圈貼文自動發佈：每次執行發 queue.txt 裡下一篇還沒發過的文。

用法：
  python post.py --check   只檢查全部貼文（字數、禁用字），不需要金鑰
  python post.py           發下一篇（需要環境變數 THREADS_TOKEN）
  DRY_RUN=1 python post.py 只顯示下一篇要發什麼，不發
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://graph.threads.net/v1.0"
QUEUE = "queue.txt"
DONE = "posted.json"
MAX_LEN = 500
POST_HOUR = 9           # 台灣時間幾點以後才發（排程每 5 分鐘檢查一次，到點且今天還沒發就發）
DEFAULT_TOPIC = "幣圈"   # 每篇預設的主題；單篇要換，就在那篇最後一行寫「主題：XXX」
BANNED = ["穩賺", "必賺", "保證獲利", "跟單", "跟著做", "穩贏", "加碼", "梭哈"]


def load_posts():
    with open(QUEUE, encoding="utf-8") as f:
        raw = f.read()
    out = []
    for block in (b.strip() for b in raw.split("\n===\n")):
        if not block:
            continue
        lines = block.splitlines()
        topic = DEFAULT_TOPIC
        if lines[-1].strip().startswith("主題："):
            topic = lines.pop().strip()[3:].strip()
        out.append((lines[0].strip(), "\n".join(lines).strip(), topic))
    keys = [k for k, _, _ in out]
    if len(set(keys)) != len(keys):
        sys.exit("錯誤：有兩篇貼文的第一行相同，第一行要能當作識別名稱")
    return out


def problems(text, topic):
    out = []
    if not 1 <= len(topic) <= 50 or "." in topic or "&" in topic:
        out.append(f"主題「{topic}」要 1～50 字，且不能有 . 或 &")
    if len(text) > MAX_LEN:
        out.append(f"字數 {len(text)} 超過 {MAX_LEN}")
    for w in BANNED:
        if w in text:
            out.append(f"含禁用字「{w}」")
    return out


def output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def call(path, params):
    data = urllib.parse.urlencode({**params, "access_token": os.environ["THREADS_TOKEN"]}).encode()
    req = urllib.request.Request(f"{API}/{path}", data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        hint = "（金鑰無效或已過期，請重新產生並更新 THREADS_TOKEN）" if '"code":190' in body.replace(" ", "") else ""
        sys.exit(f"Threads API 錯誤 {e.code}{hint}：{body}")


def main():
    posts = load_posts()

    if "--check" in sys.argv:
        bad = 0
        for key, text, topic in posts:
            p = problems(text, topic)
            print(f"{'✗' if p else '✓'} {len(text):>3} 字  [{topic}]  {key}" + (f"  → {'；'.join(p)}" if p else ""))
            bad += bool(p)
        print(f"\n共 {len(posts)} 篇，{bad} 篇有問題")
        sys.exit(1 if bad else 0)

    done = json.load(open(DONE, encoding="utf-8")) if os.path.exists(DONE) else []
    posted = {d["key"] for d in done}
    pending = [x for x in posts if x[0] not in posted]

    # 排程頻繁檢查：還沒到點、或台灣日期今天已經發過就跳過（手動執行 FORCE=1 不受限）
    tw_now = datetime.now(timezone.utc) + timedelta(hours=8)
    tw_today = tw_now.date()
    def tw_date(s):
        return (datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=8)).date()
    if pending and os.environ.get("FORCE") != "1":
        if tw_now.hour < POST_HOUR:
            print(f"還沒到發文時間（台灣 {POST_HOUR}:00），跳過。")
            return
        if any(tw_date(d["posted_at"]) == tw_today for d in done):
            print(f"今天（{tw_today}）已經發過了，跳過。")
            return

    if not pending:
        print("全部貼文都發完了，停止排程。")
        output("finished", "true")
        return

    key, text, topic = pending[0]
    p = problems(text, topic)
    if p:
        sys.exit(f"不發文，這篇有問題：{key} → {'；'.join(p)}")

    print(f"下一篇（剩 {len(pending)} 篇），主題「{topic}」：\n\n{text}\n")
    if os.environ.get("DRY_RUN") == "1":
        print("DRY_RUN：只檢查，不發文。")
        return

    container = call("me/threads", {"media_type": "TEXT", "text": text, "topic_tag": topic})["id"]
    time.sleep(30)  # Meta 建議建立後稍等再發布
    post_id = call("me/threads_publish", {"creation_id": container})["id"]

    done.append({"key": key, "post_id": post_id, "posted_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC"})
    with open(DONE, "w", encoding="utf-8") as f:
        json.dump(done, f, ensure_ascii=False, indent=2)
    print(f"已發文：{key}（post id {post_id}）")
    output("published", "true")


if __name__ == "__main__":
    main()
